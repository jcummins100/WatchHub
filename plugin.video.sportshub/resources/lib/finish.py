"""'Did you finish S02E04?' when you come back from an app (Sprint C).

Playing an episode from WatchHub (Up Next, or a pick in the info page's episode list) notes which one.
When someone is back in Kodi at least MIN_AWAY later (a key press after the app), WatchHub asks once;
Yes marks that episode watched on Trakt, so Up Next moves on. Works across Android killing Kodi:
the note is a file in the add-on's profile.
"""
import json
import os
import threading
import time

import xbmc
import xbmcgui

from resources.lib import kodi

MIN_AWAY = 15 * 60       # shorter than this and they can't have watched an episode
MAX_AWAY = 12 * 3600     # after this the question is stale
ASK_TIMEOUT_MS = 60000   # unanswered = "not yet" (and never blocks a test run for long)


def _path():
    return os.path.join(kodi.ensure_profile_dir(), "watching.json")


def remember(title, year, season, episode, name=""):
    from resources.lib.sources import trakt
    if not (title and season and episode) or not trakt.signed_in():
        return
    note = {"title": title, "year": str(year or ""), "season": int(season), "episode": int(episode),
            "name": name or "", "at": int(time.time())}
    try:
        with open(_path(), "w", encoding="utf-8") as fh:
            json.dump(note, fh)
    except OSError as exc:
        kodi.log("finish: note not saved: %s" % exc)


def _take():
    try:
        with open(_path(), encoding="utf-8") as fh:
            note = json.load(fh)
    except (OSError, ValueError):
        return None
    away = time.time() - float(note.get("at", 0))
    if away > MAX_AWAY:
        forget()
        return None
    return note if away >= MIN_AWAY else None


def _forget_if_back_early():
    """A key press 30 s to MIN_AWAY after the Play click: they came straight back, so there's nothing to ask."""
    try:
        with open(_path(), encoding="utf-8") as fh:
            away = time.time() - float(json.load(fh).get("at", 0))
    except (OSError, ValueError, TypeError):
        return
    if 30 < away < MIN_AWAY:
        forget()


def forget():
    try:
        os.remove(_path())
    except OSError:
        pass


_asking = threading.Event()


def check():
    """Called by the service every couple of seconds: ask once someone is using Kodi again."""
    if _asking.is_set() or not os.path.exists(_path()):
        return
    if xbmc.getCondVisibility("System.IdleTime(3)") or xbmc.getCondVisibility("System.HasActiveModalDialog") \
            or xbmc.getCondVisibility("Player.HasMedia"):
        return  # nobody pressed anything just now, or something else is on screen
    note = _take()
    if not note:
        _forget_if_back_early()
        return
    forget()  # ask once, whatever the answer
    _asking.set()
    threading.Thread(target=_ask, args=(note,), name="sh-finish", daemon=True).start()


def _ask(note):
    try:
        ep = "S%02dE%02d" % (note["season"], note["episode"]) + (" — %s" % note["name"] if note["name"] else "")
        yes = xbmcgui.Dialog().yesno("Did you finish it?", "%s\n%s" % (note["title"], ep),
                                     nolabel="Not yet", yeslabel="Yes, mark watched", autoclose=ASK_TIMEOUT_MS)
        if not yes:
            return
        from resources.lib.sources import trakt
        if trakt.mark_episode_watched(note["title"], note["year"], note["season"], note["episode"]):
            kodi.notify("Marked watched on Trakt")
            kodi.run_builtin("SetProperty(sh_refresh,%d,home)" % time.time())  # Up Next moves to the next episode
        else:
            kodi.notify("Trakt: couldn't mark it")
    finally:
        _asking.clear()
