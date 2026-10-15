"""On-demand titles across the user's streaming services (JustWatch availability data).

JustWatch's public GraphQL endpoint tells us what's popular on each service, with artwork and
Android TV deep links straight into the app (Netflix, Prime Video, Apple TV, Hulu, Peacock...).
No subscription credentials are involved; the app itself handles sign-in and playback.
"""
import json
import time
import urllib.request

from resources.lib import cache, kodi

API = "https://apis.justwatch.com/graphql"
IMG = "https://images.justwatch.com"
TTL = 6 * 3600
QV = "v5"  # bump when the GraphQL queries change so stale cache entries are ignored

# JustWatch package short code -> (display name, Android TV package)
SERVICES = [
    ("nfx", "Netflix", "com.netflix.ninja"),
    ("amp", "Prime Video", "com.amazon.amazonvideo.livingroom"),
    ("atp", "Apple TV", "com.apple.atve.androidtv.appletv"),
    ("hlu", "Hulu", "com.hulu.livingroomplus"),
    ("pct", "Peacock", "com.peacocktv.peacockandroid"),
    ("ppp", "Paramount+", "com.cbs.ott"),
    ("mxx", "Max", "com.wbd.stream"),
    ("dnp", "Disney+", "com.disney.disneyplus"),
    ("tbv", "Tubi", "com.tubitv"),
    ("ptv", "Pluto TV", "tv.pluto.android"),
    ("rkc", "The Roku Channel", "com.roku.web.trc"),
    ("plx", "Plex", "com.plexapp.android"),
    ("tcw", "The CW", "com.cw.fullepisodes.android"),
    ("xum", "Xumo Play", "com.xumo.xumo.tv"),
    ("yfr", "YouTube", "com.google.android.youtube.tv"),
]
AMAZON_CHANNELS = [
    ("aho", "HBO Max (Prime channel)"), ("aep", "MGM+ (Prime channel)"), ("app", "Paramount+ (Prime channel)"),
    ("saz", "Starz (Prime channel)"), ("azp", "AMC+ (Prime channel)"), ("adp", "Discovery+ (Prime channel)"),
    ("avl", "Apple TV (Prime channel)"), ("acn", "Cinemax (Prime channel)"), ("abb", "BritBox (Prime channel)"),
    ("pep", "Peacock (Prime channel)"),
]
SERVICES += [(c, n, "com.amazon.amazonvideo.livingroom") for c, n in AMAZON_CHANNELS]
BY_CODE = {c: (n, p) for c, n, p in SERVICES}
BY_PACKAGE = {p: c for c, n, p in SERVICES}

_QUERY = """
query Titles($country: Country!, $language: Language!, $first: Int!, $filter: TitleFilter, $sort: PopularTitlesSorting!) {
  popularTitles(country: $country, first: $first, filter: $filter, sortBy: $sort) {
    edges { node {
      id objectType
      content(country: $country, language: $language) {
        title originalReleaseYear shortDescription posterUrl genres { shortName }
        backdrops { backdropUrl }
        scoring { imdbScore }
        runtime ageCertification originalReleaseDate credits { name role characterName }
      }
      offers(country: $country, platform: ANDROID_TV) {
        monetizationType standardWebURL
        package { packageId shortName clearName technicalName }
      }
    } }
  }
}
"""


def installed_codes():
    """JustWatch codes for the streaming apps actually on this device (all of them off-Android)."""
    from resources.lib import health

    apps = health.installed_apps()
    amazon = [x.strip() for x in kodi.setting("amazon_channels", "aho,app").split(",") if x.strip()]
    amazon_codes = {c for c, _ in AMAZON_CHANNELS}
    codes = []
    for c, _, p in SERVICES:
        if c in amazon_codes:
            if c in amazon and (not apps or p in apps):
                codes.append(c)
        elif not apps or p in apps:
            codes.append(c)
    return codes


def _post(variables):
    key = "jw:%s:" % QV + json.dumps(variables, sort_keys=True)
    cached = cache.get(key, TTL)
    if cached is not None:
        return cached
    body = json.dumps({"query": _QUERY, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Kodi SportsHub)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        kodi.log("justwatch failed: %s" % exc)
        return cache.get(key, 10 * 365 * 86400) or {}
    if data.get("errors"):
        kodi.log("justwatch errors: %s" % data["errors"][:1])
    return cache.put(key, data.get("data") or {})


def _img(template, profile):
    if not template:
        return ""
    return IMG + template.replace("{profile}", profile).replace("{format}", "jpg")


def _best_offer(offers, codes):
    """Prefer subscription offers on services we have; then free/ads; skip rentals."""
    ranked = []
    for o in offers or []:
        code = (o.get("package") or {}).get("shortName")
        if code not in codes:
            continue
        mt = o.get("monetizationType")
        score = {"FLATRATE": 0, "FREE": 1, "ADS": 1}.get(mt)
        if score is None:
            continue
        ranked.append((score, codes.index(code), o))
    if not ranked:
        return None
    ranked.sort(key=lambda r: (r[0], r[1]))
    return ranked[0][2]


def _offers(offers, codes):
    """All playable offers on the user's services, best first, one per service."""
    seen, out = set(), []
    for o in offers or []:
        code = (o.get("package") or {}).get("shortName")
        if code not in codes or o.get("monetizationType") not in ("FLATRATE", "FREE", "ADS"):
            continue
        name, pkg = BY_CODE.get(code, ("", ""))
        if not pkg or code in seen:
            continue
        seen.add(code)
        out.append({"service": name, "pkg": pkg, "url": o.get("standardWebURL") or "", "code": code,
                    "monetization": {"FLATRATE": "subscription", "FREE": "free", "ADS": "free with ads"}.get(o.get("monetizationType"), "")})
    out.sort(key=lambda o: (o["monetization"] != "subscription", codes.index(o["code"])))
    return out


def _make(node, codes, require_offer=True):
    if node.get("__typename") == "Season" or node.get("objectType") == "SHOW_SEASON":
        # 'new this week' returns seasons; present them as their show
        show = node.get("show") or {}
        season_name = (node.get("content") or {}).get("title") or ""
        node = dict(show, objectType="SHOW", offers=node.get("offers") or show.get("offers"), season_name=season_name)
    c = node.get("content") or {}
    offer = _best_offer(node.get("offers"), codes)
    if not offer and require_offer:
        return None
    if offer:
        code = offer["package"]["shortName"]
        name, pkg = BY_CODE.get(code, (offer["package"].get("clearName", ""), ""))
    else:
        others = sorted({(o.get("package") or {}).get("clearName", "") for o in node.get("offers") or [] if o.get("monetizationType") in ("FLATRATE", "FREE", "ADS")})
        name, pkg = ("Not on your services" + (" (on %s)" % ", ".join(x for x in others if x)[:60] if others else "")), ""
    year = c.get("originalReleaseYear") or ""
    kind = "Movie" if node.get("objectType") == "MOVIE" else "Show"
    genres = ", ".join(g.get("shortName", "").title() for g in (c.get("genres") or [])[:2])
    imdb = (c.get("scoring") or {}).get("imdbScore")
    backdrops = c.get("backdrops") or []
    title = c.get("title") or ""
    return {
        "source": "ondemand",
        "service": name,
        "title": title,
        "year": year,
        "type": kind,
        "plot": c.get("shortDescription") or "",
        "poster": _img(c.get("posterUrl"), "s332"),
        "backdrop": _img(backdrops[0].get("backdropUrl"), "s1440") if backdrops else "",
        "meta": " • ".join(x for x in (name, kind, str(year), genres, ("IMDb %.1f" % imdb) if imdb else "") if x),
        "imdb": ("%.1f" % imdb) if imdb else "",
        "cast": ", ".join("%s (%s)" % (x["name"], x["characterName"]) if x.get("characterName") else x["name"]
                          for x in (c.get("credits") or []) if x.get("role") == "ACTOR")[:400],
        "director": ", ".join(x["name"] for x in (c.get("credits") or []) if x.get("role") == "DIRECTOR"),
        "runtime": ("%dh %02dm" % divmod(int(c["runtime"]), 60) if kind == "Movie" else "%d min episodes" % int(c["runtime"])) if c.get("runtime") else "",
        "certification": c.get("ageCertification") or "",
        "released": c.get("originalReleaseDate") or "",
        "season": node.get("season_name") or "",
        "offers": _offers(node.get("offers"), codes),
        "playable": bool(pkg),
        "play": {"src": "ondemand", "pkg": pkg, "url": (offer or {}).get("standardWebURL") or "", "name": name},
    }


def titles(codes=None, object_types=("MOVIE", "SHOW"), first=30, sort="POPULAR"):
    codes = codes or installed_codes()
    if not codes:
        return []
    data = _post({"country": kodi.setting("region", "us").upper(), "language": "en", "first": first, "sort": sort,
                  "filter": {"packages": codes, "objectTypes": list(object_types)}})
    out = []
    for edge in ((data.get("popularTitles") or {}).get("edges") or []):
        item = _make(edge.get("node") or {}, codes)
        if item:
            out.append(item)
    return out


_NEW = """
query New($country: Country!, $language: Language!, $date: Date!, $first: Int!) {
  newTitles(country: $country, date: $date, first: $first, filter: {packages: %s}) {
    edges { node {
      __typename objectType
      content(country: $country, language: $language) { title originalReleaseYear shortDescription posterUrl genres { shortName } backdrops { backdropUrl } scoring { imdbScore } }
      offers(country: $country, platform: ANDROID_TV) { monetizationType standardWebURL package { packageId shortName clearName technicalName } }
      ... on Season {
        show { objectType
          content(country: $country, language: $language) { title originalReleaseYear shortDescription posterUrl genres { shortName } backdrops { backdropUrl } scoring { imdbScore } runtime ageCertification originalReleaseDate credits { name role characterName } }
          offers(country: $country, platform: ANDROID_TV) { monetizationType standardWebURL package { packageId shortName clearName technicalName } }
        }
      }
    } }
  }
}
"""


def new_titles(codes=None, days=7, object_types=("MOVIE", "SHOW")):
    """Titles added to the user's services in the last `days`, newest first."""
    import datetime

    codes = codes or installed_codes()
    out, seen = [], set()
    for i in range(days):
        day = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
        variables = {"country": kodi.setting("region", "us").upper(), "language": "en", "date": day, "first": 40}
        key = "jw:new:%s:" % QV + json.dumps([variables, codes], sort_keys=True)
        data = cache.get(key, TTL)
        if data is None:
            body = json.dumps({"query": _NEW % json.dumps(codes), "variables": variables}).encode("utf-8")
            req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Kodi SportsHub)"})
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8")).get("data") or {}
            except Exception as exc:
                kodi.log("justwatch new failed: %s" % exc)
                data = None
            if data is None:
                continue  # don't remember a failure as "nothing new"
            cache.put(key, data)
        for edge in ((data.get("newTitles") or {}).get("edges") or []):
            node = edge.get("node") or {}
            if node.get("objectType") not in object_types and not (node.get("__typename") == "Season" and "SHOW" in object_types):
                continue
            item = _make(node, codes)
            if item and item["title"] not in seen:
                seen.add(item["title"])
                item["added"] = day
                item["meta"] = "Added %s \u2022 %s" % (day, item["meta"])
                out.append(item)
    return out


def rows():
    """[(label, kind, arg)] for the on-demand menu; services limited to installed apps."""
    codes = installed_codes()
    res = [("Trending on your services", "trending", {"codes": codes, "types": ["MOVIE", "SHOW"]}),
           ("Trending movies", "trending", {"codes": codes, "types": ["MOVIE"]}),
           ("Trending shows", "trending", {"codes": codes, "types": ["SHOW"]}),
           ("New this week", "new", {"codes": codes, "types": ["MOVIE", "SHOW"]}),
           ("Newest movies", "trending", {"codes": codes, "types": ["MOVIE"], "sort": "RELEASE_YEAR"}),
           ("Newest shows", "trending", {"codes": codes, "types": ["SHOW"], "sort": "RELEASE_YEAR"})]
    for c in codes:
        res.append(("New on %s" % BY_CODE[c][0], "new", {"codes": [c], "types": ["MOVIE", "SHOW"]}))
    for c in codes:
        res.append(("Popular on %s" % BY_CODE[c][0], "trending", {"codes": [c], "types": ["MOVIE", "SHOW"]}))
    return res


def row_items(index):
    rows_ = rows()
    if index < 0 or index >= len(rows_):
        return []
    label, kind, arg = rows_[index]
    if kind == "new":
        return new_titles(arg["codes"], object_types=tuple(arg["types"]))
    return titles(arg["codes"], tuple(arg["types"]), first=40, sort=arg.get("sort", "POPULAR"))


_SEARCH = """
query Search($country: Country!, $language: Language!, $first: Int!, $filter: TitleFilter) {
  popularTitles(country: $country, first: $first, filter: $filter) {
    edges { node {
      id objectType
      content(country: $country, language: $language) { title originalReleaseYear shortDescription posterUrl genres { shortName } backdrops { backdropUrl } scoring { imdbScore } runtime ageCertification originalReleaseDate credits { name role characterName } }
      offers(country: $country, platform: ANDROID_TV) { monetizationType standardWebURL deeplinkURL: deeplinkURL(platform: ANDROID_TV) package { packageId shortName clearName technicalName } }
    } }
  }
}
"""


def search(title, kind=""):
    """Titles matching a name, restricted to the user's services."""
    if not title:
        return []
    codes = installed_codes()
    flt = {"searchQuery": title}
    if kind in ("Movie", "Show"):
        flt["objectTypes"] = ["MOVIE" if kind == "Movie" else "SHOW"]
    key = "jw:search:%s:" % QV + json.dumps(flt, sort_keys=True)
    data = cache.get(key, TTL)
    if data is None:
        body = json.dumps({"query": _SEARCH, "variables": {"country": kodi.setting("region", "us").upper(), "language": "en", "first": 8, "filter": flt}}).encode("utf-8")
        req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Kodi SportsHub)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = (json.loads(resp.read().decode("utf-8")).get("data") or {})
        except Exception as exc:
            kodi.log("justwatch search failed: %s" % exc)
            data = {}
        cache.put(key, data)
    out = []
    for edge in ((data.get("popularTitles") or {}).get("edges") or []):
        item = _make(edge.get("node") or {}, codes, require_offer=False)
        if item:
            out.append(item)
    return out


def lookup(title, year="", kind=""):
    """Best single match for a title/year on the user's services, or None."""
    res = search(title, kind)
    if not res:
        return None
    for r in res:
        if str(r["year"]) == str(year) and r["title"].lower() == title.lower():
            return r
    for r in res:
        if r["title"].lower() == title.lower():
            return r
    return res[0]


_SEASONS = """
query Seasons($country: Country!, $language: Language!, $filter: TitleFilter) {
  popularTitles(country: $country, first: 1, filter: $filter) {
    edges { node { objectType
      content(country: $country, language: $language) { title originalReleaseYear }
      ... on Show {
        totalSeasonCount
        seasons {
          content(country: $country, language: $language) { seasonNumber title originalReleaseDate }
          totalEpisodeCount
          episodes { content(country: $country, language: $language) { episodeNumber title originalReleaseDate shortDescription } }
        }
      }
    } }
  }
}
"""


def seasons(title, year=""):
    """[{number, title, released, count, episodes:[{number,name,aired,overview}]}] for a show, newest season first."""
    variables = {"country": kodi.setting("region", "us").upper(), "language": "en", "filter": {"searchQuery": title, "objectTypes": ["SHOW"]}}
    key = "jw:seasons:%s:%s:%s" % (QV, title.lower(), year)
    data = cache.get(key, 24 * 3600)
    if data is None:
        body = json.dumps({"query": _SEASONS, "variables": variables}).encode("utf-8")
        req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Kodi SportsHub)"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8")).get("data") or {}
        except Exception as exc:
            kodi.log("justwatch seasons failed: %s" % exc)
            data = {}
        cache.put(key, data)
    edges = (data.get("popularTitles") or {}).get("edges") or []
    if not edges:
        return []
    node = edges[0]["node"]
    if str((node.get("content") or {}).get("originalReleaseYear")) != str(year) and year and (node.get("content") or {}).get("title", "").lower() != title.lower():
        return []
    out = []
    for sn in node.get("seasons") or []:
        c = sn.get("content") or {}
        eps = []
        for e in sn.get("episodes") or []:
            ec = e.get("content") or {}
            eps.append({"number": ec.get("episodeNumber"), "name": ec.get("title") or "", "aired": ec.get("originalReleaseDate") or "",
                        "overview": ec.get("shortDescription") or "", "still": "", "runtime": ""})
        eps.sort(key=lambda e: e["number"] or 0)
        out.append({"number": c.get("seasonNumber"), "title": c.get("title") or "Season %s" % c.get("seasonNumber"),
                    "released": c.get("originalReleaseDate") or "", "count": sn.get("totalEpisodeCount") or len(eps), "episodes": eps})
    out.sort(key=lambda x: x["number"] or 0, reverse=True)
    return out
