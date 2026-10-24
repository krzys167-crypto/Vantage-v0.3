"""Concurrent `grader push` calls (agent loop + the final flush of `make submit`) must
never send a probe twice: the grader would reject the replay as non_monotonic.

    python -m unittest framework/test_push.py -v
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()
SEEN = []


class Stub(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with LOCK:
            SEEN.extend(p["ts"] for p in body["probes"])
        out = b'{"accepted": 1, "rejected": 0}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


class ConcurrentPush(unittest.TestCase):
    def test_no_probe_is_sent_twice(self):
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        env = dict(os.environ, GRADER_URL=f"http://127.0.0.1:{srv.server_address[1]}")
        with tempfile.TemporaryDirectory() as state:
            os.makedirs(os.path.join(state, "evidence"))
            with open(os.path.join(state, "attempt.json"), "w") as f:
                json.dump({"attempt_id": "a", "token": "t"}, f)
            probes = os.path.join(state, "evidence", "probes.jsonl")
            total = 0
            for rnd in range(6):                      # the file grows between flushes
                with open(probes, "a") as f:
                    for _ in range(5):
                        total += 1
                        f.write(json.dumps({"ts": float(total), "ok": True}) + "\n")
                procs = [subprocess.Popen([sys.executable, os.path.join(HERE, "grader_client.py"), "push", state],
                                          env=env) for _ in range(6)]
                self.assertEqual([p.wait() for p in procs], [0] * 6)
        srv.shutdown()
        self.assertEqual(sorted(SEEN), [float(i) for i in range(1, total + 1)])


if __name__ == "__main__":
    unittest.main()
