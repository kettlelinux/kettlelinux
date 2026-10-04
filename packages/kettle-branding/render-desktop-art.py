#!/usr/bin/python3
# Steam library artwork for the Desktop shortcut (the Plasma desktop nested in Game Mode): the
# kettle inside a desktop window, on black with the splash's warm glow, and DESKTOP in plain
# strokes like the boot splash's wordmark (no font). Usage: render-desktop-art.py <art dir> <out dir>
#   capsule.png 600x900   portrait capsule     header.png 920x430  wide capsule
#   hero.png    3840x1240 library page banner  logo.png   1280x320 drawn over the hero
#   icon.png    256x256   the shortcut's icon
import os
import subprocess
import sys

art, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)


def inner(name):
    """An SVG's contents without its own <svg> element."""
    with open(os.path.join(art, name)) as f:
        return "".join(f.read().strip().splitlines(True)[1:-1])


KETTLE = inner("kettle.svg")  # 256x256 box, drawing about x 42-242, y 68-218
GLOW = inner("glow.svg")  # 840x600
INK = "#f4efe9"

# D E S K T O P as straight strokes, 40 high, in the wordmark's style (wordmark.svg)
LETTERS = {
    "D": (26, "M0 0 H15 L26 11 V29 L15 40 H0 Z"),
    "E": (24, "M24 0 H0 V40 H24 M0 20 H19"),
    "S": (26, "M26 0 H7 L0 7 V14 L6 20 H20 L26 26 V33 L19 40 H0"),
    "K": (26, "M0 0 V40 M26 0 L5 20 L26 40"),
    "T": (28, "M0 0 H28 M14 0 V40"),
    "O": (28, "M8 0 H20 L28 8 V32 L20 40 H8 L0 32 V8 Z"),
    "P": (26, "M0 40 V0 H19 L26 7 V14 L19 21 H0"),
}
GAP = 30


def word(text):
    """The word's strokes, and its width in the 40-high box."""
    x, paths = 0, []
    for c in text:
        w, d = LETTERS[c]
        paths.append(f'<path transform="translate({x} 0)" d="{d}"/>')
        x += w + GAP
    return "".join(paths), x - GAP


def wordmark(text, cx, y, width):
    paths, w = word(text)
    s = width / w
    return (f'<g transform="translate({cx - width / 2:.1f} {y}) scale({s:.4f})" fill="none" '
            f'stroke="{INK}" stroke-width="6" stroke-linecap="square" stroke-linejoin="miter">'
            f'{paths}</g>')


def window(cx, cy, w):
    """A desktop window (title bar, three controls) with the kettle inside, w wide, 3:4 tall."""
    h = w * 0.72
    x, y = cx - w / 2, cy - h / 2
    sw = w / 110
    bar = h * 0.14
    dots = "".join(f'<circle cx="{x + w - bar * (0.55 + 0.75 * i):.1f}" cy="{y + bar / 2:.1f}" '
                   f'r="{bar * 0.17:.1f}" fill="{INK}" opacity="{0.9 - 0.25 * i:.2f}"/>'
                   for i in range(3))
    k = (h - bar) * 0.78  # the kettle drawing's height
    ks = k / 150  # its 150-high drawing in the 256 box
    kx, ky = cx - 142 * ks, y + bar + (h - bar) / 2 - 143 * ks
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{w / 40:.1f}" '
            f'fill="#120b07" stroke="{INK}" stroke-width="{sw:.1f}" opacity="0.95"/>'
            f'<line x1="{x:.1f}" y1="{y + bar:.1f}" x2="{x + w:.1f}" y2="{y + bar:.1f}" '
            f'stroke="{INK}" stroke-width="{sw:.1f}" opacity="0.95"/>{dots}'
            f'<g transform="translate({kx:.1f} {ky:.1f}) scale({ks:.4f})">{KETTLE}</g>')


def glow(cx, cy, w, opacity=0.55):
    s = w / 840
    return (f'<g opacity="{opacity}" transform="translate({cx - 420 * s:.1f} {cy - 300 * s:.1f}) '
            f'scale({s:.4f})">{GLOW}</g>')


def render(name, w, h, body, background=True):
    bg = f'<rect width="{w}" height="{h}" fill="#000"/>' if background else ""
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
           f'viewBox="0 0 {w} {h}">{bg}{body}</svg>')
    path = os.path.join(out, name)
    with open(path + ".svg", "w") as f:
        f.write(svg)
    subprocess.run(["rsvg-convert", path + ".svg", "-o", path], check=True)
    os.remove(path + ".svg")


render("capsule.png", 600, 900,
       glow(300, 380, 760) + window(300, 360, 420) + wordmark("DESKTOP", 300, 640, 400))
render("header.png", 920, 430,
       glow(250, 215, 620) + window(250, 215, 330) + wordmark("DESKTOP", 650, 195, 400))
# Game Mode shows the hero's middle band, under its status bar: the window kept within it
render("hero.png", 3840, 1240,
       glow(2750, 680, 1700, 0.5) + window(2750, 680, 760))
render("logo.png", 1280, 320, wordmark("DESKTOP", 640, 110, 1200), background=False)
render("icon.png", 256, 256,
       f'<rect width="256" height="256" rx="40" fill="#000"/>' + glow(128, 128, 330)
       + window(128, 128, 210), background=False)
