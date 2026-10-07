#!/usr/bin/env python3
"""Score an incident run from evidence only (probes, timeline, assertions,
instance snapshots). Writes .state/evidence/report.json + ed25519 signature.

    python framework/score.py <scenario_dir>

All weights, thresholds and penalties come from <scenario_dir>/generated/scoring.json,
which `dsl/validate.py --emit` generates from the `scoring` block of scenario.yaml.
"""
import hashlib
import json
import math
import os
import subprocess
import sys
import time


def load_env(state):
    env = {}
    for line in open(os.path.join(state, "scenario.env")):
        k, _, v = line.strip().partition("=")
        if k:
            env[k] = v
    return env


def timeline(state):
    rows = []
    for line in open(os.path.join(state, "timeline.tsv")):
        ts, _, ev = line.rstrip("\n").partition("\t")
        rows.append((float(ts), ev))
    return rows


def identities(state, name):
    """svc -> instance identity (container StartedAt / pod name:restarts), see lib.sh snapshot()."""
    rows = (l.rstrip("\n").split("\t", 1) for l in open(os.path.join(state, name)) if l.strip())
    return {r[0]: (r[1] if len(r) > 1 else "") for r in rows}


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


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main(scn):
    state = os.path.join(scn, ".state")
    evid = os.path.join(state, "evidence")
    cfg = json.load(open(os.path.join(scn, "generated", "scoring.json")))
    W, P, T, C = cfg["weights"], cfg["penalties"], cfg["tiers"], cfg["caps"]
    env = load_env(state)
    tl = timeline(state)
    breaks = [ts for ts, ev in tl if ev == "break"]
    if not breaks:
        sys.exit("no break in timeline: run `make break` first")
    t_break = breaks[-1]
    now = time.time()
    hints = sum(1 for _, ev in tl if ev.startswith("hint "))

    probes = [json.loads(l) for l in open(os.path.join(evid, "probes.jsonl")) if l.strip()]
    inc = [p for p in probes if p["ts"] >= t_break]
    if not inc:
        sys.exit("no probes since break")

    # MTTR: first failed probe after break -> start of the final unbroken healthy streak
    first_fail = next((p["ts"] for p in inc if not p["ok"]), None)
    recovered = None
    for p in reversed(inc):
        if not p["ok"]:
            break
        recovered = p["ts"]
    mttr = (recovered - first_fail) if (recovered and first_fail) else None

    availability = sum(p["ok"] for p in inc) / len(inc)
    window = float(env.get("STABLE_WINDOW", 60))
    tail = [p["lat_ms"] for p in inc if p["ok"] and p["ts"] >= now - window]
    p95, p99 = pct(tail, 95), pct(tail, 99)

    # Blast radius: services the incident did not require touching
    base, cur = identities(state, "baseline.tsv"), identities(state, "current.tsv")
    br = cfg["blast_radius"]
    restarted = [s for s in br["unaffected"] if cur.get(s) != base.get(s)]
    rp = br.get("recreate_penalty") or {}
    recreated = bool(rp) and env.get("MODE", "docker") == rp.get("mode", "docker") \
        and cur.get(rp["service"]) != base.get(rp["service"])

    asr = json.load(open(os.path.join(state, "assertions.json")))
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
        "recreated": rp.get("points", 0) * recreated,
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

    files = {}
    for rel in cfg.get("evidence_files", []):
        d = os.path.join(scn, rel)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            files[f"{rel}/{f}"] = sha256(os.path.join(d, f))
    report = {
        "scenario": env["SCENARIO"], "user": env["USER_ID"], "seed_prefix": env["SEED"][:12], "mode": env.get("MODE"),
        "generated_at": now, "incident_start": t_break,
        "sli": {"availability": round(availability, 4), "p95_ms": p95, "p99_ms": p99,
                "probes": len(inc), "mttr_s": round(mttr, 1) if mttr else None},
        "blast_radius": {"restarted_unaffected": restarted, "recreated": recreated},
        "hints_used": hints,
        "parts": {k: round(v, 2) for k, v in parts.items()},
        "penalties": penalties,
        "security_weakened": weakened,
        "score": round(score, 1), "tier": tier,
        "assertions": asr,
        "evidence": files,
        "timeline": [{"ts": ts, "event": ev} for ts, ev in tl],
    }
    rpath = os.path.join(evid, "report.json")
    with open(rpath, "w") as f:
        json.dump(report, f, indent=2)
    subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", os.path.join(evid, "signing.key"),
                    "-rawin", "-in", rpath, "-out", rpath + ".sig"], check=True)

    m = f"{mttr/60:.1f} min" if mttr else "not recovered"
    print(f"availability {availability:.1%} | MTTR {m} | p95 {p95} ms | hints {hints} | "
          f"blast radius {restarted or 'none'}{' + ' + rp['service'] + ' recreated' if recreated else ''}")
    for k, v in parts.items():
        print(f"  {k:<16} {v:6.1f} / {W[k]}")
    for k, v in penalties.items():
        if v:
            print(f"  penalty {k:<8} -{v}")
    print(f"SCORE {score:.1f}  TIER {tier.upper()}   (signed: {os.path.relpath(rpath + '.sig', scn)})")
    return 0 if tier != "fail" else 1


if __name__ == "__main__":
    sys.exit(main(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")))
