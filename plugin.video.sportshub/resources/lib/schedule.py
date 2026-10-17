"""Sports calendar (Sports page > Schedules): a league's week of games, grouped by division (pro) or
conference (college), your teams first. ESPN's free scoreboard and standings; football by week, the
other leagues day by day."""
import time
from concurrent.futures import ThreadPoolExecutor

from resources.lib import cache, kodi
from resources.lib.sources import espn

BOARD = "https://site.api.espn.com/apis/site/v2/sports/%s/scoreboard"
STANDINGS = "https://site.api.espn.com/apis/v2/sports/%s/standings?%s"

# league id -> (label, standings query, scoreboard extra query, by week)
LEAGUES = {
    "nfl": ("NFL", "level=3", "", True),
    "ncaaf": ("College Football", "group=80", "groups=80&limit=300", True),
    "nba": ("NBA", "level=3", "", False),
    "ncaab": ("College Basketball", "group=50", "groups=50&limit=300", False),
    "mlb": ("MLB", "level=3", "", False),
    "nhl": ("NHL", "level=3", "", False),
}
ORDER = ["nfl", "ncaaf", "nba", "ncaab", "mlb", "nhl"]


def _short(name):
    """'American League East' -> 'AL East', 'Atlantic Division' -> 'Atlantic', 'Big Ten Conference' -> 'Big Ten'."""
    name = name.replace("American League", "AL").replace("National League", "NL")
    for tail in (" Division", " Conference"):
        if name.endswith(tail) and len(name) > len(tail) + 3:
            name = name[:-len(tail)]
    return name


def groups(lid):
    """[(group name, {team ids})] in ESPN's order: divisions (pro) or conferences (college)."""
    slug = espn.BY_ID[lid][0]
    data = cache.fetch_json(STANDINGS % (slug, LEAGUES[lid][1]), 86400) or {}
    out = []

    def walk(node):
        entries = (node.get("standings") or {}).get("entries") or []
        if entries:
            out.append((_short(node.get("name") or ""), {str((e.get("team") or {}).get("id")) for e in entries}))
        for kid in node.get("children") or []:
            walk(kid)
    for child in data.get("children") or []:
        walk(child)
    return out


def _local_midnight(t):
    lt = time.localtime(t)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def _events(lid, offset):
    """(events, label for the week) for this week + offset."""
    slug = espn.BY_ID[lid][0]
    extra = LEAGUES[lid][2]
    if LEAGUES[lid][3]:
        now = cache.fetch_json(BOARD % slug + ("?" + extra if extra else ""), 1800) or {}
        week = (now.get("week") or {}).get("number")
        stype = ((now.get("season") or {}).get("type") or 2)
        year = (now.get("season") or {}).get("year") or time.localtime().tm_year
        if not week:
            return [], "No games this week"
        w = max(1, week + offset)
        data = now if offset == 0 else (cache.fetch_json(BOARD % slug + "?seasontype=%s&week=%d&dates=%s%s" % (
            stype, w, year, "&" + extra if extra else ""), 1800) or {})
        evs = data.get("events") or []
        starts = sorted(espn._epoch(e.get("date", "")) for e in evs if e.get("date"))
        span = ("%s – %s" % (_day(starts[0]), _day(starts[-1]))) if starts else ""
        return evs, "Week %d%s" % (w, " · " + span if span else "")
    start = _local_midnight(time.time()) + offset * 7 * 86400
    days = [start + i * 86400 for i in range(7)]
    urls = [BOARD % slug + "?dates=%s%s" % (time.strftime("%Y%m%d", time.localtime(d)), "&" + extra if extra else "") for d in days]
    with ThreadPoolExecutor(max_workers=7) as pool:
        payloads = list(pool.map(lambda u: cache.fetch_json(u, 1800) or {}, urls))
    evs, seen = [], set()
    for p in payloads:
        for e in p.get("events") or []:
            if e.get("id") not in seen:
                seen.add(e.get("id"))
                evs.append(e)
    return evs, "%s – %s" % (_day(days[0]), _day(days[-1]))


def _day(t):
    return time.strftime("%a %b %d", time.localtime(t)).replace(" 0", " ")


def week(lid, offset=0):
    """{"title", "range", "groups": [(name, [game, ...])]} - a game is listed under both teams' groups."""
    label, _, _, _ = LEAGUES[lid]
    slug, _, name, sport = espn.BY_ID[lid]
    evs, rng = _events(lid, offset)
    grp = groups(lid)
    mine = {abbr for l, abbr in espn.my_teams() if l == lid}
    games = []
    for ev in evs:
        g = espn._make(lid, name, sport, ev)
        comp = (ev.get("competitions") or [{}])[0]
        g["team_ids"] = {str((c.get("team") or {}).get("id")) for c in comp.get("competitors") or []}
        g["mine"] = bool(mine & {g["home_abbr"].upper(), g["away_abbr"].upper()})
        games.append(g)
    games.sort(key=lambda g: g["start"])
    out = []
    yours = [g for g in games if g["mine"]]
    if yours:
        out.append(("Your teams", yours))
    out.append(("All games", games))
    for gname, ids in grp:
        gl = [g for g in games if g["team_ids"] & ids]
        if gl:
            out.append((gname, gl))
    kodi.log("schedule: %s %s - %d games, %d groups" % (lid, rng, len(games), len(out)))
    return {"title": label, "range": rng, "groups": out}
