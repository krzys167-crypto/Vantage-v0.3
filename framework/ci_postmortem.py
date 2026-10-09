#!/usr/bin/env python3
"""SPOILER, CI only: the reference post-mortem for a finished graded attempt
(what solution/fix.sh is to the incident).

    ci_postmortem.py <scenario_dir> [out.md]

Causes come from the catalog and the attempt's seed, the recovery time from
the local probe evidence, i.e. what a trainee would read off their own data.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import debrief as pm  # noqa: E402
import postmortem  # noqa: E402
from scoring import recovery  # noqa: E402


def main(scn, out="postmortem.md"):
    state = postmortem.state_dir(scn)
    env = dict(l.strip().split("=", 1) for l in open(os.path.join(state, "scenario.env")) if "=" in l)
    root, contrib = pm.occurred(postmortem.catalog(scn), env["SEED"])
    start = json.load(open(os.path.join(state, "evidence", "server_report.json")))["result"]["incident_start"]
    probes = []
    for line in open(os.path.join(state, "evidence", "probes.jsonl")):
        try:
            p = json.loads(line)
            probes.append({"ts": float(p["ts"]), "ok": bool(p.get("ok"))})
        except (ValueError, KeyError):
            pass
    _, recovered = recovery(sorted((p for p in probes if p["ts"] >= start), key=lambda p: p["ts"]))
    if not recovered:
        sys.exit("ci_postmortem: the probes never recovered")
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))  # noqa: E731
    hm = lambda t: time.strftime("%H:%M:%SZ", time.gmtime(t))  # noqa: E731

    if os.path.exists(out):
        os.remove(out)
    postmortem.template(scn, out)
    md = open(out).read()
    detected = min(start + 5, recovered)
    for k, v in (("detected", iso(detected)), ("mitigated", iso(recovered)),
                 ("causes", ", ".join(sorted(root | contrib)))):
        md = re.sub(rf"^{k}:.*$", f"{k}: {v}", md, count=1, flags=re.M)
    fill = {
        "## Summary": "Users could not complete requests until both injected faults were reverted.",
        "## Impact": f"Every synthetic probe failed from {hm(start)} to {hm(recovered)}.",
        "## Root cause": "; ".join(sorted(root)),
        "## Resolution": "Reverted the faulty changes and verified the stable window.",
    }
    for head, body in fill.items():
        md = md.replace(f"{head}\n", f"{head}\n{body}\n", 1)
    md = md.replace("(grader: break)\n", f"(grader: break)\n- {hm(detected)} alert fired\n"
                                         f"- {hm(detected)} evidence collected\n- {hm(recovered)} service recovered\n", 1)
    md = md.replace("- [prevent]\n", "- [prevent] review risky config changes before rollout\n", 1)
    md = md.replace("- [detect]\n", "- [detect] alert on the failing SLI within a minute\n", 1)
    with open(out, "w") as f:
        f.write(md)
    print(f"reference post-mortem: {out} (causes {sorted(root | contrib)})")


if __name__ == "__main__":
    main(*sys.argv[1:])
