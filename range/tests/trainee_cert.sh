#!/usr/bin/env bash
# Plays the trainee in a hosted Certificate Apocalypse session, with nothing but
# the trainee kubeconfig and the public repo:
#   1. the RBAC boundary holds (no backend secrets, no prober, no exec, no list)
#   2. the incident can be fixed with exactly those rights
#
#   range/tests/trainee_cert.sh <trainee.kubeconfig>
source "$(dirname "$0")/common.sh"
G="$ROOT/scenarios/certificate-apocalypse/scripts/gen_good_cert.sh"

echo "RBAC boundary:"
check no  get secret/backend-pki
check no  list secrets
check no  get configmap/scenario
check no  patch deployment/prober
check no  patch deployment/backend
check no  create pods/exec
check no  delete pods
check no  create deployments
check yes get secret/gateway-pki
check yes patch secret/gateway-pki
check yes get secret/issuer-ca
check yes patch deployment/gateway
check yes get pods/log
cannot_read secret/backend-pki
boundary_holds

echo "diagnose + fix with trainee rights only:"
w="$(mktemp -d)"; trap 'rm -rf "$w"' EXIT
mkdir -p "$w/gw" "$w/ca"
dump() { # secret dir
  kubectl get secret "$1" -o json | python3 -c '
import base64, json, os, sys
d = sys.argv[1]
for k, v in json.load(sys.stdin)["data"].items():
    open(os.path.join(d, k), "wb").write(base64.b64decode(v))' "$2"
}
dump gateway-pki "$w/gw"
dump issuer-ca "$w/ca"
# the public hostname, read the way an operator would: from the served certificate
host="$(openssl x509 -in "$w/gw/leaf.pem" -noout -ext subjectAltName | sed -n 's/.*DNS:\([^,]*\).*/\1/p' | head -1)"
echo "  edge host: $host"
export MSYS_NO_PATHCONV=1
gen() { SCN_DIR="$ROOT/scenarios/certificate-apocalypse" PROJECT=x EDGE_SVC=x EDGE_TARGET_PORT=1 bash "$G" "$@" >/dev/null; }

# the same diagnosis a person would do, on the live material
if ! openssl x509 -in "$w/gw/leaf.pem" -noout -checkend $((30*86400)) >/dev/null; then
  echo "  edge leaf expired -> re-issue (same key)"; gen server "$w/gw/leaf" "$w/ca/int-ca" "$host" 90
fi
[[ "$(grep -c 'BEGIN CERT' "$w/gw/fullchain.pem")" -lt 2 ]] && echo "  chain incomplete -> rebuild fullchain"
cat "$w/gw/leaf.pem" "$w/ca/int-ca.pem" > "$w/gw/fullchain.pem"
if ! cmp -s "$w/gw/mesh-ca.pem" "$w/ca/mesh-ca.pem"; then
  echo "  gateway trusts the wrong mesh CA -> restore"; cp "$w/ca/mesh-ca.pem" "$w/gw/mesh-ca.pem"
fi
if ! openssl x509 -in "$w/gw/client.pem" -noout -checkend $((30*86400)) >/dev/null; then
  echo "  mesh client cert expired -> re-issue (same key)"; gen client "$w/gw/client" "$w/ca/mesh-ca" gateway.mesh.internal 90
fi
rm -f "$w/gw/"*.csr "$w/ca/"*.srl
kubectl create secret generic gateway-pki --from-file="$w/gw" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
roll gateway
echo "  applied: gateway-pki updated, gateway rolled"
