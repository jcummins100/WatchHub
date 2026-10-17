"""Which of Trakt's recommendations the "Recommended for you" row shows (state in recommended.json).

The row changes once a day and on long-press > "Show me different picks"; a pick shown in the last
COOLDOWN_DAYS waits its turn unless there's nothing else. Pinned titles stay until unpinned.
"""
import json
import os
import time

from resources.lib import kodi

FILE = "recommended.json"
ROW_SIZE = 20
COOLDOWN_DAYS = 7


def _path():
    return os.path.join(kodi.ensure_profile_dir(), FILE)


def load():
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    data.setdefault("pinned", [])   # [{"key", "title", "year", "type"}]
    data.setdefault("shown", {})    # key -> when it was last in the row
    data.setdefault("picks", [])
    return data


def save(data):
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, _path())


def key(title, year, kind):
    return "%s|%s|%s" % ((title or "").strip().lower(), year or "", kind or "")


def today():
    return time.strftime("%Y-%m-%d")


def choose(cands):
    """cands: [key] in Trakt's order (already only titles on your services). Returns today's keys,
    pinned first; picks again when the day changed or after a reshuffle."""
    data = load()
    pins = [p["key"] for p in data["pinned"]]
    if data.get("day") == today() and data["picks"]:
        keep = [k for k in data["picks"] if k in cands or k in pins]
        if len(keep) >= min(ROW_SIZE, len(cands)) - 2:
            return pins + [k for k in keep if k not in pins]
    cutoff = time.time() - COOLDOWN_DAYS * 86400
    fresh = [k for k in cands if k not in pins and data["shown"].get(k, 0) < cutoff]
    rest = [k for k in cands if k not in pins and k not in fresh]
    picks = (fresh + rest)[:max(0, ROW_SIZE - len(pins))]
    now = time.time()
    for k in picks:
        data["shown"][k] = now
    data["shown"] = {k: v for k, v in data["shown"].items() if v >= cutoff}
    data.update({"day": today(), "picks": picks})
    save(data)
    return pins + picks


def reshuffle():
    data = load()
    data["day"] = ""
    save(data)


def pin(title, year, kind, on=True):
    data = load()
    k = key(title, year, kind)
    data["pinned"] = [p for p in data["pinned"] if p["key"] != k]
    if on:
        data["pinned"].append({"key": k, "title": title, "year": year, "type": kind})
    save(data)


def is_pinned(title, year, kind):
    return key(title, year, kind) in {p["key"] for p in load()["pinned"]}
