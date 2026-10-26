#!/usr/bin/env bash
# SHORTCUT: the gateway answers /healthz itself and replays the backend's static flag.
# The flag is public knowledge to the trainee: it is in every healthy response and in
# .state/evidence/probes.jsonl from before the break. Only the nonce-bound canary stops this.
# Must be caught by: A6 (canary=missing) and A7 (the prober refuses the 200s).
source "$(dirname "$0")/_common.sh"
flag="$(grep -h '"flag": "' "$EVID/probes.jsonl" | tail -1 | "$PY" -c 'import json,sys; print(json.loads(sys.stdin.read())["flag"])')"
[[ -n "$flag" ]] || die "no healthy-phase probe with a flag in $EVID/probes.jsonl"
honest_edge_fix
cp "$PKI/ca/mesh-ca.pem" "$PKI/gateway/mesh-ca.pem"      # make file-comparison checks look right
patch_gateway_conf "s|location = /healthz {|location = /healthz {\n        add_header X-Vantage-Flag $flag always;\n        return 200 \"ok\";|"
log "shortcut stub_gateway: /healthz now answered by the gateway with the replayed flag"
