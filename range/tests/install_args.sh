#!/usr/bin/env bash
# deploy/install.sh --dry-run: arguments end up in /etc/vantage/env and the Caddyfile, so anything
# that is not a plain hostname / URL / key must be refused before a single command runs.
#   bash range/tests/install_args.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
I="$ROOT/deploy/install.sh"; fail=0
ck() { if [[ "$2" == "$3" ]]; then echo "ok   $1"; else echo "FAIL $1 (rc=$2, want $3)"; fail=1; fi; }
base=(--domain r.example.com --supabase https://abc.supabase.co --supabase-key sb_publishable_AbC-1)
bash "$I" "${base[@]}" --dry-run >/dev/null 2>&1; ck "valid arguments are accepted" $? 0
# the download branch only runs when kubectl is missing, and CI runners ship one: dry-run with a PATH
# that has only the few tools install.sh executes even in --dry-run, so the result does not depend on the host
sandbox="$(mktemp -d)"; trap 'rm -rf "$sandbox"' EXIT
for tool in bash id openssl dpkg; do p="$(command -v "$tool" 2>/dev/null)" && ln -s "$p" "$sandbox/$tool"; done
out="$(PATH="$sandbox" /bin/bash "$I" "${base[@]}" --dry-run 2>&1)"
grep -q 'sha256sum -c' <<<"$out"; ck "kubectl download is checksum-verified" $? 0
bash "$I" --domain r.example.com --supabase http://abc.supabase.co --supabase-key k --dry-run >/dev/null 2>&1; ck "plain-http supabase url is refused" $? 2
bash "$I" --domain r.example.com --supabase https://abc.co --supabase-key "$(printf 'k\nRANGE_ADMIN_TOKEN=x')" --dry-run >/dev/null 2>&1; ck "newline in the key is refused" $? 2
bash "$I" "${base[@]}" --max-sessions '3;id' --dry-run >/dev/null 2>&1; ck "non-numeric --max-sessions is refused" $? 2
bash "$I" --domain r.example.com --supabase https://abc.co --supabase-key sb_secret_abc --dry-run >/dev/null 2>&1; ck "secret key is refused" $? 2
exit $fail
