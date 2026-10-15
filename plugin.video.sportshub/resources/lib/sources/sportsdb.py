"""TheSportsDB free API (v1, public test key). Schedule + TV listings only; no streams.

Free tier: 30 requests/minute, so everything is cached for a while.
https://www.thesportsdb.com/documentation
"""
import calendar
import time

from resources.lib import cache, kodi, sports

TTL = 30 * 60


def _api():
    key = kodi.setting("sportsdb_key", "").strip() or "123"
    return "https://www.thesportsdb.com/api/v1/json/%s/" % key

# Country names TheSportsDB uses for TV listings, keyed by our region setting.
_REGION_COUNTRY = {"us": "United States", "ca": "Canada", "gb": "United Kingdom"}


def _today_dates():
    """Local today and tomorrow as YYYY-MM-DD (the API is UTC-dated, so fetch both)."""
    t = time.time()
    return [time.strftime("%Y-%m-%d", time.gmtime(t)), time.strftime("%Y-%m-%d", time.gmtime(t + 86400))]


def _epoch(ev):
    ts = ev.get("strTimestamp") or ev.get("strTimeStamp")
    if ts:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return calendar.timegm(time.strptime(ts[:19], fmt))
            except ValueError:
                pass
    d, t = ev.get("dateEvent"), (ev.get("strTime") or "00:00:00")[:8]
    if d:
        try:
            return calendar.timegm(time.strptime("%s %s" % (d, t), "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            pass
    return 0


def _make(ev, channel):
    title = ev.get("strEvent") or "%s vs %s" % (ev.get("strHomeTeam", "?"), ev.get("strAwayTeam", "?"))
    start = _epoch(ev)
    sport_name = ev.get("strSport") or ""
    league = ev.get("strLeague") or ""
    return {
        "source": "sportsdb",
        "service": "TV schedule",
        "channel_id": ev.get("idEvent", ""),
        "channel": channel or league or sport_name,
        "title": title,
        "start": start,
        "end": start + 3 * 3600 if start else 0,
        "sport": sports.classify(sport_name, league, title) or sport_name or None,
        "league": league,
        "logo": ev.get("strLogo") or ev.get("strLeagueBadge") or ev.get("strThumb"),
        "art": ev.get("strThumb") or ev.get("strPoster") or ev.get("strLogo"),
        "plot": "%s - %s\n%s" % (sport_name, league, ev.get("strVenue") or ""),
        "playable": False,  # we don't know which app carries it; the UI offers PVR match / search
        "play": {"src": "sportsdb", "channel": channel or "", "title": title},
    }


def tv_today():
    """Events on TV today in the configured region, soonest first."""
    country = _REGION_COUNTRY.get(kodi.setting("region", "us"), "United States")
    out = []
    for d in _today_dates():
        data = cache.fetch_json(_api() + "eventstv.php?d=%s" % d, TTL) or {}
        for ev in data.get("tvevents") or []:
            if (ev.get("strCountry") or "") not in ("", country):
                continue
            out.append(_make(ev, ev.get("strChannel")))
    # The same event is listed once per channel; merge channels per event.
    merged = {}
    for p in out:
        key = p["channel_id"] or p["title"]
        if key in merged:
            chans = merged[key]["channel"].split(", ")
            if p["channel"] not in chans:
                merged[key]["channel"] = ", ".join(chans + [p["channel"]])
        else:
            merged[key] = p
    res = sorted(merged.values(), key=lambda p: p["start"])
    now = time.time()
    return [p for p in res if p["end"] == 0 or p["end"] > now - 3600]


def events_for_sport(sport_name):
    """Today's events for one TheSportsDB sport name (e.g. 'Soccer', 'American Football')."""
    out = []
    for d in _today_dates():
        data = cache.fetch_json(_api() + "eventsday.php?d=%s&s=%s" % (d, sport_name.replace(" ", "%20")), TTL) or {}
        for ev in data.get("events") or []:
            out.append(_make(ev, ev.get("strChannel")))
    out.sort(key=lambda p: p["start"])
    return out
