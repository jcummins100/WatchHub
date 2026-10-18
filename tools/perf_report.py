#!/usr/bin/env python3
"""How long WatchHub's screens take to load, from a Shield's Kodi log.

    python3 tools/perf_report.py --ip 10.100.1.245            # this Kodi session (kodi.log)
    python3 tools/perf_report.py --file test-results/<run>/kodi.log

Reads the add-on's own timing lines: "timing: <call> 1.23s" (every home row and list, from the plugin
call's start to its list being on screen), the info page (request -> on screen -> details ->
series row -> where-to-watch), TV Guide tabs, Browse, the sports calendar and the service's guide build.
Prints, per kind of screen: how many times, typical (median) and worst, slowest first.
"""
import argparse
import re
import statistics
import subprocess
import sys
import time

LOG = "/sdcard/Android/data/org.xbmc.kodi/files/.kodi/temp/kodi.log"
TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d+)")
PATTERNS = [
    (re.compile(r"timing: (.+?) ([\d.]+)s$"), lambda m: ("list: " + m.group(1), float(m.group(2)))),
    (re.compile(r"guide: (.+?) tab drawn \((\d+) rows\) in ([\d.]+)s"), lambda m: ("TV Guide tab: " + ("All" if m.group(1) == "All" else "other tabs"), float(m.group(3)))),
    (re.compile(r"guide: (\d+) channel rows built in ([\d.]+)s"), lambda m: ("service: guide channel list build", float(m.group(2)))),
    (re.compile(r"browse: (.+?) live row \((\d+)\) in ([\d.]+)s"), lambda m: ("Browse: live row", float(m.group(3)))),
    (re.compile(r"browse: (.+?) on-demand rows .* in ([\d.]+)s"), lambda m: ("Browse: shows/movies rows", float(m.group(2)))),
    (re.compile(r"calendar: (\w+) week ([+-]\d+) drawn in ([\d.]+)s"), lambda m: ("Calendar: a week", float(m.group(3)))),
    (re.compile(r"info: JustWatch lookup for .* in ([\d.]+)s"), lambda m: ("Info page: title lookup (before it opens)", float(m.group(1)))),
    (re.compile(r"info: details \+ Trakt filled in ([\d.]+)s"), lambda m: ("Info page: details + Trakt", float(m.group(1)))),
    (re.compile(r"info: \d+ in the series, \d+ you may also like on screen \(([\d.]+)s\)"), lambda m: ("Info page: series row on screen", float(m.group(1)))),
    (re.compile(r"info: where-to-watch filled in \(([\d.]+)s\)"), lambda m: ("Info page: where-to-watch bars", float(m.group(1)))),
    (re.compile(r"row (\w+) from its snapshot \((\d+) s old\) in ([\d.]+)s"), lambda m: ("list (saved copy): " + m.group(1), float(m.group(3)))),
    (re.compile(r"service views warmed in ([\d.]+)s"), lambda m: ("service: per-service rows warmed", float(m.group(1)))),
]


def read(args):
    if args.file:
        return open(args.file, encoding="utf-8", errors="replace").read().splitlines()
    out = subprocess.run(["adb", "-s", "%s:5555" % args.ip, "shell", "cat", LOG], capture_output=True, text=True)
    return out.stdout.splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="10.100.1.245")
    ap.add_argument("--file")
    ap.add_argument("--slow", type=float, default=3.0, help="flag anything slower than this many seconds")
    args = ap.parse_args()
    lines = [l for l in read(args) if "plugin.video.sportshub" in l]
    stats = {}
    req = {}
    for line in lines:
        m = TS.match(line)
        t = time.mktime(time.strptime(m.group(1)[:19], "%Y-%m-%d %H:%M:%S")) + float("0." + m.group(1)[20:]) if m else 0
        # info page: request -> on screen (the wait after pressing OK on a poster)
        r = re.search(r"info: request for (.+)$", line)
        if r:
            req["info"] = t
        if "info: page on screen" in line and req.get("info"):
            stats.setdefault("Info page: OK -> page on screen", []).append(t - req.pop("info"))
        for pat, fn in PATTERNS:
            mm = pat.search(line)
            if mm:
                k, v = fn(mm)
                stats.setdefault(k, []).append(v)
                break
    if not stats:
        print("No WatchHub timing lines in this log (0.7.28 or later writes them).")
        return 1
    rows = sorted(((statistics.median(v), max(v), len(v), k) for k, v in stats.items()), reverse=True)
    print("%-52s %5s %8s %8s" % ("screen", "times", "typical", "worst"))
    for med, worst, n, k in rows:
        flag = "  <- slow" if med >= args.slow else ""
        print("%-52s %5d %7.2fs %7.2fs%s" % (k[:52], n, med, worst, flag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
