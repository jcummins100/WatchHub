"""TV Guide: the free live channels (Pluto TV, Plex, The Roku Channel) as a time grid.

Channels down the side, two hours across in 30-minute columns. Left/right moves through time,
up/down through channels; tabs across the top pick Favorites, Sports, News, Movies, Shows, Kids,
Music, All - or any specific genre through "Genres...". OK watches the channel now in its own app
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

from resources.lib import kodi, launcher, sports
from resources.lib.sources import fast

SLOT = 1800            # one column = 30 minutes
COLS = 4               # columns on screen
COL_W, GRID_X = 360, 460  # column width and the x of the first column on screen (Guide.xml)
AHEAD = 16 * 3600      # furthest the first column can start from now (listings run 8-19 h ahead)
TABS, GRID, NOW_LINE = 300, 500, 400
ACTION_LEFT, ACTION_RIGHT, ACTION_CONTEXT, ACTION_BACK, ACTION_NAV_BACK = 1, 2, 117, 10, 92

# Fixed tabs (a D-pad can't browse 39 shifting genre tabs); every channel is in Shows/News/... by
# its genres, and "Genres..." opens the full list of specific genres.
FIXED_TABS = ["Favorites", "Sports", "News", "Movies", "Shows", "Game Shows", "Kids", "Music", "All"]
GENRES_TAB = "Genres..."
_CATEGORY_WORDS = (
    ("News", ("news", "opinion", "weather", "politic", "business")),
    ("Movies", ("movie", "cinema", "film", "western")),
    ("Kids", ("kid", "family", "animation", "cartoon", "anime")),
    ("Music", ("music", "vevo", "concert", "karaoke")),
)

# Game shows go by name only: Pluto's "Daytime + Game Shows" group also holds talk/judge/shopping channels
# (Dr. Phil, Judge Judy, QVC) and Roku tags America's Got Talent "Game Show". Phrases, not "game", so
# Game & Fish TV, GameTVGO, XITE Rap Game and pocket.watch Game-On stay out.
_GAME_SHOWS = re.compile(r"price is right|\btpir\b|family feud|deal or no deal|let'?s make a deal|buzzr|game show"
                         r"|quiz show|supermarket sweep|name game|jeopardy|wheel of fortune|match game|press your luck"
                         r"|card sharks|newlywed|wipeout|hollywood squares|weakest link|minute to win it|to tell the truth")
# Plex (and some Roku) channels come without genres, so their names decide - checked against the full
# channel list ('FilmRise Comedy' is a distributor, not a movie channel; 'Family Handyman' is not kids).
_NAME_WORDS = (
    ("News", re.compile(r"\bnews|weather|local now|bloomberg|cheddar|france 24|reuters|usa today|livenow|\bcnn\b")),
    ("Movies", re.compile(r"movie(?! music)|cinema|\bfilms\b|flix\b|western|pel[ií]culas|mgm presents|miramax|at the movies")),
    ("Kids", re.compile(r"\bkid(?!s in the hall)|toon|cartoon|\bbaby|teletubbies|wiggles|little pony|sonic|super mario|power rangers"
                        r"|beyblade|yu-gi-oh|transformers|strawberry shortcake|moonbug|like nastya|pocket\.watch|garfield")),
    ("Music", re.compile(r"music|\bhits\b|stingray|\bxite\b|vevo|karaoke|jazz|classic rock|k-pop|concert|\btrace\b"
                         r"|metal\.rocks|easy listening|hip-hop/r&b|country\b|soul storm")),
)

# Cell colours, the familiar cable-guide convention: green sports, purple movies, light blue kids, gold game shows,
# dark blue everything else. (normal, on now, focused row, focused row + on now)
COLORS = {
    "sports": ("FF1B3A2A", "FF22543A", "FF22482F", "FF2B6A47"),
    "movies": ("FF2E2140", "FF3E2C5A", "FF3A2A52", "FF4D3772"),
    "kids":   ("FF1C3A4F", "FF22506E", "FF23485F", "FF2A6386"),
    "gameshows": ("FF3A311A", "FF544520", "FF4A3E1F", "FF6A5726"),
    "":       ("FF1A2233", "FF22314F", "FF243150", "FF2E4472"),
}


def category(chan, title):
    """sports / movies / kids / '' for one programme on one channel (the cell colour)."""
    if chan["sports"] or sports.classify(title):
        return "sports"
    if "Game Shows" in chan["cats"]:
        return "gameshows"
    if "Kids" in chan["cats"]:
        return "kids"
    if "Movies" in chan["cats"]:
        return "movies"
    return ""


def _categories(groups, is_sports, name=""):
    """The fixed tabs a channel belongs in: its genre groups, else its name; "Shows" when nothing fits."""
    name = name.lower()
    cats = {"Sports"} if is_sports else set()
    if _GAME_SHOWS.search(name):
        cats.add("Game Shows")
    text = " ".join(groups).lower()
    for cat, words in _CATEGORY_WORDS:
        if any(w in text for w in words):
            cats.add(cat)
    if not cats - {"Sports"}:
        cats.update(cat for cat, rx in _NAME_WORDS if rx.search(name))
    return cats or {"Shows"}


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
    The first caller after Kodi starts waits for listings that are still downloading instead of
    showing an empty guide."""
    with _BUILD_LOCK:
        if rebuild or _BUILT["rows"] is None or time.time() - _BUILT["at"] > BUILT_MAX_AGE:
            t = time.time()
            rows = _build_channels()
            if not rows:
                # right after a restart the listings may still be downloading: give them a little time
                mon = xbmc.Monitor()
                for _ in range(10):
                    if mon.waitForAbort(2):
                        break
                    rows = _build_channels()
                    if rows:
                        break
            _BUILT.update(at=time.time(), rows=rows)
            kodi.log("guide: %d channel rows built in %.2fs" % (len(rows), time.time() - t))
        return _BUILT["rows"]


def _build_channels():
    """Every free channel with listings. The same channel on two services is merged into one row
    (preferred service first, the other under "Watch on...") only when both are airing the same
    programme right now - a same-named regional feed with its own schedule stays a separate row."""
    prio = {sid: i for i, sid in enumerate(fast.service_priority())}
    now = time.time()
    by_key = {}
    for sid in fast.enabled_services():
        svc = fast.SERVICES[sid]
        for cid, ch in fast._load(sid).items():
            name = ch.get("name", "")
            key = fast._norm(name)
            progs = _programs(ch.get("programs"))
            if not key or not progs:
                continue
            groups = fast._group_names(ch)
            is_sports = sports.is_sports_channel(name, groups)
            current = next((t for s, t in reversed(progs) if s <= now), "")
            by_key.setdefault(key, []).append({
                "key": key, "name": name, "logo": ch.get("logo") or "", "programs": progs, "groups": groups,
                "sports": is_sports, "cats": _categories(groups, is_sports, name), "service": svc["name"], "sid": sid,
                "play": {"src": sid, "id": cid, "name": name}, "current": fast._norm(current)})
    for feeds in by_key.values():
        known = set().union(*(f["cats"] for f in feeds if f["groups"])) - {"Shows"}
        for f in feeds:
            if not f["groups"] and known and f["cats"] <= {"Shows"}:
                f["cats"] = set(known)
    rows = []
    for key, feeds in by_key.items():
        feeds.sort(key=lambda f: prio.get(f["sid"], 99))
        clusters = []
        for f in feeds:
            home = next((c for c in clusters if _same_broadcast(c[0]["current"], f["current"])), None)
            (home.append(f) if home else clusters.append([f]))
        for c in clusters:
            row = dict(c[0])
            # a service listing the same channel twice adds nothing to "Watch on..."
            others = {f["sid"]: f for f in c[1:] if f["sid"] != c[0]["sid"]}
            row["alts"] = [{"service": f["service"], "play": f["play"]} for f in others.values()]
            row["cats"] = set().union(*(f["cats"] for f in c))
            rows.append(row)
    return sorted(rows, key=lambda c: (c["name"].lower(), c["service"]))


def _same_broadcast(a, b):
    """Two feeds' current titles are the same broadcast: equal, one inside the other
    ('Predator Pro Billiard Series' / '2026 Predator Pro Billiard Series'), or nearly identical."""
    if a == b:
        return True
    if not a or not b:
        return False
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def genres(chans):
    counts = {}
    for c in chans:
        for g in c["groups"]:
            counts[g] = counts.get(g, 0) + 1
    return sorted((g for g, n in counts.items() if n >= 2), key=str.lower)


def tabs(tab):
    """The tab strip: the fixed tabs, the specific genre in use (if any), then Genres..."""
    return FIXED_TABS + ([tab] if tab not in FIXED_TABS and tab != GENRES_TAB else []) + [GENRES_TAB]


def in_tab(chans, tab, favs):
    if tab == "Favorites":
        return [c for c in chans if c["key"] in favs]
    if tab == "All":
        return list(chans)
    if tab in FIXED_TABS:
        return [c for c in chans if tab in c["cats"]]
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
            li.setProperty("service", c["service"] + (" +%d" % len(c["alts"]) if c["alts"] else "")
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
                all_genres = genres(self.chans)
                extra = ["Hidden channels (%d)" % len(self.hidden)] if self.hidden else []
                choice = xbmcgui.Dialog().select("Genres", all_genres + extra)
                if choice < 0:
                    return
                if choice >= len(all_genres):
                    self._unhide()
                    return
                pick = all_genres[choice]
            self.tab = pick
            self._tabs()
            self._fill()
            self.setFocusId(GRID if self.rows else TABS)
        elif control_id == GRID:
            pos = self.getControl(GRID).getSelectedPosition()
            if 0 <= pos < len(self.rows):
                remember_return(self.tab)  # the 2 GB Shield often kills Kodi while the app plays
                launcher.play(self.rows[pos]["play"])  # always "watch now": the apps can't record or tune ahead

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
                kodi.notify("%s hidden - bring it back from Genres... > Hidden channels" % c["name"])
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
