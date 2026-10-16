"""WatchHub's own windows (info page, TV Guide), opened by the always-running service.

A click sets the Home window property sh_ui_request to the item's plugin URL (the skin does it directly,
the add-on does it for menu entries). A worker thread here picks it up within ~50 ms and opens the window:
no Python start-up per click, the guide's channel list is already built, and the service's own loop
(data refresh, dev hook) keeps running while a window is open.
"""
import threading
import time
from urllib.parse import parse_qsl, urlparse

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

    def run(self):
        home = xbmcgui.Window(10000)
        while not self.monitor.abortRequested():
            req = home.getProperty(REQUEST)
            if req:
                home.clearProperty(REQUEST)
                try:
                    self.handle(req)
                except Exception as exc:
                    kodi.log("window request failed (%s): %s" % (req, exc))
            if self.monitor.waitForAbort(0.05):
                break

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
            infodialog.show_by_title(params.get("title", ""), params.get("year", ""), params.get("kind", ""))
        elif action == "guide":
            from resources.lib import guide
            guide.show(params.get("tab") or None)
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
            guide.channels(rebuild=True)
        except Exception as exc:
            kodi.log("guide prebuild failed: %s" % exc)
    threading.Thread(target=work, name="sh-guide-build", daemon=True).start()


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
    pick = xbmcgui.Dialog().contextmenu([e[0] for e in entries])
    if pick >= 0:
        xbmc.executebuiltin(entries[pick][1])


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
