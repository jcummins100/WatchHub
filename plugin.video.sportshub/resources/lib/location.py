"""Where this Shield is, for "Your local stations" (setting local_market = "auto").

The service looks the location up from the internet connection (ipinfo.io, no account) at start and every
few hours, and picks the nearest TV market below; take the Shield to Texas and the guide's Local stations
follow it. The stations' call letters (KDKA, WPXI...) are learned from the guide itself: the local channels
the free services carry name the market ("CBS News Pittsburgh") and their shows carry the call letters
("KDKA News at 6"). Typing your own words in WatchHub settings turns all of this off.
"""
import json
import math
import os
import re
import time

from resources.lib import kodi

FILE = "location.json"
LOOKUP_EVERY = 6 * 3600
AUTO = "auto"

# TV markets: (the words local channels use for the market, latitude, longitude of its main city)
MARKETS = [
    ("Pittsburgh", 40.44, -80.00), ("Philadelphia", 39.95, -75.17), ("Harrisburg, Lancaster, York", 40.27, -76.88),
    ("Wilkes-Barre, Scranton", 41.25, -75.88), ("Johnstown, Altoona", 40.33, -78.92), ("Erie", 42.13, -80.09),
    ("Cleveland", 41.50, -81.69), ("Columbus", 39.96, -83.00), ("Cincinnati", 39.10, -84.51), ("Youngstown", 41.10, -80.65),
    ("Wheeling, Steubenville", 40.06, -80.72), ("Buffalo", 42.89, -78.88), ("Detroit", 42.33, -83.05),
    ("New York", 40.71, -74.01), ("Boston", 42.36, -71.06), ("Washington, DC", 38.91, -77.04), ("Baltimore", 39.29, -76.61),
    ("Chicago", 41.88, -87.63), ("Atlanta", 33.75, -84.39), ("Charlotte", 35.23, -80.84), ("Raleigh, Durham", 35.78, -78.64),
    ("Nashville", 36.16, -86.78), ("Indianapolis", 39.77, -86.16), ("St. Louis", 38.63, -90.20), ("Kansas City", 39.10, -94.58),
    ("Minneapolis, St. Paul", 44.98, -93.27), ("Milwaukee", 43.04, -87.91), ("Denver", 39.74, -104.99),
    ("Phoenix", 33.45, -112.07), ("Las Vegas", 36.17, -115.14), ("Los Angeles", 34.05, -118.24), ("San Diego", 32.72, -117.16),
    ("San Francisco, Oakland, San Jose", 37.77, -122.42), ("Sacramento", 38.58, -121.49), ("Seattle, Tacoma", 47.61, -122.33),
    ("Portland", 45.52, -122.68), ("Salt Lake City", 40.76, -111.89), ("Miami, Fort Lauderdale", 25.76, -80.19),
    ("Tampa, St. Petersburg", 27.95, -82.46), ("Orlando", 28.54, -81.38), ("Jacksonville", 30.33, -81.66),
    ("New Orleans", 29.95, -90.07), ("Memphis", 35.15, -90.05), ("Louisville", 38.25, -85.76), ("Oklahoma City", 35.47, -97.52),
    ("Tulsa", 36.15, -95.99), ("Albuquerque", 35.08, -106.65), ("Green Bay", 44.51, -88.01), ("Hartford, New Haven", 41.76, -72.69),
    ("Providence", 41.82, -71.41), ("Richmond", 37.54, -77.44), ("Norfolk", 36.85, -76.29), ("Birmingham", 33.52, -86.80),
    # Texas
    ("Dallas, Fort Worth", 32.78, -96.80), ("Houston", 29.76, -95.37), ("San Antonio", 29.42, -98.49), ("Austin", 30.27, -97.74),
    ("El Paso", 31.76, -106.49), ("Waco, Temple, Bryan", 31.55, -97.15), ("Corpus Christi", 27.80, -97.40),
    ("Lubbock", 33.58, -101.86), ("Amarillo", 35.22, -101.83), ("McAllen, Brownsville, Harlingen", 26.20, -98.23),
    ("Tyler, Longview", 32.35, -95.30), ("Beaumont, Port Arthur", 30.08, -94.13), ("Midland, Odessa", 31.99, -102.08),
    ("Abilene", 32.45, -99.73), ("Wichita Falls", 33.91, -98.49), ("San Angelo", 31.46, -100.44), ("Laredo", 27.51, -99.51),
]
NEAR_KM = 160
_CALLS = re.compile(r"\b[KW][A-Z]{3}\b")
_NOT_CALLS = {"WWE", "KIDS", "WEEK", "WILD", "KING", "WEST", "WINS", "WIFE", "KEYS", "KILL", "WALK", "WORK", "WAKE",
              "WHAT", "WHEN", "WITH", "WOOD", "WAVE", "WARS", "WILL", "KICK", "KNOW"}


def _path():
    return os.path.join(kodi.ensure_profile_dir(), FILE)


def load():
    try:
        with open(_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save(data):
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, _path())


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def nearest_market(lat, lon, city=""):
    """The market's words ("Dallas, Fort Worth"), or the city itself when no listed market is near."""
    best = min(MARKETS, key=lambda m: _km((lat, lon), (m[1], m[2])))
    return best[0] if _km((lat, lon), (best[1], best[2])) <= NEAR_KM else city


def detect(force=False):
    """Look up where the Shield is (at most every LOOKUP_EVERY). Run by the service, never while you wait."""
    data = load()
    if not force and time.time() - data.get("at", 0) < LOOKUP_EVERY:
        return data
    try:
        import urllib.request
        req = urllib.request.Request("https://ipinfo.io/json", headers={"User-Agent": "Kodi WatchHub", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        lat, lon = (float(x) for x in info["loc"].split(","))
        market = nearest_market(lat, lon, info.get("city", ""))
        if market != data.get("market"):
            kodi.log("location: %s, %s -> local market %s (was %s)" % (info.get("city"), info.get("region"), market, data.get("market") or "none"))
            data["calls"] = []   # learned again from this market's channels
        data.update(at=time.time(), city=info.get("city", ""), region=info.get("region", ""), market=market)
        _save(data)
    except Exception as exc:
        kodi.log("location lookup failed (keeping %s): %s" % (data.get("market") or "none", exc))
    return data


def market_words():
    """'Pittsburgh, KDKA, WPXI' style words for the current market, learned call letters included."""
    data = load()
    words = [w.strip() for w in (data.get("market") or "").split(",") if w.strip()]
    return words + [c for c in data.get("calls", []) if c not in words]


def learn_calls(channels):
    """channels: [(name, [programme titles])]. The call letters shown by the market's own channels (2+ times)."""
    words = [w.strip() for w in (load().get("market") or "").split(",") if w.strip()]
    if not words:
        return
    rx = re.compile(r"\b(%s)\b" % "|".join(re.escape(w) for w in words), re.I)
    seen = {}
    for name, titles in channels:
        if not rx.search(name or ""):
            continue
        for text, weight in [(name, 2)] + [(t, 1) for t in titles]:   # in the channel's own name: enough on its own
            for c in set(_CALLS.findall(text or "")):
                if c not in _NOT_CALLS:
                    seen[c] = seen.get(c, 0) + weight
    calls = sorted(c for c, n in seen.items() if n >= 2)
    data = load()
    if calls and calls != data.get("calls"):
        data["calls"] = calls
        _save(data)
        kodi.log("location: %s stations learned: %s" % (data.get("market"), ", ".join(calls)))


_STATUS = {"at": 0, "text": "", "title": ""}


def vpn_status(max_age=30):
    """(title, line) for the VPN button: is the internet connection a VPN (a data-centre address, which is what
    VPN servers use) and where does it put you. ip-api.com, no account; checked only while the button is
    highlighted. Kodi can't ask Android whether IPVanish is connected, so this is what the internet sees."""
    if time.time() - _STATUS["at"] < max_age and _STATUS["text"]:
        return _STATUS["title"], _STATUS["text"]
    try:
        import urllib.request
        url = "http://ip-api.com/json/?fields=status,city,regionName,isp,proxy,hosting"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Kodi WatchHub"}), timeout=6) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        where = ", ".join(x for x in (info.get("city"), info.get("regionName")) if x) or "somewhere unknown"
        if info.get("city") and info["city"] != load().get("city") and kodi.setting("local_market", "auto").strip().lower() == AUTO:
            detect(force=True)   # moved (a VPN switched on or off): local stations follow now, not in 6 hours
        if info.get("hosting") or info.get("proxy"):
            title, text = "VPN · on", "Connected: the internet sees you in %s. Apps and your local stations follow it." % where
        else:
            title, text = "VPN · off", "Not connected: you're on %s in %s. OK opens IPVanish." % (info.get("isp") or "your own internet", where)
    except Exception as exc:
        kodi.log("vpn status: %s" % exc)
        title, text = "VPN", "Couldn't check the connection right now. OK opens IPVanish."
    _STATUS.update(at=time.time(), title=title, text=text)
    return title, text
