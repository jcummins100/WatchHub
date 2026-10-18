"""WatchHub's own windows (info page, TV Guide, Browse), opened by the always-running service.

A click sets the Home window property sh_ui_request to the item's plugin URL (the skin does it directly,
the add-on does it for menu entries). A worker thread here picks it up within ~50 ms and opens the window:
no Python start-up per click, the guide's channel list is already built, and the service's own loop
(data refresh, dev hook) keeps running while a window is open.
"""
import threading
import time
from urllib.parse import parse_qsl, urlparse

import xbmc
import xbmcgui

from resources.lib import kodi

REQUEST = "sh_ui_request"


def request(url):
    """Ask the service to open a window; False if no service is running (caller opens it itself)."""
    home = xbmcgui.Window(10000)
    if not home.getProperty("sh_service_alive"):
        return False
    home.setProperty(REQUEST, url)
    return True


class Worker(threading.Thread):
    def __init__(self, monitor):
        super().__init__(name="sh-ui", daemon=True)
        self.monitor = monitor

    # the window each request opens: a second press while it's on screen does nothing
    WINDOWS = {"guide": "Guide.xml", "info": "TitleInfo.xml", "calendar": "Calendar.xml", "browse": "Browse.xml",
               "wh_settings": "selectdialog", "ctx": "contextmenu"}

    def run(self):
        """Each request runs on its own thread. One at a time used to be the rule, and a window that vanished
        without closing (a skin reload under the TV Guide) left every later request waiting forever (Oct 17)."""
        home = xbmcgui.Window(10000)
        running = {}
        while not self.monitor.abortRequested():
            req = home.getProperty(REQUEST)
            if req:
                home.clearProperty(REQUEST)
                action = dict(parse_qsl(urlparse(req).query)).get("action", "")
                busy = running.get(action)
                win = self.WINDOWS.get(action)
                if busy and busy.is_alive() and win and xbmc.getCondVisibility("Window.IsActive(%s)" % win):
                    kodi.log("window request skipped, %s is already open" % action)
                else:
                    t = threading.Thread(target=self._safe, args=(req,), name="sh-ui-%s" % action, daemon=True)
                    running[action] = t
                    t.start()
            if self.monitor.waitForAbort(0.05):
                break

    def _safe(self, req):
        try:
            self.handle(req)
        except Exception as exc:
            kodi.log("window request failed (%s): %s" % (req, exc))

    @staticmethod
    def handle(req):
        params = dict(parse_qsl(urlparse(req).query))
        action = params.get("action")
        t = time.time()
        if action == "ctx":
            show_menu()
            return
        if action == "info":
            from resources.lib import infodialog
            kodi.log("info: request for %s" % params.get("title", ""))
            infodialog.show_by_title(params.get("title", ""), params.get("year", ""), params.get("kind", ""),
                                     season=params.get("season", ""), episode=params.get("episode", ""))
        elif action == "guide":
            from resources.lib import guide
            guide.show(params.get("tab") or None)
        elif action == "wh_settings":
            from resources.lib import settingsmenu
            settingsmenu.show()
        elif action == "browse":
            from resources.lib import browse
            browse.show(params.get("cat") or "Comedy")
        elif action == "calendar":
            from resources.lib import calendarwin
            calendarwin.show(params.get("league") or "nfl")
        else:
            kodi.log("unknown window request: %s" % req)
            return
        kodi.log("%s window closed after %.0fs" % (action, time.time() - t))


def fill_show_genres():
    """A few more single-show channels get their show's genres each refresh (Plex has no labels)."""
    def work():
        try:
            from resources.lib import categories, guide
            names = [c["name"] for c in guide.channels() if not c["cats"] - {categories.SINGLE_SHOW}]
            n = categories.fill_show_genres(names, budget=40)
            if n:
                kodi.log("categories: looked up %d channel shows" % n)
                guide.channels(rebuild=True)
        except Exception as exc:
            kodi.log("show genre lookup failed: %s" % exc)
    threading.Thread(target=work, name="sh-show-genres", daemon=True).start()


def warm_guide():
    """Build the guide's channel list ahead of time (after each data refresh), on its own thread."""
    def work():
        try:
            from resources.lib import guide
            # just built (the guide reopened at start-up, or a window asked for it): the listings it used
            # are the ones just refreshed, so a second ~10 s build would only compete with the home rows
            if guide._BUILT["rows"] is not None and time.time() - guide._BUILT["at"] < 5 * 60:
                return
            guide.channels(rebuild=True)
        except Exception as exc:
            kodi.log("guide prebuild failed: %s" % exc)
    threading.Thread(target=work, name="sh-guide-build", daemon=True).start()


# Long-press menus list their entries in one order everywhere (a row only shows the ones that apply):
# play / watch on, trailer, schedule, Up Next moves, row refresh, more like this, favorites, Trakt
# watchlist, Trakt watched, pin, hide. Matched on the label's start.
MENU_ORDER = [
    ("Play",), ("Watch on",), ("Watch trailer",), ("Full schedule",),
    ("Move to the top", "Move up", "Move to the end", "Move back", "Put back"),
    ("Show me",), ("More like this",),
    ("\u2605", "Add to Favorites", "Remove from Favorites"),
    ("Trakt: add to watchlist", "Trakt: remove from watchlist"),
    ("Trakt: mark", "Trakt: unmark"),
    ("Pin", "Unpin"),
    ("Hide", "Undo hide"),
]


def menu_rank(label):
    for i, starts in enumerate(MENU_ORDER):
        if label.startswith(starts):
            return i
    return len(MENU_ORDER)


def show_menu():
    """Long-press OK on a WatchHub card: just the card's own entries, without Kodi's (Play next, Queue item,
    Add to favourites...). Anything that isn't a WatchHub card gets Kodi's normal menu."""
    import json
    import xbmc
    raw = xbmc.getInfoLabel("ListItem.Property(sh_ctx)")
    try:
        entries = [e for e in json.loads(raw) if isinstance(e, list) and len(e) == 2] if raw else []
    except ValueError:
        entries = []
    if not entries:
        xbmc.executebuiltin("Action(ContextMenu)")
        return
    entries = [[_fav_label(label, cmd), cmd] for label, cmd in entries]
    entries.sort(key=lambda e: menu_rank(e[0]))   # one order on every row (stable within a group)
    top = group_menu(entries)
    pick = xbmcgui.Dialog().contextmenu([t[0] for t in top])
    if pick < 0:
        return
    label, sub = top[pick]
    if isinstance(sub, list):   # a "…" group: its own short menu
        p2 = xbmcgui.Dialog().contextmenu([e[0] for e in sub])
        if p2 >= 0:
            xbmc.executebuiltin(sub[p2][1])
    else:
        xbmc.executebuiltin(sub)


# groups folded into one "…" entry when they have two or more options (else the option shows directly)
SUBMENUS = [("Watch on\u2026", ("Watch on",)),
            ("Move\u2026", ("Move to the top", "Move up", "Move to the end", "Move back", "Put back")),
            ("Trakt\u2026", ("Trakt:",))]


def group_menu(entries):
    """[(label, command or [[label, command], ...])] in menu order. A group with one option shows that
    option itself; inside "Trakt…" the options drop their "Trakt: " prefix."""
    out, groups = [], {}
    for label, cmd in entries:
        name = next((n for n, starts in SUBMENUS if label.startswith(starts)), None)
        if name is None:
            out.append((label, cmd))
            continue
        if name not in groups:
            groups[name] = []
            out.append((name, groups[name]))
        groups[name].append([label, cmd])
    result = []
    for label, item in out:
        if not isinstance(item, list):
            result.append((label, item))
        elif len(item) == 1:
            result.append((item[0][0], item[0][1]))
        else:
            if label == "Trakt\u2026":
                item = [[l.replace("Trakt: ", "", 1).capitalize(), c] for l, c in item]
            result.append((label, item))
    return result


KEYMAP = """<keymap>
  <!-- installed by WatchHub: long-press OK opens WatchHub's own menu on its cards (no Kodi extras) -->
  <home><keyboard><return mod="longpress">SetProperty(sh_ui_request,plugin://plugin.video.sportshub/?action=ctx,home)</return></keyboard></home>
  <videos><keyboard><return mod="longpress">SetProperty(sh_ui_request,plugin://plugin.video.sportshub/?action=ctx,home)</return></keyboard></videos>
</keymap>
"""


def install_keymap():
    """Write userdata/keymaps/watchhub.xml (once, or when it changes) and reload Kodi's keymaps."""
    import os
    import xbmc
    import xbmcvfs
    folder = xbmcvfs.translatePath("special://profile/keymaps/")
    path = os.path.join(folder, "watchhub.xml")
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.read() == KEYMAP:
                return
    except OSError:
        pass
    try:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(KEYMAP)
        xbmc.executebuiltin("Action(reloadkeymaps)")
        kodi.log("installed the WatchHub long-press keymap")
    except OSError as exc:
        kodi.log("keymap not installed: %s" % exc)


def remove_keymap():
    import os
    import xbmc
    import xbmcvfs
    path = os.path.join(xbmcvfs.translatePath("special://profile/keymaps/"), "watchhub.xml")
    if os.path.exists(path):
        try:
            os.remove(path)
            xbmc.executebuiltin("Action(reloadkeymaps)")
        except OSError:
            pass



def _fav_label(label, cmd):
    """The card was drawn before any change: say Add or Remove by what's in Favorites right now."""
    if "action=fav" not in cmd:
        return label
    from resources.lib import favorites
    try:
        q = dict(parse_qsl(urlparse(cmd[cmd.index("plugin://"):].rstrip(")")).query))
    except ValueError:
        return label
    on = favorites.has_channel(q.get("name", "")) if q.get("what") == "channel" else favorites.has(q.get("key", ""))
    return "\u2605 Remove from Favorites" if on else "\u2605 Add to Favorites"
