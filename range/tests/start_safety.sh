#!/usr/bin/env bash
# range.sh start without a cluster, against a fake repo tree:
#  1. a user id full of shell metacharacters (an IdP e-mail claim can carry them)
#     must reach the scenario as the same literal string and execute nothing;
#  2. a start that fails after the namespace exists must tear it down and
#     release its subnet claim (the API never learns the session id of a failed start).
#   bash range/tests/start_safety.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/range" "$tmp/bin" "$tmp/scenarios/demo/k8s" "$tmp/scenarios/demo/scripts"
cp "$ROOT/range/range.sh" "$tmp/range/range.sh"
: > "$tmp/scenarios/demo/k8s/trainee-role.yaml"
cat > "$tmp/bin/kubectl" <<'K'
#!/usr/bin/env bash
case "$*" in *"create token"*) echo fake-token ;; *"config view"*) echo fake ;; esac
exit 0
K
cat > "$tmp/scenarios/demo/scripts/ctl.sh" <<'C'
#!/usr/bin/env bash
case "$1" in
  up)   printf '%s' "$USER_ID" > "$FAKE_OUT/seen_user"; [[ "${FAIL_UP:-0}" == 1 ]] && exit 1; exit 0 ;;
  down) echo "down $VANTAGE_NS" >> "$FAKE_OUT/down.log" ;;
esac
C
printf '#!/usr/bin/env bash\nexit 0\n' > "$tmp/scenarios/demo/scripts/break.sh"
chmod +x "$tmp/bin/kubectl" "$tmp/scenarios/demo/scripts/"*.sh
export PATH="$tmp/bin:$PATH" RANGE_SESSIONS="$tmp/sessions" GRADER_URL=http://127.0.0.1:1 FAKE_OUT="$tmp" KUBE_CONTEXT=fake
fail=0; ck() { if [[ "$2" == ok ]]; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }

evil="a\$(touch\${IFS}$tmp/PWNED)\`touch\${IFS}$tmp/PWNED2\`;x@y.io"
id="$(bash "$tmp/range/range.sh" start demo "$evil" 2>/dev/null | tail -1)"
[[ "$id" =~ ^[0-9a-f]{8}$ ]] && ck "start with a hostile user id succeeds" ok || ck "start with a hostile user id succeeds" no
[[ ! -e "$tmp/PWNED" && ! -e "$tmp/PWNED2" ]] && ck "no command from the user id ran" ok || ck "no command from the user id ran" no
[[ "$(cat "$tmp/seen_user" 2>/dev/null)" == "$evil" ]] && ck "scenario sees the user id verbatim" ok || ck "scenario sees the user id verbatim" no
[[ "$(ls "$tmp/sessions/.nets" 2>/dev/null | wc -l)" == 1 ]] && ck "successful start keeps its claim" ok || ck "successful start keeps its claim" no

rm -f "$tmp/down.log"
FAIL_UP=1 bash "$tmp/range/range.sh" start demo alice >/dev/null 2>&1; rc=$?
[[ $rc != 0 ]] && ck "failed start exits non-zero" ok || ck "failed start exits non-zero" no
grep -q '^down vr-' "$tmp/down.log" 2>/dev/null && ck "failed start tears its namespace down" ok || ck "failed start tears its namespace down" no
[[ "$(ls "$tmp/sessions/.nets" | wc -l)" == 1 ]] && ck "failed start released its claim (only the first session's remains)" ok || ck "failed start released its claim" no

# 3. scenario.env (written by framework/lib.sh, sourced by require_state) must not execute the user id either
eval "$(awk '/^safe_user_id\(\)/,/^}/' "$ROOT/framework/lib.sh")"
[[ "$(safe_user_id 'jan.kowalski+test@firma.pl')" == 'jan.kowalski+test@firma.pl' ]] && ck "ordinary e-mail id is kept" ok || ck "ordinary e-mail id is kept" no
[[ "$(safe_user_id '3f2a1c9e-8b1d-4c53-9a77-0d2c1f4e5a6b')" == '3f2a1c9e-8b1d-4c53-9a77-0d2c1f4e5a6b' ]] && ck "uuid id is kept" ok || ck "uuid id is kept" no
safe="$(safe_user_id "$evil")"
[[ "$safe" =~ ^u-[0-9a-f]{16}$ ]] && ck "hostile id becomes a pseudonym" ok || ck "hostile id becomes a pseudonym" no
[[ "$(safe_user_id "$evil")" == "$safe" ]] && ck "pseudonym is stable" ok || ck "pseudonym is stable" no
printf 'USER_ID=%s\nSEED=1\n' "$safe" > "$tmp/scenario.env"
( set -a; source "$tmp/scenario.env"; set +a; [[ "$USER_ID" == "$safe" ]] ) && [[ ! -e "$tmp/PWNED" ]] && ck "sourcing scenario.env runs nothing" ok || ck "sourcing scenario.env runs nothing" no
exit $fail
