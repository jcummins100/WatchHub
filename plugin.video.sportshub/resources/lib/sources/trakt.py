"""Trakt.tv: the memory for shows and movies - what you've watched, what's next, what's new.

Sign-in uses Trakt's device-code flow (a short code typed at trakt.tv/activate on any device);
the access token lives in this add-on's settings on the Shield. Needs the user's own Trakt app
Client ID / Client Secret (free, trakt.tv/oauth/applications).
"""
import json
import time
import urllib.request

import xbmcgui

from resources.lib import cache, kodi

API = "https://api.trakt.tv/"
TTL = 15 * 60


def configured():
    # New Trakt apps are PKCE "public" clients with no secret; the device flow only needs the Client ID.
    return bool(kodi.setting("trakt_client_id", "").strip())


def _client():
    c = {"client_id": kodi.setting("trakt_client_id", "").strip()}
    secret = kodi.setting("trakt_client_secret", "").strip()
    if secret:
        c["client_secret"] = secret
    return c


def signed_in():
    return configured() and bool(kodi.setting("trakt_access_token", ""))


def _headers(auth=True):
    h = {"Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": kodi.setting("trakt_client_id", "").strip(),
         "User-Agent": "Kodi SportsHub/0.1"}
    if auth and kodi.setting("trakt_access_token", ""):
        h["Authorization"] = "Bearer " + kodi.setting("trakt_access_token", "")
    return h


def _call(path, data=None, auth=True, method=None, cache_ttl=0):
    url = API + path
    key = "trakt:" + url
    if cache_ttl and data is None:
        hit = cache.get(key, cache_ttl)
        if hit is not None:
            return hit
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=_headers(auth), method=method or ("POST" if body else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            out = json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code == 401 and auth and _refresh():
            return _call(path, data, auth, method, cache_ttl)
        kodi.log("trakt %s -> HTTP %s" % (path, exc.code))
        return None
    except Exception as exc:
        kodi.log("trakt %s failed: %s" % (path, exc))
        return cache.get(key, 10 * 365 * 86400) if cache_ttl else None
    if cache_ttl and data is None:
        cache.put(key, out)
    return out


# ---------------------------------------------------------------- auth
def _save_tokens(tok):
    kodi.ADDON.setSetting("trakt_access_token", tok.get("access_token", ""))
    kodi.ADDON.setSetting("trakt_refresh_token", tok.get("refresh_token", ""))
    kodi.ADDON.setSetting("trakt_token_expires", str(int(time.time()) + int(tok.get("expires_in", 7776000))))


def _refresh():
    rt = kodi.setting("trakt_refresh_token", "")
    if not rt:
        return False
    body = dict(_client(), refresh_token=rt, redirect_uri="urn:ietf:wg:oauth:2.0:oob", grant_type="refresh_token")
    tok = _call("oauth/token", body, auth=False)
    if not tok or "access_token" not in tok:
        return False
    _save_tokens(tok)
    return True


def sign_in():
    """Device-code flow with an on-screen dialog. Returns True when signed in."""
    if not configured():
        xbmcgui.Dialog().ok(kodi.ADDON_NAME, "Enter your Trakt Client ID in Settings first.")
        return False
    code = _call("oauth/device/code", {"client_id": kodi.setting("trakt_client_id").strip()}, auth=False)
    if not code or "device_code" not in code:
        kodi.notify("Trakt: could not start sign-in", icon=xbmcgui.NOTIFICATION_ERROR)
        return False
    dlg = xbmcgui.DialogProgress()
    dlg.create("Sign in to Trakt", "On your phone or computer go to [B]%s[/B]\nand enter the code  [B]%s[/B]" % (code.get("verification_url", "https://trakt.tv/activate"), code.get("user_code", "")))
    interval = int(code.get("interval", 5))
    deadline = time.time() + int(code.get("expires_in", 600))
    monitor = __import__("xbmc").Monitor()
    while time.time() < deadline and not dlg.iscanceled() and not monitor.abortRequested():
        dlg.update(int(100 - 100 * (deadline - time.time()) / int(code.get("expires_in", 600))))
        if monitor.waitForAbort(interval):
            break
        req = urllib.request.Request(API + "oauth/device/token", data=json.dumps(dict(_client(), code=code["device_code"])).encode("utf-8"),
                                     headers=_headers(auth=False))
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                tok = json.loads(resp.read().decode("utf-8"))
                _save_tokens(tok)
                dlg.close()
                kodi.notify("Signed in to Trakt")
                cache.clear()
                return True
        except urllib.error.HTTPError as exc:
            if exc.code == 400:  # pending: keep polling
                continue
            if exc.code == 429:  # slow down
                interval += 2
                continue
            dlg.close()
            kodi.notify("Trakt sign-in failed (%s)" % exc.code, icon=xbmcgui.NOTIFICATION_ERROR)
            return False
        except Exception as exc:
            kodi.log("trakt device poll: %s" % exc)
    dlg.close()
    return False


def sign_out():
    for k in ("trakt_access_token", "trakt_refresh_token", "trakt_token_expires"):
        kodi.ADDON.setSetting(k, "")
    cache.clear()


# ---------------------------------------------------------------- data
def _title(show, kind, year=None):
    return {"title": show.get("title", ""), "year": str(show.get("year") or year or ""), "type": kind,
            "ids": show.get("ids") or {}, "tmdb": (show.get("ids") or {}).get("tmdb")}


def up_next(limit=20):
    """Next episode to watch for the most recently watched shows (Trakt 'progress/watched'), fetched in parallel."""
    if not signed_in():
        return []
    from concurrent.futures import ThreadPoolExecutor

    watched = _call("sync/watched/shows?extended=noseasons", cache_ttl=TTL) or []
    watched.sort(key=lambda w: w.get("last_watched_at") or "", reverse=True)
    recent = [w for w in watched if (w.get("show") or {}).get("ids", {}).get("trakt")][:limit * 2]

    def progress(w):
        sid = w["show"]["ids"]["trakt"]
        return w, _call("shows/%s/progress/watched?hidden=false&specials=false" % sid, cache_ttl=TTL) or {}

    out = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for w, prog in pool.map(progress, recent):
            nxt = prog.get("next_episode")
            if not nxt:
                continue
            t = _title(w["show"], "Show")
            t.update({"next": "S%02dE%02d" % (nxt.get("season", 0), nxt.get("number", 0)), "episode_title": nxt.get("title") or "",
                      "season": nxt.get("season", 0), "number": nxt.get("number", 0),
                      "aired": prog.get("aired", 0), "completed": prog.get("completed", 0), "last_watched": w.get("last_watched_at") or ""})
            out.append(t)
            if len(out) >= limit:
                break
    return out


def recommendations(kind="movies", limit=40):
    """Trakt's picks for you from your watch history (free accounts too); [{title, year, type, rating}]."""
    if not signed_in():
        return []
    data = _call("recommendations/%s?limit=%d&ignore_collected=true" % (kind, limit), cache_ttl=6 * 3600) or []
    return [{"title": x["title"], "year": x.get("year") or "", "type": "Movie" if kind == "movies" else "Show",
             "rating": x.get("rating") or 0, "ids": x.get("ids") or {}}
            for x in data if isinstance(x, dict) and x.get("title")]


def calendar(days=14):
    """New episodes of your shows in the next `days` (and the past 2 so 'just dropped' shows up)."""
    if not signed_in():
        return []
    start = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 2 * 86400))
    eps = _call("calendars/my/shows/%s/%d" % (start, days + 2), cache_ttl=TTL) or []
    out = []
    for e in eps:
        show = e.get("show") or {}
        ep = e.get("episode") or {}
        t = _title(show, "Show")
        t.update({"next": "S%02dE%02d" % (ep.get("season", 0), ep.get("number", 0)), "episode_title": ep.get("title") or "",
                  "first_aired": e.get("first_aired") or "", "premiere": ep.get("number") == 1})
        out.append(t)
    return out


def watchlist():
    if not signed_in():
        return []
    items = _call("sync/watchlist?extended=full", cache_ttl=TTL) or []
    out, seen = [], set()
    for it in items:
        kind = "Movie" if it.get("type") == "movie" else "Show"
        obj = it.get("movie") or it.get("show") or {}  # seasons/episodes on the list carry their parent show
        key = (kind, (obj.get("ids") or {}).get("trakt") or obj.get("title"))
        if key in seen:
            continue
        seen.add(key)
        t = _title(obj, kind)
        t["listed_at"] = it.get("listed_at") or ""
        out.append(t)
    out.sort(key=lambda t: t["listed_at"], reverse=True)
    return out


def mark_watched(kind, ids):
    key = "movies" if kind == "Movie" else "shows"
    return _call("sync/history", {key: [{"ids": ids}]}) is not None


def unmark_watched(kind, ids):
    """Take a movie or show out of your Trakt history (every play of it)."""
    key = "movies" if kind == "Movie" else "shows"
    return _call("sync/history/remove", {key: [{"ids": ids}]}) is not None


def mark_episode_watched(title, year, season, number):
    """Mark one episode watched (the user said they finished it); Up Next moves on at its next load."""
    ids = search_ids(title, year, "Show")
    if not ids:
        return False
    ok = _call("sync/history", {"shows": [{"ids": ids, "seasons": [{"number": int(season), "episodes": [{"number": int(number)}]}]}]}) is not None
    if ok and ids.get("trakt"):
        cache.forget("trakt:" + API + "shows/%s/progress/watched?hidden=false&specials=false" % ids["trakt"])
        cache.forget("trakt:" + API + "sync/watched/shows?extended=noseasons")
    return ok


def add_watchlist(kind, ids):
    key = "movies" if kind == "Movie" else "shows"
    return _call("sync/watchlist", {key: [{"ids": ids}]}) is not None


def search_ids(title, year, kind):
    """Trakt ids for a title we only know by name (from JustWatch)."""
    typ = "movie" if kind == "Movie" else "show"
    q = urllib.parse.quote(title)
    res = _call("search/%s?query=%s%s" % (typ, q, "&years=%s" % year if year else ""), auth=False, cache_ttl=7 * 86400) or []
    return ((res[0].get(typ) or {}).get("ids") or {}) if res else {}


import urllib.parse  # noqa: E402  (used by search_ids)


def show_progress(title, year=""):
    """{"seasons": {n: {"aired", "completed", "episodes": {e: watched_bool}}}, "aired", "completed"} or {}."""
    if not signed_in():
        return {}
    ids = search_ids(title, year, "Show")
    if not ids.get("trakt"):
        return {}
    prog = _call("shows/%s/progress/watched?hidden=false&specials=false" % ids["trakt"], cache_ttl=5 * 60) or {}
    out = {"aired": prog.get("aired", 0), "completed": prog.get("completed", 0), "seasons": {}}
    for sn in prog.get("seasons") or []:
        out["seasons"][sn.get("number")] = {"aired": sn.get("aired", 0), "completed": sn.get("completed", 0),
                                             "episodes": {e.get("number"): bool(e.get("completed")) for e in sn.get("episodes") or []}}
    return out


def movie_watched(title, year=""):
    if not signed_in():
        return False
    ids = search_ids(title, year, "Movie")
    if not ids.get("trakt"):
        return False
    hist = _call("sync/history/movies/%s?limit=1" % ids["trakt"], cache_ttl=5 * 60) or []
    return bool(hist)


def forget_watched():
    """Drop the cached watched-movies pages (marked something watched): the next read asks Trakt."""
    for page in range(1, 41):
        cache.forget("trakt:" + API + "sync/watched/movies?page=%d&limit=250" % page)


def watched_movie_ids():
    """{"tmdb": set, "imdb": set} of every movie in the user's Trakt history (cached 6 h); empty when signed out."""
    out = {"tmdb": set(), "imdb": set()}
    if not signed_in():
        return out
    rows = []
    for page in range(1, 41):  # Trakt pages this list (100 a page by default); 250 a page, up to 10,000 movies
        got = _call("sync/watched/movies?page=%d&limit=250" % page, cache_ttl=6 * 3600) or []
        rows += got
        if len(got) < 250:
            break
    for row in rows:
        ids = (row.get("movie") or {}).get("ids") or {}
        if ids.get("tmdb"):
            out["tmdb"].add(str(ids["tmdb"]))
        if ids.get("imdb"):
            out["imdb"].add(ids["imdb"])
    return out

