"""Your own order for Up Next (Trakt has no way to reorder it).

Long-press on an Up Next card: "Move to the top", "Move up one", "Move to the end" (each stays put until
"Put back in its usual place") or "Hide from Up Next for now" (gone until its next episode changes - you watched one somewhere -
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
    data.setdefault("top", [])   # moved up: these lead, in this order
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
    """Trakt's Up Next in your order: shows you moved up first (in your order), then the rest in Trakt's
    order, then shows you pushed back (in the order you pushed them); hidden shows out unless their next
    episode moved on."""
    data = _load()
    changed = False
    front, top, back = [], {}, {}
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
        elif k in data["top"]:
            top[k] = t
        else:
            front.append(t)
    if changed:
        _save(data)
    return [top[k] for k in data["top"] if k in top] + front + [back[k] for k in data["back"] if k in back]


def fit(items, n):
    """At most n of arrange()'s list, with the shows you pushed back still at the end (pushed back, not
    removed): they keep up to half the row when there are more shows than fit."""
    back_keys = _load()["back"]
    back = [t for t in items if key(t["title"], t["year"]) in back_keys]
    rest = [t for t in items if key(t["title"], t["year"]) not in back_keys]
    nb = min(len(back), max(n - len(rest), n // 2))
    return rest[:n - nb] + (back[-nb:] if nb else [])


def is_moved(title, year):
    k = key(title, year)
    data = _load()
    return k in data["back"] or k in data["top"]


def move_top(title, year):
    data = _load()
    k = key(title, year)
    data["back"] = [x for x in data["back"] if x != k]
    data["top"] = [k] + [x for x in data["top"] if x != k]
    _save(data)


def move_up(title, year, current):
    """One place up. current = the keys in the order Up Next shows now. Moving up among Trakt's own order
    fixes the shows above it in place (that's what "up one" means to someone looking at the row)."""
    data = _load()
    k = key(title, year)
    if k not in current or current.index(k) == 0:
        return
    i = current.index(k)
    if k in data["back"]:
        j = data["back"].index(k)
        if j > 0:
            data["back"][j - 1], data["back"][j] = data["back"][j], data["back"][j - 1]
            _save(data)
            return
        data["back"].remove(k)
    order = [x for x in current if x not in data["back"]]
    i = order.index(k) if k in order else len(order)
    order = [x for x in order if x != k]
    data["top"] = order[:max(i - 1, 0)] + [k] + order[max(i - 1, 0):i]
    _save(data)


def is_back(title, year):
    return key(title, year) in _load()["back"]


def move_back(title, year):
    data = _load()
    k = key(title, year)
    data["top"] = [x for x in data["top"] if x != k]
    data["back"] = [x for x in data["back"] if x != k] + [k]
    _save(data)


def move_front(title, year):
    """Back in its usual place (Trakt's order)."""
    data = _load()
    k = key(title, year)
    data["back"] = [x for x in data["back"] if x != k]
    data["top"] = [x for x in data["top"] if x != k]
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
