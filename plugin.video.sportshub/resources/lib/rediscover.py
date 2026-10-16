"""Rediscover: a daily Home row of well-liked 1985-2015 movies on your services (WatchHub map 5.1).

- Pool: the ~400 most popular movies from those years on your services (Included or free), kept only when
  the score means something: IMDb >= 6.5 with >= 25k votes, or (no IMDb score) TMDB >= 6.5.
- Movies you've seen stay in (they're "back in the day" favourites) and are marked Seen; a setting
  shows unseen ones only.
- Picked once a day, so the row never reshuffles under someone browsing: a mix of decades and
  categories, one film per franchise, nothing already in New this week or Trending, and a film
  doesn't come back for two weeks.
- Long-press: More like this (nudges its categories and decade) and Hide this movie (with Undo).
  Feedback stays in WatchHub (rediscover.json), never as Trakt ratings.
"""
import json
import os
import random
import re
import threading
import time

from resources.lib import kodi
from resources.lib.sources import ondemand, tmdb, trakt

YEARS = (1985, 2015)
ROW_SIZE = 20
COOLDOWN_DAYS = 14
PER_CATEGORY = 5          # at most this many cards share a first category
UNDO_WINDOW = 3600        # "Undo hide" stays on the long-press menu this long


def _path():
    return os.path.join(kodi.ensure_profile_dir(), "rediscover.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _save(state):
    path = _path()
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())  # the service and a row can save at once
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, path)
    except OSError as exc:
        kodi.log("rediscover state not saved: %s" % exc)


def _today():
    return time.strftime("%Y-%m-%d")


def _decade(year):
    try:
        return int(year) // 10 * 10
    except (TypeError, ValueError):
        return 0


def _qualifies(t):
    if t["imdb_score"]:
        return t["imdb_score"] >= 6.5 and t["imdb_votes"] >= 25000
    return t["tmdb_score"] >= 6.5  # no IMDb score isn't a bad score


_SEQUEL = re.compile(r"(\s*[:\-(].*$)|(\s+(part\s+)?([2-9]|ii|iii|iv|v|vi)$)")


def _franchise(t):
    """TMDB's collection when there's a key (Back to the Future 1-3 share one), else the title without
    its subtitle or sequel number."""
    if tmdb.enabled() and t.get("tmdb_id"):
        coll = (tmdb._get("/movie/%s" % t["tmdb_id"]) or {}).get("belongs_to_collection") or {}
        if coll.get("id"):
            return "c%s" % coll["id"]
    title = re.sub(r"^the\s+", "", t["title"].lower())
    return _SEQUEL.sub("", title).strip() or title


def pool():
    """Qualifying movies on the user's services: Included or free offers only."""
    subs = ondemand.subscriptions()
    codes = [c for c in ondemand.installed_codes() if c in subs or c in ondemand.FREE_CODES]
    return [t for t in ondemand.classic_movies(codes, *YEARS) if _qualifies(t)]


def _elsewhere():
    """Titles already in another Home row (New this week, Trending)."""
    seen = set()
    for row in (3, 0):
        try:
            seen |= {t["jw_id"] for t in ondemand.row_items(row) if t.get("jw_id")}
        except Exception as exc:
            kodi.log("rediscover: row %d not checked: %s" % (row, exc))
    return seen


def _pick(cands, state, day):
    """Today's cards: best-scored first with a daily shuffle, liked categories/decades nudged up,
    decades taken in turn, one per franchise, at most PER_CATEGORY per first category."""
    rnd = random.Random(day)
    liked = state.get("liked") or []
    like_genres = {}
    like_decades = {}
    for lk in liked[-20:]:
        for g in lk.get("genres") or []:
            like_genres[g] = like_genres.get(g, 0) + 1
        like_decades[lk.get("decade")] = like_decades.get(lk.get("decade"), 0) + 1

    def score(t):
        s = (t["imdb_score"] or t["tmdb_score"]) + rnd.uniform(0, 1.5)
        s += min(2.0, 0.5 * sum(like_genres.get(g, 0) for g in t["genre_codes"]))
        s += min(1.0, 0.5 * like_decades.get(_decade(t["year"]), 0))
        return s

    by_decade = {}
    for t in sorted(cands, key=score, reverse=True):
        by_decade.setdefault(_decade(t["year"]), []).append(t)
    decades = sorted(by_decade)
    rnd.shuffle(decades)
    picks, franchises, per_cat = [], set(), {}
    while len(picks) < ROW_SIZE and any(by_decade.values()):
        for d in decades:
            queue = by_decade[d]
            while queue:
                t = queue.pop(0)
                cat = (t["genre_codes"] or [""])[0]
                if per_cat.get(cat, 0) >= PER_CATEGORY:
                    continue
                fr = _franchise(t)
                if fr in franchises:
                    continue
                franchises.add(fr)
                per_cat[cat] = per_cat.get(cat, 0) + 1
                picks.append(t)
                break
            if len(picks) >= ROW_SIZE:
                break
    return picks


def today():
    """Today's Rediscover cards (title dicts, each with "seen"). Picked on the first call of the day."""
    state = _load()
    day = _today()
    all_ = pool()
    by_id = {t["jw_id"]: t for t in all_}
    if state.get("day") != day or not state.get("picks"):
        hidden = set(state.get("hidden") or [])
        cutoff = time.time() - COOLDOWN_DAYS * 86400
        shown = {k: v for k, v in (state.get("shown") or {}).items() if v >= cutoff}
        watched = trakt.watched_movie_ids()
        unseen_only = kodi.setting_bool("rediscover_unseen_only", False)
        elsewhere = _elsewhere()
        cands = [t for t in all_ if t["jw_id"] not in hidden and t["jw_id"] not in shown
                 and t["jw_id"] not in elsewhere
                 and not (unseen_only and _seen(t, watched))]
        picks = _pick(cands, state, day)
        now = time.time()
        for t in picks:
            shown[t["jw_id"]] = now
        state.update({"day": day, "picks": [t["jw_id"] for t in picks], "shown": shown})
        _save(state)
        kodi.log("rediscover: %d picked from %d (pool %d)" % (len(picks), len(cands), len(all_)))
    watched = trakt.watched_movie_ids()
    out = []
    for jid in state["picks"]:
        t = by_id.get(jid)
        if t and jid not in (state.get("hidden") or []):
            out.append(dict(t, seen=_seen(t, watched)))
    return out


def _seen(t, watched):
    return t.get("tmdb_id") in watched["tmdb"] or t.get("imdb_id") in watched["imdb"]


def find(jw_id):
    return next((t for t in pool() if t["jw_id"] == jw_id), None)


def like(jw_id):
    t = find(jw_id)
    if not t:
        return None
    state = _load()
    state.setdefault("liked", []).append({"id": jw_id, "genres": t["genre_codes"], "decade": _decade(t["year"]), "at": int(time.time())})
    state["liked"] = state["liked"][-50:]
    _save(state)
    return t


def hide(jw_id):
    state = _load()
    hidden = state.setdefault("hidden", [])
    if jw_id not in hidden:
        hidden.append(jw_id)
    state["last_hidden"] = {"id": jw_id, "at": int(time.time())}
    _save(state)


def undo_candidate():
    """(jw_id, title) of the movie hidden in the last hour, else None."""
    last = _load().get("last_hidden") or {}
    if last.get("id") and time.time() - last.get("at", 0) < UNDO_WINDOW:
        t = find(last["id"])
        return last["id"], (t["title"] if t else "the last movie")
    return None


def unhide(jw_id):
    state = _load()
    state["hidden"] = [x for x in state.get("hidden") or [] if x != jw_id]
    state.pop("last_hidden", None)
    _save(state)
