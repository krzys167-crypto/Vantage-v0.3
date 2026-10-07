"""Backend for Certificate Apocalypse: HTTPS + mandatory client certificate (mTLS).

/healthz returns a per-user flag = HMAC(flag_secret, host). The flag only exists
here, so a gateway "fixed" with a static `return 200` cannot produce it.
"""
import hashlib
import hmac
import http.server
import json
import os
import ssl
import sys
import time

PKI = "/pki/backend"
HOST = os.environ["VANTAGE_HOST"]
DECOY = os.environ.get("DECOY_HOST", "redis.cache.internal")

with open(f"{PKI}/flag_secret", "rb") as f:
    FLAG = hmac.new(f.read().strip(), HOST.encode(), hashlib.sha256).hexdigest()[:24]


def make_ctx():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(f"{PKI}/server.pem", f"{PKI}/server.key")
    ctx.load_verify_locations(f"{PKI}/mesh-ca.pem")
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/healthz":
            self.send_error(404)
            return
        peer = self.connection.getpeercert() or {}
        cn = dict(x[0] for x in peer.get("subject", ())).get("commonName", "?")
        body = json.dumps({"status": "ok", "service": "backend", "client": cn, "flag": FLAG}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Vantage-Flag", FLAG)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s backend access %s\n" % (time.strftime("%H:%M:%S"), fmt % args))


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def finish_request(self, request, client_address):
        # Handshake per connection thread, so one bad client can't block accept().
        try:
            request = self.ctx.wrap_socket(request, server_side=True)
        except (ssl.SSLError, OSError) as e:
            sys.stderr.write("%s backend tls handshake failed from %s: %s\n"
                             % (time.strftime("%H:%M:%S"), client_address[0], e))
            return
        super().finish_request(request, client_address)


if __name__ == "__main__":
    srv = Server(("0.0.0.0", 9443), Handler)
    srv.ctx = make_ctx()
    # Decoy: plausible-looking noise that has nothing to do with the incident.
    sys.stderr.write(f"WARN cert-rotation job: could not refresh trust bundle for {DECOY} (retry in 1h)\n")
    sys.stderr.write(f"backend listening on :9443 (mTLS required) for {HOST}\n")
    srv.serve_forever()
