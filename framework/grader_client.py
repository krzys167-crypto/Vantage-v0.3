#!/usr/bin/env python3
"""Client side of the grader protocol, used by framework/lib.sh when GRADER_URL is set.

    grader_client.py create  <state_dir> <scenario> <user>     -> prints seed
    grader_client.py event   <state_dir> <type> [json_data]
    grader_client.py push    <state_dir>                        -> sends probes not sent yet
    grader_client.py submit  <scenario_dir>                     -> prints the signed server result
    grader_client.py profile [user]                             -> your badges and bests (signed)
    grader_client.py league  [YYYY-MM]                          -> the monthly league (signed, aliases)

The attempt id and token live in <state_dir>/attempt.json; the push offset in
<state_dir>/grader.offset. Stdlib only, no proxy (the grader is usually local or
on a private network).
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoring import summary_lines  # noqa: E402

URL = os.environ.get("GRADER_URL", "").rstrip("/")
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, path, body=None, token=None, timeout=10, headers=None):
    req = urllib.request.Request(URL + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {token}"} if token else {}),
                                          **(headers or {})})
    try:
        with OP.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {"error": f"http {e.code}"}


def attempt(state):
    with open(os.path.join(state, "attempt.json")) as f:
        return json.load(f)


def die(msg):
    sys.stderr.write(f"grader: {msg}\n")
    sys.exit(1)


def create(state, scenario, user):
    import time
    code, a = call("POST", "/v1/attempts", {"scenario": scenario, "user": user, "client_time": time.time()})
    if code != 201:
        die(f"cannot start attempt ({code}): {a.get('error')}")
    with open(os.path.join(state, "attempt.json"), "w") as f:
        json.dump(a, f)
    os.chmod(os.path.join(state, "attempt.json"), 0o600)
    print(a["seed"])


def event(state, etype, data="{}"):
    a = attempt(state)
    code, r = call("POST", f"/v1/attempts/{a['attempt_id']}/events", {"type": etype, "data": json.loads(data)},
                   a["token"])
    if code != 200:
        die(f"event {etype} rejected ({code}): {r.get('error')}")


def push(state):
    """Send probe lines appended since the last push. Called every few seconds."""
    a = attempt(state)
    path = os.path.join(state, "evidence", "probes.jsonl")
    off_path = os.path.join(state, "grader.offset")
    offset = int(open(off_path).read() or 0) if os.path.exists(off_path) else 0
    if not os.path.exists(path):
        return
    with open(path) as f:
        lines = f.readlines()
    # k3d re-syncs the whole prober log each time: shrinking means a new pod, start over
    if offset > len(lines):
        offset = 0
    batch = []
    for line in lines[offset:]:
        try:
            batch.append(json.loads(line))
        except ValueError:
            pass
    if batch:
        code, r = call("POST", f"/v1/attempts/{a['attempt_id']}/probes", {"probes": batch}, a["token"])
        if code != 200:
            die(f"probes rejected ({code}): {r.get('error')}")
    with open(off_path, "w") as f:
        f.write(str(len(lines)))


def identities(state, name):
    try:
        rows = (l.rstrip("\n").split("\t", 1) for l in open(os.path.join(state, name)) if l.strip())
        return {r[0]: (r[1] if len(r) > 1 else "") for r in rows}
    except FileNotFoundError:
        return {}


def submit(scn):
    state = os.environ.get("VANTAGE_STATE") or os.path.join(scn, ".state")
    a = attempt(state)
    env = dict(l.strip().split("=", 1) for l in open(os.path.join(state, "scenario.env")) if "=" in l)
    body = {"assertions": json.load(open(os.path.join(state, "assertions.json"))), "mode": env.get("MODE", "docker"),
            "baseline": identities(state, "baseline.tsv"), "current": identities(state, "current.tsv")}
    # a hosted-range controller identifies itself, so the grader knows the
    # assertions ran on the platform and not on the trainee's machine
    platform = os.environ.get("VANTAGE_PLATFORM_TOKEN")
    code, res = call("POST", f"/v1/attempts/{a['attempt_id']}/submit", body, a["token"], timeout=30,
                     headers={"X-Vantage-Platform": platform} if platform else None)
    if code != 200:
        die(f"submit rejected ({code}): {res.get('error')}")
    out = os.path.join(state, "evidence", "server_report.json")
    with open(out, "w") as f:
        json.dump(res, f, indent=2)
    r = res["result"]
    cfg = json.load(open(os.path.join(scn, "generated", "scoring.json")))
    print("\n".join(summary_lines(cfg, r)))
    i = r["integrity"]
    print(f"  integrity: stable={i['server_stable_ok']} max_gap={i['max_gap_during_incident_s']}s "
          f"rejected={i['rejected_probes'] or 0} wrong_flag={i['probes_with_wrong_flag']}")
    t = r.get("trust", {})
    print(f"  trust: assertions={t.get('assertions')} hidden={t.get('hidden')}")
    print(f"SERVER SCORE {r['score']:.1f}  TIER {r['tier'].upper()}  "
          f"{'ATTESTED' if r['attested'] else 'NOT ATTESTED'}   (attempt {r['attempt_id']}, {os.path.relpath(out, scn)})")
    return 0 if r["tier"] != "fail" else 1


def profile(user=None):
    import urllib.parse
    user = user or os.environ.get("USER_ID") or "anonymous"
    code, res = call("GET", f"/v1/users/{urllib.parse.quote(user, safe='')}/profile")
    if code != 200:
        die(f"profile ({code}): {res.get('error')}")
    p = res["result"]
    print(f"{p['user']} (league alias {p['alias']})")
    for scn, s in sorted(p["scenarios"].items()):
        m = f"{s['best_mttr_s'] / 60:.1f} min" if s["best_mttr_s"] else "-"
        print(f"  {scn:<24} best {s['best_score'] or '-':>5} {s['best_tier'] or '':<6} MTTR {m:<9} "
              f"attempts {s['attempts']}{'  post-mortem verified' if s['debrief_verified'] else ''}")
    for b in p["badges"]:
        print(f"  * {b['badge']:<16} {b['scenario'] or '':<24} attempt {b['attempt_id']}  ({b['text']})")
    if not p["badges"]:
        print("  no badges yet: they come from attested results and verified post-mortems only")


def league(month=None):
    code, res = call("GET", "/v1/league" + (f"?season={month}" if month else ""))
    if code != 200:
        die(f"league ({code}): {res.get('error')}")
    lg = res["result"]
    print(f"league {lg['season']}: {lg['rules']}")
    for r in lg["rows"]:
        print(f"  {r['rank']:>3}. {r['alias']:<14} {r['points']:>7.1f}  ({r['scenarios']} scenarios)")


if __name__ == "__main__":
    if not URL:
        die("GRADER_URL is not set")
    cmd, args = sys.argv[1], sys.argv[2:]
    sys.exit({"create": create, "event": event, "push": push, "submit": submit, "profile": profile,
              "league": league}[cmd](*args) or 0)
