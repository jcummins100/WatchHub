#!/usr/bin/env python3
"""Refresh the Plex channel-link snapshot (run outside Kodi, with each release).

    python3 tools/plex_slugs.py

Plex channel links are https://watch.plex.tv/live-tv/channel/<slug>, and the slug can't be worked out from the
name: Plex adds -2/-3 when names repeat ("21 Jump Street" is 21-jump-street-2) and renames some ("ION" is
ion-streaming). The guide page on watch.plex.tv lists every channel's id and slug; this saves them to
plugin.video.sportshub/resources/data/plex_slugs.json as {channel id: slug}. The channel id is the part after
the "-" in i.mjh.nz's Plex ids (the part before it is the region).
"""
import json, os, re, sys, time, urllib.request

PAGES = ["https://watch.plex.tv/live-tv", "https://watch.plex.tv/live-tv/channel/get"]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plugin.video.sportshub", "resources", "data",
                   "plex_slugs.json")
PAIR = re.compile(r'\\?"id\\?":\\?"(?:[0-9a-f]{24}-)?([0-9a-f]{24})\\?",\\?"slug\\?":\\?"([a-z0-9-]+)\\?"')


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def main():
    slugs = {}
    for url in PAGES:
        found = dict(PAIR.findall(fetch(url)))
        print("%s: %d channels" % (url, len(found)))
        slugs.update(found)
        if len(slugs) > 300:
            break
    if len(slugs) < 300:
        sys.exit("Only %d channels found - Plex changed its page? Snapshot not written." % len(slugs))
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump({"captured": time.strftime("%Y-%m-%d"), "source": url, "slugs": dict(sorted(slugs.items()))},
                  fh, indent=0, sort_keys=False)
    print("wrote %d slugs to %s" % (len(slugs), os.path.normpath(OUT)))


if __name__ == "__main__":
    main()
