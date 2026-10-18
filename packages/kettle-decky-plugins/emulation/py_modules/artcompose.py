# Composes a ROM's Steam artwork from libretro-thumbnails' pictures, in a process of its own
# (Qt stays out of the plugin's): art.py runs
#   artcompose.py <out dir> <box art> <snap> <title screen>     (a missing one: "")
# and reads {Steam asset type: PNG path} as JSON from stdout:
#   0 portrait capsule 600x900: the box art whole, on a blurred, darkened copy of itself
#   1 hero 1920x620: the snap (else the title screen), filling it
#   3 wide capsule 920x430: the title screen (else the snap, else the box art), whole, on its blur
# Box art comes in every shape (a cartridge label, a CD case, a tall DVD box), so it's never cut.
import json
import os
import sys

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

SIZES = {0: (600, 900), 1: (1920, 620), 3: (920, 430)}


def blurred(img: QImage, w: int, h: int) -> QImage:
    """img filling w x h, blurred (down to a few pixels and back) and darkened."""
    small = img.scaled(max(1, w // 24), max(1, h // 24), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    big = small.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = big.copy(QRect((big.width() - w) // 2, (big.height() - h) // 2, w, h)).convertToFormat(QImage.Format_ARGB32)
    p = QPainter(out)
    p.fillRect(out.rect(), QColor(0, 0, 0, 110))
    p.end()
    return out


def fit(img: QImage, w: int, h: int, margin: int) -> QImage:
    """img whole, as large as fits w x h less the margin, on its own blur."""
    canvas = blurred(img, w, h)
    # pixel art stays sharp when it grows a lot
    mode = Qt.FastTransformation if img.width() * 3 <= w else Qt.SmoothTransformation
    inner = img.scaled(w - 2 * margin, h - 2 * margin, Qt.KeepAspectRatio, mode)
    p = QPainter(canvas)
    p.drawImage((w - inner.width()) // 2, (h - inner.height()) // 2, inner)
    p.end()
    return canvas


def fill(img: QImage, w: int, h: int) -> QImage:
    mode = Qt.FastTransformation if img.width() * 3 <= w else Qt.SmoothTransformation
    big = img.scaled(w, h, Qt.KeepAspectRatioByExpanding, mode)
    return big.copy(QRect((big.width() - w) // 2, (big.height() - h) // 2, w, h))


def load(path: str) -> QImage | None:
    if not path:
        return None
    img = QImage(path)
    return None if img.isNull() else img


def main(argv: list[str]) -> int:
    out_dir, box, snap, title = argv[1], load(argv[2]), load(argv[3]), load(argv[4])
    QGuiApplication(argv[:1])
    made = {}
    plans = {
        0: (box, lambda i: fit(i, 600, 900, 36)),
        1: (snap or title, lambda i: fill(i, 1920, 620)),
        3: (title or snap or box, lambda i: fit(i, 920, 430, 24)),
    }
    for kind, (img, how) in plans.items():
        if img is None:
            continue
        path = os.path.join(out_dir, f"{kind}.png")
        if how(img).save(path, "PNG"):
            made[kind] = path
    print(json.dumps(made))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
