#!/usr/bin/env python3
"""Post-mortem (debrief) client: write, check, sign and send the incident write-up.

    postmortem.py template <scenario_dir> [out.md]    -> skeleton for this attempt + cause catalog
    postmortem.py lint     <scenario_dir> <file.md>   -> the grader's hard checks, locally
    postmortem.py sign     <file.md> [bundle.json]    -> signed with your key (attempt id from the front matter)
    postmortem.py send     <scenario_dir> <bundle.json>
    postmortem.py submit   <scenario_dir> <file.md>   -> lint + sign + send (make debrief)
    postmortem.py keygen                              -> prints your key's fingerprint

Your key: $VANTAGE_USER_KEY or ~/.vantage/user.key (ed25519, created on first
use). The grader binds it to your user on your first post-mortem, so keep it.
One post-mortem per attempt: lint first, problems with the format are free,
a wrong root cause is not.
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import debrief as pm  # noqa: E402

KEY = os.environ.get("VANTAGE_USER_KEY") or os.path.expanduser("~/.vantage/user.key")


def die(msg):
    sys.stderr.write(f"postmortem: {msg}\n")
    sys.exit(1)


def state_dir(scn):
    return os.environ.get("VANTAGE_STATE") or os.path.join(scn, ".state")


def catalog(scn):
    path = os.path.join(scn, "generated", "debrief.json")
    if not os.path.exists(path):
        die(f"{os.path.basename(os.path.abspath(scn))} has no post-mortem catalog (generated/debrief.json)")
    return json.load(open(path))


def attempt_id(scn):
    try:
        return json.load(open(os.path.join(state_dir(scn), "attempt.json")))["attempt_id"]
    except FileNotFoundError:
        die("no graded attempt: post-mortems are checked by the grader (GRADER_URL, make submit)")


def keygen():
    if not os.path.exists(KEY):
        os.makedirs(os.path.dirname(KEY), mode=0o700, exist_ok=True)
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", KEY], check=True, capture_output=True)
        os.chmod(KEY, 0o600)
    pub = subprocess.run(["openssl", "pkey", "-in", KEY, "-pubout"], check=True, capture_output=True, text=True).stdout
    der = subprocess.run(["openssl", "pkey", "-in", KEY, "-pubout", "-outform", "DER"], check=True,
                         capture_output=True).stdout
    return pub, hashlib.sha256(der).hexdigest()


def template(scn, out=None):
    cat, aid = catalog(scn), attempt_id(scn)
    start = None
    report = os.path.join(state_dir(scn), "evidence", "server_report.json")
    if os.path.exists(report):
        start = json.load(open(report))["result"]["incident_start"]
    t = time.strftime("%H:%M:%SZ", time.gmtime(start)) if start else "HH:MM:SSZ"
    width = max(len(c["id"]) for c in cat["causes"])
    lines = "\n".join(f"  {c['id']:<{width}}  {c['text']}" for c in cat["causes"])
    text = f"""---
attempt: {aid}
detected:
mitigated:
causes:
---
<!--
detected / mitigated: UTC, e.g. {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(start or time.time()))}.
  'mitigated' is checked against the grader's probes (when users were served again).
causes: comma-separated ids of what THIS incident had (root causes and contributing
  factors). Several are plausible, some are decoys; every wrong id costs points.
{lines}
Timeline bullets start with a UTC time; action items with [prevent], [detect],
[mitigate] or [process]. One post-mortem per attempt: run 'make lint-postmortem' first.
-->
# Post-mortem: {os.path.basename(os.path.abspath(scn))}

## Summary

## Impact

## Timeline
- {t} incident started (grader: break)

## Root cause

## Resolution

## Action items
- [prevent]
- [detect]
"""
    if out:
        if os.path.exists(out):
            die(f"{out} exists; edit it, or remove it for a fresh template")
        with open(out, "w") as f:
            f.write(text)
        print(f"post-mortem template: {out}")
    else:
        sys.stdout.write(text)


def lint(scn, path, quiet=False):
    md = open(path).read()
    # on a hosted range the attempt lives with the controller: the grader checks the id
    aid = attempt_id(scn) if os.path.exists(os.path.join(state_dir(scn), "attempt.json")) else None
    errs = pm.lint(pm.parse(md), catalog(scn), aid)
    for e in errs:
        print(f"  xx {e}")
    if not errs and not quiet:
        doc = pm.parse(md)
        print(f"  ok format; {len(doc['causes'])} causes, {len(doc['timeline'])} timeline entries, "
              f"action kinds {sorted(set(doc['actions']))}")
    return 1 if errs else 0


def sign(path, out=None):
    md = open(path).read()
    aid = pm.parse(md)["front"].get("attempt")
    if not aid:
        die("front matter has no 'attempt'")
    pub, fp = keygen()
    with tempfile.NamedTemporaryFile() as msg:      # ed25519 needs a regular file for -rawin
        msg.write(pm.message(aid, md))
        msg.flush()
        sig = subprocess.run(["openssl", "pkeyutl", "-sign", "-inkey", KEY, "-rawin", "-in", msg.name],
                             check=True, capture_output=True).stdout
    bundle = {"attempt_id": aid, "markdown": md, "pubkey": pub, "signature": base64.b64encode(sig).decode(),
              "key_sha256": fp}
    if out:
        with open(out, "w") as f:
            json.dump(bundle, f, indent=2)
        print(f"signed for attempt {aid} with key {fp[:16]}: {out}")
    return bundle


def send(scn, bundle):
    if isinstance(bundle, str):
        bundle = json.load(open(bundle))
    from grader_client import URL, call
    if not URL:
        die("GRADER_URL is not set")
    a = json.load(open(os.path.join(state_dir(scn), "attempt.json")))
    if bundle["attempt_id"] != a["attempt_id"]:
        die(f"signed for attempt {bundle['attempt_id']}, this is {a['attempt_id']}")
    code, res = call("POST", f"/v1/attempts/{a['attempt_id']}/debrief",
                     {k: bundle[k] for k in ("markdown", "pubkey", "signature")}, a["token"], timeout=30)
    if code != 200:
        for p in res.get("problems", []):
            print(f"  xx {p}")
        die(f"post-mortem rejected ({code}): {res.get('error')}")
    out = os.path.join(state_dir(scn), "evidence", "debrief_report.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=2)
    r = res["result"]
    print("\n".join(pm.summary_lines(r)))
    print(f"  trust: causes={r['trust']['causes']}")
    print(f"DEBRIEF SCORE {r['score']:.1f}  {r['verdict'].upper()}   (attempt {r['attempt_id']}, "
          f"{os.path.relpath(out, scn)})")
    return 0 if r["verdict"] == "verified" else 1


def submit(scn, path):
    if lint(scn, path, quiet=True):
        die("fix the problems above first (nothing was sent)")
    return send(scn, sign(path))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    fns = {"template": template, "lint": lint, "sign": sign, "send": send, "submit": submit,
           "keygen": lambda: print(f"key {KEY}\nsha256 {keygen()[1]}")}
    if cmd not in fns:
        sys.exit(__doc__)
    r = fns[cmd](*args)
    sys.exit(r if isinstance(r, int) else 0)
