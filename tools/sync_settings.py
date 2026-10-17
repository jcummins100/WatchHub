#!/usr/bin/env python3
"""Keep WatchHub's settings and favorites the same on every Shield (run from the workstation, over adb).

    python3 tools/sync_settings.py --from 10.100.1.200 --to 10.100.1.245            # show what differs
    python3 tools/sync_settings.py --from 10.100.1.200 --to 10.100.1.245 --apply    # copy it over

Copies WatchHub's settings (subscriptions, Prime channels, sources, local stations, teams...) and the
favorites / hidden-channel lists. Never copies the Trakt sign-in (each Shield has its own; WatchHub
rotates the token, so a copy would sign the other one out). --apply quits Kodi on the target, writes
the files and starts Kodi again: run it when nobody is watching that TV.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import time

KODI = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi"
PROFILE = KODI + "/userdata/addon_data/plugin.video.sportshub"
NEVER = {"trakt_access_token", "trakt_refresh_token", "trakt_token_expires"}  # per Shield
FILES = ["favorites.json", "guide_favorites.json", "guide_hidden.json", "upnext_order.json"]
SETTING = re.compile(r'<setting id="([^"]+)"([^>]*?)(?:/>|>(.*?)</setting>)', re.S)


def adb(ip, *args, check=True):
    return subprocess.run(["adb", "-s", "%s:5555" % ip] + list(args), capture_output=True, text=True, check=check).stdout


def settings(ip):
    xml = adb(ip, "shell", "cat %s/settings.xml" % PROFILE)
    return xml, {m.group(1): (m.group(3) or "") for m in SETTING.finditer(xml)}


def read_file(ip, name):
    return adb(ip, "shell", "cat %s/%s 2>/dev/null" % (PROFILE, name), check=False)


def merged_xml(target_xml, values):
    """The target's settings.xml with the source's values for every shared setting."""
    def put(m):
        sid = m.group(1)
        if sid in NEVER or sid not in values:
            return m.group(0)
        v = values[sid].replace("&", "&amp;").replace("<", "&lt;") if "&" not in values[sid] else values[sid]
        return '<setting id="%s">%s</setting>' % (sid, v) if v else '<setting id="%s" />' % sid
    xml = SETTING.sub(put, target_xml)
    missing = [k for k in values if k not in NEVER and not re.search(r'<setting id="%s"' % re.escape(k), xml)]
    if missing:
        add = "".join('    <setting id="%s">%s</setting>\n' % (k, values[k]) for k in missing)
        xml = xml.replace("</settings>", add + "</settings>")
    return xml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--to", dest="dst", required=True, nargs="+")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    _, src_vals = settings(a.src)
    src_files = {n: read_file(a.src, n) for n in FILES}
    for ip in a.dst:
        xml, vals = settings(ip)
        diff = [(k, vals.get(k, "(unset)"), v) for k, v in sorted(src_vals.items()) if k not in NEVER and vals.get(k) != v]
        fdiff = [n for n in FILES if read_file(ip, n) != src_files[n]]
        print("== %s: %d setting(s), %d list(s) differ from %s" % (ip, len(diff), len(fdiff), a.src))
        for k, old, new in diff:
            secretish = "key" in k or "secret" in k or "client_id" in k
            print("   %-24s %s -> %s" % (k, "***" if secretish else old, "***" if secretish else new))
        for n in fdiff:
            print("   %s" % n)
        if not a.apply or not (diff or fdiff):
            continue
        print("   quitting Kodi on %s ..." % ip)
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "cmd"), "w").write("Quit()\n")
            adb(ip, "push", os.path.join(tmp, "cmd"), PROFILE + "/cmd")
            for _ in range(20):
                time.sleep(2)
                if not adb(ip, "shell", "pidof org.xbmc.kodi", check=False).strip():
                    break
            else:
                sys.exit("   Kodi didn't quit on %s; nothing written" % ip)
            path = os.path.join(tmp, "settings.xml")
            open(path, "w").write(merged_xml(xml, src_vals))
            adb(ip, "push", path, PROFILE + "/settings.xml")
            for n in fdiff:
                if src_files[n]:
                    p = os.path.join(tmp, n)
                    open(p, "w").write(src_files[n])
                    adb(ip, "push", p, "%s/%s" % (PROFILE, n))
                else:
                    adb(ip, "shell", "rm -f %s/%s" % (PROFILE, n))
        adb(ip, "shell", "monkey -p org.xbmc.kodi -c android.intent.category.LEANBACK_LAUNCHER 1", check=False)
        print("   copied; Kodi started again")


if __name__ == "__main__":
    main()
