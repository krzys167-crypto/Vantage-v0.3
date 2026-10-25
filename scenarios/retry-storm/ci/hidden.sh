# Hidden assertions for retry-storm: the public practice pack.
# Sourced by ci/assertions.sh through run_hidden_pack, after the public block,
# with its variables in scope. A platform can replace this file with a private
# pack ($VANTAGE_HIDDEN_PACK/retry-storm/hidden.sh) that follows the same contract:
# call `record <id> hidden <name> <0|1> ""` once per check.
pol() { "$PY" -c 'import json,sys; v=json.loads(sys.argv[1] or "{}").get(sys.argv[2]); print("" if v is None else v)' "$(j api.policy)" "$1" 2>/dev/null; }
# H1 retry budget: at most 3 retries per request
[[ -n "$(pol retries)" && "$(pol retries)" -le 3 ]] && p=1 || p=0; record H1 hidden retries_bounded "$p" ""
# H2 retries spread out: exponential backoff from >= 50 ms, with jitter
[[ "$(le 50 "$(pol backoff_ms)")" == 1 && "$(pol jitter)" == True ]] && p=1 || p=0; record H2 hidden backoff_with_jitter "$p" ""
# H3 timeout above the real latency but not a "wait forever" (200 ms .. 3 s)
t="$(pol timeout_ms)"; [[ "$(le 200 "$t")" == 1 && "$(le "$t" 3000)" == 1 ]] && p=1 || p=0; record H3 hidden timeout_sane "$p" ""
# H4 load shedding kept: bounded backlog in inventory
qm="$(j inventory.queue_max)"; [[ -n "$qm" && "$qm" -gt 0 && "$qm" -le 1000 ]] && p=1 || p=0; record H4 hidden backlog_bounded "$p" ""
# H5 checkouts reserve real stock: no static fallback answering instead of inventory
[[ "$(j api.fallback)" == 0 && "$(pol fallback_static)" == False && "$(j body)" == *'"served_by": "inventory"'* ]] && p=1 || p=0
record H5 hidden no_static_fallback "$p" ""
# H6 flag is the real api HMAC for this user's host
expected="$("$PY" -c 'import hmac,hashlib,sys; print(hmac.new(open(sys.argv[1],"rb").read().strip(), sys.argv[2].encode(), hashlib.sha256).hexdigest()[:24])' "$STATE/secret/flag_secret" "$VANTAGE_HOST")"
[[ -n "$flag" && "$flag" == "$expected" ]] && p=1 || p=0; record H6 hidden flag_authentic "$p" ""
# H7 the cost of one unit of work is a property of the code, not a tunable: a "faster" model is a
# falsified one, not a repaired one (security-critical)
bs="$(j inventory.base_service_ms)"
[[ "$(le "$bs" "$BASE_SERVICE_MS")" == 1 && "$(le "$BASE_SERVICE_MS" "${bs:-0}")" == 1 ]] && p=1 || p=0
record H7 hidden workload_model_intact "$p" ""
# H8 capacity restored, not inflated: at most twice the baseline pool and CPU (the incident was a
# cost review; the answer to it is not an open cheque)
w="$(j inventory.workers)"; c="$(j inventory.cpu_millicores)"
[[ "$(le "$w" $(( 2 * BASE_WORKERS )))" == 1 && "$(le "$c" $(( 2 * BASE_CPU_MILLICORES )))" == 1 ]] && p=1 || p=0
record H8 hidden capacity_within_budget "$p" ""
