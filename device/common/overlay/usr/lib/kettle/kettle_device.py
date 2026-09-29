"""This image's device settings: device/<name>/device.conf, which scripts/build-image.sh installs
as /usr/lib/kettle/device.conf (KEY=value lines, shell quoting, # comments), with DEVICE=<name>.
Scripts in /usr/lib/kettle import it; shell scripts source the file instead.
"""
import shlex

PATH = "/usr/lib/kettle/device.conf"


def load(path=PATH):
    conf = {}
    try:
        with open(path) as f:
            for line in f:
                for word in shlex.split(line, comments=True):
                    key, sep, value = word.partition("=")
                    if sep:
                        conf[key] = value
    except OSError:
        pass
    return conf


conf = load()
