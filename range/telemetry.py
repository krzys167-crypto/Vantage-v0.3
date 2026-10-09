"""Behaviour telemetry for the hosted range: where trainees get stuck.

Server-side only (no third-party trackers) and pseudonymous: users are stored
as their league alias (sha256 prefix), never as e-mail addresses.

    t = Telemetry("/var/lib/vantage/telemetry.db")
    t.record(user, "start", scenario="dns-poison", session="ab12cd34")
    t.funnel(since_ts)            # stage counts, conversion, median stage times

Funnel stages, per (user, session):
    start -> ready -> kubeconfig -> graded -> passed
plus "returned": users with sessions on two or more distinct days. (Post-mortems
are sent from the CLI straight to the grader; "debriefed" joins the funnel once
the panel sends them.)
"""
import json
import os
import sqlite3
import statistics
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "grader"))
from league import alias  # noqa: E402

EVENTS = {"start", "ready", "start_failed", "kubeconfig", "grade", "graded", "grade_failed", "stop", "expired",
          "panel", "debriefed"}
STAGES = ["start", "ready", "kubeconfig", "graded", "passed"]


class Telemetry:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS events (ts REAL, user TEXT, event TEXT, session TEXT, "
                        "scenario TEXT, data TEXT)")
        self.db.commit()
        self.lock = threading.Lock()

    def record(self, user, event, session=None, scenario=None, **data):
        if event not in EVENTS:
            raise ValueError(f"unknown telemetry event {event}")
        with self.lock:
            self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)",
                            (time.time(), alias(user), event, session, scenario, json.dumps(data)[:1000]))
            self.db.commit()

    def funnel(self, since=0.0):
        rows = self.db.execute("SELECT ts, user, event, session, scenario, data FROM events WHERE ts >= ? ORDER BY ts",
                               (since,)).fetchall()
        attempts = {}     # (user, start ts) -> first time each stage was reached
        current = {}      # user -> key of the attempt in progress (sessions are per user, one at a time)
        days = {}
        for ts, user, ev, session, scenario, data in rows:
            if ev == "start":
                current[user] = (user, ts)
                attempts[current[user]] = {"scenario": scenario, "start": ts}
                days.setdefault(user, set()).add(time.strftime("%Y-%m-%d", time.gmtime(ts)))
                continue
            key = current.get(user)
            if not key:
                continue
            a = attempts[key]
            d = json.loads(data or "{}")
            stage = {"ready": "ready", "kubeconfig": "kubeconfig", "graded": "graded"}.get(ev)
            if stage and stage not in a:
                a[stage] = ts
            if ev == "graded" and d.get("attested") and d.get("tier") in ("pass", "merit", "elite") and "passed" not in a:
                a["passed"] = ts
            if ev in ("start_failed", "grade_failed"):
                a.setdefault("failures", []).append(ev)

        def med(pairs):
            vals = [b - a for a, b in pairs]
            return round(statistics.median(vals), 1) if vals else None

        counts = {s: sum(1 for a in attempts.values() if s in a) for s in STAGES}
        conv = {f"{a}->{b}": (round(counts[b] / counts[a], 3) if counts[a] else None)
                for a, b in zip(STAGES, STAGES[1:])}
        times = {
            "start->ready_s": med([(a["start"], a["ready"]) for a in attempts.values() if "ready" in a]),
            "ready->kubeconfig_s": med([(a["ready"], a["kubeconfig"]) for a in attempts.values()
                                        if "ready" in a and "kubeconfig" in a]),
            "ready->graded_s": med([(a["ready"], a["graded"]) for a in attempts.values()
                                    if "ready" in a and "graded" in a]),
        }
        per_scenario = {}
        for a in attempts.values():
            p = per_scenario.setdefault(a["scenario"], {"started": 0, "passed": 0})
            p["started"] += 1
            p["passed"] += "passed" in a
        # stuck = reached a stage and went no further: where to look first
        stuck = {s: sum(1 for a in attempts.values() if s in a and all(n not in a for n in STAGES[i + 1:]))
                 for i, s in enumerate(STAGES[:-1])}
        return {"since": since, "attempts": len(attempts), "users": len(days),
                "returned_users": sum(1 for d in days.values() if len(d) >= 2),
                "stages": counts, "conversion": conv, "median_times": times, "stuck_after": stuck,
                "failures": sum(len(a.get("failures", [])) for a in attempts.values()),
                "per_scenario": per_scenario}
