# Shared helpers for ci/shortcuts/*.sh. Source, don't execute.
#
# Each shortcut is a LAZY "fix": it makes the public symptoms go away without repairing the
# cause, the way a rushed engineer, the 2022 runbook or a careless LLM answer would. They exist
# as negative controls: ci/run_shortcuts.sh proves that the assertion pack catches every one.
# Exit 0 = applied, 3 = not applicable to this seed.
source "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib.sh"
require_state
is_k8s && { warn "shortcuts edit the running nginx config in place: docker mode only"; exit 3; }

# The part of the task every shortcut still does honestly: a valid public certificate.
honest_edge_fix() {
  local g="$SCN_DIR/scripts/gen_good_cert.sh" gw="$PKI/gateway"
  if ! openssl x509 -in "$gw/leaf.pem" -noout -checkend $((30*86400)) >/dev/null; then
    "$g" server "$gw/leaf" "$PKI/ca/int-ca" "$VANTAGE_HOST" 90 >/dev/null
  fi
  cat "$gw/leaf.pem" "$PKI/ca/int-ca.pem" > "$gw/fullchain.pem"
}

# Edit the rendered config inside the gateway (what `docker exec` + vi would do) and reload.
patch_gateway_conf() { # sed-script
  svc_exec gateway sh -c "sed -i '$1' /etc/nginx/conf.d/default.conf && nginx -t -q && nginx -s reload" 2>&1 \
    | grep -v 'signal process' || true
}
