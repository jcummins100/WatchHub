#!/usr/bin/env python3
"""Print the TV Guide's channel sorting as JSON (run outside Kodi, like dev_run.py).

    SH_apps=tv.pluto.android,com.plexapp.android,com.roku.web.trc python3 tools/guide_report.py

Used by watchhub_test.py (A6) to check the Game Shows tab, Plex/Roku genres and the Spanish filter.
"""
import contextlib
import io
import json
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.argv = [sys.argv[0], "action=__none__"]
with contextlib.redirect_stdout(io.StringIO()):
    runpy.run_path(os.path.join(ROOT, "tools", "dev_run.py"), run_name="guide_report")
sys.path.insert(0, os.path.join(ROOT, "plugin.video.sportshub"))
from resources.lib import guide  # noqa: E402
from resources.lib.sources import fast  # noqa: E402

chans = guide.channels()
tabs = {}
for tab in guide.FIXED_TABS:
    if tab in ("Favorites", "All"):
        continue
    rows = guide.in_tab(chans, tab, [])
    by = {}
    for c in rows:
        by[c["service"]] = by.get(c["service"], 0) + 1
    tabs[tab] = {"total": len(rows), "by_service": by}
out = {
    "rows": len(chans),
    "tabs": tabs,
    "game_shows": sorted({c["name"] for c in guide.in_tab(chans, "Game Shows", [])}),
    "spanish_shown": sorted({c["name"] for c in chans if fast.is_spanish({"name": c["name"]})}),
}
print(json.dumps(out))
