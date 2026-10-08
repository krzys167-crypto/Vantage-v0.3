#!/usr/bin/env bash
# Plays the trainee in a hosted Split-Brain DNS session, with nothing but the
# trainee kubeconfig and the public repo:
#   1. the RBAC boundary holds (no Secrets, no prober, no exec, no list)
#   2. the incident can be fixed with exactly those rights
#
#   range/tests/trainee_dns.sh <trainee.kubeconfig>
source "$(dirname "$0")/common.sh"

echo "RBAC boundary:"
check no  get secret/keys
check no  list secrets
check no  get configmap/scenario
check no  get configmap/app-code
check no  create configmaps
check no  patch deployment/prober
check no  patch deployment/legacy
check no  patch deployment/payments
check no  create pods/exec
check no  delete pods
check yes get configmap/zone
check yes patch configmap/zone
check yes patch configmap/svc-config
check yes patch deployment/dns
check yes patch deployment/api
check yes get pods/log
cannot_read secret/keys
boundary_holds

echo "diagnose + fix with trainee rights only:"
w="$(mktemp -d)"; trap 'rm -rf "$w"' EXIT
ip() { kubectl get svc "$1" -o jsonpath='{.spec.clusterIP}'; }
pay="$(ip payments)"; fx="$(ip fx)"; legacy="$(ip legacy)"
echo "  hosts: payments=$pay fx=$fx legacy=$legacy"

# 1. static overrides bypass DNS entirely
cm_get svc-config hosts.json > "$w/hosts.json"
if [[ "$(tr -d ' \n' < "$w/hosts.json")" != "{}" ]]; then
  echo "  hosts.json carries overrides -> remove"
  printf '{}\n' > "$w/hosts.json"; cm_set svc-config hosts.json "$w/hosts.json"
fi

# 2. zone: payments to the live instance, fx present and spelled right, nothing
#    pointing at the legacy box, serial bumped
cm_get zone internal.zone > "$w/zone"
python3 - "$w/zone" "$pay" "$fx" "$legacy" <<'PY'
import re, sys
path, pay, fx, legacy = sys.argv[1:]
lines = [l for l in open(path).read().splitlines()
         if not re.match(r"^(payments|fx)\.inter\w*\s", l) and legacy not in l]
lines += [f"payments.internal   300  A  {pay}", f"fx.internal         300  A  {fx}"]
z = "\n".join(lines) + "\n"
z = re.sub(r"^\$SERIAL (\d+)", lambda m: f"$SERIAL {int(m.group(1)) + 1}", z, flags=re.M)
open(path, "w").write(z)
PY
cm_set zone internal.zone "$w/zone"
echo "  zone fixed, serial $(sed -n 's/^\$SERIAL //p' "$w/zone")"

# 3. dns reloads the zone on start; the api's resolver cache dies with the pod
roll dns
roll api
echo "  applied: zone + svc-config updated, dns and api rolled"
