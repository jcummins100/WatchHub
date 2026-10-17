"""TMDB (themoviedb.org): trailers for any movie or show, played in the YouTube app.

Needs the user's free TMDB API key (settings -> tmdb_key). Nothing is stored beyond a cache.
"""
import urllib.parse

from resources.lib import cache, kodi

API = "https://api.themoviedb.org/3/"
TTL = 7 * 86400


def enabled():
    return bool(kodi.setting("tmdb_key", "").strip())


def _get(path, **params):
    params["api_key"] = kodi.setting("tmdb_key", "").strip()
    url = API + path + "?" + urllib.parse.urlencode(params)
    return cache.fetch_json(url, TTL) or {}


def find(title, year="", kind="Show"):
    """Best TMDB match for a title -> (media_type, id) or (None, None)."""
    if not title or not enabled():
        return None, None
    media = "movie" if kind == "Movie" else "tv"
    params = {"query": title}
    if year:
        params["year" if media == "movie" else "first_air_date_year"] = year
    res = _get("search/%s" % media, **params).get("results") or []
    if not res and year:
        res = _get("search/%s" % media, query=title).get("results") or []
    return (media, res[0]["id"]) if res else (None, None)


def trailer_url(title, year="", kind="Show"):
    """YouTube URL of the best trailer, or ''."""
    media, tid = find(title, year, kind)
    if not tid:
        return ""
    vids = _get("%s/%s/videos" % (media, tid), language="en-US").get("results") or []
    vids = [v for v in vids if v.get("site") == "YouTube"]
    vids.sort(key=lambda v: (v.get("type") != "Trailer", not v.get("official", False), v.get("published_at") or ""))
    return "https://www.youtube.com/watch?v=%s" % vids[0]["key"] if vids else ""


IMG = "https://image.tmdb.org/t/p/"


def details(title, year="", kind="Show"):
    """Overview, rating, genres, runtime, cast, seasons for the detail page ({} when unknown)."""
    media, tid = find(title, year, kind)
    if not tid:
        return {}
    d = _get("%s/%s" % (media, tid), append_to_response="credits,content_ratings,release_dates", language="en-US")
    if not d:
        return {}
    cast = ", ".join(c.get("name", "") for c in (d.get("credits") or {}).get("cast", [])[:6])
    runtime = ""
    if media == "movie" and d.get("runtime"):
        runtime = "%dh %02dm" % divmod(int(d["runtime"]), 60)
    elif media == "tv" and d.get("episode_run_time"):
        runtime = "%d min episodes" % d["episode_run_time"][0]
    cert = ""
    if media == "tv":
        for r in (d.get("content_ratings") or {}).get("results", []):
            if r.get("iso_3166_1") == "US":
                cert = r.get("rating", "")
    else:
        for r in (d.get("release_dates") or {}).get("results", []):
            if r.get("iso_3166_1") == "US":
                certs = [x.get("certification") for x in r.get("release_dates", []) if x.get("certification")]
                cert = certs[0] if certs else ""
    return {
        "tmdb_id": tid, "media": media,
        "overview": d.get("overview") or "",
        "vote": ("%.1f" % d["vote_average"]) if d.get("vote_average") else "",
        "genres": ", ".join(g.get("name", "") for g in d.get("genres", [])[:3]),
        "runtime": runtime,
        "seasons": ("%d seasons" % d["number_of_seasons"]) if d.get("number_of_seasons") else "",
        "certification": cert,
        "cast": cast,
        "poster": IMG + "w500" + d["poster_path"] if d.get("poster_path") else "",
        "backdrop": IMG + "w1280" + d["backdrop_path"] if d.get("backdrop_path") else "",
        "status": d.get("status") or "",
        "next_air": (d.get("next_episode_to_air") or {}).get("air_date") or "",
    }


def related(media, tmdb_id, limit=14):
    """(series name, [movies in the series, oldest first], [recommended]) for the info page row.
    Items: {title, year, type, poster, tmdb_id}. A movie's series is its TMDB collection."""
    if not tmdb_id or not enabled():
        return "", [], []
    kind = "Movie" if media == "movie" else "Show"

    def item(r):
        date = r.get("release_date") or r.get("first_air_date") or ""
        return {"title": r.get("title") or r.get("name") or "", "year": date[:4], "date": date, "type": kind,
                "poster": IMG + "w342" + r["poster_path"] if r.get("poster_path") else "", "tmdb_id": r.get("id")}
    name, parts = "", []
    if media == "movie":
        col = (_get("movie/%s" % tmdb_id, language="en-US").get("belongs_to_collection") or {})
        if col.get("id"):
            c = _get("collection/%s" % col["id"], language="en-US")
            name = c.get("name") or col.get("name") or ""
            parts = sorted((item(x) for x in c.get("parts") or [] if x.get("poster_path")), key=lambda x: x["date"] or "9999")
    recs = [item(x) for x in (_get("%s/%s/recommendations" % (media, tmdb_id), language="en-US").get("results") or [])
            if x.get("poster_path") and x.get("id") not in {p["tmdb_id"] for p in parts}]
    return name, parts, recs[:limit]


def seasons(tv_id):
    if not tv_id:
        return []
    d = _get("tv/%s" % tv_id, language="en-US")
    return [{"number": s["season_number"], "count": s.get("episode_count", 0), "name": s.get("name", "")}
            for s in d.get("seasons", []) if s.get("season_number", 0) > 0]


def episodes(tv_id, season):
    d = _get("tv/%s/season/%s" % (tv_id, season), language="en-US")
    out = []
    for e in d.get("episodes", []):
        out.append({"number": e.get("episode_number"), "name": e.get("name") or "", "aired": e.get("air_date") or "",
                    "runtime": ("%d min" % e["runtime"]) if e.get("runtime") else "", "overview": e.get("overview") or "",
                    "still": IMG + "w500" + e["still_path"] if e.get("still_path") else ""})
    return out


def upcoming(kind="Movie", region="US"):
    """Upcoming theatrical movies / shows airing in the next week (for the 'Coming soon' rows)."""
    if not enabled():
        return []
    if kind == "Movie":
        res = _get("movie/upcoming", region=region, language="en-US").get("results") or []
    else:
        res = _get("tv/on_the_air", language="en-US").get("results") or []
    out = []
    for r in res[:30]:
        out.append({"title": r.get("title") or r.get("name") or "", "year": (r.get("release_date") or r.get("first_air_date") or "")[:4],
                    "date": r.get("release_date") or r.get("first_air_date") or "", "type": kind, "plot": r.get("overview") or "",
                    "poster": IMG + "w342" + r["poster_path"] if r.get("poster_path") else "",
                    "backdrop": IMG + "w1280" + r["backdrop_path"] if r.get("backdrop_path") else "",
                    "vote": r.get("vote_average") or 0})
    out.sort(key=lambda x: x["date"])
    return out


# TMDB watch-provider ids (US) for the services WatchHub knows, keyed by JustWatch code
PROVIDERS = {"nfx": 8, "amp": 9, "atp": 350, "hlu": 15, "pct": 386, "ppp": 531, "mxx": 1899, "dnp": 337, "tbv": 73, "ptv": 300,
             "rkc": 207, "plx": 538, "aho": 1899, "app": 531}


def service_for(tmdb_id, codes, kind="Movie", region="US"):
    """The JustWatch code of the first of your services TMDB lists for a title ('' if none)."""
    media = "movie" if kind == "Movie" else "tv"
    res = (_get("%s/%s/watch/providers" % (media, tmdb_id)).get("results") or {}).get(region) or {}
    ids = [p.get("provider_id") for k in ("flatrate", "ads", "free") for p in res.get(k) or []]
    for pid in ids:
        code = next((c for c in codes if PROVIDERS.get(c) == pid), "")
        if code:
            return code
    return ""


def coming_soon(codes, kind="Movie", days=60, region="US"):
    """Titles releasing in the next `days` on the given services (JustWatch codes -> TMDB providers)."""
    import datetime

    if not enabled():
        return []
    ids = sorted({PROVIDERS[c] for c in codes if c in PROVIDERS})
    if not ids:
        return []
    today = datetime.date.today()
    end = today + datetime.timedelta(days=days)
    if kind == "Movie":
        res = _get("discover/movie", with_watch_providers="|".join(map(str, ids)), watch_region=region, language="en-US",
                   sort_by="primary_release_date.asc", **{"primary_release_date.gte": today.isoformat(), "primary_release_date.lte": end.isoformat()})
    else:
        res = _get("discover/tv", with_watch_providers="|".join(map(str, ids)), watch_region=region, language="en-US",
                   sort_by="first_air_date.asc", **{"first_air_date.gte": today.isoformat(), "first_air_date.lte": end.isoformat()})
    out = []
    for r in (res.get("results") or [])[:40]:
        date = r.get("release_date") or r.get("first_air_date") or ""
        out.append({"title": r.get("title") or r.get("name") or "", "year": date[:4], "date": date, "type": kind,
                    "plot": r.get("overview") or "", "poster": IMG + "w342" + r["poster_path"] if r.get("poster_path") else "",
                    "backdrop": IMG + "w1280" + r["backdrop_path"] if r.get("backdrop_path") else "", "vote": r.get("vote_average") or 0,
                    "tmdb_id": r.get("id")})
    return out
