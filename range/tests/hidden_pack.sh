#!/usr/bin/env bash
# Unit test for hidden_assertions (framework/lib.sh): in-repo reference pack by default,
# private pack when VANTAGE_HIDDEN_DIR is set, hard failure when that pack is missing.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/scn/demo/ci" "$T/priv/demo"
echo 'echo "ran public pack"' > "$T/scn/demo/ci/hidden.sh"
echo 'echo "ran private pack"' > "$T/priv/demo/hidden.sh"
# extract just the function so the test needs no cluster state
fn="$(sed -n '/^hidden_assertions() {/,/^}/p' "$ROOT/framework/lib.sh")"
run() { ( eval "$fn"; hidden_assertions "$T/scn/demo/ci" ) 2>&1; }
fail=0
chk() { [[ "$2" == *"$3"* ]] && echo "ok   $1" || { echo "FAIL $1: got [$2]"; fail=1; }; }
out="$(run)";                                     chk default-uses-repo-pack "$out" "ran public pack"
out="$(VANTAGE_HIDDEN_DIR="$T/priv" run)";        chk private-pack-wins      "$out" "ran private pack"
[[ "$out" != *"ran public pack"* ]] || { echo "FAIL private pack must replace, not add"; fail=1; }
chmod o+w "$T/priv/demo/hidden.sh"
out="$(VANTAGE_HIDDEN_DIR="$T/priv" run)";        chk world-writable-pack-rejected "$out" "world-writable"
[[ "$out" != *"ran private pack"* ]] || { echo "FAIL ran a world-writable pack"; fail=1; }
chmod o-w "$T/priv/demo/hidden.sh"
rm "$T/priv/demo/hidden.sh"
out="$(VANTAGE_HIDDEN_DIR="$T/priv" run)"; rc=$?
chk missing-private-pack-errors "$out" "no private hidden pack"
[[ "$out" != *"ran public pack"* ]] || { echo "FAIL fell back to public pack"; fail=1; }
exit $fail
