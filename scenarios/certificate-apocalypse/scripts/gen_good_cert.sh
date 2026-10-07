#!/usr/bin/env bash
# PKI primitive: issue a valid CA, server or client certificate (EC P-256).
#
#   gen_good_cert.sh ca     <out_prefix> <cn> [issuer_prefix]        # root if no issuer, else intermediate
#   gen_good_cert.sh server <out_prefix> <issuer_prefix> <cn> [days] [dns_san...]
#   gen_good_cert.sh client <out_prefix> <issuer_prefix> <cn> [days]
#
# <prefix> means files <prefix>.pem + <prefix>.key. An existing key is reused,
# so re-issuing a certificate keeps the key pair stable.
source "$(dirname "$0")/lib.sh"

kind="${1:?kind}"; out="${2:?out_prefix}"
mkdir -p "$(dirname "$out")"
[[ -f "$out.key" ]] || openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$out.key" 2>/dev/null
ext="$(mktemp)"; trap 'rm -f "$ext" "$out.csr"' EXIT

sign() { # issuer days
  openssl req -new -key "$out.key" -subj "/O=Vantage/CN=$cn" -out "$out.csr"
  openssl x509 -req -in "$out.csr" -CA "$1.pem" -CAkey "$1.key" -CAcreateserial \
    -days "$2" -sha256 -extfile "$ext" -out "$out.pem" 2>/dev/null
}

case "$kind" in
  ca)
    cn="${3:?cn}"; issuer="${4:-}"
    if [[ -z "$issuer" ]]; then
      openssl req -x509 -new -key "$out.key" -subj "/O=Vantage/CN=$cn" -days 3650 -sha256 \
        -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -out "$out.pem"
    else
      printf 'basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n' > "$ext"
      sign "$issuer" 1825
    fi ;;
  server)
    issuer="${3:?issuer}"; cn="${4:?cn}"; days="${5:-90}"; shift 5 2>/dev/null || shift $#
    sans="DNS:$cn"; for s in "$@"; do sans+=",DNS:$s"; done
    printf 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=%s\nauthorityKeyIdentifier=keyid\n' "$sans" > "$ext"
    sign "$issuer" "$days" ;;
  client)
    issuer="${3:?issuer}"; cn="${4:?cn}"; days="${5:-90}"
    printf 'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=clientAuth\nsubjectAltName=DNS:%s\nauthorityKeyIdentifier=keyid\n' "$cn" > "$ext"
    sign "$issuer" "$days" ;;
  *) die "unknown kind: $kind" ;;
esac
echo "$out.pem"
