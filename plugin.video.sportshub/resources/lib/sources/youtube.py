"""Official league / broadcaster YouTube channels that regularly stream free live events.

Opened in the YouTube Android TV app on the Shield (no API key or Kodi YouTube add-on needed).
"""
CHANNELS = [
    ("NFL", "@NFL", "Football (NFL/College)"),
    ("NBA", "@NBA", "Basketball"),
    ("MLB", "@MLB", "Baseball"),
    ("NHL", "@NHL", "Hockey"),
    ("PGA TOUR", "@PGATOUR", "Golf"),
    ("LIV Golf", "@LIVGolf", "Golf"),
    ("FIFA", "@FIFA", "Soccer"),
    ("MLS", "@MLS", "Soccer"),
    ("UFC", "@UFC", "MMA / Combat"),
    ("DAZN Boxing", "@DAZNBoxing", "Boxing"),
    ("WWE", "@WWE", "Wrestling"),
    ("NASCAR", "@NASCAR", "Motorsport"),
    ("FORMULA 1", "@Formula1", "Motorsport"),
    ("IndyCar", "@INDYCAR", "Motorsport"),
    ("World Surf League", "@wsl", "Surf / Outdoor"),
    ("Olympics", "@Olympics", "Olympics / Team USA"),
    ("ESPN", "@ESPN", "Multi-sport"),
    ("CBS Sports", "@CBSSports", "Multi-sport"),
    ("FOX Sports", "@FOXSports", "Multi-sport"),
]

PACKAGE = "com.google.android.youtube.tv"


def items():
    out = []
    for name, handle, sport in CHANNELS:
        out.append({
            "source": "youtube",
            "service": "YouTube",
            "channel_id": handle,
            "channel": name,
            "title": "%s - live streams" % name,
            "start": 0,
            "end": 0,
            "sport": sport,
            "logo": None,
            "art": None,
            "plot": "Opens the %s channel's live streams tab in the YouTube app." % name,
            "playable": True,
            "play": {"src": "youtube", "id": handle, "name": name},
        })
    return out


def url_for(handle):
    return "https://www.youtube.com/%s/streams" % handle
