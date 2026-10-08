#!/usr/bin/env bash
# Hosted range: material the trainee legitimately needs to do the job, published
# as Secrets their Role can read. The issuing CAs are part of the job (re-issue
# certificates); the backend's keys and flag secret are not.
source "$(dirname "$0")/lib.sh"
require_state
k8s_apply create secret generic issuer-ca \
  --from-file=int-ca.pem="$PKI/ca/int-ca.pem" --from-file=int-ca.key="$PKI/ca/int-ca.key" \
  --from-file=root-ca.pem="$PKI/ca/root-ca.pem" \
  --from-file=mesh-ca.pem="$PKI/ca/mesh-ca.pem" --from-file=mesh-ca.key="$PKI/ca/mesh-ca.key"
