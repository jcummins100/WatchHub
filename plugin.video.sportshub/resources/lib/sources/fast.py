"""Free ad-supported TV (FAST) services: Pluto TV, Plex, The Roku Channel, Samsung TV Plus.

Guide data comes from the public channel/EPG JSON published at i.mjh.nz (metadata only,
no stream URLs). Playback is done by launching the service's official Android TV app.
"""
import json
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
    "tubi": {
        "name": "Tubi",
        "url": "tubi:",            # lineup shipped in resources/data/tubi_channels.json; schedules fetched live
        "layout": "tubi",
        "package": "com.tubitv",
        "deeplink": "https://tubitv.com/live/{id}",  # verified on the Shield: tunes the channel (NFL Channel)
        "setting": "src_tubi",
        "color": "FFFA382F",
    },
    "xumo": {
        "name": "Xumo Play",
        "url": "xumo:",
        "layout": "xumo",
        "package": "com.xumo.xumo.tv",
        # Xumo's app reads deepLinkType/channelId from www.xumo.tv links, but only when the link has a path
        # (it ignores "https://www.xumo.tv/?..."); channel_no_ui plays the channel full screen (verified on
        # the Shield Pro, Oct 16: Saved by the Bell)
        "deeplink": "https://www.xumo.tv/live?deepLinkType=channel_no_ui&channelId={id}",
        "setting": "src_xumo",
        "color": "FF7B2FF7",
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


# Spanish-language channels: Pluto files them under "En Español"; Plex and Roku only say so in the name
SPANISH_GROUP = re.compile(r"espa[nñ]ol", re.I)
SPANISH_NAME = re.compile(r"espa[nñ]ol|\blatino|telemundo|univisi[oó]n|unim[aá]s|galavisi[oó]n|tudn|azteca|televisa|estrella|caracol"
                          r"|\bnoticias\b|\bdeportes\b|\bnovelas?\b|telenovela|\bcine\b|\ben vivo\b|\bn\+", re.I)


SPANISH_NAME_EXTRA = re.compile(r"\bvix\b|\ben alerta\b|cr[ií]menes|pel[ií]culas|cl[aá]sicos?\b|misterios|\bseries gratis\b|\bconcursos\b"
                                r"|freetv (banda|estelar|acci|cl[aá]sico|drama|familia|hits|horror|sure)|\bdelito\b|\bconflicto\b|entravision"
                                r"|americatev|buen viaje|autopista al cielo|\bnovelas?\b|como dice el dicho|\bpelimex\b|\btelevisa\b"
                                r"|novel[ií]sima|\bmi casa\b|\blatv\b|\bwapa\b|caso cerrado|\brebelde\b|vas o no vas|reino infantil|\bcanela\b"
                                r"|\bacci[oó]n\b|\bcorazón\b|\bnaturaleza\b|\bverdaderos\b|\bsalvaje\b|\blatinus\b|hispanic favorites|\blatinx\b|\blucha plus\b|addictatv|^clic$|freetv live|mera mera", re.I)
# words that are common in Spanish titles and rare in English ones; accents/ñ/¿¡ count too
# (é is left out: English uses it too - Pokémon, café; so are lone "el"/"de"/"la")
SPANISH_WORDS = re.compile(r"[ñ¿¡]|[áíóú]\w|\b(del|los|las|y|con|para|una|por|que|en vivo|cuando|familia|historia|noche)\b", re.I)
# place and people names that look Spanish inside English titles
SPANISH_NAMES_IN_ENGLISH = re.compile(r"\b(los angeles|las vegas|el paso|el dorado|el camino|de la hoya|san \w+|santa \w+|la la land)\b", re.I)


def is_spanish(ch):
    if any(SPANISH_GROUP.search(g) for g in _group_names(ch)):
        return True
    name = ch.get("name", "")
    if SPANISH_NAME.search(name) or SPANISH_NAME_EXTRA.search(name):
        return True
    # Plex has no genres, so a name in Spanish ("Crímenes Verdaderos", "Historias de Corazón") is the best sign
    if SPANISH_WORDS.search(SPANISH_NAMES_IN_ENGLISH.sub("", name)):
        return True
    # no label at all (Plex/Roku): judge by what it airs from now on - but only with enough evidence
    # (3+ different titles, 60%+ clearly Spanish); when unsure, the channel stays visible
    now = time.time()
    titles = []
    for entry in sorted(ch.get("programs") or [], key=lambda e: e[0] if e and isinstance(e[0], (int, float)) else 0):
        try:
            start, title = int(entry[0]), str(entry[1])
        except (IndexError, TypeError, ValueError):
            continue
        if start + 4 * 3600 >= now and title not in titles:  # recent/upcoming, a marathon counts once
            titles.append(title)
        if len(titles) >= 12:
            break
    if len(titles) < 3:
        return False
    titles = [SPANISH_NAMES_IN_ENGLISH.sub(" ", t) for t in titles]
    return sum(1 for t in titles if SPANISH_WORDS.search(t)) / len(titles) >= 0.6


def enabled_services():
    """Services switched on in settings whose app is on this device (or can't be checked).

    A channel whose app is definitely missing would only lead to the Play Store, so it's left out
    of every row, list and "Watch on" choice rather than shown.
    """
    from resources.lib import health

    return [sid for sid, s in SERVICES.items() if kodi.setting_bool(s["setting"], sid != "samsung")
            and (not s["package"] or health.app_installed(s["package"]) is not False)]


def _cache_ttl():
    return max(10, kodi.setting_int("cache_minutes", 60)) * 60


def _mirrors(url):
    # The gzipped copy is served separately; it survives when the plain file is mid-regeneration.
    return [url + ".gz"]


TUBI_EPG = "https://epg-cdn.production-public.tubi.io/content/epg/programming?platform=web&lookahead=1&content_id="


def _load_tubi():
    """Tubi's live channels in the same shape as the i.mjh.nz files: {id: {name, logo, groups, programs}}.

    Tubi's channel list needs a signed-in browser session, so WatchHub ships the lineup (ids, names,
    Tubi's categories) and refreshes it with each release; the schedules come from Tubi's public EPG,
    25 channels per request, cached like every other guide file."""
    import calendar
    import os
    try:
        with open(os.path.join(kodi.ADDON_PATH, "resources", "data", "tubi_channels.json"), encoding="utf-8") as fh:
            lineup = json.load(fh).get("channels") or []
    except (OSError, ValueError):
        return {}
    out = {}
    ids = [c["id"] for c in lineup if not c.get("needs_login")]
    meta = {c["id"]: c for c in lineup}
    for k in range(0, len(ids), 25):
        data = cache.fetch_json(TUBI_EPG + ",".join(ids[k:k + 25]), _cache_ttl()) or {}
        for row in data.get("rows") or []:
            cid = str(row.get("content_id") or "")
            if cid not in meta:
                continue
            progs = []
            for p in row.get("programs") or []:
                try:
                    start = calendar.timegm(time.strptime(p["start_time"][:19], "%Y-%m-%dT%H:%M:%S"))
                except (KeyError, ValueError, TypeError):
                    continue
                progs.append([start, p.get("title") or ""])
            imgs = row.get("images") or {}
            logo = next((v[0] if isinstance(v, list) else v for k2 in ("custom", "landscape", "hero") for v in [imgs.get(k2)] if v), "")
            out[cid] = {"name": meta[cid]["name"], "logo": logo, "groups": meta[cid].get("groups") or [], "programs": progs}
    return out


XUMO_API = "https://valencia-app-mds.xumo.com/v2/"
XUMO_GEO = "10006"   # Xumo's US lineup


def _load_xumo():
    """Xumo Play's channels with the next ~12 hours: channel list (names, genres) + the EPG grid in 6-hour blocks,
    50 channels per page, titles included (f=asset.title)."""
    import calendar
    lst = cache.fetch_json(XUMO_API + "proxy/channels/list/%s.json?geoId=unknown" % XUMO_GEO, 6 * 3600) or {}
    chans = ((lst.get("channel") or {}).get("item")) or []
    out = {}
    for c in chans:
        cid = str((c.get("guid") or {}).get("value") or "")
        if not cid or (c.get("properties") or {}).get("is_live") == "false":
            continue
        out[cid] = {"name": c.get("title") or "", "groups": [g.get("value") for g in (c.get("genre") or []) if g.get("value")],
                    "logo": "https://image.xumo.com/v1/channels/channel/%s/168x168.png?type=color_onBlack" % cid, "programs": []}
    if not out:
        return {}
    now = time.time()
    total = len(chans)
    for block_start in (now - now % 21600, now - now % 21600 + 21600):        # this 6-hour block and the next
        day = time.strftime("%Y%m%d", time.gmtime(block_start))
        block = int(time.gmtime(block_start).tm_hour // 6)
        for offset in range(0, max(total, 50), 50):
            url = XUMO_API + "epg/%s/%s/%d.json?limit=50&offset=%d&f=asset.title" % (XUMO_GEO, day, block, offset)
            data = cache.fetch_json(url, _cache_ttl()) or {}
            assets = data.get("assets") or {}
            for row in data.get("channels") or []:
                ch = out.get(str(row.get("channelId")))
                if ch is None:
                    continue
                for slot in row.get("schedule") or []:
                    try:
                        start = calendar.timegm(time.strptime(slot["start"][:19], "%Y-%m-%dT%H:%M:%S"))
                    except (KeyError, ValueError, TypeError):
                        continue
                    ch["programs"].append([start, (assets.get(slot.get("assetId")) or {}).get("title") or ch["name"]])
    for ch in out.values():
        ch["programs"] = sorted({p[0]: p for p in ch["programs"]}.values())
    return {cid: ch for cid, ch in out.items() if ch["programs"]}


def _load(sid):
    svc = SERVICES[sid]
    if svc["layout"] == "xumo":
        out = _load_xumo()
        if kodi.setting_bool("hide_spanish", True):
            out = {cid: ch for cid, ch in out.items() if not is_spanish(ch)}
        return out
    if svc["layout"] == "tubi":
        out = _load_tubi()
        if kodi.setting_bool("hide_spanish", True):
            out = {cid: ch for cid, ch in out.items() if not is_spanish(ch)}
        return out
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
    if kodi.setting_bool("hide_spanish", True):
        out = {cid: ch for cid, ch in out.items() if not is_spanish(ch)}
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
        # same channel name AND same programme on now: a regional variant airing something else stays separate
        # same channel name, same programme, same quarter hour: the same broadcast on two services
        key = (_norm(p["channel"]), _norm(p.get("title")), int(p.get("start") or 0) // 900)
        if not key[0]:
            key = (p["channel_id"], "", 0)
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
