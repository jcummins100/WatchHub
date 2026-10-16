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
QV = "v8"  # bump when the GraphQL queries change so stale cache entries are ignored

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
    ("aho", "HBO Max (Prime)"), ("aep", "MGM+ (Prime)"), ("app", "Paramount+ (Prime)"),
    ("saz", "Starz (Prime)"), ("azp", "AMC+ (Prime)"), ("adp", "Discovery+ (Prime)"),
    ("avl", "Apple TV (Prime)"), ("acn", "Cinemax (Prime)"), ("abb", "BritBox (Prime)"),
    ("pep", "Peacock (Prime)"),
]
SERVICES += [(c, n, "com.amazon.amazonvideo.livingroom") for c, n in AMAZON_CHANNELS]
BY_CODE = {c: (n, p) for c, n, p in SERVICES}
# Free services: everything on them is included without a subscription
FREE_CODES = {"tbv", "ptv", "rkc", "plx", "xum", "yfr"}
# Stores that rent and sell inside an app we have (JustWatch lists them under their own codes)
STORES = {"amz": ("Prime Video", "com.amazon.amazonvideo.livingroom"), "itu": ("Apple TV", "com.apple.atve.androidtv.appletv")}
# Offer labels, best first (map 5.4): included in a confirmed subscription > free > free with ads >
# a subscription you haven't confirmed > rent > buy
RANK = {"Included": 0, "Free": 1, "Free with ads": 2, "Subscription": 3, "Rent": 4, "Buy": 5}
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
        monetizationType retailPrice(language: $language) standardWebURL deeplinkURL: deeplinkURL(platform: ANDROID_TV)
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
    # settings.xml supplies the default (aho,app); an empty value means the user cleared it - no channels
    amazon = [x.strip() for x in kodi.setting("amazon_channels").split(",") if x.strip()]
    amazon_codes = {c for c, _ in AMAZON_CHANNELS}
    codes = []
    for c, _, p in SERVICES:
        if c in amazon_codes:
            if c in amazon and (not apps or p in apps):
                codes.append(c)
        elif not apps or p in apps:
            codes.append(c)
    return codes


def subscriptions():
    """JustWatch codes of the paid services the user confirmed (Settings or WatchHub menu > Your subscriptions)."""
    return {x.strip() for x in kodi.ADDON.getSetting("subscriptions").split(",") if x.strip()}


def _label(offer, subs):
    """Included / Free / Free with ads / Subscription / Rent $3.99 / Buy $14.99, or "" for offers we don't show."""
    code = (offer.get("package") or {}).get("shortName")
    mt = offer.get("monetizationType")
    if mt == "FLATRATE":
        return "Included" if code in subs or code in FREE_CODES else "Subscription"
    if mt in ("FREE", "ADS"):
        return "Free" if mt == "FREE" else "Free with ads"
    if mt in ("RENT", "BUY") and code in STORES:
        price = offer.get("retailPrice") or ""
        return ("Rent" if mt == "RENT" else "Buy") + (" " + price if price else "")
    return ""


def _rank(label):
    return RANK.get(label.split(" $")[0], 9)


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


def _link(offer):
    """Deep link for an offer. Peacock's app ignores its web URLs (lands on its home page, cold or warm)
    but honours JustWatch's peacocktv.com/deeplink form, which arrives wrapped as an intent:// URI."""
    offer = offer or {}
    dl = offer.get("deeplinkURL") or ""
    if (offer.get("package") or {}).get("shortName") == "pct" and dl.startswith("intent://"):
        return "https://" + dl[len("intent://"):].split("#Intent;", 1)[0]
    return offer.get("standardWebURL") or ""


def _best_offer(offers, codes):
    """The offer a card plays: best label first (Included > Free > Free with ads), then the user's service
    order. A subscription the user hasn't confirmed, or a rental, never makes a card - those are only
    listed under "Watch on..." (and Search says "Not on your services")."""
    subs = subscriptions()
    ranked = []
    for o in offers or []:
        code = (o.get("package") or {}).get("shortName")
        if code not in codes:
            continue
        label = _label(o, subs)
        if not label or _rank(label) > RANK["Free with ads"]:
            continue
        ranked.append((_rank(label), codes.index(code), o))
    if not ranked:
        return None
    ranked.sort(key=lambda r: (r[0], r[1]))
    return ranked[0][2]


def _offers(offers, codes):
    """Every way to watch on the user's services (and their apps' stores), best first, one per service."""
    subs = subscriptions()
    best = {}
    for o in offers or []:
        code = (o.get("package") or {}).get("shortName")
        if code in STORES:
            name, pkg = STORES[code]
            if pkg not in {BY_CODE[c][1] for c in codes if c in BY_CODE}:
                continue  # that store's app isn't on this device
        elif code in codes:
            name, pkg = BY_CODE.get(code, ("", ""))
        else:
            continue
        label = _label(o, subs)
        if not pkg or not label:
            continue
        if code not in best or _rank(label) < _rank(best[code]["label"]):
            best[code] = {"service": name, "pkg": pkg, "url": _link(o), "code": code, "label": label, "monetization": label}
    order = {c: i for i, c in enumerate(codes)}
    out, apps = [], set()
    for o in sorted(best.values(), key=lambda o: (_rank(o["label"]), order.get(o["code"], 99))):
        if o["pkg"] not in apps:  # one way per app: Included on Prime Video beats renting in Prime Video
            apps.add(o["pkg"])
            out.append(o)
    return out


GENRE_NAMES = {"act": "Action", "ani": "Animation", "cmy": "Comedy", "crm": "Crime", "doc": "Documentary", "drm": "Drama",
               "eur": "European", "fml": "Family", "fnt": "Fantasy", "hrr": "Horror", "hst": "History", "msc": "Music",
               "rly": "Reality", "rma": "Romance", "scf": "Sci-Fi", "spt": "Sport", "trl": "Thriller", "war": "War",
               "wsn": "Western"}


def genre_name(code):
    """JustWatch's short genre code -> the word ("cmy" -> "Comedy")."""
    return GENRE_NAMES.get(code, code.title())


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
    where = []
    label = ""
    if offer:
        code = offer["package"]["shortName"]
        name, pkg = BY_CODE.get(code, (offer["package"].get("clearName", ""), ""))
        label = _label(offer, subscriptions())
    else:
        others = sorted({(o.get("package") or {}).get("clearName", "") for o in node.get("offers") or [] if o.get("monetizationType") in ("FLATRATE", "FREE", "ADS")})
        name, pkg = ("Not on your services" + (" (on %s)" % ", ".join(x for x in others if x)[:60] if others else "")), ""
        where = [x for x in others if x]
    year = c.get("originalReleaseYear") or ""
    kind = "Movie" if node.get("objectType") == "MOVIE" else "Show"
    genres = ", ".join(genre_name(g.get("shortName", "")) for g in (c.get("genres") or [])[:2])
    imdb = (c.get("scoring") or {}).get("imdbScore")
    backdrops = c.get("backdrops") or []
    title = c.get("title") or ""
    return {
        "source": "ondemand",
        "jw_id": node.get("id") or "",  # identity (map 5.4): a remake shares the name, never the id
        "service": name,
        "title": title,
        "year": year,
        "type": kind,
        "plot": c.get("shortDescription") or "",
        "poster": _img(c.get("posterUrl"), "s332"),
        "backdrop": _img(backdrops[0].get("backdropUrl"), "s1440") if backdrops else "",
        "meta": " • ".join(x for x in ((name + " · " + label) if label else name, kind, str(year), genres, ("IMDb %.1f" % imdb) if imdb else "") if x),
        "imdb": ("%.1f" % imdb) if imdb else "",
        "cast": ", ".join("%s (%s)" % (x["name"], x["characterName"]) if x.get("characterName") else x["name"]
                          for x in (c.get("credits") or []) if x.get("role") == "ACTOR")[:400],
        "director": ", ".join(x["name"] for x in (c.get("credits") or []) if x.get("role") == "DIRECTOR"),
        "runtime": ("%dh %02dm" % divmod(int(c["runtime"]), 60) if kind == "Movie" else "%d min episodes" % int(c["runtime"])) if c.get("runtime") else "",
        "certification": c.get("ageCertification") or "",
        "released": c.get("originalReleaseDate") or "",
        "season": node.get("season_name") or "",
        "genre_codes": [g.get("shortName") for g in (c.get("genres") or []) if g.get("shortName")],
        "offers": _offers(node.get("offers"), codes),
        "label": label,
        "where": where,  # not on your services: where it streams instead
        "playable": bool(pkg),
        "play": {"src": "ondemand", "pkg": pkg, "url": _link(offer), "name": name},
    }


def titles(codes=None, object_types=("MOVIE", "SHOW"), first=30, sort="POPULAR", genres=None):
    """Popular titles on these services; genres = JustWatch genre codes (any of them) for Browse."""
    codes = codes or installed_codes()
    if not codes:
        return []
    flt = {"packages": codes, "objectTypes": list(object_types)}
    if genres:
        flt["genres"] = list(genres)
    data = _post({"country": kodi.setting("region", "us").upper(), "language": "en", "first": first, "sort": sort,
                  "filter": flt})
    out, seen = [], set()
    for edge in ((data.get("popularTitles") or {}).get("edges") or []):
        item = _make(edge.get("node") or {}, codes)
        if item and (item["jw_id"] or item["title"]) not in seen:
            seen.add(item["jw_id"] or item["title"])
            out.append(item)
    return out


_CLASSICS = """
query Classics($country: Country!, $language: Language!, $first: Int!, $filter: TitleFilter, $after: String) {
  popularTitles(country: $country, first: $first, filter: $filter, sortBy: POPULAR, after: $after) {
    pageInfo { endCursor hasNextPage }
    edges { node {
      id objectType
      content(country: $country, language: $language) {
        title originalReleaseYear shortDescription posterUrl genres { shortName }
        backdrops { backdropUrl }
        scoring { imdbScore imdbVotes tmdbScore }
        externalIds { tmdbId imdbId }
        runtime ageCertification originalReleaseDate credits { name role characterName }
      }
      offers(country: $country, platform: ANDROID_TV) {
        monetizationType retailPrice(language: $language) standardWebURL deeplinkURL: deeplinkURL(platform: ANDROID_TV)
        package { packageId shortName clearName technicalName }
      }
    } }
  }
}
"""


def classic_movies(codes, year_min, year_max, pages=4, per_page=100):
    """The most popular movies from these years on these services (Rediscover's pool), cached 24 h.
    Each item also carries jw_id, imdb_votes, tmdb_score, tmdb_id and imdb_id."""
    if not codes:
        return []
    key = "jw:classics:%s:" % QV + json.dumps([sorted(codes), year_min, year_max, pages], sort_keys=True)
    nodes = cache.get(key, 24 * 3600)
    if nodes is None:
        nodes, after = [], None
        flt = {"objectTypes": ["MOVIE"], "packages": list(codes), "releaseYear": {"min": year_min, "max": year_max},
               "monetizationTypes": ["FLATRATE", "FREE", "ADS"]}
        for _ in range(pages):
            variables = {"country": kodi.setting("region", "us").upper(), "language": "en", "first": per_page,
                         "filter": flt, "after": after}
            body = json.dumps({"query": _CLASSICS, "variables": variables}).encode("utf-8")
            req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0 (Kodi SportsHub)"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    page = (json.loads(resp.read().decode("utf-8")).get("data") or {}).get("popularTitles") or {}
            except Exception as exc:
                kodi.log("justwatch classics failed: %s" % exc)
                break
            nodes += [e.get("node") or {} for e in page.get("edges") or []]
            after = (page.get("pageInfo") or {}).get("endCursor")
            if not (page.get("pageInfo") or {}).get("hasNextPage") or not after:
                break
        if nodes:
            cache.put(key, nodes)
        else:
            nodes = cache.get(key, 10 * 365 * 86400) or []
    out = []
    for node in nodes:
        item = _make(node, codes)
        if not item:
            continue
        c = node.get("content") or {}
        sc = c.get("scoring") or {}
        ext = c.get("externalIds") or {}
        item.update({"jw_id": node.get("id") or "", "imdb_votes": int(sc.get("imdbVotes") or 0),
                     "imdb_score": float(sc.get("imdbScore") or 0), "tmdb_score": float(sc.get("tmdbScore") or 0),
                     "tmdb_id": str(ext.get("tmdbId") or ""), "imdb_id": ext.get("imdbId") or ""})
        out.append(item)
    return out


_NEW = """
query New($country: Country!, $language: Language!, $date: Date!, $first: Int!) {
  newTitles(country: $country, date: $date, first: $first, filter: {packages: %s}) {
    edges { node {
      __typename id objectType
      content(country: $country, language: $language) { title originalReleaseYear shortDescription posterUrl genres { shortName } backdrops { backdropUrl } scoring { imdbScore } }
      offers(country: $country, platform: ANDROID_TV) { monetizationType retailPrice(language: $language) standardWebURL deeplinkURL: deeplinkURL(platform: ANDROID_TV) package { packageId shortName clearName technicalName } }
      ... on Season {
        show { id objectType
          content(country: $country, language: $language) { title originalReleaseYear shortDescription posterUrl genres { shortName } backdrops { backdropUrl } scoring { imdbScore } runtime ageCertification originalReleaseDate credits { name role characterName } }
          offers(country: $country, platform: ANDROID_TV) { monetizationType retailPrice(language: $language) standardWebURL deeplinkURL: deeplinkURL(platform: ANDROID_TV) package { packageId shortName clearName technicalName } }
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
            if item and (item["jw_id"] or item["title"]) not in seen:  # a show's new seasons are one card
                seen.add(item["jw_id"] or item["title"])
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


def row_items(index, svc=""):
    """Items for rows()[index]; `svc` (a JustWatch code) narrows the row to that one service."""
    rows_ = rows()
    if index < 0 or index >= len(rows_):
        return []
    label, kind, arg = rows_[index]
    codes = [svc] if svc else arg["codes"]
    if kind == "new":
        return new_titles(codes, object_types=tuple(arg["types"]))
    return titles(codes, tuple(arg["types"]), first=40, sort=arg.get("sort", "POPULAR"))


def short_name(code):
    """Display name for a service code (Prime channels already carry the short "(Prime)" form)."""
    return BY_CODE[code][0].replace(" channel)", ")")


_SEARCH = """
query Search($country: Country!, $language: Language!, $first: Int!, $filter: TitleFilter) {
  popularTitles(country: $country, first: $first, filter: $filter) {
    edges { node {
      id objectType
      content(country: $country, language: $language) { title originalReleaseYear shortDescription posterUrl genres { shortName } backdrops { backdropUrl } scoring { imdbScore } runtime ageCertification originalReleaseDate credits { name role characterName } }
      offers(country: $country, platform: ANDROID_TV) { monetizationType retailPrice(language: $language) standardWebURL deeplinkURL: deeplinkURL(platform: ANDROID_TV) package { packageId shortName clearName technicalName } }
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
    key = "jw:search16:%s:" % QV + json.dumps(flt, sort_keys=True)
    data = cache.get(key, TTL)
    if data is None:
        body = json.dumps({"query": _SEARCH, "variables": {"country": kodi.setting("region", "us").upper(), "language": "en", "first": 16, "filter": flt}}).encode("utf-8")
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
