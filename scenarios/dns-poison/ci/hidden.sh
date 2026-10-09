# Hidden assertions for dns-poison: the public practice pack.
# Sourced by ci/assertions.sh through run_hidden_pack, after the public block,
# with its variables in scope. A platform can replace this file with a private
# pack ($VANTAGE_HIDDEN_PACK/dns-poison/hidden.sh) that follows the same contract:
# call `record <id> hidden <name> <0|1> ""` once per check.
# H1 api still verifies upstream signatures (otherwise any squatter on the IP is trusted)
verify="$(svc_exec api cat /config/api.json 2>/dev/null | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("verify_upstream_signature", True))' 2>/dev/null || echo False)"
[[ "$verify" == True ]] && p=1 || p=0; record H1 hidden upstream_signature_verified "$p" ""
# H2 fixed at the source of truth: no static overrides left in hosts.json
ov="$(svc_exec api cat /config/hosts.json 2>/dev/null | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 1)"
[[ "$ov" == 0 ]] && p=1 || p=0; record H2 hidden no_static_overrides "$p" ""
# H3 change management: served zone serial moved past the broken one
served="$(j zone.serial)"
[[ -n "$served" && "$served" -gt "$(cat "$STATE/break_serial")" ]] && p=1 || p=0; record H3 hidden zone_serial_bumped "$p" ""
# H4 poisoned long TTL reverted (sane TTL on the payments record)
ttl="$(j dig_payments.ttl)"
[[ -n "$ttl" && "$ttl" -le 3600 && "$ttl" -gt 0 ]] && p=1 || p=0; record H4 hidden payments_ttl_sane "$p" ""
# H5 nothing in the zone still points at the decommissioned instance
[[ "$(j zone.records)" != *"$LEGACY_IP"* && -n "$(j zone.records)" ]] && p=1 || p=0; record H5 hidden no_record_to_legacy "$p" ""
# H6 flag is the real api HMAC for this user's host
expected="$("$PY" -c 'import hmac,hashlib,sys; print(hmac.new(open(sys.argv[1],"rb").read().strip(), sys.argv[2].encode(), hashlib.sha256).hexdigest()[:24])' "$STATE/secret/flag_secret" "$VANTAGE_HOST")"
[[ -n "$flag" && "$flag" == "$expected" ]] && p=1 || p=0; record H6 hidden flag_authentic "$p" ""
