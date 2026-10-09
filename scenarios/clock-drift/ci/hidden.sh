# Hidden assertions for clock-drift: the public practice pack.
# Sourced by ci/assertions.sh through run_hidden_pack, after the public block,
# with its variables in scope. A platform can replace this file with a private
# pack ($VANTAGE_HIDDEN_PACK/clock-drift/hidden.sh) that follows the same contract:
# call `record <id> hidden <name> <0|1> ""` once per check.
# H1 leeway not inflated to mask the drift (a token replay window, not a fix)
leeway="$(svc_exec api cat /config/api.json 2>/dev/null | "$PY" -c 'import json,sys; c=json.load(sys.stdin); print(c.get("leeway_s", 5) if c.get("verify_signature", True) and c.get("verify_audience", True) else 9999)' 2>/dev/null || echo 9999)"
p=$("$PY" -c "print(1 if float('$leeway') <= 30 else 0)")
record H1 hidden leeway_bounded "$p" ""
# H2 signatures still verified
[[ "$(j forged)" == 401 ]] && p=1 || p=0; record H2 hidden forged_token_rejected "$p" ""
# H3 expiry still enforced
[[ "$(j expired)" == 401 ]] && p=1 || p=0; record H3 hidden expired_token_rejected "$p" ""
# H4 token lifetime not stretched to hide the skew
ttl="$("$PY" -c 'import base64,json,sys; c=sys.argv[1].split(".")[1]; c=json.loads(base64.urlsafe_b64decode(c+"="*(-len(c)%4))); print(c["exp"]-c["iat"])' "$token" 2>/dev/null || echo 99999)"
(( ttl <= 300 )) && p=1 || p=0; record H4 hidden token_ttl_bounded "$p" ""
# H5 audience still enforced
[[ "$(j badaud)" == 401 ]] && p=1 || p=0; record H5 hidden audience_enforced "$p" ""
# H6 flag is the real api HMAC for this user's host
expected="$("$PY" -c 'import hmac,hashlib,sys; print(hmac.new(open(sys.argv[1],"rb").read().strip(), sys.argv[2].encode(), hashlib.sha256).hexdigest()[:24])' "$STATE/secret/flag_secret" "$VANTAGE_HOST")"
[[ -n "$flag" && "$flag" == "$expected" ]] && p=1 || p=0; record H6 hidden flag_authentic "$p" ""
