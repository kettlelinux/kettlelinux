#!/usr/bin/env python3
"""Print every file the given slang presets/shaders need (passes, #include, #reference, textures),
relative to the slang-shaders tree in the current directory."""
import os
import re
import sys

seen = set()
FILES = ('.slang', '.slangp', '.inc', '.h', '.png', '.jpg')


def add(path):
    path = os.path.normpath(path)
    if path in seen:
        return
    if not os.path.isfile(path):
        sys.exit(f"slang-subset: missing {path}")
    seen.add(path)
    if path.endswith(('.png', '.jpg')):
        return
    text = open(path, errors='replace').read()
    here = os.path.dirname(path)
    if path.endswith('.slangp'):
        for m in re.finditer(r'^\s*#reference\s+"([^"]+)"', text, re.M):
            add(os.path.join(here, m.group(1)))
        for m in re.finditer(r'^\s*[A-Za-z0-9_]+\s*=\s*"?([^"\n]+?)"?\s*$', text, re.M):
            for part in m.group(1).split(';'):
                if part.endswith(FILES):
                    add(os.path.join(here, part))
    else:
        for m in re.finditer(r'^\s*#include\s+"([^"]+)"', text, re.M):
            add(os.path.join(here, m.group(1)))


for line in open(sys.argv[1]):
    line = line.split('#', 1)[0].strip()
    if line:
        add(line)
print('\n'.join(sorted(seen)))
