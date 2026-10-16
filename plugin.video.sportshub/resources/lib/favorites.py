"""WatchHub Favorites: channels (shared with the TV Guide's Favorites tab) plus shows, movies and games.

Channels live in the guide's guide_favorites.json (channel keys), so starring a channel anywhere shows it in
both places. Titles and games live in favorites.json as small dicts with what's needed to draw and open them.
Anything added with Kodi's own "Add to favourites" (it stays on Kodi's long-press menu) is shown too.
"""
import json
import os
import time

from resources.lib import kodi


def _path():
    return os.path.join(kodi.ensure_profile_dir(), "favorites.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        return [x for x in data if isinstance(x, dict) and x.get("key")] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items):
    from resources.lib import guide
    return guide._write_json(_path(), items)


def title_key(title, year=""):
    return "title:%s:%s" % (title.strip().lower(), year or "")


def game_key(title):
    return "game:%s" % title.strip().lower()


def items():
    """Shows, movies and games, newest first."""
    return sorted(_load(), key=lambda x: -float(x.get("added", 0)))


def has(key):
    return any(x["key"] == key for x in _load())


def toggle(item):
    """Add the item (dict with at least key/kind/label) or remove it if it's already there. Returns True if added."""
    cur = _load()
    if any(x["key"] == item["key"] for x in cur):
        _save([x for x in cur if x["key"] != item["key"]])
        return False
    _save([dict(item, added=time.time())] + cur)
    return True


# ---- channels: the guide's list
def channel_keys():
    from resources.lib import guide
    return guide.favorites()


def has_channel(name):
    from resources.lib.sources import fast
    return fast._norm(name) in channel_keys()


def toggle_channel(name):
    from resources.lib import guide
    from resources.lib.sources import fast
    key = fast._norm(name)
    cur = guide.favorites()
    new = [k for k in cur if k != key] if key in cur else cur + [key]
    guide._write_json(guide._fav_path(), new)
    return key in new


def kodi_favourites():
    """Kodi's own favourites ([{title, path, thumbnail}])."""
    res = kodi.jsonrpc("Favourites.GetFavourites", {"properties": ["path", "thumbnail", "window", "windowparameter"]}) or {}
    return res.get("favourites") or []
