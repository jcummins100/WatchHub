"""Free ad-supported TV (FAST) services: Pluto TV, Plex, The Roku Channel, Samsung TV Plus.

Guide data comes from the public channel/EPG JSON published at i.mjh.nz (metadata only,
no stream URLs). Playback is done by launching the service's official Android TV app.
"""
import re
import time

from resources.lib import cache, kodi, sports

SERVICES = {
    "pluto": {
        "name": "Pluto TV",
        "url": "https://i.mjh.nz/PlutoTV/.channels.json",
        "layout": "regions",  # regions -> {region: {channels: {...}}}
        "package": "tv.pluto.android",
        "deeplink": "https://pluto.tv/live-tv/{id}",
        "setting": "src_pluto",
        "color": "FFFFD700",
    },
    "plex": {
        "name": "Plex",
        "url": "https://i.mjh.nz/Plex/.channels.json",
        "layout": "flat",  # channels -> {id: {regions: [...]}}
        "package": "com.plexapp.android",
        "deeplink": "https://watch.plex.tv/live-tv/channel/{slug}",  # verified on the Shield: opens the channel
        "setting": "src_plex",
        "color": "FFE5A00D",
    },
    "roku": {
        "name": "The Roku Channel",
        "url": "https://i.mjh.nz/Roku/.channels.json",
        "layout": "flat",
        "package": "com.roku.web.trc",
        "deeplink": "roku://trc/watch/{id}",  # verified on the Shield (FOX Sports, ALF)
        "setting": "src_roku",
        "color": "FF6F1AB1",
    },
    "samsung": {
        "name": "Samsung TV Plus",
        "url": "https://i.mjh.nz/SamsungTVPlus/.channels.json",
        "layout": "regions",
        "package": None,  # no Shield app
        "deeplink": None,
        "setting": "src_samsung",
        "color": "FF1428A0",
    },
}


def enabled_services():
    return [sid for sid, s in SERVICES.items() if kodi.setting_bool(s["setting"], sid != "samsung")]


def _cache_ttl():
    return max(10, kodi.setting_int("cache_minutes", 60)) * 60


def _mirrors(url):
    # The gzipped copy is served separately; it survives when the plain file is mid-regeneration.
    return [url + ".gz"]


def _load(sid):
    svc = SERVICES[sid]
    data = cache.fetch_json(svc["url"], _cache_ttl(), mirrors=_mirrors(svc["url"]))
    if not data:
        return {}
    region = kodi.setting("region", "us")
    out = {}
    if svc["layout"] == "regions":
        regions = data.get("regions", {})
        reg = regions.get(region) or regions.get("all") or regions.get("us") or {}
        out = reg.get("channels", {})
    else:
        for cid, ch in data.get("channels", {}).items():
            regs = ch.get("regions")
            if not regs or region in regs:
                out[cid] = ch
    return out


def channels(sid, sports_only=True):
    """Return [(channel_id, channel_dict)] for a service, sports channels first/only."""
    result = []
    for cid, ch in _load(sid).items():
        groups = ch.get("groups") or ch.get("group")
        if sports_only and not sports.is_sports_channel(ch.get("name", ""), groups):
            continue
        result.append((cid, ch))
    result.sort(key=lambda c: c[1].get("name", "").lower())
    return result


def _programme_at(programs, when):
    """Return (start, end, title) of the programme airing at `when`, or None."""
    if not programs:
        return None
    prev = None
    for entry in programs:
        try:
            start, title = int(entry[0]), str(entry[1])
        except (TypeError, ValueError, IndexError):
            continue
        if start > when:
            if prev is None:
                return None
            return prev[0], start, prev[1]
        prev = (start, title)
    if prev is not None:
        return prev[0], prev[0] + 3600, prev[1]  # last known programme; assume an hour
    return None


def _programmes_window(programs, start_after, start_before):
    """Return [(start, end, title)] for programmes starting within the window."""
    out = []
    items = []
    for entry in programs or []:
        try:
            items.append((int(entry[0]), str(entry[1])))
        except (TypeError, ValueError, IndexError):
            continue
    for i, (start, title) in enumerate(items):
        if start_after <= start <= start_before:
            end = items[i + 1][0] if i + 1 < len(items) else start + 3600
            out.append((start, end, title))
    return out


def _make(sid, cid, ch, start, end, title):
    svc = SERVICES[sid]
    name = ch.get("name", "")
    sport = sports.classify(name, title)
    play = {"src": sid, "id": cid, "name": name}
    return {
        "source": sid,
        "service": svc["name"],
        "channel_id": cid,
        "channel": name,
        "title": title,
        "start": start,
        "end": end,
        "sport": sport,
        "logo": ch.get("logo"),
        "art": ch.get("art") or ch.get("fanart") or ch.get("logo"),
        "plot": ch.get("description", ""),
        "playable": bool(svc["package"]) and kodi.is_android(),
        "play": play,
    }


def live_now(now=None):
    now = now or int(time.time())
    out = []
    for sid in enabled_services():
        for cid, ch in channels(sid):
            p = _programme_at(ch.get("programs"), now)
            if p:
                out.append(_make(sid, cid, ch, p[0], p[1], p[2]))
            else:
                out.append(_make(sid, cid, ch, 0, 0, ch.get("name", "")))
    return dedupe(out)


def starting_soon(minutes, now=None):
    now = now or int(time.time())
    out = []
    for sid in enabled_services():
        for cid, ch in channels(sid):
            for start, end, title in _programmes_window(ch.get("programs"), now + 1, now + minutes * 60):
                out.append(_make(sid, cid, ch, start, end, title))
    out.sort(key=lambda p: p["start"])
    # same programme on the same channel via several services -> one entry
    seen = {}
    merged = []
    for p in out:
        key = (_norm(p["channel"]), p["title"], p["start"] // 300)
        if key in seen:
            seen[key].setdefault("alts", []).append({"service": p.get("service"), "play": p["play"]})
            continue
        p["alts"] = []
        seen[key] = p
        merged.append(p)
    return merged


def channel_schedule(sid, cid, hours=24, now=None):
    now = now or int(time.time())
    ch = _load(sid).get(cid)
    if not ch:
        return None, []
    items = []
    current = _programme_at(ch.get("programs"), now)
    if current:
        items.append(_make(sid, cid, ch, current[0], current[1], current[2]))
    for start, end, title in _programmes_window(ch.get("programs"), now + 1, now + hours * 3600):
        items.append(_make(sid, cid, ch, start, end, title))
    return ch, items


def _group_names(ch):
    g = ch.get("groups") or ch.get("group") or []
    return [str(x) for x in (g if isinstance(g, list) else [g]) if x]


def groups():
    """[(group, channel_count)] across enabled services, excluding sports (that's the rest of the hub)."""
    counts = {}
    for sid in enabled_services():
        for cid, ch in _load(sid).items():
            for g in _group_names(ch):
                if "sport" in g.lower():
                    continue
                counts[g] = counts.get(g, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def live_now_group(group, now=None):
    now = now or int(time.time())
    out = []
    for sid in enabled_services():
        for cid, ch in _load(sid).items():
            if group not in _group_names(ch):
                continue
            p = _programme_at(ch.get("programs"), now)
            out.append(_make(sid, cid, ch, p[0], p[1], p[2]) if p else _make(sid, cid, ch, 0, 0, ch.get("name", "")))
    out.sort(key=lambda p: (p["source"], p["channel"].lower()))
    return dedupe(out)


# ---------------------------------------------------------------- de-duplication
_NOISE = re.compile(r"\b(channel|network|tv|the|hd|live|plus|\+|on pluto|by [a-z]+)\b|[^a-z0-9 ]")


def _norm(name):
    n = _NOISE.sub(" ", (name or "").lower().replace("&", " and "))
    return " ".join(n.split())


def service_priority():
    """Service order used to pick the default stream for a channel found on several services."""
    pref = kodi.setting("service_priority", "pluto,plex,roku,samsung")
    order = [x.strip() for x in pref.split(",") if x.strip() in SERVICES]
    return order + [sid for sid in SERVICES if sid not in order]


def dedupe(items):
    """Merge programmes whose channel names match across services; keep the preferred service's
    entry and list the others under 'alts' (the UI offers them on the context menu)."""
    prio = {sid: i for i, sid in enumerate(service_priority())}
    groups = {}
    order = []
    for p in items:
        key = _norm(p["channel"])
        if not key:
            key = p["channel_id"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)
    out = []
    for key in order:
        cands = sorted(groups[key], key=lambda p: (not p.get("playable"), prio.get(p["source"], 99)))
        best = dict(cands[0])
        best["alts"] = [{"service": c.get("service"), "play": c["play"]} for c in cands[1:] if c["source"] != best["source"]]
        out.append(best)
    return out
