"""Post-mortem checks: the trainee's write-up against the grader's evidence.

Pure functions, no I/O, so the grader and the local client (lint before the
one-shot submit) apply exactly the same rules.

A post-mortem is Markdown with a front matter block:

    ---
    attempt: 3f2a9c0d1e2b4a5c
    detected: 2026-10-09T12:03:10Z
    mitigated: 2026-10-09T12:09:44Z
    causes: inventory_cpu_limit_cut, retries_7x_120ms_no_backoff
    ---
    # Post-mortem: checkout outage
    ## Summary / ## Impact / ## Timeline / ## Root cause / ## Resolution / ## Action items

`causes` are ids from the scenario's catalog (generated/debrief.json). The
catalog lists every variant the seed can pick plus plausible decoys, so the
right answer depends on what happened in this attempt, not on the scenario
name. Timeline bullets start with a UTC time ("- 12:04:30Z what happened"),
action items with a kind ("- [prevent] ...", "- [detect] ...").
"""
import datetime as dt
import hashlib
import re

SECTIONS = ["summary", "impact", "timeline", "root cause", "resolution", "action items"]
ACTION_KINDS = ("prevent", "detect", "mitigate", "process")
WHEN_RE = re.compile(r"^seed\[(\d+)\] % (\d+) == (\d+)$")
TIME_RE = re.compile(r"^\s*[-*]\s+`?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
                     r"|\d{2}:\d{2}(?::\d{2})?Z?)`?\s+\S")
ACTION_RE = re.compile(r"^\s*[-*]\s+\[(\w+)\]\s+\S")
PASS_SCORE = 70
WEIGHTS = {"causes_recall": 35, "causes_precision": 15, "mitigated": 20, "detected": 5, "timeline": 5,
           "sections": 10, "action_items": 10}


def message(attempt_id, markdown):
    """What the trainee signs: binds the write-up to one attempt."""
    return f"vantage-debrief-v1\n{attempt_id}\n{hashlib.sha256(markdown.encode()).hexdigest()}\n".encode()


def parse_time(s, ref=None):
    """ISO 8601 (UTC if no offset) -> epoch. A bare HH:MM[:SS] is taken on the UTC
    day that puts it closest to ref (the incident start)."""
    s = s.strip().strip("`")
    if re.match(r"^\d{2}:\d{2}(:\d{2})?Z?$", s):
        if ref is None:
            raise ValueError(f"time without a date: {s}")
        parts = [int(x) for x in s.rstrip("Z").split(":")] + [0]
        day = dt.datetime.fromtimestamp(ref, dt.timezone.utc).date()
        cands = [dt.datetime(day.year, day.month, day.day, parts[0], parts[1], parts[2],
                             tzinfo=dt.timezone.utc) + dt.timedelta(days=d) for d in (-1, 0, 1)]
        return min((c.timestamp() for c in cands), key=lambda t: abs(t - ref))
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.timestamp()


def parse(md):
    lines = md.replace("\r\n", "\n").split("\n")
    front = {}
    if lines and lines[0].strip() == "---":
        end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
        if end is not None:
            for l in lines[1:end]:
                if ":" in l and not l.lstrip().startswith("#"):
                    k, v = l.split(":", 1)
                    front[k.strip().lower()] = v.strip()
            lines = lines[end + 1:]
    sections, cur = {}, None
    for l in lines:
        m = re.match(r"^##\s+(.+?)\s*$", l)
        if m:
            cur = m.group(1).strip().lower()
            sections[cur] = []
        elif cur is not None:
            sections[cur].append(l)
    text = {k: "\n".join(v).strip() for k, v in sections.items()}
    timeline = [m.group(1) for l in sections.get("timeline", []) if (m := TIME_RE.match(l))]
    actions = [m.group(1).lower() for l in sections.get("action items", []) if (m := ACTION_RE.match(l))]
    causes = [c.strip() for c in re.split(r"[,\s]+", front.get("causes", "")) if c.strip()]
    return {"front": front, "sections": text, "timeline": timeline, "actions": actions, "causes": causes}


def lint(doc, catalog, attempt_id=None):
    """Hard errors: the grader rejects the post-mortem (without using up the attempt's debrief)."""
    errs = []
    f = doc["front"]
    for k in ("attempt", "detected", "mitigated", "causes"):
        if not f.get(k):
            errs.append(f"front matter: '{k}' is missing")
    if attempt_id and f.get("attempt") and f["attempt"] != attempt_id:
        errs.append(f"front matter: attempt {f['attempt']} is not this attempt ({attempt_id})")
    for k in ("detected", "mitigated"):
        if f.get(k):
            try:
                parse_time(f[k], 0)
            except ValueError:
                errs.append(f"front matter: '{k}' is not a time: {f[k]!r} (use 2026-10-09T12:03:10Z)")
    known = {c["id"] for c in catalog["causes"]}
    unknown = [c for c in doc["causes"] if c not in known]
    if unknown:
        errs.append(f"unknown cause ids {unknown}; pick from the catalog (make postmortem lists them)")
    if len(set(doc["causes"])) != len(doc["causes"]):
        errs.append("a cause is listed twice")
    bad_kinds = sorted(set(doc["actions"]) - set(ACTION_KINDS))
    if bad_kinds:
        errs.append(f"action items: unknown kinds {bad_kinds}, use {list(ACTION_KINDS)}")
    return errs


def occurred(catalog, seed):
    """(root causes, contributing factors) that this seed's incident really had."""
    root, contrib = set(), set()
    for c in catalog["causes"]:
        kind = c.get("kind", "root")
        if kind == "decoy":
            continue
        w = c.get("when")
        if w:
            m = WHEN_RE.match(w)
            if not m:
                raise ValueError(f"bad when: {w}")
            i, mod, val = (int(x) for x in m.groups())
            if int(seed[i], 16) % mod != val:
                continue
        (root if kind == "root" else contrib).add(c["id"])
    return root, contrib


def linear(x, full, zero):
    if x <= full:
        return 1.0
    return max(0.0, 1 - (x - full) / (zero - full))


def evaluate(doc, catalog, seed, t_break, t_recovered, t_submit):
    """Score 0..100 plus feedback. t_recovered: start of the final healthy streak
    the grader saw (None if the service never recovered)."""
    tol = float(catalog.get("timeline_tolerance_s", 30))
    root, contrib = occurred(catalog, seed)
    claimed = set(doc["causes"])
    recall = len(claimed & root) / len(root) if root else 1.0
    precision = len(claimed & (root | contrib)) / len(claimed) if claimed else 0.0

    f = doc["front"]
    detected = parse_time(f["detected"], t_break)
    mitigated = parse_time(f["mitigated"], t_break)
    mit_err = abs(mitigated - t_recovered) if t_recovered else None
    stamps = []
    for s in doc["timeline"]:
        try:
            stamps.append(parse_time(s, t_break))
        except ValueError:
            stamps.append(None)
    timeline_ok = (len(stamps) >= 4 and None not in stamps
                   and all(t_break - 600 <= t <= t_submit + 60 for t in stamps)
                   and all(a <= b for a, b in zip(stamps, stamps[1:])))
    present = [s for s in SECTIONS if doc["sections"].get(s)]

    parts = {
        "causes_recall": WEIGHTS["causes_recall"] * recall,
        "causes_precision": WEIGHTS["causes_precision"] * precision,
        "mitigated": WEIGHTS["mitigated"] * (linear(mit_err, tol, 10 * tol) if mit_err is not None else 0.0),
        "detected": WEIGHTS["detected"] * (t_break - tol <= detected <= mitigated),
        "timeline": WEIGHTS["timeline"] * timeline_ok,
        "sections": WEIGHTS["sections"] * len(present) / len(SECTIONS),
        "action_items": WEIGHTS["action_items"] * (("prevent" in doc["actions"]) + ("detect" in doc["actions"])) / 2,
    }
    score = round(sum(parts.values()), 1)
    return {
        "score": score,
        # a post-mortem that names a cause which did not happen sends the fix the wrong way
        "verdict": "verified" if score >= PASS_SCORE and recall == 1.0 and claimed <= root | contrib else "insufficient",
        "parts": {k: round(v, 2) for k, v in parts.items()},
        "causes": {"confirmed": sorted(claimed & root), "contributing": sorted(claimed & contrib),
                   "missed": sorted(root - claimed), "wrong": sorted(claimed - root - contrib)},
        "timeline": {"incident_start": t_break, "server_recovered": t_recovered,
                     "claimed_mitigated": mitigated, "mitigated_error_s": round(mit_err, 1) if mit_err is not None else None,
                     "claimed_detected": detected, "tolerance_s": tol, "entries": len(stamps),
                     "entries_ok": timeline_ok},
        "sections_missing": [s for s in SECTIONS if s not in present],
        "action_kinds": sorted(set(doc["actions"])),
    }


def summary_lines(r):
    c, t = r["causes"], r["timeline"]
    err = f"{t['mitigated_error_s']} s" if t["mitigated_error_s"] is not None else "service never recovered"
    out = [f"causes: confirmed {c['confirmed'] or '-'} | missed {c['missed'] or '-'} | wrong {c['wrong'] or '-'}"
           + (f" | contributing {c['contributing']}" if c["contributing"] else ""),
           f"timeline: 'mitigated' off by {err} (tolerance {t['tolerance_s']:.0f} s), "
           f"{t['entries']} entries{'' if t['entries_ok'] else ' (need >= 4, in order, inside the incident)'}"]
    if r["sections_missing"]:
        out.append(f"sections missing: {r['sections_missing']}")
    for k, v in r["parts"].items():
        out.append(f"  {k:<17} {v:6.1f} / {WEIGHTS[k]}")
    return out
