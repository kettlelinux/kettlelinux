# GameStream hosts (Sunshine, Apollo) as the Moonlight plugin sees them, without moonlight-qt's
# CLI, whose `list` can wait forever on a host it's still polling: finding hosts on the network
# (mDNS, _nvstream._tcp), a host's serverinfo (HTTP, no pairing needed; HTTPS for a paired one),
# its app list and box art (HTTPS with moonlight-qt's own client certificate, the host's
# certificate pinned to the one stored at pairing), and Wake-on-LAN.
# Pairing itself is moonlight-qt's (main.py runs `moonlight pair`), so its config stays its own.
import os
import socket
import ssl
import struct
import tempfile
import time
import uuid as uuidlib
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from http.client import HTTPConnection, HTTPException, HTTPSConnection

HTTP_PORT = 47989
HTTPS_PORT = 47984
TIMEOUT = 4


class HostError(Exception):
    pass


def _parse(body: bytes) -> ET.Element:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise HostError(f"the host's answer isn't XML: {e}") from None
    if root.get("status_code") not in (None, "200"):
        raise HostError(root.get("status_message") or f"the host answered {root.get('status_code')}")
    return root


def _query(uid: str) -> str:
    return f"uniqueid={uid}&uuid={uuidlib.uuid4().hex}"


def serverinfo(address: str, port: int = HTTP_PORT, uid: str = "0123456789ABCDEF", timeout: float = TIMEOUT) -> dict:
    """What any client may ask a host, paired or not."""
    c = HTTPConnection(address, port, timeout=timeout)
    try:
        c.request("GET", f"/serverinfo?{_query(uid)}")
        r = c.getresponse()
        return _info(_parse(r.read()))
    except OSError as e:
        raise HostError(f"no answer from {address}: {e.strerror or e}") from None
    except HTTPException as e:
        raise HostError(f"{address} didn't answer as a GameStream host: {e!r}") from None
    finally:
        c.close()


def _int(v: str, default: int = 0) -> int:
    try:
        return int(v)
    except ValueError:
        raise HostError(f"the host's answer isn't readable: {v!r} isn't a number") from None


def _info(root: ET.Element) -> dict:
    t = lambda k, d="": (root.findtext(k) or d).strip()
    codecs = _int(t("ServerCodecModeSupport", "0") or "0")
    return {
        "name": t("hostname"),
        "uuid": t("uniqueid"),
        "mac": t("mac"),
        "https_port": _int(t("HttpsPort", str(HTTPS_PORT)) or str(HTTPS_PORT)),
        "local_ip": t("LocalIP"),
        "paired": t("PairStatus") == "1",
        "busy": t("state").endswith("_BUSY"),
        "current_app": _int(t("currentgame", "0") or "0"),
        "version": t("appversion"),
        # Sunshine's codec mode bits: 0x1 H.264, 0x100 HEVC, 0x200 HEVC Main10, 0x10000 AV1 Main8
        "hevc": bool(codecs & 0x100),
        "av1": bool(codecs & 0x10000),
        # Apollo answers with the client's permission set; Sunshine has no such element
        "apollo": root.find("Permission") is not None,
    }


class Client:
    """A paired host over HTTPS: moonlight-qt's identity (uid, cert, key: PEM bytes) and the
    host's certificate as stored at pairing (PEM), which the host must present."""

    def __init__(self, uid: str, cert: bytes, key: bytes, server_cert: bytes):
        self.uid = uid
        self.cert = cert
        self.key = key
        self.server_der = ssl.PEM_cert_to_DER_cert(server_cert.decode())

    @contextmanager
    def _context(self):
        # the key goes to a private file only for as long as load_cert_chain reads it
        fd, path = tempfile.mkstemp(prefix="kettle-moonlight-", suffix=".pem")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(self.cert + b"\n" + self.key)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            # hosts sign their own certificates: it's pinned below instead
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.load_cert_chain(path)
        finally:
            os.unlink(path)
        yield ctx

    def get(self, address: str, port: int, path: str, params: str = "") -> bytes:
        with self._context() as ctx:
            c = HTTPSConnection(address, port, timeout=TIMEOUT, context=ctx)
            try:
                c.connect()
                if c.sock.getpeercert(binary_form=True) != self.server_der:
                    raise HostError("the host's certificate isn't the one it was paired with")
                c.request("GET", f"/{path}?{_query(self.uid)}{'&' + params if params else ''}")
                r = c.getresponse()
                body = r.read()
                if r.status != 200:
                    raise HostError(f"the host answered HTTP {r.status}")
                return body
            except (OSError, ssl.SSLError) as e:
                raise HostError(f"no answer from {address}: {getattr(e, 'strerror', None) or e}") from None
            except HTTPException as e:
                raise HostError(f"{address} didn't answer as a GameStream host: {e!r}") from None
            finally:
                c.close()

    def serverinfo(self, address: str, port: int) -> dict:
        return _info(_parse(self.get(address, port, "serverinfo")))

    def applist(self, address: str, port: int) -> list[dict]:
        root = _parse(self.get(address, port, "applist"))
        return [{"id": _int(a.findtext("ID") or "0"), "name": (a.findtext("AppTitle") or "").strip(),
                 "hdr": a.findtext("IsHdrSupported") == "1"} for a in root.iter("App")]

    def boxart(self, address: str, port: int, app_id: int) -> bytes:
        return self.get(address, port, "appasset", f"appid={app_id}&AssetType=2&AssetIdx=0")


def wake(mac: str):
    """A Wake-on-LAN magic packet to the broadcast address, ports 9 and 7."""
    raw = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(raw) != 6 or raw == bytes(6):
        raise HostError("the host didn't say its network card's address")
    packet = b"\xff" * 6 + raw * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            s.sendto(packet, ("255.255.255.255", port))


# mDNS: one question for _nvstream._tcp.local's PTR records, asked from an ordinary port, so
# responders answer straight back to it (RFC 6762 "legacy unicast"); avahi-daemon isn't needed.
SERVICE = "_nvstream._tcp.local"


def _name(msg: bytes, off: int) -> tuple[str, int]:
    labels, end, hops = [], None, 0
    while True:
        n = msg[off]
        if n & 0xC0 == 0xC0:
            if end is None:
                end = off + 2
            off = ((n & 0x3F) << 8) | msg[off + 1]
            hops += 1
            if hops > 32:
                raise ValueError("name loop")
            continue
        off += 1
        if n == 0:
            break
        labels.append(msg[off:off + n].decode(errors="replace"))
        off += n
    return ".".join(labels), (end if end is not None else off)


def _records(msg: bytes):
    qd, an, ns, ar = struct.unpack(">4H", msg[4:12])
    off = 12
    for _ in range(qd):
        _, off = _name(msg, off)
        off += 4
    for _ in range(an + ns + ar):
        name, off = _name(msg, off)
        rtype, _, _, rdlen = struct.unpack(">HHIH", msg[off:off + 10])
        off += 10
        yield name, rtype, msg, off, rdlen
        off += rdlen


def discover(seconds: float = 1.5) -> list[dict]:
    """The hosts that answer on the local network: [{name, address, port}]."""
    q = struct.pack(">6H", 0, 0, 1, 0, 0, 0)
    q += b"".join(bytes([len(l)]) + l.encode() for l in SERVICE.split(".")) + b"\0"
    q += struct.pack(">HH", 12, 0x8001)  # PTR, IN, unicast response wanted
    ptrs, srvs, addrs = set(), {}, {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        s.settimeout(0.2)
        s.sendto(q, ("224.0.0.251", 5353))
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                msg, _ = s.recvfrom(9000)
            except socket.timeout:
                continue
            try:
                for name, rtype, m, off, rdlen in _records(msg):
                    if rtype == 12 and name.lower() == SERVICE:  # PTR -> instance
                        ptrs.add(_name(m, off)[0])
                    elif rtype == 33:  # SRV -> target, port
                        port = struct.unpack(">H", m[off + 4:off + 6])[0]
                        srvs[name] = (_name(m, off + 6)[0], port)
                    elif rtype == 1 and rdlen == 4:  # A
                        addrs[name.lower()] = socket.inet_ntoa(m[off:off + 4])
            except (IndexError, ValueError, struct.error):
                continue  # a packet we can't read: someone else's
    found = []
    for inst in ptrs:
        target, port = srvs.get(inst, ("", HTTP_PORT))
        address = addrs.get(target.lower())
        if address:
            found.append({"name": inst.split(".")[0], "address": address, "port": port})
    return found
