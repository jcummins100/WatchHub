#!/usr/bin/env python3
"""Build a personal Kodi add-on repository so Kodi auto-updates Sports Hub.

Output (default ./repo/) is a static site; host it anywhere (GitHub Pages works well):

    repo/
      addons.xml, addons.xml.md5
      plugin.video.sportshub/plugin.video.sportshub-<ver>.zip
      repository.sportshub/repository.sportshub-<ver>.zip   <- install this zip once in Kodi

Usage: python3 tools/make_repo.py --base-url https://<user>.github.io/<repo>/
Then bump the version in plugin.video.sportshub/addon.xml, re-run, push: Kodi picks it up on
its next add-on update check (default: every 24h, or Settings > Add-ons > Check for updates).
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ID = "repository.sportshub"
REPO_VERSION = "1.0.0"
ADDONS = ["plugin.video.sportshub", "skin.sportshub"]

REPO_ADDON_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="{id}" name="WatchHub Repository" version="{version}" provider-name="jcummins">
  <extension point="xbmc.addon.repository" name="WatchHub Repository">
    <dir>
      <info compressed="false">{base}addons.xml</info>
      <checksum>{base}addons.xml.md5</checksum>
      <datadir zip="true">{base}</datadir>
    </dir>
  </extension>
  <extension point="xbmc.addon.metadata">
    <summary lang="en_GB">Updates for WatchHub (add-on and skin)</summary>
    <description lang="en_GB">Keeps the WatchHub add-on and skin up to date automatically.</description>
    <platform>all</platform>
    <license>MIT</license>
  </extension>
</addon>
"""


def addon_xml_text(folder):
    with open(os.path.join(folder, "addon.xml"), encoding="utf-8") as fh:
        return fh.read()


def version_of(xml_text):
    return re.search(r'<addon[^>]*\bversion="([^"]+)"', xml_text, re.S).group(1)


def zip_dir(src, dest_zip, top):
    os.makedirs(os.path.dirname(dest_zip), exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", ".git")]
            for fn in filenames:
                if fn.endswith((".pyc", ".pyo")) or fn == ".DS_Store":
                    continue
                full = os.path.join(dirpath, fn)
                zf.write(full, os.path.join(top, os.path.relpath(full, src)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="public URL where repo/ will be served, with trailing slash")
    ap.add_argument("--out", default=os.path.join(ROOT, "repo"))
    args = ap.parse_args()
    base = args.base_url if args.base_url.endswith("/") else args.base_url + "/"
    out = args.out
    os.makedirs(out, exist_ok=True)

    # 1. The repository add-on itself (generated into a temp folder, then zipped).
    tmp_repo = os.path.join(out, "_" + REPO_ID)
    shutil.rmtree(tmp_repo, ignore_errors=True)
    os.makedirs(tmp_repo)
    repo_xml = REPO_ADDON_XML.format(id=REPO_ID, version=REPO_VERSION, base=base)
    with open(os.path.join(tmp_repo, "addon.xml"), "w", encoding="utf-8") as fh:
        fh.write(repo_xml)
    icon = os.path.join(ROOT, ADDONS[0], "icon.png")
    if os.path.exists(icon):
        shutil.copy(icon, os.path.join(tmp_repo, "icon.png"))
    zip_dir(tmp_repo, os.path.join(out, REPO_ID, "%s-%s.zip" % (REPO_ID, REPO_VERSION)), REPO_ID)
    shutil.rmtree(tmp_repo)

    # 2. Each add-on zip + collected addons.xml.
    entries = [repo_xml]
    for aid in ADDONS:
        src = os.path.join(ROOT, aid)
        xml = addon_xml_text(src)
        ver = version_of(xml)
        zip_dir(src, os.path.join(out, aid, "%s-%s.zip" % (aid, ver)), aid)
        for asset in ("icon.png", "fanart.jpg"):
            if os.path.exists(os.path.join(src, asset)):
                shutil.copy(os.path.join(src, asset), os.path.join(out, aid, asset))
        entries.append(xml)

    body = "\n".join(re.sub(r"<\?xml[^>]*\?>\s*", "", e).strip() for e in entries)
    addons_xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n%s\n</addons>\n' % body
    with open(os.path.join(out, "addons.xml"), "w", encoding="utf-8") as fh:
        fh.write(addons_xml)
    with open(os.path.join(out, "addons.xml.md5"), "w", encoding="utf-8") as fh:
        fh.write(hashlib.md5(addons_xml.encode("utf-8")).hexdigest())
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("<h1>WatchHub Kodi repository</h1><p>Install <a href='%s/%s-%s.zip'>%s-%s.zip</a> in Kodi.</p>\n"
                 % (REPO_ID, REPO_ID, REPO_VERSION, REPO_ID, REPO_VERSION))
    print("Repository written to", out)
    for dirpath, _, files in os.walk(out):
        for f in files:
            print("  ", os.path.relpath(os.path.join(dirpath, f), out))


if __name__ == "__main__":
    sys.exit(main())
