"""Map TV network / streaming service names to Android TV apps on the Shield.

Used when a schedule entry says "on ESPN" / "on Prime Video" and there's no matching
Kodi PVR channel: we launch the app that carries it (you still need your own subscription).
"""
import re

# (regex over the network/service name, Android package, friendly name)
_APPS = [
    (r"prime video|amazon", "com.amazon.amazonvideo.livingroom", "Prime Video"),
    (r"apple tv|mls season pass", "com.apple.atve.androidtv.appletv", "Apple TV"),
    (r"\bhulu\b", "com.hulu.livingroomplus", "Hulu"),
    (r"peacock|\bnbc|\busa\b|golf ch|\bcnbc\b|telemundo|universo", "com.peacocktv.peacockandroid", "Peacock"),
    (r"trutv|\btru\b", "com.turner.trutv", "truTV"),
    (r"paramount|\bcbs|golazo", "com.cbs.ott", "Paramount+"),
    (r"\bespn|\babc\b|\bsec ?n|\bacc ?n|longhorn", "com.espn.score_center", "ESPN"),
    (r"\bmax\b|\btnt\b|\btbs\b|trutv|b/r", "com.wbd.stream", "Max"),
    (r"\bfox|fs1|fs2|big ten|\bbtn\b", "com.fox.foxone", "FOX One"),
    (r"\bdazn\b", "com.dazn", "DAZN"),
    (r"nfl\+|nfl net|nfl redzone|nfl ?n\b", "com.gotv.nflgamecenter.us.lite", "NFL"),
    (r"nba tv|nba league pass|nba app", "com.nbaimd.gametime.nba2011", "NBA"),
    (r"mlb\.tv|mlb network|mlb app", "com.bamnetworks.mobile.android.gameday.atbat", "MLB"),
    (r"nhl network|nhl\.tv|espn\+", "com.espn.score_center", "ESPN"),
    (r"youtube tv", "com.google.android.youtube.tvunplugged", "YouTube TV"),
    (r"youtube", "com.google.android.youtube.tv", "YouTube"),
    (r"fubo", "com.fubo.firetv.screen", "Fubo"),
    (r"sling", "com.sling", "Sling TV"),
    (r"directv", "com.att.tv", "DIRECTV"),
    (r"pluto", "tv.pluto.android", "Pluto TV"),
    (r"tubi", "com.tubitv", "Tubi"),
    (r"\bthe cw\b|\bcw\b", "com.cw.fullepisodes.android", "The CW"),
    (r"xumo", "com.xumo.xumo.tv", "Xumo Play"),
    (r"roku", "com.roku.web.trc", "The Roku Channel"),
    (r"plex", "com.plexapp.android", "Plex"),
    (r"\bf1 ?tv\b", "com.formulaone.production", "F1 TV"),
    (r"flo(sports|racing|wrestling|hoops)?", "tv.flosports", "FloSports"),
    (r"bally|fanduel sports", "com.fanduel.sportsnetwork", "FanDuel Sports Network"),
    (r"nesn|msg|yes network|sny|marquee|altitude|monumental|space city|victory\+", None, None),  # RSNs: varies
]
APPS = [(re.compile(rx, re.I), pkg, name) for rx, pkg, name in _APPS]


def for_network(name):
    """Return (package, friendly_name) for a network/service string, or (None, None)."""
    if not name:
        return None, None
    for rx, pkg, friendly in APPS:
        if rx.search(name):
            if pkg == "com.cbs.ott":
                return _paramount_via_prime(pkg, friendly)
            return pkg, friendly
    return None, None


def _paramount_via_prime(pkg, friendly):
    """CBS / Paramount+: no Paramount+ app, but Paramount+ comes through Prime Video (Prime channel 'app')
    -> Prime Video, where the channel's live CBS station is under Live TV."""
    try:
        from resources.lib import health, kodi
        if health.app_installed(pkg) is False and "app" in [x.strip() for x in kodi.setting("amazon_channels").split(",")]:
            return "com.amazon.amazonvideo.livingroom", "Paramount+ (Prime Video)"
    except Exception:
        pass
    return pkg, friendly


# Apps worth a tile on the home screen, in display order (only shown when installed).
LAUNCHABLE = [
    ("Netflix", "com.netflix.ninja"), ("Prime Video", "com.amazon.amazonvideo.livingroom"),
    ("Apple TV", "com.apple.atve.androidtv.appletv"), ("Hulu", "com.hulu.livingroomplus"),
    ("Peacock", "com.peacocktv.peacockandroid"), ("YouTube", "com.google.android.youtube.tv"),
    ("ESPN", "com.espn.score_center"), ("FOX One", "com.fox.foxone"), ("FOX Sports", "com.foxsports.android"),
    ("NBC Sports", "com.nbcsports.apps.tv"), ("truTV", "com.turner.trutv"), ("FloSports", "tv.flosports"),
    ("Pluto TV", "tv.pluto.android"), ("Plex", "com.plexapp.android"), ("The Roku Channel", "com.roku.web.trc"),
    ("Tubi", "com.tubitv"), ("Xumo Play", "com.xumo.xumo.tv"), ("The CW", "com.cw.fullepisodes.android"),
    ("Freevee", "com.imdbtv.livingroom"), ("Google TV", "com.google.android.videos"),
    ("Fox Nation", "com.fng.foxnation"), ("Fox News", "com.foxnews.android"),
    ("Paramount+", "com.cbs.ott"), ("Max", "com.wbd.stream"), ("Disney+", "com.disney.disneyplus"), ("DAZN", "com.dazn"),
    ("NFL", "com.gotv.nflgamecenter.us.lite"), ("NBA", "com.nbaimd.gametime.nba2011"),
    ("MLB", "com.bamnetworks.mobile.android.gameday.atbat"), ("YouTube TV", "com.google.android.youtube.tvunplugged"),
    ("Fubo", "com.fubo.firetv.screen"), ("Sling TV", "com.sling"), ("F1 TV", "com.formulaone.production"),
    ("Steam Link", "com.valvesoftware.steamlink"), ("UniFi Protect", "com.ubnt.unifi.protect"),
]
