#!/usr/bin/env bash
# Subnet claims of range.sh without a cluster: 30 controllers starting at once
# must get 30 different /24s, none already used by a Service, and stop must
# release exactly its own claim.
#   bash range/tests/net_claims.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
cat > "$tmp/bin/kubectl" <<'K'
#!/usr/bin/env bash
# Services already on the cluster: 10.43.200-219 are taken
for n in $(seq 200 219); do echo "10.43.$n.10"; done
echo "10.43.0.1"
K
chmod +x "$tmp/bin/kubectl"
export PATH="$tmp/bin:$PATH" SESSIONS="$tmp/sessions" KUBE_CONTEXT=fake
die() { echo "xx $*" >&2; exit 1; }
# the functions under test, straight from range.sh
eval "$(awk '/^(with_lock|claim_svc_net|free_svc_net|release_svc_net)\(\)/,/^}/' "$ROOT/range/range.sh")"

for i in $(seq 1 30); do ( free_svc_net "s$i" > "$tmp/out.$i" ) & done
wait
nets="$(cat "$tmp"/out.* | sort)"
[[ "$(wc -l <<<"$nets")" == 30 ]] || { echo "FAIL: expected 30 claims"; exit 1; }
[[ -z "$(uniq -d <<<"$nets")" ]] || { echo "FAIL: duplicate subnets: $(uniq -d <<<"$nets")"; exit 1; }
if grep -qE '^10\.43\.(20[0-9]|21[0-9])$' <<<"$nets"; then echo "FAIL: handed out a subnet a Service uses"; exit 1; fi
[[ "$(ls "$SESSIONS/.nets" | wc -l)" == 30 ]] || { echo "FAIL: claims on disk"; exit 1; }
release_svc_net s7
[[ "$(ls "$SESSIONS/.nets" | wc -l)" == 29 ]] || { echo "FAIL: release"; exit 1; }
! grep -rqx s7 "$SESSIONS/.nets" || { echo "FAIL: s7 still holds a claim"; exit 1; }
[[ ! -d "$SESSIONS/.lock" ]] || { echo "FAIL: lock left behind"; exit 1; }
echo "ok: 30 concurrent claims, all distinct and free; release drops only its own"
