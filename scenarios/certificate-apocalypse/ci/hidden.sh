# Hidden assertions for certificate-apocalypse: the public practice pack.
# Sourced by ci/assertions.sh through run_hidden_pack, after the public block,
# with its variables in scope. A platform can replace this file with a private
# pack ($VANTAGE_HIDDEN_PACK/certificate-apocalypse/hidden.sh) that follows the same contract:
# call `record <id> hidden <name> <0|1> ""` once per check.
# H1 sane validity: >= 30 days left, <= 398 days total (no "100-year cert" fix)
if [[ -s "$leaf" ]]; then
  p=$("$PY" - "$leaf" <<'EOF'
import subprocess, sys, datetime as d
def get(f):
    v = subprocess.check_output(["openssl", "x509", "-in", sys.argv[1], "-noout", f"-{f}"], text=True).split("=", 1)[1].strip()
    return d.datetime.strptime(v, "%b %d %H:%M:%S %Y %Z")
nb, na = get("startdate"), get("enddate")
now = d.datetime.now(d.timezone.utc).replace(tzinfo=None)
print(1 if (na - now).days >= 30 and (na - nb).days <= 398 else 0)
EOF
)
else p=0; fi
record H1 hidden validity_window "$p" ""

# H2 key strength: EC >= 256 or RSA >= 2048
bits="$(openssl x509 -in "$leaf" -noout -text 2>/dev/null | grep -oE 'Public-Key: \([0-9]+ bit' | grep -oE '[0-9]+' || echo 0)"
alg="$(openssl x509 -in "$leaf" -noout -text 2>/dev/null | grep -m1 'Public Key Algorithm' || true)"
if [[ "$alg" == *id-ecPublicKey* ]]; then (( bits >= 256 )) && p=1 || p=0; else (( bits >= 2048 )) && p=1 || p=0; fi
record H2 hidden key_strength "$p" ""

# H3 gateway still verifies the backend, against the mesh CA (not "verify off")
conf="$(svc_exec gateway nginx -T 2>/dev/null || true)"
same_ca=$(cmp -s <(svc_exec gateway cat /pki/gateway/mesh-ca.pem 2>/dev/null) "$PKI/ca/mesh-ca.pem" && echo 1 || echo 0)
grep -Eq '^\s*proxy_ssl_verify\s+on;' <<<"$conf" && [[ "$same_ca" == 1 ]] && p=1 || p=0
record H3 hidden upstream_verify_on "$p" ""

# H4 flag is the real backend HMAC for this user's host
expected="$("$PY" -c 'import hmac,hashlib,sys; print(hmac.new(open(sys.argv[1],"rb").read().strip(), sys.argv[2].encode(), hashlib.sha256).hexdigest()[:24])' "$PKI/backend/flag_secret" "$VANTAGE_HOST")"
[[ "$flag" == "$expected" ]] && p=1 || p=0
record H4 hidden flag_authentic "$p" ""

# H5 backend still enforces mTLS: a client without a certificate must be rejected
p=$(svc_exec prober python - <<'EOF' 2>/dev/null || echo 0
import os, socket, ssl
c = ssl.create_default_context(cafile="/pki/backend/mesh-ca.pem")
try:
    with socket.create_connection((os.environ.get("BACKEND_DIAL", "backend.mesh.internal"), 9443), timeout=3) as s:
        with c.wrap_socket(s, server_hostname="backend.mesh.internal") as t:
            t.sendall(b"GET /healthz HTTP/1.0\r\n\r\n")
            print(0 if t.recv(64).startswith(b"HTTP/1.0 200") else 1)
except (ssl.SSLError, ConnectionError, OSError):
    print(1)
EOF
)
record H5 hidden backend_requires_client_cert "${p:-0}" ""

# H6 no wildcard / no stray SANs on the edge certificate
[[ "$san" == "DNS:$VANTAGE_HOST" ]] && p=1 || p=0
record H6 hidden san_minimal "$p" ""
