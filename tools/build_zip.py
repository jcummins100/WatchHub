#!/usr/bin/env python3
"""Package plugin.video.sportshub into an installable Kodi zip.

Usage: python3 tools/build_zip.py [--out build/]
The zip contains a single top-level folder named after the add-on id, which
is what Kodi's "Install from zip file" expects.
"""
import argparse
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_ID = "plugin.video.sportshub"
SRC = os.path.join(ROOT, ADDON_ID)
SKIP_DIRS = {"__pycache__", ".git", ".DS_Store"}
SKIP_EXT = {".pyc", ".pyo"}


def version():
    with open(os.path.join(SRC, "addon.xml"), encoding="utf-8") as fh:
        m = re.search(r'<addon[^>]*\bversion="([^"]+)"', fh.read(), re.S)
    return m.group(1) if m else "0.0.0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "build"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, "%s-%s.zip" % (ADDON_ID, version()))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(SRC):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn in SKIP_DIRS or os.path.splitext(fn)[1] in SKIP_EXT:
                    continue
                full = os.path.join(dirpath, fn)
                arc = os.path.join(ADDON_ID, os.path.relpath(full, SRC))
                zf.write(full, arc)
    print(out)


if __name__ == "__main__":
    main()
