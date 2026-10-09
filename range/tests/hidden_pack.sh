#!/usr/bin/env bash
# run_hidden_pack (framework/lib.sh): an unusable private pack aborts with exit 2,
# which range.sh grade tells apart from "public assertions failed" (exit 1).
#   bash range/tests/hidden_pack.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fn="$(awk '/^run_hidden_pack\(\)/,/^}/' "$ROOT/framework/lib.sh")"
run() { # pack dir -> exit code of run_hidden_pack
  ( eval "$fn"; SCENARIO=demo SCN_DIR="$tmp/scn" ASSERT_TMP="$tmp/at" VANTAGE_HIDDEN_PACK="$1"
    run_hidden_pack >/dev/null 2>&1; echo "after" ) > "$tmp/out"; echo $?
}
mkdir -p "$tmp/scn/ci" "$tmp/pack/demo" "$tmp/at"
echo 'true' > "$tmp/pack/demo/hidden.sh"; chmod 644 "$tmp/pack/demo/hidden.sh"
fail=0
check() { if [[ "$2" == "$3" ]]; then echo "ok   $1"; else echo "FAIL $1: exit $2, want $3"; fail=1; fi; }
check "usable private pack runs" "$(run "$tmp/pack")" 0
check "missing pack aborts" "$(run "$tmp/nowhere")" 2
chmod o+w "$tmp/pack/demo/hidden.sh"
check "world-writable pack aborts" "$(run "$tmp/pack")" 2
exit $fail
