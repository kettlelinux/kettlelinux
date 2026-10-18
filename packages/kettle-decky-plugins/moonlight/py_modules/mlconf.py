# moonlight-qt's own config (~/.config/Moonlight Game Streaming Project/Moonlight.conf), read and
# written through Qt's QSettings (PySide6), as moonlight-qt does: the same escaping, and its lock
# file, so a write here and one by a running moonlight-qt don't clobber each other.
# What the plugin needs from it: moonlight-qt's identity (uniqueid, client certificate and key,
# shared by every host it pairs with) and the hosts it knows, with each one's pinned certificate.
import os

import decky

PATH = os.path.join(decky.DECKY_USER_HOME, ".config", "Moonlight Game Streaming Project", "Moonlight.conf")


def _settings():
    from PySide6.QtCore import QSettings  # Qt only when the config is read, not at plugin start

    return QSettings(PATH, QSettings.IniFormat)


def _bytes(v) -> bytes:
    if v is None:
        return b""
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    if hasattr(v, "data"):  # QByteArray
        return bytes(v.data())
    return str(v).encode("latin-1")


def identity() -> tuple[str, bytes, bytes] | None:
    """moonlight-qt's uniqueid, client certificate and key (PEM), or None before its first run."""
    s = _settings()
    uid = s.value("uniqueid")
    cert, key = _bytes(s.value("certificate")), _bytes(s.value("key"))
    if not uid or not cert or not key:
        return None
    return str(uid), cert, key


def hosts() -> list[dict]:
    """The hosts moonlight-qt knows; paired ones have their certificate (srvcert)."""
    s = _settings()
    out = []
    n = s.beginReadArray("hosts")
    for i in range(n):
        s.setArrayIndex(i)
        addresses = []
        for a, p in (("manualaddress", "manualport"), ("localaddress", "localport"), ("remoteaddress", "remoteport")):
            addr = s.value(a)
            if addr:
                addresses.append((str(addr), int(s.value(p) or 0) or 47989))
        mac = _bytes(s.value("mac"))
        out.append({
            "uuid": str(s.value("uuid") or ""),
            "name": str(s.value("hostname") or ""),
            "addresses": addresses,
            "mac": ":".join(f"{b:02x}" for b in mac) if len(mac) == 6 else "",
            "srvcert": _bytes(s.value("srvcert")),
        })
    s.endArray()
    return [h for h in out if h["uuid"]]


def forget(host_uuid: str) -> bool:
    """Takes a host out of moonlight-qt's list (its pairing with it ends here; the host keeps the
    device in its own list until it's removed there)."""
    s = _settings()
    keep = []
    n = s.beginReadArray("hosts")
    for i in range(n):
        s.setArrayIndex(i)
        entry = {k: s.value(k) for k in s.allKeys()}
        if str(s.value("uuid") or "") != host_uuid:
            keep.append(entry)
    s.endArray()
    if len(keep) == n:
        return False
    s.remove("hosts")
    s.beginWriteArray("hosts", len(keep))
    for i, entry in enumerate(keep):
        s.setArrayIndex(i)
        for k, v in entry.items():
            s.setValue(k, v)
    s.endArray()
    s.sync()
    return True
