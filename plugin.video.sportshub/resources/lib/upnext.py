"""Your own order for Up Next (Trakt has no way to reorder it).

Long-press on an Up Next card: "Move to the end of Up Next" (stays at the end until moved back to the
front) or "Hide from Up Next for now" (gone until its next episode changes - you watched one somewhere -
or until you bring it back from the "Hidden" card at the end of the row). Kept per Shield in
upnext_order.json; tools/sync_settings.py copies it like the favorites.
"""
import json
import os
import time

from resources.lib import kodi

FILE = "upnext_order.json"


def _path():
    return os.path.join(kodi.ensure_profile_dir(), FILE)


def _load():
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data.setdefault("back", [])
    data.setdefault("hidden", {})
    return data


def _save(data):
    tmp = _path() + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, _path())
    except OSError as exc:
        kodi.log("Up Next order not saved: %s" % exc)


def key(title, year):
    return "%s|%s" % ((title or "").strip().lower(), year or "")


def arrange(items):
    """Trakt's Up Next in your order: hidden shows out (unless their next episode moved on), shows you
    pushed back at the end, in the order you pushed them."""
    data = _load()
    changed = False
    front, back = [], {}
    for t in items:
        k = key(t["title"], t["year"])
        h = data["hidden"].get(k)
        if h is not None:
            if h.get("next") and t.get("next") and h["next"] != t["next"]:
                del data["hidden"][k]  # you watched an episode: it's current again
                changed = True
            else:
                continue
        if k in data["back"]:
            back[k] = t
        else:
            front.append(t)
    if changed:
        _save(data)
    return front + [back[k] for k in data["back"] if k in back]


def is_back(title, year):
    return key(title, year) in _load()["back"]


def move_back(title, year):
    data = _load()
    k = key(title, year)
    data["back"] = [x for x in data["back"] if x != k] + [k]
    _save(data)


def move_front(title, year):
    data = _load()
    data["back"] = [x for x in data["back"] if x != key(title, year)]
    _save(data)


def hide(title, year, next_ep=""):
    data = _load()
    data["hidden"][key(title, year)] = {"title": title, "year": year, "next": next_ep, "at": int(time.time())}
    _save(data)


def hidden():
    """[(key, title)] hidden right now, most recent first."""
    h = _load()["hidden"]
    return [(k, v.get("title") or k) for k, v in sorted(h.items(), key=lambda kv: -kv[1].get("at", 0))]


def unhide(keys):
    data = _load()
    for k in keys:
        data["hidden"].pop(k, None)
    _save(data)
