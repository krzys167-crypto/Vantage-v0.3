"""Badges, profiles and the monthly league, computed only from signed evidence.

Pure functions over the grader's stored results, so every badge points at an
attempt whose signed result anyone can verify (grader/verify.py). Nothing here
counts activity: a badge says something about the quality of the work.

    attempts: [{"id", "user", "scenario", "submitted", "result": {...}}]
    debriefs: {attempt_id: debrief result}
"""
import hashlib
import time

PASSING = ("pass", "merit", "elite")
DEBRIEF_POINTS = 10          # league bonus per scenario with a verified post-mortem
BADGES = {
    "first_recovery": "first attested recovery (tier pass or better)",
    "fast_hands": "attested pass with MTTR under 5 minutes",
    "surgeon": "attested pass without hints, restarts of unaffected services or recreated services",
    "elite": "elite tier on an attested attempt (every hidden check passed)",
    "forensic": "post-mortem verified against the evidence",
    "coroner": "verified post-mortem quoting every fact, recovery time within 10 s",
    "range_certified": "attested pass on the hosted range, hidden checks from a private pack",
    "polymath": "attested passes in 3 different scenarios",
}
PER_SCENARIO = {"fast_hands", "surgeon", "elite", "forensic", "coroner", "range_certified"}


def alias(user):
    """Public name on the league: never the e-mail itself."""
    return "u-" + hashlib.sha256(user.encode()).hexdigest()[:10]


def season(ts):
    return time.strftime("%Y-%m", time.gmtime(ts))


def passed(r):
    return bool(r.get("attested")) and r.get("tier") in PASSING


def earned(a, debrief):
    """Badge ids one attempt earns on its own (polymath and first_recovery need the history)."""
    r, out = a["result"], []
    if passed(r):
        mttr = (r.get("sli") or {}).get("mttr_s")
        br = r.get("blast_radius") or {}
        if mttr is not None and mttr < 300:
            out.append("fast_hands")
        if not r.get("hints_used") and not br.get("restarted_unaffected") and not br.get("recreated"):
            out.append("surgeon")
        if r.get("tier") == "elite":
            out.append("elite")
        t = r.get("trust") or {}
        if t.get("assertions") == "platform" and t.get("hidden") == "platform, private pack":
            out.append("range_certified")
    if debrief and debrief.get("verdict") == "verified":
        out.append("forensic")
        err = (debrief.get("timeline") or {}).get("mitigated_error_s")
        facts = debrief.get("facts")        # absent on post-mortems checked before facts existed
        if facts is not None and not facts.get("missing") and err is not None and err <= 10:
            out.append("coroner")
    return out


def badges(attempts, debriefs):
    """Earliest attempt that earned each badge (per scenario where it makes sense)."""
    got, scenarios_passed = {}, []
    for a in sorted(attempts, key=lambda a: a["submitted"]):
        ids = earned(a, debriefs.get(a["id"]))
        if passed(a["result"]):
            ids.append("first_recovery")
            if a["scenario"] not in scenarios_passed:
                scenarios_passed.append(a["scenario"])
                if len(scenarios_passed) == 3:
                    ids.append("polymath")
        for b in ids:
            key = (b, a["scenario"] if b in PER_SCENARIO else None)
            if key not in got:
                got[key] = {"badge": b, "text": BADGES[b], "scenario": key[1], "attempt_id": a["id"],
                            "at": a["submitted"]}
    return sorted(got.values(), key=lambda b: b["at"])


def profile(user, attempts, debriefs):
    mine = [a for a in attempts if a["user"] == user]
    per = {}
    for a in mine:
        r, s = a["result"], per.setdefault(a["scenario"], {"attempts": 0, "attested_passes": 0, "best_score": None,
                                                          "best_tier": None, "best_attempt": None,
                                                          "best_mttr_s": None, "debrief_verified": False})
        s["attempts"] += 1
        d = debriefs.get(a["id"])
        if d and d.get("verdict") == "verified":
            s["debrief_verified"] = True
        if not passed(r):
            continue
        s["attested_passes"] += 1
        if s["best_score"] is None or r["score"] > s["best_score"]:
            s.update(best_score=r["score"], best_tier=r["tier"], best_attempt=a["id"])
        m = (r.get("sli") or {}).get("mttr_s")
        if m is not None and (s["best_mttr_s"] is None or m < s["best_mttr_s"]):
            s["best_mttr_s"] = m
    return {"kind": "profile", "user": user, "alias": alias(user), "generated_at": time.time(),
            "scenarios": per, "badges": badges(mine, debriefs),
            "note": "only attested results and verified post-mortems count; every badge names its attempt"}


def league(month, attempts, debriefs):
    """Points: best attested score per scenario this month, +10 per scenario with a verified post-mortem."""
    best, bonus, first = {}, {}, {}
    for a in attempts:
        if season(a["submitted"]) != month:
            continue
        r, key = a["result"], (a["user"], a["scenario"])
        d = debriefs.get(a["id"])
        if d and d.get("verdict") == "verified":
            bonus[key] = DEBRIEF_POINTS
        if passed(r) and r["score"] > best.get(key, -1):
            best[key] = r["score"]
            first[key] = a["submitted"]
    users = {}
    for (user, scn), score in best.items():
        u = users.setdefault(user, {"alias": alias(user), "points": 0.0, "scenarios": 0, "since": first[(user, scn)]})
        u["points"] += score + bonus.get((user, scn), 0)
        u["scenarios"] += 1
        u["since"] = min(u["since"], first[(user, scn)])
    rows = sorted(users.values(), key=lambda u: (-u["points"], u["since"]))
    for i, u in enumerate(rows, 1):
        u["rank"], u["points"] = i, round(u["points"], 1)
        del u["since"]
    return {"kind": "league", "season": month, "generated_at": time.time(), "rows": rows,
            "teams": teams(month, attempts, debriefs, {u: r["points"] for u, r in users.items()}),
            "rules": "best attested score per scenario + %d per scenario with a verified post-mortem; "
                     "teams: sum of members' points, ties broken by median MTTR" % DEBRIEF_POINTS}


def teams(month, attempts, debriefs, points):
    """Team table: a team is only as good as all of its members' recoveries."""
    team_of, mttrs = {}, {}
    for a in sorted(attempts, key=lambda a: a["submitted"]):
        if season(a["submitted"]) != month or not a.get("team"):
            continue
        team_of[a["user"]] = a["team"]                      # the latest team a user played for this month
        m = (a["result"].get("sli") or {}).get("mttr_s")
        if passed(a["result"]) and m is not None:
            mttrs.setdefault(a["team"], []).append(m)
    out = {}
    for user, team in team_of.items():
        t = out.setdefault(team, {"team": team, "points": 0.0, "members": 0})
        t["points"] += points.get(user, 0.0)
        t["members"] += 1
    for name, t in out.items():
        ms = sorted(mttrs.get(name, []))
        t["median_mttr_s"] = round(ms[len(ms) // 2], 1) if ms else None
        t["points"] = round(t["points"], 1)
    rows = sorted(out.values(), key=lambda t: (-t["points"], t["median_mttr_s"] if t["median_mttr_s"] is not None else 1e9))
    for i, t in enumerate(rows, 1):
        t["rank"] = i
    return rows
