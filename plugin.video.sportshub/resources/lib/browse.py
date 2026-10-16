"""Browse: one category across everything WatchHub knows about.

Picking a category (Comedy, Crime, Kids...) from the home row opens one screen with up to three rows:
channels in that category that are on right now (from the TV Guide's list), then popular shows and
movies with that genre on your services (JustWatch). Categories that only exist as channels (News,
Game Shows, Talk...) show the live row alone. Opened by the service like the guide (uiworker.py).
"""
import json
import threading
import time

import xbmc
import xbmcgui

from resources.lib import categories, guide, kodi, launcher
from resources.lib.sources import ondemand

LIVE, SHOWS, MOVIES, LIVE_GRID = 100, 200, 300, 110
ACTION_BACK, ACTION_NAV_BACK = 10, 92
LIVE_MAX = 80
GRID_MAX = 120


def tiles():
    """(category, live channel count, has on-demand titles) for the home row, Sports left out (it has its own rows)."""
    # the service publishes the counts with each guide build; building the list here would take ~4 s per home load
    try:
        counts = json.loads(xbmcgui.Window(10000).getProperty(guide.COUNTS_PROP) or "null")
    except ValueError:
        counts = None
    if not counts:
        counts = guide.genre_counts(guide.channels())
    out = []
    for c in categories.CATEGORIES:
        if c == "Sports":
            continue
        on_demand = has_ondemand(c)
        if counts.get(c) or on_demand:
            out.append((c, counts.get(c, 0), on_demand))
    return out


def _on_now(programs, now):
    """(title, minutes left) of what's on now, or (None, 0)."""
    for i, (start, title) in enumerate(programs):
        end = programs[i + 1][0] if i + 1 < len(programs) else None
        if start <= now and (end is None or now < end):
            return title, int((end - now) // 60) if end else 0
    return None, 0


def live_items(cat, limit=LIVE_MAX):
    now = time.time()
    rows = []
    seen = set()
    for c in guide.in_tab(guide.channels(), cat, []):
        title, left = _on_now(c["programs"], now)
        # one card per channel: the guide keeps BUZZR on Pluto and on Roku apart when their schedules
        # differ; Browse shows the first (preferred service), the other stays in the guide
        key = c["key"].replace(" ", "")  # "Wipeout Xtra" / "WipeoutXtra"
        if title and key not in seen:
            seen.add(key)
            rows.append((c, title, left))
    rows.sort(key=lambda r: r[0]["name"].lower())
    return rows[:limit]


def has_ondemand(cat):
    return cat == "Movies" or bool(categories.JW_FOR.get(cat))


def _ondemand(cat, kind):
    if cat == "Movies":
        return ondemand.titles(object_types=("MOVIE",), first=40) if kind == "MOVIE" else []
    codes = categories.JW_FOR.get(cat)
    if not codes:
        return []
    return ondemand.titles(object_types=(kind,), first=40, genres=codes)


class Browse(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.cat = kwargs.get("cat") or "Comedy"
        self.live = []
        self.live_id = LIVE
        self.shows, self.movies = [], []
        self.closed = threading.Event()
        super().__init__(*args)
        self.setProperty("title", self.cat)
        self.setProperty("loading", "1")

    def onInit(self):
        t = time.time()
        self.live = live_items(self.cat)
        # a channels-only category (News, Game Shows, Talk...) fills the screen with a grid instead of one row
        self.live_id = LIVE if has_ondemand(self.cat) else LIVE_GRID
        if self.live_id == LIVE_GRID:
            self.live = live_items(self.cat, GRID_MAX)
            self.setProperty("liveonly", "1")
        lst = self.getControl(self.live_id)
        lst.reset()
        items = []
        for c, title, left in self.live:
            li = xbmcgui.ListItem(c["name"])
            li.setArt({"thumb": c["logo"]})
            li.setProperty("now", title)
            li.setProperty("meta", "%s%s" % (c["service"], " · %d min left" % left if left else ""))
            items.append(li)
        lst.addItems(items)
        self.setProperty("live_count", "%d on now" % len(self.live) if self.live else "")
        if self.live:
            self._focus(self.live_id)
        kodi.log("browse: %s live row (%d) in %.2fs" % (self.cat, len(self.live), time.time() - t))
        if self.live_id == LIVE_GRID:
            self.setProperty("loading", "")
            self.setProperty("empty", "" if self.live else "1")
            return
        threading.Thread(target=self._load, name="sh-browse", daemon=True).start()

    def _load(self):
        t = time.time()
        try:
            shows = _ondemand(self.cat, "SHOW")
            movies = _ondemand(self.cat, "MOVIE")
        except Exception as exc:
            kodi.log("browse: on-demand failed: %s" % exc)
            shows, movies = [], []
        if self.closed.is_set():
            return
        self.shows, self.movies = shows, movies
        for cid, rows in ((SHOWS, shows), (MOVIES, movies)):
            lst = self.getControl(cid)
            lst.reset()
            items = []
            for it in rows:
                li = xbmcgui.ListItem(it["title"])
                li.setArt({"thumb": it["poster"] or "DefaultVideo.png"})
                li.setProperty("service", it["service"])
                items.append(li)
            lst.addItems(items)
        self.setProperty("loading", "")
        self.setProperty("empty", "" if (self.live or shows or movies) else "1")
        if not self.live and (shows or movies):
            self._focus(SHOWS if shows else MOVIES)
        kodi.log("browse: %s on-demand rows (%d shows, %d movies) in %.2fs" % (self.cat, len(shows), len(movies), time.time() - t))

    def _focus(self, cid):
        for _ in range(10):  # a row only takes focus once the skin has shown it (it's hidden while empty)
            self.setFocusId(cid)
            if self.getFocusId() == cid:
                return
            xbmc.sleep(30)

    def onAction(self, action):
        if action.getId() in (ACTION_BACK, ACTION_NAV_BACK):
            self.close()

    def onClick(self, control_id):
        pos = self.getControl(control_id).getSelectedPosition()
        if control_id in (LIVE, LIVE_GRID) and 0 <= pos < len(self.live):
            launcher.play(self.live[pos][0]["play"])
        elif control_id in (SHOWS, MOVIES):
            rows = self.shows if control_id == SHOWS else self.movies
            if 0 <= pos < len(rows):
                from resources.lib import infodialog
                infodialog.show(rows[pos])


def show(cat):
    kodi.log("browse: open %s" % cat)
    win = Browse("Browse.xml", kodi.ADDON_PATH, "Default", "1080i", cat=cat)
    try:
        win.doModal()
    finally:
        win.closed.set()
    del win
