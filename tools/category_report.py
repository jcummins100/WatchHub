#!/usr/bin/env python3
"""List the TV Guide channels in one category with their service labels and what they air (run outside Kodi).

    SH_apps=tv.pluto.android,com.plexapp.android,com.roku.web.trc,com.tubitv,com.xumo.xumo.tv python3 tools/category_report.py [Category]

Default category: Other (channels with no category). Used to sort channels by hand (CHANNEL_CATS in categories.py).
"""
import contextlib, io, os, runpy, sys
ROOT=os.getcwd(); CAT = sys.argv[1:]; sys.argv=[sys.argv[0],"action=__none__"]
with contextlib.redirect_stdout(io.StringIO()):
    runpy.run_path(os.path.join(ROOT,"tools","dev_run.py"), run_name="x")
sys.path.insert(0, os.path.join(ROOT,"plugin.video.sportshub"))
from resources.lib import guide
ch=guide.channels()
for c in sorted(guide.in_tab(ch, CAT[0] if CAT else guide.OTHER, []), key=lambda c:c["name"].lower()):
    titles=[]
    for _,t in c["programs"]:
        if t not in titles: titles.append(t)
    print("%s [%s] groups=%s :: %s" % (c["name"], c["service"], c["groups"], " / ".join(titles[:5])[:150]))
