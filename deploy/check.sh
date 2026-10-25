#!/usr/bin/env bash
# Smoke test of a running Vantage hosted range: one command, one line per check.
#
#   bash deploy/check.sh range.example.com            # from any machine
#   sudo bash deploy/check.sh range.example.com       # on the server: also checks the services
#   bash deploy/check.sh --base http://127.0.0.1:8080 # test against any base URL (no DNS/TLS/6443 checks)
#
# Exit code 0 = everything passed. Read-only: it never starts an incident.
set -uo pipefail

DOMAIN="" BASE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="${2%/}"; shift 2 ;;
    -h|--help) sed -n 2,9p "$0"; exit 0 ;;
    *) DOMAIN="$1"; shift ;;
  esac
done
[[ -n "$DOMAIN" || -n "$BASE" ]] || { echo "usage: check.sh <domain> | --base <url>" >&2; exit 2; }
[[ -n "$BASE" ]] || BASE="https://$DOMAIN"

FAILS=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAILS=$((FAILS + 1)); }
note() { printf '        %s\n' "$*"; }
get()  { curl -s -m 15 -o "${2:-/dev/null}" -w '%{http_code}' "$BASE$1" 2>/dev/null || true; }   # 000 = no answer

if [[ -n "$DOMAIN" ]]; then
  ip="$(getent hosts "$DOMAIN" 2>/dev/null | awk '{print $1; exit}')"
  if [[ -n "$ip" ]]; then ok "DNS: $DOMAIN -> $ip"
  else bad "DNS: $DOMAIN does not resolve"; note "add an A record pointing at the server and wait for it to propagate"; fi
fi

tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
code="$(get / "$tmp")"
if [[ "$code" == 200 ]] && grep -qi "vantage" "$tmp"; then ok "panel: $BASE/ answers 200"
elif [[ "$code" != 000 ]]; then bad "panel: $BASE/ answered $code"; note "see: sudo journalctl -u vantage-range-api -n 50"
else bad "panel: $BASE/ unreachable"
  [[ -n "$DOMAIN" ]] && note "usual causes: DNS not propagated, ports 80/443 closed at the provider, no certificate yet (sudo journalctl -u caddy -n 50)"; fi

code="$(get /v1/pubkey "$tmp")"
if [[ "$code" == 200 ]] && grep -q "BEGIN PUBLIC KEY" "$tmp"; then ok "grader: /v1/pubkey serves the signing key"
else bad "grader: /v1/pubkey answered ${code/000/nothing}"; note "see: sudo systemctl status vantage-grader"; fi

code="$(get /api/sessions/mine)"
if [[ "$code" == 401 ]]; then ok "API: login is enforced (401 without a token)"
elif [[ "$code" == 200 ]]; then bad "API: /api/sessions/mine answered 200 WITHOUT a token"; note "authentication is not enforced, do not open this to users"
else bad "API: /api/sessions/mine answered ${code/000/nothing} (expected 401)"; fi

if [[ -n "$DOMAIN" ]]; then
  if timeout 8 bash -c "exec 3<>/dev/tcp/$DOMAIN/6443" 2>/dev/null; then ok "Kubernetes API: $DOMAIN:6443 accepts connections"
  else bad "Kubernetes API: $DOMAIN:6443 unreachable"; note "open TCP 6443 at the provider (Security List / firewall) and in iptables; k3d: sudo -u vantage k3d cluster list"; fi
fi

if [[ $EUID == 0 && -d /run/systemd/system ]]; then
  for s in vantage-grader vantage-range-api caddy; do
    if systemctl is-active --quiet "$s"; then ok "service $s is active"
    else bad "service $s is not active"; note "sudo journalctl -u $s -n 50 --no-pager"; fi
  done
else
  note "(run with sudo on the server to check the services as well)"
fi

echo
if [[ $FAILS == 0 ]]; then echo "all checks passed"; else echo "$FAILS check(s) failed"; fi
[[ $FAILS == 0 ]]
