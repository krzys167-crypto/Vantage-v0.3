"""Pure scoring: evidence in, result out. No I/O, so the local CLI (score.py) and
the server-side grader compute exactly the same thing from their own inputs.

cfg            generated/scoring.json of the scenario
mode           "docker" | "k3d" (recreate penalties are per mode)
stable_window  seconds used for the p95 tail
t_break        incident start (epoch s)
now            scoring time (epoch s)
hints          number of hints taken
probes         [{"ts", "ok", "lat_ms", ...}] (all, any order)
asr            assertions.json content
base, cur      {service: instance identity} at break / at scoring
"""
import math


def linear(x, full, zero):
    if x is None:
        return 0.0
    if x <= full:
        return 1.0
    return max(0.0, 1 - (x - full) / (zero - full))


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, math.ceil(p / 100 * len(s)) - 1)]


def compute(cfg, mode, stable_window, t_break, now, hints, probes, asr, base, cur):
    W, P, T, C = cfg["weights"], cfg["penalties"], cfg["tiers"], cfg["caps"]
    inc = sorted((p for p in probes if p["ts"] >= t_break), key=lambda p: p["ts"])
    if not inc:
        raise ValueError("no probes since break")

    # MTTR: first failed probe after break -> start of the final unbroken healthy streak
    first_fail = next((p["ts"] for p in inc if not p["ok"]), None)
    recovered = None
    for p in reversed(inc):
        if not p["ok"]:
            break
        recovered = p["ts"]
    mttr = (recovered - first_fail) if (recovered and first_fail) else None

    availability = sum(p["ok"] for p in inc) / len(inc)
    tail = [p["lat_ms"] for p in inc if p["ok"] and p["ts"] >= now - stable_window]
    p95, p99 = pct(tail, 95), pct(tail, 99)

    # Blast radius: services the incident did not require touching
    br = cfg["blast_radius"]
    restarted = [s for s in br["unaffected"] if cur.get(s) != base.get(s)]
    # recreate_penalty: one rule or a list; a rule applies only in its runtime mode
    rules = br.get("recreate_penalty") or []
    rules = [rules] if isinstance(rules, dict) else rules
    recreated = [r for r in rules if mode == r.get("mode", "docker")
                 and cur.get(r["service"]) != base.get(r["service"])]

    hidden_ratio = asr["hidden_pass"] / max(1, asr["hidden_total"])
    parts = {
        "availability": W["availability"] * availability,
        "time_to_recover": W["time_to_recover"] * linear(mttr, cfg["time_to_recover"]["full_s"], cfg["time_to_recover"]["zero_s"]),
        "latency": W["latency"] * linear(p95, cfg["latency"]["full_p95_ms"], cfg["latency"]["zero_p95_ms"]),
        "blast_radius": W["blast_radius"] * (1 - min(1, len(restarted) / max(1, len(br["unaffected"])))),
        "hidden": W["hidden"] * hidden_ratio,
    }
    penalties = {
        "hints": P["hint"] * hints,
        "restart_unaffected": P["restart_unaffected"] * len(restarted),
        "recreated": sum(r.get("points", 0) for r in recreated),
    }
    score = max(0.0, sum(parts.values()) - sum(penalties.values()))
    failed = not asr["public_pass"] or mttr is None
    if failed:
        score = min(score, C["public_fail"])
    tiers = sorted(T.items(), key=lambda kv: -kv[1])
    tier = next((name for name, th in tiers if score >= th), "fail")
    if tier == "elite" and hidden_ratio < 1:
        tier = "merit"
    weakened = [a["id"] for a in asr["assertions"] if a["id"] in cfg["security_critical"] and not a["pass"]]
    if weakened:
        score = min(score, C["security_weakened"])
        tier = "pass" if score >= T["pass"] else "fail"
    if failed:
        tier = "fail"

    return {
        "incident_start": t_break,
        "sli": {"availability": round(availability, 4), "p95_ms": p95, "p99_ms": p99,
                "probes": len(inc), "mttr_s": round(mttr, 1) if mttr else None},
        "blast_radius": {"restarted_unaffected": restarted, "recreated": [r["service"] for r in recreated]},
        "hints_used": hints,
        "parts": {k: round(v, 2) for k, v in parts.items()},
        "penalties": penalties,
        "security_weakened": weakened,
        "score": round(score, 1),
        "tier": tier,
    }


def summary_lines(cfg, r):
    """Human-readable lines shared by the CLI and the grader client."""
    s, br = r["sli"], r["blast_radius"]
    m = f"{s['mttr_s'] / 60:.1f} min" if s["mttr_s"] else "not recovered"
    out = [f"availability {s['availability']:.1%} | MTTR {m} | p95 {s['p95_ms']} ms | hints {r['hints_used']} | "
           f"blast radius {br['restarted_unaffected'] or 'none'}"
           f"{' + recreated ' + ','.join(br['recreated']) if br['recreated'] else ''}"]
    for k, v in r["parts"].items():
        out.append(f"  {k:<16} {v:6.1f} / {cfg['weights'][k]}")
    for k, v in r["penalties"].items():
        if v:
            out.append(f"  penalty {k:<8} -{v}")
    return out
