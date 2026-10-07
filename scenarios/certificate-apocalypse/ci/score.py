#!/usr/bin/env python3
"""Score an incident run from evidence only (probes, timeline, assertions,
container start times). Writes .state/evidence/report.json + ed25519 signature.

Weights mirror `scoring` in scenario.yaml.
"""
import hashlib
import json
import math
import os
import subprocess
import sys
import time

SCN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(SCN, ".state")
EVID = os.path.join(STATE, "evidence")

WEIGHTS = {"availability": 20, "time_to_recover": 35, "latency": 10, "blast_radius": 15, "hidden": 20}
MTTR_FULL_S, MTTR_ZERO_S = 600, 3600          # full points <= 10 min, zero at 60 min
P95_FULL_MS, P95_ZERO_MS = 50, 500
PENALTY = {"hint": 5, "restart_unaffected": 10, "gateway_recreated": 3}
TIERS = [("elite", 92), ("merit", 80), ("pass", 60)]
FAIL_CAP = 40                                   # public assertions failing caps the score
SECURITY_CRITICAL = {"H3", "H5"}                # "fixed" by weakening security -> at most PASS
SECURITY_CAP = 65


def load_env():
    env = {}
    for line in open(os.path.join(STATE, "scenario.env")):
        k, _, v = line.strip().partition("=")
        if k:
            env[k] = v
    return env


def timeline():
    rows = []
    for line in open(os.path.join(STATE, "timeline.tsv")):
        ts, _, ev = line.rstrip("\n").partition("\t")
        rows.append((float(ts), ev))
    return rows


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


def identities(name):
    """svc -> instance identity (container StartedAt / pod name:restarts), see lib.sh snapshot()."""
    rows = (l.rstrip("\n").split("\t", 1) for l in open(os.path.join(STATE, name)) if l.strip())
    return {r[0]: (r[1] if len(r) > 1 else "") for r in rows}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def main():
    env = load_env()
    tl = timeline()
    breaks = [ts for ts, ev in tl if ev == "break"]
    if not breaks:
        sys.exit("no break in timeline: run `make break` first")
    t_break = breaks[-1]
    now = time.time()
    hints = sum(1 for _, ev in tl if ev.startswith("hint "))

    probes = [json.loads(l) for l in open(os.path.join(EVID, "probes.jsonl")) if l.strip()]
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
    if inc[-1]["ok"] is False:
        recovered = None
    mttr = (recovered - first_fail) if (recovered and first_fail) else None

    availability = sum(p["ok"] for p in inc) / len(inc)
    window = float(env.get("STABLE_WINDOW", 60))
    tail = [p["lat_ms"] for p in inc if p["ok"] and p["ts"] >= now - window]
    p95 = pct(tail, 95)
    p99 = pct(tail, 99)

    # Blast radius: services the incident did not require touching
    # (assertions.sh writes current.tsv right before scoring)
    base, cur = identities("baseline.tsv"), identities("current.tsv")
    restarted = [s for s in ("backend", "prober") if cur.get(s) != base.get(s)]
    # On k3d a rolling restart is the normal way to load a new Secret: no penalty.
    gateway_recreated = env.get("MODE", "docker") == "docker" and cur.get("gateway") != base.get("gateway")

    asr = json.load(open(os.path.join(STATE, "assertions.json")))
    hidden_ratio = asr["hidden_pass"] / max(1, asr["hidden_total"])

    parts = {
        "availability": WEIGHTS["availability"] * availability,
        "time_to_recover": WEIGHTS["time_to_recover"] * linear(mttr, MTTR_FULL_S, MTTR_ZERO_S),
        "latency": WEIGHTS["latency"] * linear(p95, P95_FULL_MS, P95_ZERO_MS),
        "blast_radius": WEIGHTS["blast_radius"] * (1 - min(1, len(restarted) / 2)),
        "hidden": WEIGHTS["hidden"] * hidden_ratio,
    }
    penalties = {
        "hints": PENALTY["hint"] * hints,
        "restart_unaffected": PENALTY["restart_unaffected"] * len(restarted),
        "gateway_recreated": PENALTY["gateway_recreated"] * gateway_recreated,
    }
    score = max(0.0, sum(parts.values()) - sum(penalties.values()))
    if not asr["public_pass"] or mttr is None:
        score = min(score, FAIL_CAP)
    tier = next((name for name, th in TIERS if score >= th), "fail")
    if tier == "elite" and hidden_ratio < 1:
        tier = "merit"
    weakened = [a["id"] for a in asr["assertions"] if a["id"] in SECURITY_CRITICAL and not a["pass"]]
    if weakened:
        score = min(score, SECURITY_CAP)
        tier = "pass" if score >= TIERS[-1][1] else "fail"
    if not asr["public_pass"] or mttr is None:
        tier = "fail"

    pki = os.path.join(STATE, "pki", "gateway")
    report = {
        "scenario": env["SCENARIO"], "user": env["USER_ID"], "seed_prefix": env["SEED"][:12],
        "generated_at": now, "incident_start": t_break,
        "sli": {"availability": round(availability, 4), "p95_ms": p95, "p99_ms": p99,
                "probes": len(inc), "mttr_s": round(mttr, 1) if mttr else None},
        "blast_radius": {"restarted_unaffected": restarted, "gateway_recreated": gateway_recreated},
        "hints_used": hints,
        "parts": {k: round(v, 2) for k, v in parts.items()},
        "penalties": penalties,
        "security_weakened": weakened,
        "score": round(score, 1), "tier": tier,
        "assertions": asr,
        "evidence": {f: sha256(os.path.join(pki, f)) for f in sorted(os.listdir(pki)) if f.endswith((".pem", ".key"))},
        "timeline": [{"ts": ts, "event": ev} for ts, ev in tl],
    }
    rpath = os.path.join(EVID, "report.json")
    with open(rpath, "w") as f:
        json.dump(report, f, indent=2)
    subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", os.path.join(EVID, "signing.key"),
                    "-rawin", "-in", rpath, "-out", rpath + ".sig"], check=True)

    m = f"{mttr/60:.1f} min" if mttr else "not recovered"
    print(f"availability {availability:.1%} | MTTR {m} | p95 {p95} ms | hints {hints} | "
          f"blast radius {restarted or 'none'}{' + gateway recreated' if gateway_recreated else ''}")
    for k, v in parts.items():
        print(f"  {k:<16} {v:6.1f} / {WEIGHTS[k]}")
    for k, v in penalties.items():
        if v:
            print(f"  penalty {k:<8} -{v}")
    print(f"SCORE {score:.1f}  TIER {tier.upper()}   (signed: {os.path.relpath(rpath + '.sig', SCN)})")
    return 0 if tier != "fail" else 1


if __name__ == "__main__":
    sys.exit(main())
