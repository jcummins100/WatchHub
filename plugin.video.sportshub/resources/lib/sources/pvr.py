"""Kodi PVR channels (HDHomeRun, IPTV Simple Client, etc.) via JSON-RPC.

Anything the user has set up in Kodi's own Live TV shows up here; we just filter it
to sports using the EPG genre and our keyword rules, and play natively.
"""
import calendar
import time

from resources.lib import kodi, sports

_PROPS = ["channel", "thumbnail", "channelnumber", "broadcastnow", "broadcastnext", "hidden"]


def available():
    res = kodi.jsonrpc("PVR.GetProperties", {"properties": ["available"]})
    return bool(res and res.get("available"))


def _epoch(s):
    """Kodi returns broadcast times as 'YYYY-MM-DD HH:MM:SS' in local time."""
    if not s:
        return 0
    try:
        return int(time.mktime(time.strptime(s[:19], "%Y-%m-%d %H:%M:%S")))
    except (ValueError, OverflowError):
        return 0


def _channels():
    res = kodi.jsonrpc("PVR.GetChannels", {"channelgroupid": "alltv", "properties": _PROPS})
    return (res or {}).get("channels") or []


def _make(ch, bc, sport):
    title = (bc or {}).get("title") or ch.get("label", "")
    return {
        "source": "pvr",
        "service": "Live TV",
        "channel_id": str(ch.get("channelid")),
        "channel": ch.get("label", ""),
        "title": title,
        "start": _epoch((bc or {}).get("starttime")),
        "end": _epoch((bc or {}).get("endtime")),
        "sport": sport,
        "logo": ch.get("thumbnail"),
        "art": ch.get("thumbnail"),
        "plot": (bc or {}).get("plot") or "",
        "playable": True,
        "play": {"src": "pvr", "id": ch.get("channelid"), "name": ch.get("label", "")},
    }


def _is_sport(ch, bc):
    genre = " ".join((bc or {}).get("genre") or []) if isinstance((bc or {}).get("genre"), list) else str((bc or {}).get("genre") or "")
    if "sport" in genre.lower():
        return sports.classify(ch.get("label", ""), (bc or {}).get("title", "")) or "Multi-sport"
    return sports.classify(ch.get("label", ""), (bc or {}).get("title", ""))


def live_now(all_channels=False):
    out = []
    for ch in _channels():
        if ch.get("hidden"):
            continue
        bc = ch.get("broadcastnow") or {}
        sport = _is_sport(ch, bc)
        if sport or all_channels:
            out.append(_make(ch, bc, sport))
    return out


def starting_soon(minutes):
    now = time.time()
    out = []
    for ch in _channels():
        if ch.get("hidden"):
            continue
        bc = ch.get("broadcastnext") or {}
        if not bc:
            continue
        start = _epoch(bc.get("starttime"))
        if now < start <= now + minutes * 60:
            sport = _is_sport(ch, bc)
            if sport:
                out.append(_make(ch, bc, sport))
    out.sort(key=lambda p: p["start"])
    return out


def find_channel(name):
    """Best-effort match of a TV network name (e.g. 'FOX', 'CBS') to a PVR channel id."""
    if not name:
        return None
    needle = name.lower().replace("-", " ").split("(")[0].strip()
    best = None
    for ch in _channels():
        label = ch.get("label", "").lower()
        if label == needle:
            return ch.get("channelid")
        if needle in label or label in needle:
            best = best or ch.get("channelid")
    return best
