#!/usr/bin/python3
# Steam library artwork for the Game Stores plugin's Mod Manager entry: Amethyst's own banner
# (icons/AmethystBanner.png, the purple wordmark) on a dark violet glow, and its app icon.
# Usage: render-steam-art.py <banner.png> <icon.png> <out dir>
#   capsule.png 600x900   portrait capsule     header.png 920x430  wide capsule
#   hero.png    3840x1240 library page banner  logo.png   1280x320 drawn over the hero
#   icon.png    256x256   the shortcut's icon
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

banner_path, icon_path, out = sys.argv[1:4]
os.makedirs(out, exist_ok=True)
banner = Image.open(banner_path).convert("RGBA")
banner = banner.crop(banner.getbbox())  # the wordmark without its transparent margin

BG = (14, 9, 22)
GLOW = (96, 38, 160)


def backdrop(w, h):
    """Near black with a soft violet glow behind the middle."""
    im = Image.new("RGB", (w, h), BG)
    glow = Image.new("L", (w, h), 0)
    ImageDraw.Draw(glow).ellipse((w * 0.15, h * 0.25, w * 0.85, h * 0.75), fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) * 0.18))
    im.paste(Image.new("RGB", (w, h), GLOW), mask=glow)
    return im


def fit(im, w, h):
    s = min(w / im.width, h / im.height)
    return im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)


def card(w, h, width_share):
    im = backdrop(w, h)
    mark = fit(banner, w * width_share, h * 0.8)
    im.paste(mark, ((w - mark.width) // 2, (h - mark.height) // 2), mark)
    return im


card(600, 900, 0.86).save(os.path.join(out, "capsule.png"))
card(920, 430, 0.8).save(os.path.join(out, "header.png"))
backdrop(3840, 1240).save(os.path.join(out, "hero.png"))
logo = Image.new("RGBA", (1280, 320), (0, 0, 0, 0))
mark = fit(banner, 1280, 320)
logo.paste(mark, ((1280 - mark.width) // 2, (320 - mark.height) // 2), mark)
logo.save(os.path.join(out, "logo.png"))
fit(Image.open(icon_path).convert("RGBA"), 256, 256).save(os.path.join(out, "icon.png"))
