#!/usr/bin/env python3
"""Verify a signed grader result, e.g. one a candidate sent you.

    python grader/verify.py server_report.json grader_pubkey.pem
    python grader/verify.py debrief_report.json grader_pubkey.pem     (post-mortem verdict)

Exit 0 and print the summary when the signature matches the grader's public
key (GET /v1/pubkey on the grader); exit 1 otherwise.
"""
import base64
import json
import os
import subprocess
import sys
import tempfile


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def main(report_path, pubkey_path):
    with open(report_path) as f:
        doc = json.load(f)
    r = doc["result"]
    with tempfile.TemporaryDirectory() as d:
        msg, sig = os.path.join(d, "msg"), os.path.join(d, "sig")
        with open(msg, "wb") as f:
            f.write(canonical(r))
        with open(sig, "wb") as f:
            f.write(base64.b64decode(doc["signature"]))
        ok = subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", pubkey_path, "-rawin",
                             "-in", msg, "-sigfile", sig], capture_output=True).returncode == 0
    if not ok:
        print("INVALID signature: the result was modified or signed by another key")
        return 1
    if r.get("kind") not in ("profile", "league"):
        print(f"valid signature | {r['user']} | {r['scenario']} | attempt {r['attempt_id']}")
    else:
        print("valid signature")
    if r.get("kind") == "profile":
        print(f"profile {r['user']} ({r['alias']}): badges {[b['badge'] for b in r['badges']]}")
        return 0
    if r.get("kind") == "league":
        print(f"league {r['season']}: {len(r['rows'])} players")
        return 0
    if r.get("kind") == "debrief":
        c = r["causes"]
        print(f"post-mortem score {r['score']} | {r['verdict']} | author key {r['author_key_sha256'][:16]} | "
              f"for attempt result sha256 {r['attempt_result_sha256'][:16]} (tier {r['attempt_tier']})")
        print(f"causes confirmed {c['confirmed']} missed {c['missed']} wrong {c['wrong']} | "
              f"mitigated off by {r['timeline']['mitigated_error_s']} s")
    else:
        print(f"score {r['score']} | tier {r['tier']} | attested {r['attested']} | MTTR {r['sli']['mttr_s']} s")
    print(f"trust: {json.dumps(r['trust'])}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
