"""The "Kettle" network share of ~/Emulation (Samba), for copying games from a Windows, macOS or
Linux computer. Off until the user turns it on in the Emulation plugin; kettle-emu-share does
the root part (through pkexec) and this module is what the plugin calls.

Turned on, it owns:
  /etc/samba/smb.conf                  only when there was none (marked as Kettle's); a smb.conf
                                       of the user's own must include kettle-emulation.conf
  /etc/samba/kettle-emulation.conf     the [Kettle] share
  /etc/avahi/services/kettle-smb.service   so macOS and Linux file managers list the device
  /etc/samba/kettle-emulation.state    what turning it on started (avahi-daemon), for turning off
plus the user's Samba password (smbpasswd) and smb.service and nmb.service enabled. Turning it
off removes the files, disables the units and the Samba password. /etc is kept across A/B
updates, so the share stays as the user left it.
"""
import json
import os
import socket
import subprocess

HELPER = "/usr/lib/kettle/kettle-emu-share"
SMB_CONF = "/etc/samba/smb.conf"
SHARE_CONF = "/etc/samba/kettle-emulation.conf"
AVAHI_SERVICE = "/etc/avahi/services/kettle-smb.service"
STATE = "/etc/samba/kettle-emulation.state"
SHARE = "Kettle"
MARK = "# Kettle Linux: written by kettle-emu-share (the Emulation plugin's network share)"
INCLUDE = f"include = {SHARE_CONF}"
MIN_PASSWORD = 8


def smb_conf():
    return f"""{MARK}
# Remove this file only with the share turned off. To use a smb.conf of your own instead, keep
# the include line below in its [global] section.
[global]
   workgroup = WORKGROUP
   server string = Kettle
   server role = standalone server
   security = user
   map to guest = never
   server min protocol = SMB2_10
   # local networks only
   hosts allow = 127. 10. 172.16.0.0/12 192.168. 169.254. fe80::/10 fc00::/7
   load printers = no
   printing = bsd
   printcap name = /dev/null
   disable spoolss = yes
   {INCLUDE}
"""


def share_conf(user, path):
    return f"""{MARK}
[{SHARE}]
   comment = Kettle games: ROMs, BIOS, saves
   path = {path}
   valid users = {user}
   force user = {user}
   read only = no
   browseable = yes
   create mask = 0644
   directory mask = 0755
"""


AVAHI = f"""<?xml version="1.0" standalone='no'?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<!-- {MARK[2:]} -->
<service-group>
  <name replace-wildcards="yes">%h</name>
  <service>
    <type>_smb._tcp</type>
    <port>445</port>
  </service>
</service-group>
"""


def _active(unit):
    return subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0


def _enabled(unit):
    return subprocess.run(["systemctl", "is-enabled", "--quiet", unit]).returncode == 0


def status():
    """{enabled, active, share, path, user, hostname, urls} without root."""
    conf = {}
    try:
        with open(SHARE_CONF) as f:
            for line in f:
                k, sep, v = line.strip().partition(" = ")
                if sep:
                    conf[k] = v
    except OSError:
        pass
    host = socket.gethostname()
    from .upload import lan_addresses
    addrs = lan_addresses()
    return {"enabled": bool(conf) and _enabled("smb.service"), "active": _active("smb.service"),
            "share": SHARE, "path": conf.get("path"), "user": conf.get("valid users"),
            "hostname": host,
            "urls": [f"smb://{host}.local/{SHARE}"] + [f"\\\\{a}\\{SHARE}" for a in addrs]}


def _helper(*args, password=None):
    r = subprocess.run(["pkexec", HELPER, *args], input=(password + "\n") if password else "",
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"kettle-emu-share {args[0]} failed ({r.returncode})")
    return r.stdout


def enable(password):
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"the password needs at least {MIN_PASSWORD} characters")
    if "\n" in password or "\0" in password:
        raise ValueError("the password can't have line breaks")
    # the folder the share is of: made here, as the user (kettle-emu-share, as root, won't)
    os.makedirs(os.path.join(os.path.expanduser("~"), "Emulation"), exist_ok=True)
    _helper("enable", password=password)
    return status()


def disable():
    _helper("disable")
    return status()
