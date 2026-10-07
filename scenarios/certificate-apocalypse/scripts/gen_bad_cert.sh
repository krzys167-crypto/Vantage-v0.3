#!/usr/bin/env bash
# Fault primitive: produce broken certificates for the break step.
#
#   gen_bad_cert.sh expired  <out_prefix> <issuer_prefix> <cn> <server|client>
#       re-issues the cert with the SAME key, valid from -400d to -1d
#   gen_bad_cert.sh rogue-ca <out_prefix> <cn>
#       self-signed CA nobody trusts (for the invalid_truststore fault)
source "$(dirname "$0")/lib.sh"

kind="${1:?kind}"; out="${2:?out_prefix}"

case "$kind" in
  expired)
    issuer="${3:?issuer}"; cn="${4:?cn}"; usage="${5:?server|client}"
    [[ -f "$out.key" ]] || openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$out.key" 2>/dev/null
    eku=$([[ "$usage" == server ]] && echo serverAuth || echo clientAuth)
    # `openssl x509 -days` cannot back-date, so use a throwaway `openssl ca` db.
    db="$(mktemp -d)"; trap 'rm -rf "$db"' EXIT
    : > "$db/index.txt"; echo 1000 > "$db/serial"
    cat > "$db/ca.cnf" <<EOF
[ca]
default_ca = bad
[bad]
database = $db/index.txt
serial = $db/serial
new_certs_dir = $db
default_md = sha256
policy = any
unique_subject = no
[any]
commonName = supplied
organizationName = optional
[ext]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature
extendedKeyUsage = $eku
subjectAltName = DNS:$cn
authorityKeyIdentifier = keyid
EOF
    read -r start end < <("$PY" -c 'import datetime as d; n=d.datetime.now(d.timezone.utc); f="%Y%m%d%H%M%SZ"; print((n-d.timedelta(days=400)).strftime(f), (n-d.timedelta(days=1)).strftime(f))')
    openssl req -new -key "$out.key" -subj "/O=Vantage/CN=$cn" -out "$db/req.csr"
    openssl ca -batch -config "$db/ca.cnf" -cert "$issuer.pem" -keyfile "$issuer.key" \
      -startdate "$start" -enddate "$end" -extensions ext -notext \
      -in "$db/req.csr" -out "$out.pem" 2>/dev/null ;;
  rogue-ca)
    cn="${3:?cn}"
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -keyout "$out.key" \
      -subj "/O=Vantage/CN=$cn" -days 3650 -addext "basicConstraints=critical,CA:TRUE" -out "$out.pem" 2>/dev/null ;;
  *) die "unknown kind: $kind" ;;
esac
echo "$out.pem"
