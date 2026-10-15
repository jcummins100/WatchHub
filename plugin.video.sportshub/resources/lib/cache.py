"""Tiny JSON file cache with TTL, stored in the add-on profile directory."""
import hashlib
import json
import os
import threading
import time

from resources.lib import kodi


def _path(key):
    name = hashlib.sha1(key.encode("utf-8")).hexdigest()[:24] + ".json"
    return os.path.join(kodi.ensure_profile_dir(), "cache", name)


def get(key, max_age_s):
    p = _path(key)
    try:
        if time.time() - os.path.getmtime(p) > max_age_s:
            return None
        with open(p, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def put(key, value):
    p = _path(key)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    # Kodi runs each add-on call (service, every home row) on its own thread in one process, and on
    # a cold cache several of them fetch the same URL at once - give each writer its own temp file.
    tmp = "%s.%d.%d.tmp" % (p, os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(value, fh)
    os.replace(tmp, p)
    return value


def clear():
    d = os.path.join(kodi.ensure_profile_dir(), "cache")
    if not os.path.isdir(d):
        return 0
    n = 0
    for f in os.listdir(d):
        try:
            os.remove(os.path.join(d, f))
            n += 1
        except OSError:
            pass
    return n


def fetch_json(url, max_age_s, headers=None, timeout=20, mirrors=None):
    """GET a JSON document with on-disk caching, trying mirrors in order.

    Cached under the primary URL. On total failure returns stale cached data (any age)
    rather than nothing, so a dead upstream degrades gracefully instead of blanking menus.
    """
    import gzip
    import urllib.request

    cached = get(url, max_age_s)
    if cached is not None:
        return cached
    for candidate in [url] + list(mirrors or []):
        req = urllib.request.Request(candidate, headers={"User-Agent": "Kodi SportsHub/0.1", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip" or candidate.endswith(".gz") or data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                value = json.loads(data.decode("utf-8"))
            if candidate != url:
                kodi.log("fetched %s from mirror %s" % (url, candidate))
            return put(url, value)
        except Exception as exc:  # network errors, bad JSON
            kodi.log("fetch failed %s: %s" % (candidate, exc))
    return get(url, 10 * 365 * 86400)
