"""Today's games, live scores and the network carrying each one, from ESPN's public
scoreboard JSON (schedule metadata only - no streams).

Each game knows its broadcasters ("Prime Video", "Apple TV", "FS1", "TNT", "ESPN+", "CBS"...),
which launcher.py turns into: your over-the-air PVR channel if you have one, else the app.
"""
import calendar
import time
from concurrent.futures import ThreadPoolExecutor

from resources.lib import cache, kodi, sports

API = "https://site.api.espn.com/apis/site/v2/sports/%s/scoreboard"
TTL = 3 * 60  # scores change; the background service keeps this warm anyway

# (slug, league id, display name, sport label)
LEAGUES = [
    ("football/nfl", "nfl", "NFL", "Football (NFL/College)"),
    ("football/college-football", "ncaaf", "College Football", "Football (NFL/College)"),
    ("basketball/nba", "nba", "NBA", "Basketball"),
    ("basketball/wnba", "wnba", "WNBA", "Basketball"),
    ("basketball/mens-college-basketball", "ncaab", "College Basketball", "Basketball"),
    ("baseball/mlb", "mlb", "MLB", "Baseball"),
    ("hockey/nhl", "nhl", "NHL", "Hockey"),
    ("soccer/usa.1", "mls", "MLS", "Soccer"),
    ("soccer/eng.1", "epl", "Premier League", "Soccer"),
    ("soccer/uefa.champions", "ucl", "Champions League", "Soccer"),
    ("golf/pga", "pga", "PGA Tour", "Golf"),
    ("racing/f1", "f1", "Formula 1", "Motorsport"),
    ("mma/ufc", "ufc", "UFC", "MMA / Combat"),
    ("tennis/atp", "atp", "ATP Tennis", "Tennis"),
    ("tennis/wta", "wta", "WTA Tennis", "Tennis"),
]
BY_ID = {lid: (slug, lid, name, sport) for slug, lid, name, sport in LEAGUES}

# Show games from this long ago (finished recently) to this far ahead.
PAST_S = 4 * 3600
FUTURE_S = 36 * 3600


def _epoch(iso):
    try:
        return calendar.timegm(time.strptime(iso[:16], "%Y-%m-%dT%H:%M"))
    except (ValueError, TypeError):
        return 0


def _fetch(slug):
    return cache.fetch_json(API % slug, TTL) or {}


def _networks(comp):
    names = []
    for b in comp.get("broadcasts") or []:
        for n in b.get("names") or []:
            if n and n not in names:
                names.append(n)
    for g in comp.get("geoBroadcasts") or []:
        n = (g.get("media") or {}).get("shortName")
        if n and n not in names and (g.get("market") or {}).get("type") != "Home" or not names:
            names.append(n)
    return names


def _make(lid, name, sport, ev):
    comp = (ev.get("competitions") or [{}])[0]
    status = (ev.get("status") or {}).get("type") or {}
    state = status.get("state") or "pre"  # pre | in | post
    start = _epoch(ev.get("date", ""))
    networks = _networks(comp)
    teams = comp.get("competitors") or []
    home = next((t for t in teams if t.get("homeAway") == "home"), teams[0] if teams else {})
    away = next((t for t in teams if t.get("homeAway") == "away"), teams[1] if len(teams) > 1 else {})
    title = ev.get("name") or ev.get("shortName") or ""
    score = ""
    if state != "pre" and home.get("score") not in (None, "") and away.get("score") not in (None, ""):
        score = "%s - %s" % (away.get("score"), home.get("score"))
    logo = (away.get("team") or {}).get("logo") or (home.get("team") or {}).get("logo")
    detail = status.get("shortDetail") or status.get("detail") or ""
    end = start + 3 * 3600 if start else 0
    if state == "post":
        end = min(end, int(time.time()))  # already over
    return {
        "source": "game",
        "service": name,
        "league": name,
        "league_id": lid,
        "channel_id": ev.get("id", ""),
        "channel": ", ".join(networks),
        "title": title,
        "short": ev.get("shortName") or "",
        "away_logo": (away.get("team") or {}).get("logo") or "",
        "away_abbr": (away.get("team") or {}).get("abbreviation") or "",
        "home_abbr": (home.get("team") or {}).get("abbreviation") or "",
        "home_logo": (home.get("team") or {}).get("logo") or "",
        "league_logo": "",
        "start": start,
        "end": end,
        "state": state,
        "detail": detail,
        "score": score,
        "sport": sports.classify(name, title) or sport,
        "logo": logo,
        "art": (home.get("team") or {}).get("logo"),
        "plot": "%s\n%s\nOn: %s\n%s" % (name, detail, ", ".join(networks) or "no broadcast listed",
                                        ((comp.get("venue") or {}).get("fullName") or "")),
        "playable": bool(networks),
        "play": {"src": "game", "channel": ", ".join(networks), "title": title},
    }


def games(league_ids=None, window=True):
    """Games for the given leagues (default all), live first, then by start time."""
    now = time.time()
    wanted = [BY_ID[l] for l in (league_ids or BY_ID) if l in BY_ID]
    with ThreadPoolExecutor(max_workers=6) as pool:
        payloads = list(pool.map(lambda l: (l, _fetch(l[0])), wanted))
    out = []
    for (slug, lid, name, sport), data in payloads:
        league_logo = ((data.get("leagues") or [{}])[0].get("logos") or [{}])[0].get("href") or ""
        for ev in data.get("events") or []:
            g = _make(lid, name, sport, ev)
            g["league_logo"] = league_logo
            if window and g["start"] and not (now - PAST_S <= g["start"] <= now + FUTURE_S) and g["state"] != "in":
                continue
            out.append(g)
    order = {"in": 0, "pre": 1, "post": 2}
    out.sort(key=lambda g: (order.get(g["state"], 1), g["start"]))
    return out


def counts():
    """{league_id: (name, total, live)} for the menu."""
    res = {}
    for g in games():
        name, total, live = res.get(g["league_id"], (g["league"], 0, 0))
        res[g["league_id"]] = (name, total + 1, live + (1 if g["state"] == "in" else 0))
    return res
