"""Tiny DNS (RFC 1035 subset, A records over UDP) shared by the dns server, the
api's resolver and the trainee's `dig`. Stdlib only.

Zone file format (one record per line, '#' comments):
    $SERIAL 2026100701
    $NEGTTL 600                     # SOA minimum: how long NXDOMAIN is cached
    payments.internal  300  A  172.30.0.20
"""
import random
import socket
import struct
import time

QTYPE_A, QCLASS_IN = 1, 1
NOERROR, NXDOMAIN = 0, 3


def encode_name(name):
    out = b""
    for label in name.rstrip(".").split("."):
        out += bytes([len(label)]) + label.encode()
    return out + b"\x00"


def decode_name(msg, off):
    labels = []
    while True:
        n = msg[off]
        if n & 0xC0 == 0xC0:  # compression pointer
            ptr = struct.unpack("!H", msg[off:off + 2])[0] & 0x3FFF
            labels.append(decode_name(msg, ptr)[0])
            return ".".join(l for l in labels if l), off + 2
        off += 1
        if n == 0:
            return ".".join(labels), off
        labels.append(msg[off:off + n].decode())
        off += n


# --- zone -------------------------------------------------------------------
def load_zone(path):
    zone = {"serial": 0, "negttl": 600, "records": {}}
    with open(path) as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if parts[0] == "$SERIAL":
                zone["serial"] = int(parts[1])
            elif parts[0] == "$NEGTTL":
                zone["negttl"] = int(parts[1])
            elif len(parts) == 4 and parts[2].upper() == "A":
                zone["records"].setdefault(parts[0].lower().rstrip("."), []).append((int(parts[1]), parts[3]))
    return zone


def build_response(query, zone):
    tid, qd = struct.unpack("!H", query[:2])[0], 1
    qname, off = decode_name(query, 12)
    qtype, qclass = struct.unpack("!HH", query[off:off + 4])
    question = query[12:off + 4]
    answers = zone["records"].get(qname.lower(), []) if (qtype, qclass) == (QTYPE_A, QCLASS_IN) else []
    known = qname.lower() in zone["records"]
    rcode = NOERROR if known else NXDOMAIN
    flags = 0x8400 | rcode  # QR + AA
    body = b""
    for ttl, ip in answers:
        body += b"\xc0\x0c" + struct.pack("!HHIH", QTYPE_A, QCLASS_IN, ttl, 4) + socket.inet_aton(ip)
    authority = b""
    if not answers:
        # SOA for negative caching (RFC 2308): minimum = negative TTL
        soa_rdata = encode_name("ns.internal") + encode_name("hostmaster.internal") + struct.pack(
            "!IIIII", zone["serial"], 3600, 600, 86400, zone["negttl"])
        authority = encode_name("internal") + struct.pack("!HHIH", 6, QCLASS_IN, zone["negttl"], len(soa_rdata)) + soa_rdata
    header = struct.pack("!HHHHHH", tid, flags, qd, len(answers), 1 if authority else 0, 0)
    return header + question + body + authority, rcode, qname


# --- client -----------------------------------------------------------------
def query(server, name, port=53, timeout=2.0):
    """Return {"rcode", "ips", "ttl"}; ttl is the answer TTL or SOA minimum for NXDOMAIN."""
    tid = random.randint(0, 0xFFFF)
    q = struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0) + encode_name(name) + struct.pack("!HH", QTYPE_A, QCLASS_IN)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(q, (server, port))
        msg, _ = s.recvfrom(4096)
    rtid, flags, qd, an, ns, _ar = struct.unpack("!HHHHHH", msg[:12])
    if rtid != tid:
        raise ValueError("dns transaction id mismatch")
    off = 12
    for _ in range(qd):
        _, off = decode_name(msg, off)
        off += 4
    ips, ttl = [], None
    for _ in range(an + ns):
        _, off = decode_name(msg, off)
        rtype, _rclass, rttl, rdlen = struct.unpack("!HHIH", msg[off:off + 10])
        off += 10
        rdata = msg[off:off + rdlen]
        off += rdlen
        if rtype == QTYPE_A:
            ips.append(socket.inet_ntoa(rdata))
            ttl = rttl if ttl is None else min(ttl, rttl)
        elif rtype == 6 and not ips:  # SOA minimum -> negative TTL
            ttl = min(rttl, struct.unpack("!I", rdata[-4:])[0])
    return {"rcode": flags & 0xF, "ips": ips, "ttl": ttl or 0}


class CachingResolver:
    """What most service-discovery clients do: honour the TTL, cache NXDOMAIN too."""

    def __init__(self, server, port=53, max_ttl=86400):
        self.server, self.port, self.max_ttl = server, port, max_ttl
        self.cache = {}

    def resolve(self, name):
        now = time.time()
        hit = self.cache.get(name)
        if hit and hit["expires"] > now:
            return dict(hit, source="cache", ttl_left=round(hit["expires"] - now))
        r = query(self.server, name, self.port)
        entry = {"rcode": r["rcode"], "ips": r["ips"], "expires": now + min(r["ttl"], self.max_ttl)}
        self.cache[name] = entry
        return dict(entry, source="dns", ttl_left=min(r["ttl"], self.max_ttl))

    def flush(self):
        n = len(self.cache)
        self.cache.clear()
        return n
