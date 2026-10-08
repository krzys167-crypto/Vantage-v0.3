#!/usr/bin/env python3
"""Score an incident run locally from evidence only (probes, timeline,
assertions, instance snapshots). Writes .state/evidence/report.json + ed25519
signature with the local key.

    python framework/score.py <scenario_dir>

This is the practice score: everything it reads lives on your machine. For a
server-attested result use `make submit` with GRADER_URL set (see docs/grader.md).
All weights come from <scenario_dir>/generated/scoring.json (dsl/validate.py --emit).
"""
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoring import compute, summary_lines  # noqa: E402


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


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main(scn):
    state = os.path.join(scn, ".state")
    evid = os.path.join(state, "evidence")
    cfg = json.load(open(os.path.join(scn, "generated", "scoring.json")))
    env = load_env(state)
    tl = timeline(state)
    breaks = [ts for ts, ev in tl if ev == "break"]
    if not breaks:
        sys.exit("no break in timeline: run `make break` first")
    now = time.time()
    probes = [json.loads(l) for l in open(os.path.join(evid, "probes.jsonl")) if l.strip()]
    asr = json.load(open(os.path.join(state, "assertions.json")))
    try:
        r = compute(cfg, env.get("MODE", "docker"), float(env.get("STABLE_WINDOW", 60)), breaks[-1], now,
                    sum(1 for _, ev in tl if ev.startswith("hint ")), probes, asr,
                    identities(state, "baseline.tsv"), identities(state, "current.tsv"))
    except ValueError as e:
        sys.exit(str(e))

    files = {}
    for rel in cfg.get("evidence_files", []):
        d = os.path.join(scn, rel)
        for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            files[f"{rel}/{f}"] = sha256(os.path.join(d, f))
    report = dict({"scenario": env["SCENARIO"], "user": env["USER_ID"], "seed_prefix": env["SEED"][:12],
                   "mode": env.get("MODE"), "generated_at": now, "trust": "practice (local evidence, local key)"},
                  **r, assertions=asr, evidence=files, timeline=[{"ts": ts, "event": ev} for ts, ev in tl])
    rpath = os.path.join(evid, "report.json")
    with open(rpath, "w") as f:
        json.dump(report, f, indent=2)
    subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", os.path.join(evid, "signing.key"),
                    "-rawin", "-in", rpath, "-out", rpath + ".sig"], check=True)

    print("\n".join(summary_lines(cfg, r)))
    print(f"SCORE {r['score']:.1f}  TIER {r['tier'].upper()}   (practice, signed: {os.path.relpath(rpath + '.sig', scn)})")
    return 0 if r["tier"] != "fail" else 1


if __name__ == "__main__":
    sys.exit(main(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")))
