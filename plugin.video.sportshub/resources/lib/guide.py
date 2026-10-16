"""TV Guide: the free live channels (Pluto TV, Plex, The Roku Channel) as a time grid.

Channels down the side, two hours across in 30-minute columns. Left/right moves through time,
up/down through channels; tabs across the top pick Favorites, Sports, News, Movies, Game Shows, Kids,
All - or any specific category through "Categories". OK watches the channel now in its own app
(WatchHub never plays streams itself); long-press offers favorites, the channel's schedule and the
other services airing the same thing.

Each column shows what's on at its start; a programme that starts later inside the column is
flagged "+1 more" rather than silently dropped (a proportional grid isn't possible with Kodi lists).
"""
import difflib
import json
import os
import re
import threading
import time

import xbmc
import xbmcgui

from resources.lib import categories, kodi, launcher, sports
from resources.lib.sources import fast

SLOT = 1800            # one column = 30 minutes
COLS = 4               # columns on screen
COL_W, GRID_X = 360, 460  # column width and the x of the first column on screen (Guide.xml)
AHEAD = 16 * 3600      # furthest the first column can start from now (listings run 8-19 h ahead)
TABS, GRID, NOW_LINE, CAT_PANEL = 300, 500, 400, 600
ACTION_LEFT, ACTION_RIGHT, ACTION_CONTEXT, ACTION_BACK, ACTION_NAV_BACK = 1, 2, 117, 10, 92

# Fixed tabs (a D-pad can't browse 39 shifting genre tabs); every channel is in Shows/News/... by
# its genres, and "Categories" opens the full list as tiles.
FIXED_TABS = ["Favorites", "Sports", "News", "Movies", "Game Shows", "Kids", "All"]
GENRES_TAB = "Categories"   # opens the category tiles
OTHER = "Other"   # channels no source labels, name or show lookup could place: never dropped, listed here and in All

# Cell colours, the familiar cable-guide convention: green sports, purple movies, light blue kids, gold game shows,
# dark blue everything else. (normal, on now, focused row, focused row + on now)
COLORS = {
    "sports": ("FF1B3A2A", "FF22543A", "FF22482F", "FF2B6A47"),
    "movies": ("FF2E2140", "FF3E2C5A", "FF3A2A52", "FF4D3772"),
    "kids":   ("FF1C3A4F", "FF22506E", "FF23485F", "FF2A6386"),
    "gameshows": ("FF3A311A", "FF544520", "FF4A3E1F", "FF6A5726"),
    "":       ("FF1A2233", "FF22314F", "FF243150", "FF2E4472"),
}


TILE_COLORS = {"Sports": "FF22543A", "Movies": "FF3E2C5A", "Kids": "FF22506E", "Game Shows": "FF544520", "News": "FF5A2A2A",
               "Comedy": "FF5E4A1E", "Drama": "FF3A2E4F", "Crime": "FF4A2626", "Reality": "FF4F2E4A", "Horror": "FF3A1E1E",
               "Sci-Fi": "FF1E3A4F", "Westerns": "FF5A3E22", "Music": "FF2A4A5A", "International": "FF3A2E55", "Nature": "FF2E4A2A",
               "Food & Home": "FF5A3A22", "Travel": "FF22465A", "Single Show": "FF4A3A1E", "Local": "FF1F5A4A", OTHER: "FF2E3442"}


def category(chan, title):
    """sports / movies / kids / gameshows / '' for one programme on one channel (the cell colour)."""
    if chan["sports"] or sports.classify(title):
        return "sports"
    if "Game Shows" in chan["cats"]:
        return "gameshows"
    if "Kids" in chan["cats"]:
        return "kids"
    if "Movies" in chan["cats"]:
        return "movies"
    return ""


# ---------------------------------------------------------------- small json files in the profile
def _write_json(path, data):
    """Atomic write; True on success."""
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        kodi.log("guide: could not save %s: %s" % (os.path.basename(path), exc))
        return False


def _fav_path():
    return os.path.join(kodi.ensure_profile_dir(), "guide_favorites.json")


def favorites():
    try:
        with open(_fav_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return [x for x in data if isinstance(x, str)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _hidden_path():
    return os.path.join(kodi.ensure_profile_dir(), "guide_hidden.json")


def hidden():
    """Channels the user hid by hand (long-press > Hide this channel)."""
    try:
        with open(_hidden_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return [x for x in data if isinstance(x, str)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


# ---------------------------------------------------------------- "back to the guide" after an app
RETURN_WINDOW = 3 * 3600  # a cold start within this long after launching from the guide reopens it


def _return_path():
    return os.path.join(kodi.ensure_profile_dir(), "guide_return.json")


def remember_return(tab):
    _write_json(_return_path(), {"at": int(time.time()), "tab": tab})


def forget_return():
    try:
        os.remove(_return_path())
    except OSError:
        pass


def pending_return():
    """The tab to reopen on if Kodi was killed while a channel from the guide was playing, else None."""
    try:
        with open(_return_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict) and time.time() - float(data.get("at", 0)) < RETURN_WINDOW:
            return str(data.get("tab") or "")
    except (OSError, ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------- time
def _clock(ts, ampm=False):
    t = time.localtime(ts)
    s = "%d:%02d" % (t.tm_hour % 12 or 12, t.tm_min)
    return s + (" am" if t.tm_hour < 12 else " pm") if ampm else s


def _day(ts):
    """Today / Tomorrow / weekday, by local calendar date (not elapsed hours)."""
    d, today = time.localtime(ts), time.localtime()
    days = (time.mktime((d.tm_year, d.tm_mon, d.tm_mday, 12, 0, 0, 0, 0, -1)) -
            time.mktime((today.tm_year, today.tm_mon, today.tm_mday, 12, 0, 0, 0, 0, -1))) / 86400
    return {0: "Today", 1: "Tomorrow"}.get(round(days), time.strftime("%A", d))


def _now_slot():
    return int(time.time()) // SLOT * SLOT


# ---------------------------------------------------------------- data
def _programs(raw):
    out = []
    for entry in raw or []:
        try:
            out.append((int(entry[0]), str(entry[1])))
        except (TypeError, ValueError, IndexError):
            continue
    out.sort()
    return out


_BUILT = {"at": 0.0, "rows": None}
_BUILD_LOCK = threading.Lock()
BUILT_MAX_AGE = 20 * 60   # the service rebuilds after every data refresh (~10 min); this is a backstop


def channels(rebuild=False):
    """The guide's rows, kept built in memory by the service (building them takes ~1 s on a Shield).

    A rebuild happens beside the current list: callers keep getting the previous rows until the new ones
    are ready, so opening the guide never waits on a refresh. Only the very first build (right after Kodi
    starts) is waited for, and it gives listings that are still downloading a little time instead of
    showing an empty guide."""
    rows = _BUILT["rows"]
    if rows is not None:
        if rebuild:
            _rebuild_now()                      # the service's refresh thread: build, then swap
            return _BUILT["rows"]
        if time.time() - _BUILT["at"] > BUILT_MAX_AGE:
            _rebuild_in_background()            # stale: serve it this time, refresh behind it
        return rows
    with _BUILD_LOCK:
        if _BUILT["rows"] is None:              # first build: wait for it (another thread may have finished meanwhile)
            t = time.time()
            new = _build_channels()
            mon = xbmc.Monitor()
            for _ in range(10):
                if new or mon.waitForAbort(2):
                    break
                new = _build_channels()
            _publish(new, t)
        return _BUILT["rows"]


def _rebuild_now():
    """Build a new list and swap it in; skipped if another build is already running."""
    if not _BUILD_LOCK.acquire(blocking=False):
        return
    try:
        _publish(_build_channels())
    finally:
        _BUILD_LOCK.release()


COUNTS_PROP = "sh_category_counts"  # Home window property: channels per category, for the home Browse row


def _publish(rows, t=None):
    _BUILT.update(at=time.time(), rows=rows)
    try:
        xbmcgui.Window(10000).setProperty(COUNTS_PROP, json.dumps(genre_counts(rows)))
    except Exception as exc:  # no GUI (off-device tools)
        kodi.debug("category counts not published: %s" % exc)
    if t:
        kodi.log("guide: %d channel rows built in %.2fs" % (len(rows), time.time() - t))
    else:
        kodi.log("guide: %d channel rows rebuilt" % len(rows))


def _rebuild_in_background():
    threading.Thread(target=_rebuild_now, name="sh-guide-rebuild", daemon=True).start()


def _build_channels():
    """Every free channel with listings. The same channel on several services is one row: the preferred
    service's feed, the others under "Watch on..." (even when their schedules differ - no duplicate rows).
    Two same-named feeds on one service (regional versions) stay separate unless they air the same thing."""
    prio = {sid: i for i, sid in enumerate(fast.service_priority())}
    now = time.time()
    by_key = {}
    for sid in fast.enabled_services():
        svc = fast.SERVICES[sid]
        for cid, ch in fast._load(sid).items():
            name = ch.get("name", "")
            key = _key(name)
            progs = _programs(ch.get("programs"))
            if not key or not progs:
                continue
            groups = fast._group_names(ch)
            is_sports = sports.is_sports_channel(name, groups)
            current = next((t for s, t in reversed(progs) if s <= now), "")
            by_key.setdefault(key, []).append({
                "key": key, "name": name, "logo": ch.get("logo") or "", "programs": progs, "groups": groups,
                "sports": is_sports, "cats": categories.with_single_show(categories.for_channel(name, groups, is_sports), name, progs), "service": svc["name"], "sid": sid,
                "play": {"src": sid, "id": cid, "name": name}, "current": fast._norm(current)})
    for feeds in by_key.values():
        # a feed without labels (Plex) takes the categories of a same-named labelled channel (Pluto)
        known = set().union(*(f["cats"] for f in feeds if f["groups"]))
        for f in feeds:
            if not f["groups"] and known and not f["cats"] - {"Sports"}:
                f["cats"] = f["cats"] | known
    rows = []
    for key, feeds in by_key.items():
        feeds.sort(key=lambda f: prio.get(f["sid"], 99))
        clusters = []
        for f in feeds:
            # another service's feed joins the first row; the same service's only when it's the same broadcast
            home = next((c for c in clusters if f["sid"] not in {x["sid"] for x in c}
                         or _same_broadcast(c[0]["current"], f["current"])), None)
            (home.append(f) if home else clusters.append([f]))
        for c in clusters:
            row = dict(c[0])
            # a service listing the same channel twice adds nothing to "Watch on..."
            others = {f["sid"]: f for f in c[1:] if f["sid"] != c[0]["sid"]}
            row["alts"] = [{"service": f["service"], "play": f["play"]} for f in others.values()]
            row["cats"] = set().union(*(f["cats"] for f in c))
            rows.append(row)
    return sorted(rows, key=lambda c: (c["name"].lower(), c["service"]))


def _key(name):
    """Channel identity across services: fast._norm, but "+"/"Plus" counts (ION and ION Plus are two channels)."""
    return fast._norm(re.sub(r"\+|\bplus\b", " xplus ", name or "", flags=re.I)).replace("xplus", "plus")


def _same_broadcast(a, b):
    """Two feeds' current titles are the same broadcast: equal, one inside the other
    ('Predator Pro Billiard Series' / '2026 Predator Pro Billiard Series'), or nearly identical."""
    if a == b:
        return True
    if not a or not b:
        return False
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def genre_counts(chans):
    """{WatchHub category or source label: channel count}."""
    counts = {}
    for c in chans:
        for g in set(c["cats"]) | set(c["groups"]):
            counts[g] = counts.get(g, 0) + 1
    counts[OTHER] = sum(1 for c in chans if not c["cats"])
    return counts


def genres(chans):
    """What "Categories" offers: Single Show and the common ones first, the rest by size, then Other.
    Categories with their own tab (Sports, News, Movies, Game Shows, Kids) aren't repeated: the tab
    shows exactly the same channels."""
    counts = genre_counts(chans)
    own_tab = {categories.TAB_CATEGORY.get(t, t) for t in FIXED_TABS}
    cats = [c for c in categories.CATEGORIES if counts.get(c) and c not in own_tab]
    cats = cats[:categories.COMMON] + sorted(cats[categories.COMMON:], key=lambda c: -counts[c])
    return cats + ([OTHER] if counts[OTHER] else [])


def tabs(tab):
    """The tab strip, one screen wide: Favorites, Categories, the category picked from it (if any), then the rest."""
    picked = [tab] if tab not in FIXED_TABS and tab != GENRES_TAB else []
    return FIXED_TABS[:1] + [GENRES_TAB] + picked + FIXED_TABS[1:]


def in_tab(chans, tab, favs):
    if tab == "Favorites":
        return [c for c in chans if c["key"] in favs]
    if tab == "All":
        return list(chans)
    if tab == OTHER:
        return [c for c in chans if not c["cats"]]
    cat = categories.TAB_CATEGORY.get(tab, tab)
    if cat == "News":
        # your own stations first (map 5.5)
        news = [c for c in chans if cat in c["cats"]]
        return [c for c in news if categories.LOCAL in c["cats"]] + [c for c in news if categories.LOCAL not in c["cats"]]
    if cat in categories.CATEGORIES:
        return [c for c in chans if cat in c["cats"]]
    return [c for c in chans if tab in c["groups"]]


def cells(programs, t0):
    """Per 30-minute column: (title, 'start - end', continues_from_left, on_now, n_more_starting_inside)."""
    now = time.time()
    out, prev = [], None
    for i in range(COLS):
        s = t0 + i * SLOT
        p = None
        for j, (start, title) in enumerate(programs):
            if start > s:
                break
            if j + 1 < len(programs):  # only when the next listing gives a real end time
                p = (start, programs[j + 1][0], title)
        if p and s >= p[1]:
            p = None
        more = sum(1 for start, _ in programs if s < start < s + SLOT)
        if not p:
            out.append(("", "", False, False, more))
            prev = None
            continue
        start, end, title = p
        cont = prev is not None and prev[0] == start
        out.append((title, "%s - %s" % (_clock(start), _clock(end)), cont, start <= now < end, more))
        prev = p
    return out


# ---------------------------------------------------------------- window
class Guide(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        start_tab = kwargs.pop("tab", None)
        super().__init__(*args)
        self.hidden = hidden()
        self.all_chans = channels()
        self.chans = [c for c in self.all_chans if c["key"] not in self.hidden]
        self.loaded = time.time()
        self.favs = favorites()
        self.tab = start_tab or "Favorites"   # always opens on Favorites (a restart returns to the tab you were on)
        self.rows = []
        self.cat_choices = []
        self.t0 = _now_slot()

    def onInit(self):
        t = time.time()
        if self.tab == GENRES_TAB or (self.tab not in FIXED_TABS and self.tab not in genres(self.chans)):
            self.tab = "Favorites"
        self._tabs()
        self._fill()
        self.setFocusId(GRID if self.rows else TABS)
        kodi.log("guide: %s tab drawn (%d rows) in %.2fs" % (self.tab, len(self.rows), time.time() - t))

    # ---- drawing
    def _tabs(self):
        lst = self.getControl(TABS)
        lst.reset()
        names = tabs(self.tab)
        for name in names:
            li = xbmcgui.ListItem(name)
            li.setProperty("active", "1" if name == self.tab else "")
            lst.addItem(li)
        lst.selectItem(names.index(self.tab))

    def _fill(self, keep=0):
        self.rows = in_tab(self.chans, self.tab, self.favs)
        for i in range(COLS):
            self.setProperty("slot%d" % i, _clock(self.t0 + i * SLOT, ampm=True))
        self.setProperty("day", _day(self.t0))
        self.setProperty("tab", self.tab)
        self.setProperty("empty", "" if self.rows else
                         ("No favorites yet - long-press any channel and choose Add to Favorites" if self.tab == "Favorites"
                          else "No channels in %s" % self.tab))
        lst = self.getControl(GRID)
        lst.reset()
        items = []
        for c in self.rows:
            li = xbmcgui.ListItem(c["name"])
            li.setArt({"thumb": c["logo"]})
            li.setProperty("service", ("[COLOR FF4CD27F]LOCAL[/COLOR] \u00b7 " if categories.LOCAL in c["cats"] else "")
                           + c["service"] + (" \u00b7 opens its guide" if c["sid"] == "xumo" else "")
                           + (" +%d" % len(c["alts"]) if c["alts"] else "")
                           + ("  [COLOR FFFFC93D]★[/COLOR]" if c["key"] in self.favs else ""))
            row = cells(c["programs"], self.t0)
            for i, (title, span, cont, live, more) in enumerate(row):
                # how many columns this programme fills from here, so its title can run across them
                run = 1
                while i + run < COLS and row[i + run][2]:
                    run += 1
                cols = COLORS[category(c, title) if title else ""]
                li.setProperty("r%d" % i, str(run))
                li.setProperty("bg%d" % i, cols[1] if live else cols[0])     # normal row
                li.setProperty("bf%d" % i, cols[3] if live else cols[2])     # focused row
                li.setProperty("t%d" % i, title)
                li.setProperty("s%d" % i, span + ("   +%d more" % more if more else "") if title else
                               ("+%d starting" % more if more else ""))
                li.setProperty("c%d" % i, "1" if cont else "")
                li.setProperty("l%d" % i, "1" if live else "")
            items.append(li)
        lst.addItems(items)
        if items:
            lst.selectItem(min(keep, len(items) - 1))
        self._now_line()

    def _now_line(self):
        line = self.getControl(NOW_LINE)
        now = time.time()
        if self.t0 <= now < self.t0 + COLS * SLOT:
            line.setPosition(int(GRID_X + (now - self.t0) / SLOT * COL_W), 230)
            line.setVisible(True)
        else:
            line.setVisible(False)

    def _tick(self):
        """Keep a guide left open current: reload listings every 10 min, never show the past."""
        changed = False
        if time.time() - self.loaded > 600:
            self.all_chans, self.loaded, changed = channels(), time.time(), True
            self.chans = [c for c in self.all_chans if c["key"] not in self.hidden]
        if self.t0 < _now_slot():
            self.t0, changed = _now_slot(), True
        return changed

    # ---- input
    def onAction(self, action):
        aid = action.getId()
        kodi.debug("guide action %d (button %s)" % (aid, action.getButtonCode()))
        if aid in (ACTION_BACK, ACTION_NAV_BACK) and self.getProperty("picking"):
            self._hide_categories()     # Back closes the tiles, not the guide
            self.setFocusId(TABS)
            return
        if aid in (ACTION_BACK, ACTION_NAV_BACK):
            forget_return()  # closed on purpose: don't reopen it after a restart
            self.close()
            return
        pos = self.getControl(GRID).getSelectedPosition() if self.rows else 0
        if self._tick():
            self._fill(pos)
        else:
            self._now_line()
        if self.getFocusId() != GRID:
            return
        if aid == ACTION_RIGHT and self.t0 + SLOT <= _now_slot() + AHEAD:
            self.t0 += SLOT
            self._fill(pos)
        elif aid == ACTION_LEFT and self.t0 > _now_slot():
            self.t0 -= SLOT
            self._fill(pos)
        elif aid == ACTION_CONTEXT and 0 <= pos < len(self.rows):
            self._menu(self.rows[pos], pos)

    def onClick(self, control_id):
        if control_id == TABS:
            names = tabs(self.tab)
            pos = self.getControl(TABS).getSelectedPosition()
            if not 0 <= pos < len(names):
                return
            pick = names[pos]
            if pick == GENRES_TAB:
                self._show_categories()
                return
            self.tab = pick
            self._tabs()
            self._fill()
            self.setFocusId(GRID if self.rows else TABS)
        elif control_id == CAT_PANEL:
            pos = self.getControl(CAT_PANEL).getSelectedPosition()
            if not 0 <= pos < len(self.cat_choices):
                return
            pick = self.cat_choices[pos]
            self._hide_categories()
            if pick is None:
                self._unhide()
                return
            self.tab = pick
            self._tabs()
            self._fill()
            self.setFocusId(GRID if self.rows else TABS)
        elif control_id == GRID:
            pos = self.getControl(GRID).getSelectedPosition()
            if 0 <= pos < len(self.rows):
                remember_return(self.tab)  # the 2 GB Shield often kills Kodi while the app plays
                launcher.play(self.rows[pos]["play"])  # always "watch now": the apps can't record or tune ahead

    def _show_categories(self):
        """Categories as tiles in the guide itself (not a Kodi pop-up): name, channel count, colour."""
        counts = genre_counts(self.chans)
        self.cat_choices = genres(self.chans) + ([None] if self.hidden else [])
        panel = self.getControl(CAT_PANEL)
        panel.reset()
        items = []
        for c in self.cat_choices:
            li = xbmcgui.ListItem(c if c else "Hidden channels")
            li.setProperty("count", "%d channels" % (counts.get(c, 0) if c else len(self.hidden)))
            li.setProperty("color", TILE_COLORS.get(c, "FF2A3550"))
            items.append(li)
        panel.addItems(items)
        self.setProperty("picking", "1")
        for _ in range(10):  # the panel only takes focus once the skin has shown it
            self.setFocusId(CAT_PANEL)
            if self.getFocusId() == CAT_PANEL:
                break
            xbmc.sleep(30)

    def _hide_categories(self):
        self.setProperty("picking", "")

    def _menu(self, c, pos):
        fav = c["key"] in self.favs
        opts = ["Remove from Favorites" if fav else "Add to Favorites", "Full schedule"]
        opts += ["Watch on %s" % a["service"] for a in c["alts"]]
        opts += ["Hide this channel"]
        choice = xbmcgui.Dialog().contextmenu(opts)
        if choice == len(opts) - 1:
            if _write_json(_hidden_path(), self.hidden + [c["key"]]):
                self.hidden.append(c["key"])
                self.chans = [x for x in self.chans if x["key"] != c["key"]]
                kodi.notify("%s hidden - bring it back from Categories > Hidden channels" % c["name"])
                self._fill(pos)
                if not self.rows:
                    self.setFocusId(TABS)
            return
        if choice == 0:
            new = [k for k in self.favs if k != c["key"]] if fav else self.favs + [c["key"]]
            if not _write_json(_fav_path(), new):
                kodi.notify("Couldn't save your favorites")
                return
            self.favs = new
            self._tabs()
            self._fill(pos)
            if not self.rows:
                self.setFocusId(TABS)
        elif choice == 1:
            now, progs = time.time(), c["programs"]
            lines = []
            for i, (start, title) in enumerate(progs):
                end = progs[i + 1][0] if i + 1 < len(progs) else None
                if end is None:
                    lines.append("%s %s  %s  (end time not listed)" % (_day(start) if _day(start) != "Today" else "", _clock(start, True), title))
                elif end > now:
                    lines.append("%s %s  %s" % (_day(start) if _day(start) != "Today" else "", _clock(start, True), title))
            xbmcgui.Dialog().select("%s - schedule" % c["name"], [l.strip() for l in lines[:60]] or ["No listings"])
        elif choice >= 2:
            remember_return(self.tab)
            launcher.play(c["alts"][choice - 2]["play"])


    def _unhide(self):
        names = {c["key"]: c["name"] for c in self.all_chans}
        keys = list(self.hidden)
        picked = xbmcgui.Dialog().multiselect("Show these channels again", [names.get(k, k) for k in keys])
        if not picked:
            return
        keep = [k for i, k in enumerate(keys) if i not in picked]
        if _write_json(_hidden_path(), keep):
            self.hidden = keep
            self.chans = [c for c in self.all_chans if c["key"] not in keep]
            self._fill()


def show(tab=None):
    kodi.log("guide: open%s" % (" on %s" % tab if tab else ""))
    win = Guide("Guide.xml", kodi.ADDON_PATH, "Default", "1080i", tab=tab)
    win.doModal()
    del win
