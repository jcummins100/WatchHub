"""Menu tree and list rendering."""
import json
import time

import xbmc
import xbmcgui

from resources.lib import apps, cache, health, kodi, launcher, sports
from resources.lib import infodialog
from resources.lib.sources import espn, fast, ondemand, pvr, sportsdb, tmdb, trakt, youtube

ICON_LIVE = "DefaultTVShows.png"
ICON_FOLDER = "DefaultFolder.png"
PLAIN = False  # set when the skin asks (skin=1): no colour tags in labels, data goes into properties

SPORT_COLORS = {
    "Football (NFL/College)": "FF2F5D3A", "Basketball": "FF8A4B1F", "Baseball": "FF1F3F6E", "Hockey": "FF2E4A5E",
    "Soccer": "FF1F6E4A", "Golf": "FF3C6E1F", "Tennis": "FF6E5E1F", "MMA / Combat": "FF6E1F2A", "Boxing": "FF5E1F1F",
    "Wrestling": "FF4A1F6E", "Motorsport": "FF6E3A1F", "Cricket": "FF1F6E66", "Rugby": "FF3A3A6E", "Poker": "FF2A2A2A",
    "Billiards": "FF2F4F2F", "Pickleball": "FF5E6E1F", "Surf / Outdoor": "FF1F5E6E", "Women's Sports": "FF6E1F5E",
    "Olympics / Team USA": "FF1F3A6E", "Multi-sport": "FF2C3E66", "Other": "FF3B3F4A",
}


def _timeleft(p):
    if not p.get("end"):
        return ""
    left = int((p["end"] - time.time()) / 60)
    if left <= 0:
        return ""
    return "%dh %02dm left" % divmod(left, 60) if left >= 60 else "%dm left" % left


def _props(p):
    """Properties the skin reads: state, progress, when, meta..."""
    now = time.time()
    live = bool(p["start"] and p["end"] and p["start"] <= now < p["end"]) or (not p["start"] and p["source"] in fast.SERVICES)
    pct = ""
    if p["start"] and p["end"] and p["end"] > p["start"] and p["start"] <= now < p["end"]:
        pct = str(int(100 * (now - p["start"]) / (p["end"] - p["start"])))
    if live:
        when = _timeleft(p)
        kicker = " \u2022 ".join(x for x in (p.get("sport"), p.get("service")) if x).upper()
    else:
        when = _fmt_time(p["start"]) if p["start"] else ""
        kicker = "STARTS %s" % when.upper() if when else ""
    service = p.get("service") or ""
    if p.get("alts"):
        service += " (also on %s)" % ", ".join(a["service"] for a in p["alts"] if a.get("service"))
    meta = " \u2022 ".join(x for x in (p.get("channel"), service, p.get("sport"), when) if x)
    return {
        "kind": "channel",
        "title": p["title"], "channel": p.get("channel") or "", "service": p.get("service") or "",
        "sport": p.get("sport") or "", "state": "live" if live else "upcoming", "progress": pct,
        "when": when, "kicker": kicker, "meta": meta,
    }


# ---------------------------------------------------------------- helpers
def _fmt_time(epoch):
    if not epoch:
        return ""
    lt = time.localtime(epoch)
    today = time.localtime()
    s = time.strftime("%I:%M %p", lt).lstrip("0")
    if (lt.tm_year, lt.tm_yday) != (today.tm_year, today.tm_yday):
        s = time.strftime("%a ", lt) + s
    return s


def _progress(p):
    if not p["start"] or not p["end"] or p["end"] <= p["start"]:
        return ""
    now = time.time()
    pct = int(100 * (now - p["start"]) / (p["end"] - p["start"]))
    pct = max(0, min(100, pct))
    left = int((p["end"] - now) / 60)
    return " [COLOR gray](%d%%, %dm left)[/COLOR]" % (pct, left) if left > 0 else ""


def _label(p, show_time=False, show_channel=True):
    if PLAIN:
        return p["title"]
    parts = []
    if show_time and p["start"]:
        parts.append("[COLOR cyan]%s[/COLOR]" % _fmt_time(p["start"]))
    if sports.looks_like_game(p["title"]):
        parts.append("[B]%s[/B]" % p["title"])
    else:
        parts.append(p["title"])
    if show_channel and p["channel"] and p["channel"] != p["title"]:
        parts.append("[COLOR gray]- %s[/COLOR]" % p["channel"])
    label = " ".join(parts)
    if not p["playable"]:
        label += " [COLOR gray][guide only][/COLOR]"
    return label


def _service_tag(p):
    svc = p.get("service") or p["source"]
    color = fast.SERVICES.get(p["source"], {}).get("color")
    return "[COLOR %s]%s[/COLOR]" % (color, svc) if color else svc


def _add_programme(p, show_time=False, show_channel=True):
    info = {
        "title": p["title"],
        "plot": "%s  |  %s\n%s - %s\n\n%s" % (
            _service_tag(p), p.get("sport") or "", _fmt_time(p["start"]), _fmt_time(p["end"]), p.get("plot") or ""),
        "genre": p.get("sport") or "Sport",
    }
    art = {"thumb": p.get("logo") or ICON_LIVE, "icon": p.get("logo") or ICON_LIVE}
    if p.get("art") and p["art"] != p.get("logo"):
        art["fanart"] = p["art"]
        art["landscape"] = p["art"]
    # One click = watch. The channel's schedule is on the context menu (long-press / menu button).
    url = kodi.build_url(action="play", **p["play"])
    ctx = []
    for alt in p.get("alts") or []:
        ctx.append(("Watch on %s" % alt["service"], "RunPlugin(%s)" % kodi.build_url(action="play", **alt["play"])))
    if p["source"] in fast.SERVICES or p["source"] == "pvr":
        ctx.append(("%s schedule" % p["channel"],
                    "ActivateWindow(Videos,%s,return)" % kodi.build_url(action="channel", src=p["source"], id=p["channel_id"])))
    ctx = ctx or None
    info["plot"] = "%s%s\n%s" % (_fmt_time(p["start"]) + " - " + _fmt_time(p["end"]) if p["start"] else "", _progress(p), info["plot"])
    kodi.add_item(_label(p, show_time, show_channel), url, is_folder=False, art=art, info=info, context=ctx, props=_props(p))


def _filter_games(items):
    if kodi.setting_bool("games_only"):
        return [p for p in items if sports.looks_like_game(p["title"])]
    return items


def _sorted_live(items):
    # Games first, then by service/channel name.
    return sorted(items, key=lambda p: (not sports.looks_like_game(p["title"]), p["source"], p["channel"].lower()))


# ---------------------------------------------------------------- screens
MENU_COLORS = ["FF2C3E66", "FF234F3E", "FF3A2F5C", "FF5C3A2F", "FF2B4A5E", "FF4A2B5E", "FF3B3F4A", "FF2F5D3A", "FF6E3A1F", "FF1F3F6E", "FF3B3F4A", "FF3B3F4A"]


def root():
    kodi.set_content("videos")
    tiles = [
        ("Live Now", "live", "DefaultTVShows.png", "What's on right now"),
        ("Starting Soon", "soon", "DefaultRecentlyAddedEpisodes.png", "Next %d minutes" % kodi.setting_int("soon_minutes", 120)),
        ("Today's Games & Scores", "games", "DefaultPVRGuide.png", "Live scores and where to watch") if kodi.setting_bool("src_scores", True) else None,
        ("By Sport", "sports", "DefaultGenre.png", "Browse by sport"),
        ("Search", "search", "DefaultAddonsSearch.png", "Movies, shows and channels"),
        ("What's Streaming", "ondemand", "DefaultMovies.png", "Trending, new this week, newest releases"),
        ("My Shows & Movies (Trakt)", "trakt", "DefaultTVShows.png", "Up next, new episodes, watchlist"),
        ("Free Live TV", "tvgroups", "DefaultTVShows.png", "News, movies, kids and more"),
        ("By Service", "services", "DefaultNetwork.png", "Pluto, Plex, Roku..."),
        (kodi.localized(30004), "pvr", "DefaultTVShows.png", "Kodi Live TV") if pvr_has_channels() else None,
        (kodi.localized(30005), "tv", "DefaultPVRGuide.png", "TheSportsDB listings") if kodi.setting_bool("src_sportsdb", False) else None,
        ("Official YouTube Channels", "youtube", "DefaultAddonVideo.png", "League live streams") if kodi.setting_bool("src_youtube", True) else None,
        ("Your Apps", "apps", "DefaultAddonProgram.png", "Installed streaming apps"),
        ("WatchHub look (skin)", "skin", "DefaultAddonSkin.png", "Switch to the WatchHub skin"),
        (kodi.localized(30008), "refresh", "DefaultAddonsUpdates.png", "Re-download guide data"),
        ("Status", "status", "DefaultAddonService.png", "Sources and apps"),
        (kodi.localized(30007), "settings", "DefaultAddonService.png", "Sports Hub settings"),
    ]
    i = 0
    for t in tiles:
        if not t:
            continue
        label, action, icon, meta = t
        folder = action not in ("refresh", "settings", "skin")
        kodi.add_item(label, kodi.build_url(action=action), folder, art={"icon": icon, "thumb": icon},
                      props={"kind": "tile", "color": MENU_COLORS[i % len(MENU_COLORS)], "meta": meta})
        i += 1
    kodi.end_directory()


def live():
    kodi.set_content("videos")
    items = fast.live_now()
    if kodi.setting_bool("src_pvr", True) and pvr.available():
        items += pvr.live_now()
    items = _filter_games(items)
    if not items:
        kodi.add_item(kodi.localized(30020), kodi.build_url(action="root"), False)
    for p in _sorted_live(items):
        _add_programme(p)
    kodi.end_directory()


def soon():
    kodi.set_content("videos")
    minutes = kodi.setting_int("soon_minutes", 120)
    items = fast.starting_soon(minutes)
    if kodi.setting_bool("src_pvr", True) and pvr.available():
        items += pvr.starting_soon(minutes)
    items = _filter_games(items)
    items.sort(key=lambda p: p["start"])
    for p in items:
        _add_programme(p, show_time=True)
    kodi.end_directory()


def sports_menu():
    items = fast.live_now()
    if kodi.setting_bool("src_pvr", True) and pvr.available():
        items += pvr.live_now()
    counts = {}
    for p in items:
        counts[p["sport"] or "Other"] = counts.get(p["sport"] or "Other", 0) + 1
    for label in sports.SPORT_LABELS + ["Other"]:
        n = counts.get(label, 0)
        if n:
            text = label if PLAIN else "%s [COLOR gray](%d)[/COLOR]" % (label, n)
            kodi.add_item(text, kodi.build_url(action="sport", name=label), True, art={"icon": ICON_FOLDER},
                          props={"kind": "tile", "color": SPORT_COLORS.get(label, "FF3B3F4A"), "meta": "%d on now" % n, "count": str(n)})
    kodi.end_directory()


def sport(name):
    kodi.set_content("videos")
    items = fast.live_now()
    if kodi.setting_bool("src_pvr", True) and pvr.available():
        items += pvr.live_now()
    items = [p for p in items if (p["sport"] or "Other") == name]
    for p in _sorted_live(_filter_games(items)):
        _add_programme(p)
    kodi.end_directory()


def services():
    for sid in fast.enabled_services():
        svc = fast.SERVICES[sid]
        n = len(fast.channels(sid))
        if not svc["package"]:
            tag = " [COLOR gray][guide only][/COLOR]"
        elif health.app_installed(svc["package"]) is False:
            tag = " [COLOR orange][app not installed][/COLOR]"
        else:
            tag = ""
        kodi.add_item(svc["name"] if PLAIN else "%s [COLOR gray](%d sports channels)[/COLOR]%s" % (svc["name"], n, tag),
                      kodi.build_url(action="service", id=sid), True, art={"icon": ICON_FOLDER},
                      props={"kind": "tile", "color": "FF" + svc["color"][2:] if svc.get("color") else "FF2C3E66",
                             "meta": "%d sports channels%s" % (n, "" if svc["package"] else " (guide only)")})
    kodi.end_directory()


def service(sid):
    kodi.set_content("videos")
    now = int(time.time())
    for cid, ch in fast.channels(sid):
        p = fast._programme_at(ch.get("programs"), now)
        prog = fast._make(sid, cid, ch, p[0], p[1], p[2]) if p else fast._make(sid, cid, ch, 0, 0, ch.get("name", ""))
        # Channel-first label here.
        prog_label = prog["title"] if prog["title"] != prog["channel"] else ""
        label = "[B]%s[/B]" % prog["channel"] + (" [COLOR gray]- %s[/COLOR]" % prog_label if prog_label else "")
        info = {"title": prog["channel"], "plot": prog["plot"], "genre": prog["sport"] or "Sport"}
        art = {"thumb": prog["logo"] or ICON_LIVE, "fanart": prog["art"] or ""}
        info["plot"] = "%s\n%s" % (_progress(prog), info["plot"])
        kodi.add_item(label, kodi.build_url(action="play", **prog["play"]), False, art=art, info=info,
                      context=[("%s schedule" % prog["channel"],
                                "ActivateWindow(Videos,%s,return)" % kodi.build_url(action="channel", src=sid, id=cid))])
    kodi.end_directory()


def channel(src, cid):
    """A channel's next 24h, with 'Tune now' on top."""
    kodi.set_content("videos")
    if src == "pvr":
        kodi.add_item("[B]Tune to channel now[/B]", kodi.build_url(action="play", src="pvr", id=cid), False, art={"icon": ICON_LIVE})
        kodi.end_directory()
        return
    ch, items = fast.channel_schedule(src, cid)
    if ch is None:
        kodi.end_directory(succeeded=False)
        return
    svc = fast.SERVICES[src]
    play_url = kodi.build_url(action="play", src=src, id=cid, name=ch.get("name", ""))
    if svc["package"]:
        kodi.add_item("[B]Watch now in %s[/B]" % svc["name"], play_url, False,
                      art={"thumb": ch.get("logo") or ICON_LIVE, "fanart": ch.get("art") or ch.get("fanart") or ""})
    else:
        kodi.add_item("[COLOR gray]%s has no app on this device (guide only)[/COLOR]" % svc["name"], play_url, False)
    for p in items:
        # Schedule rows are informational; clicking any of them tunes the channel.
        label = "[COLOR cyan]%s[/COLOR] %s%s" % (_fmt_time(p["start"]), ("[B]%s[/B]" if sports.looks_like_game(p["title"]) else "%s") % p["title"], _progress(p))
        kodi.add_item(label, play_url, False, art={"thumb": ch.get("logo") or ICON_LIVE}, info={"title": p["title"], "plot": p["plot"]})
    kodi.end_directory()


def pvr_has_channels():
    return kodi.setting_bool("src_pvr", True) and pvr.available() and bool(pvr.live_now(all_channels=True))


def pvr_menu():
    kodi.set_content("videos")
    if not pvr.available():
        kodi.add_item(kodi.localized(30026), kodi.build_url(action="root"), False)
        kodi.add_item("[COLOR gray]Set up an HDHomeRun or IPTV Simple Client under Settings > Add-ons > PVR clients[/COLOR]",
                      kodi.build_url(action="root"), False)
        kodi.end_directory()
        return
    live_items = pvr.live_now()
    for p in _sorted_live(live_items):
        _add_programme(p)
    kodi.add_item("[COLOR gray]%s[/COLOR]" % kodi.localized(30009), kodi.build_url(action="pvr_all"), True)
    kodi.end_directory()


def pvr_all():
    kodi.set_content("videos")
    for p in sorted(pvr.live_now(all_channels=True), key=lambda p: p["channel"].lower()):
        _add_programme(p)
    kodi.end_directory()


def _add_game(g, show_league=True):
    now = time.time()
    if g["state"] == "in":
        head = "[COLOR lime]LIVE[/COLOR] "
        when = "[COLOR gray]%s[/COLOR]" % g["detail"] if g["detail"] else ""
    elif g["state"] == "post":
        head = "[COLOR gray]FINAL[/COLOR] "
        when = ""
    else:
        head = ""
        when = "[COLOR cyan]%s[/COLOR]" % _fmt_time(g["start"]) if g["start"] else ""
    title = "[B]%s[/B]" % g["title"]
    if g["score"]:
        title += " [COLOR yellow]%s %s[/COLOR]" % (g.get("away_abbr", ""), g["score"].replace(" - ", " - %s " % g.get("home_abbr", "")))
    tail = " [COLOR gray]- %s[/COLOR]" % g["channel"] if g["channel"] else " [COLOR gray][no broadcast listed][/COLOR]"
    league = " [COLOR gray](%s)[/COLOR]" % g["league"] if show_league else ""
    label = "%s%s %s%s%s" % (head, when, title, tail, league)
    info = {"title": g["title"], "plot": g["plot"], "genre": g["sport"] or "Sport"}
    art = {"thumb": g["logo"] or ICON_LIVE, "icon": g["logo"] or ICON_LIVE, "away": g.get("away_logo") or "", "home": g.get("home_logo") or ""}
    state = {"in": "live", "pre": "upcoming", "post": "final"}.get(g["state"], "upcoming")
    when = g["detail"] if g["state"] != "pre" else (_fmt_time(g["start"]) if g["start"] else "")
    props = {
        "kind": "game",
        "title": g["short"] or g["title"], "score": g["score"], "detail": g["detail"], "league": g["league"],
        "network": g["channel"] or "No broadcast listed", "state": state, "when": when,
        "kicker": {"live": g["league"].upper(), "final": "FINAL \u2022 %s" % g["league"].upper(), "upcoming": "%s \u2022 STARTS %s" % (g["league"].upper(), when.upper())}[state],
        "away": g.get("away_abbr") or "", "home": g.get("home_abbr") or "",
        "meta": " \u2022 ".join(x for x in (g["league"], g["channel"], g["detail"] if g["state"] != "pre" else "") if x),
        "league_logo": g.get("league_logo") or "",
    }
    if PLAIN:
        label = g["short"] or g["title"]
    if g["playable"]:
        kodi.add_item(label, kodi.build_url(action="play", **g["play"]), False, art=art, info=info, props=props)
    else:
        kodi.add_item(label, kodi.build_url(action="games"), False, art=art, info=info, props=props)
    return now


def games_menu():
    kodi.set_content("videos")
    stats = espn.counts()
    total = sum(t for _, t, _ in stats.values())
    live = sum(l for _, _, l in stats.values())
    kodi.add_item("[B]All games today[/B] [COLOR gray](%d, %d live)[/COLOR]" % (total, live),
                  kodi.build_url(action="games", league="all"), True, art={"icon": ICON_LIVE})
    for slug, lid, name, sport in espn.LEAGUES:
        if lid in stats:
            _, t, l = stats[lid]
            tag = " [COLOR lime]%d live[/COLOR]" % l if l else ""
            kodi.add_item("%s [COLOR gray](%d)[/COLOR]%s" % (name, t, tag), kodi.build_url(action="games", league=lid), True,
                          art={"icon": ICON_FOLDER})
    kodi.end_directory()


def games_list(league):
    kodi.set_content("videos")
    items = espn.games(None if league == "all" else [league])
    if not items:
        kodi.add_item("No games scheduled", kodi.build_url(action="games"), False)
    for g in items:
        _add_game(g, show_league=(league == "all"))
    kodi.end_directory()


def tv():
    kodi.set_content("videos")
    items = sportsdb.tv_today()
    now = time.time()
    for p in items:
        live_now_tag = "[COLOR lime]LIVE[/COLOR] " if p["start"] and p["start"] <= now <= p["end"] else ""
        label = "%s[COLOR cyan]%s[/COLOR] [B]%s[/B] [COLOR gray]- %s (%s)[/COLOR]" % (
            live_now_tag, _fmt_time(p["start"]), p["title"], p["channel"], p.get("league") or p.get("sport") or "")
        info = {"title": p["title"], "plot": p["plot"], "genre": p["sport"] or "Sport"}
        art = {"thumb": p["logo"] or ICON_LIVE, "fanart": p["art"] or ""}
        kodi.add_item(label, kodi.build_url(action="play", **p["play"]), False, art=art, info=info)
    if not items:
        kodi.add_item("No TV listings found for today", kodi.build_url(action="root"), False)
    kodi.end_directory()


def youtube_menu():
    kodi.set_content("videos")
    for p in youtube.items():
        kodi.add_item(p["channel"] if PLAIN else "%s [COLOR gray]- %s[/COLOR]" % (p["channel"], p["sport"]), kodi.build_url(action="play", **p["play"]), False,
                      art={"icon": "DefaultAddonVideo.png"}, info={"title": p["title"], "plot": p["plot"]},
                      props={"kind": "tile", "color": SPORT_COLORS.get(p["sport"], "FF3B3F4A"), "meta": p["sport"]})
    kodi.end_directory()


def _add_title(t):
    props = {"kind": "title", "title": t["title"], "meta": t["meta"], "kicker": t["service"].upper(), "service": t["service"],
             "year": str(t["year"]), "type": t["type"], "state": ""}
    art = {"thumb": t["poster"] or "DefaultVideo.png", "poster": t["poster"], "landscape": t["backdrop"], "fanart": t["backdrop"]}
    info = {"title": t["title"], "plot": t["plot"], "genre": t["type"]}
    label = t["title"] if PLAIN else "%s [COLOR gray](%s, %s)[/COLOR]" % (t["title"], t["year"], t["service"])
    ctx = [("Play on %s" % t["service"], "RunPlugin(%s)" % kodi.build_url(action="play", **t["play"]))]
    for o in (t.get("offers") or [])[1:]:
        ctx.append(("Watch on %s" % o["service"], "RunPlugin(%s)" % kodi.build_url(action="play", src="ondemand", pkg=o["pkg"], url=o["url"], name=o["service"])))
    if tmdb.enabled():
        ctx.append(("Watch trailer", "RunPlugin(%s)" % kodi.build_url(action="trailer", title=t["title"], year=t["year"], kind=t["type"])))
    if trakt.signed_in():
        ctx.append(("Trakt: add to watchlist", "RunPlugin(%s)" % kodi.build_url(action="trakt_watchlist", title=t["title"], year=t["year"], kind=t["type"])))
        ctx.append(("Trakt: mark as watched", "RunPlugin(%s)" % kodi.build_url(action="trakt_watched", title=t["title"], year=t["year"], kind=t["type"])))
    # Click = detail page (play is one button away there, or on the long-press menu)
    kodi.add_item(label, kodi.build_url(action="info", title=t["title"], year=t["year"], kind=t["type"]), False, art=art, info=info, props=props, context=ctx)


def _add_upcoming(t, kicker):
    import time as _time
    when = t["date"]
    nice = _time.strftime("%b %d", _time.strptime(when, "%Y-%m-%d")).replace(" 0", " ") if when else ""
    props = {"kind": "title", "title": t["title"], "meta": "%s \u2022 %s%s" % ("Coming %s" % nice if nice else "Coming soon", t["type"], (" \u2022 TMDB %.1f" % t["vote"]) if t.get("vote") else ""),
             "kicker": kicker, "service": "Coming %s" % nice if nice else "Coming soon", "year": str(t["year"]), "type": t["type"], "state": "upcoming"}
    art = {"thumb": t["poster"] or "DefaultVideo.png", "poster": t["poster"], "landscape": t["backdrop"], "fanart": t["backdrop"]}
    ctx = [("Watch trailer", "RunPlugin(%s)" % kodi.build_url(action="trailer", title=t["title"], year=t["year"], kind=t["type"]))]
    if trakt.signed_in():
        ctx.append(("Trakt: add to watchlist", "RunPlugin(%s)" % kodi.build_url(action="trakt_watchlist", title=t["title"], year=t["year"], kind=t["type"])))
    kodi.add_item(t["title"] if PLAIN else "%s [COLOR gray](%s)[/COLOR]" % (t["title"], nice), kodi.build_url(action="info", title=t["title"], year=t["year"], kind=t["type"]), False,
                  art=art, info={"title": t["title"], "plot": t["plot"]}, props=props, context=ctx)


def coming_soon_list(which):
    kodi.set_content("videos")
    codes = ondemand.installed_codes()
    if which == "movies":
        items = tmdb.coming_soon(codes, "Movie")
    elif which == "shows":
        items = tmdb.coming_soon(codes, "Show")
    else:
        items = tmdb.upcoming("Movie")
    for t in items:
        _add_upcoming(t, "COMING SOON" if which != "theaters" else "IN THEATERS SOON")
    kodi.end_directory(view="posters")


def ondemand_menu():
    kodi.set_content("videos")
    palette = list(SPORT_COLORS.values())
    kodi.add_item("Search", kodi.build_url(action="search"), True, art={"icon": "DefaultAddonsSearch.png"},
                  props={"kind": "tile", "color": "FF3B3F4A", "meta": "Movies, shows and channels"})
    if tmdb.enabled():
        kodi.add_item("Coming soon: movies on your services", kodi.build_url(action="coming", which="movies"), True, art={"icon": ICON_FOLDER},
                      props={"kind": "tile", "color": "FF6E1F2A", "meta": "Next 60 days on Netflix, Prime, Apple TV, Hulu..."})
        kodi.add_item("Coming soon: shows on your services", kodi.build_url(action="coming", which="shows"), True, art={"icon": ICON_FOLDER},
                      props={"kind": "tile", "color": "FF1F3F6E", "meta": "New shows and seasons, next 60 days"})
        kodi.add_item("In theaters soon", kodi.build_url(action="coming", which="theaters"), True, art={"icon": ICON_FOLDER},
                      props={"kind": "tile", "color": "FF3C6E1F", "meta": "Upcoming US releases"})
    for i, (label, kind, arg) in enumerate(ondemand.rows()):
        codes = arg["codes"]
        kodi.add_item(label, kodi.build_url(action="ondemand", row=i), True, art={"icon": ICON_FOLDER},
                      props={"kind": "tile", "color": palette[(i * 3) % len(palette)], "meta": ", ".join(ondemand.BY_CODE[c][0] for c in codes[:4]) + ("..." if len(codes) > 4 else "")})
    kodi.end_directory()


def ondemand_list(row, svc=""):
    kodi.set_content("videos")
    for t in ondemand.row_items(row, svc):
        _add_title(t)
    kodi.end_directory(view="posters")


def providers(svc=""):
    """The home screen's Services row: All + each installed service. `svc` = the one selected now."""
    kodi.set_content("videos")
    items = [("", "All services", "", "DefaultVideo.png")] + [
        (c, ondemand.short_name(c), ondemand.BY_CODE[c][1], "androidapp://sources/apps/%s.png" % ondemand.BY_CODE[c][1]) for c in ondemand.installed_codes()]
    for code, name, pkg, thumb in items:
        selected = code == svc
        if selected and code:
            meta = "Showing only %s" % name
        elif selected:
            meta = "Showing everything - pick a service to narrow the rows"
        else:
            meta = "Show only %s" % name if code else "Show everything again"
        kodi.add_item(name, kodi.build_url(action="provider", code=code), False, art={"thumb": thumb, "icon": "DefaultAddonProgram.png"},
                      info={"title": name}, props={"kind": "app", "meta": meta, "kicker": "SHOWING" if selected else "SERVICES", "selected": "1" if selected else ""})
        if selected and code:
            # the app itself, right next to its filter (comes after it, so the filters' positions don't shift)
            kodi.add_item("Open %s" % name, kodi.build_url(action="play", src="app", id=pkg, name=name), False,
                          art={"thumb": thumb, "icon": "DefaultAddonProgram.png"}, info={"title": "Open %s" % name},
                          props={"kind": "app", "meta": "Launch the %s app" % name, "kicker": "OPEN APP"})
    kodi.end_directory()


def pick_provider(code):
    """Services row click: narrow the home rows to one service (or back to All); the selected one again opens its app.

    (There is also an explicit "Open <service>" card next to the selected one - this is just the shortcut.)
    """
    home = xbmcgui.Window(10000)
    if code and code == home.getProperty("sh_provider"):
        launcher.play({"src": "app", "id": ondemand.BY_CODE[code][1], "name": ondemand.short_name(code)})
        return
    codes = [""] + ondemand.installed_codes()
    home.setProperty("sh_provider_name", ondemand.short_name(code).upper() if code else "")
    home.setProperty("sh_provider", code)
    # the All rows (9000) and the provider rows (9001) swap visibility: wait a frame, then put focus
    # back on the clicked service in whichever Services row is now showing
    xbmc.sleep(250)
    kodi.run_builtin("SetFocus(%d,%d,absolute)" % (9051 if code else 9050, codes.index(code) if code in codes else 0))


def search(query=None):
    """Search movies/shows on the user's services and live channels by name."""
    kodi.set_content("videos")
    if query is None:
        query = xbmcgui.Dialog().input("Search", type=xbmcgui.INPUT_ALPHANUM)
        if not query:
            kodi.end_directory(succeeded=False)
            return
        # re-enter with the query in the URL so Back/refresh keeps the results
        kodi.run_builtin("Container.Update(%s,replace)" % kodi.build_url(action="search", q=query))
        kodi.end_directory(succeeded=False)
        return
    q = query.lower()
    for p in fast.live_now():
        if q in p["channel"].lower() or q in p["title"].lower():
            _add_programme(p)
    for t in ondemand.search(query):
        _add_title(t)
    kodi.end_directory(view="posters")


def _trakt_item(t, kicker, meta_extra=""):
    """A Trakt title -> card. Availability/deep link comes from JustWatch by name; falls back to a search."""
    od = ondemand.lookup(t["title"], t["year"], t["type"])
    if od:
        od = dict(od)
        od["meta"] = " \u2022 ".join(x for x in (meta_extra, od["meta"]) if x)
        od["service"] = od["service"]
        props = {"kind": "title", "title": t["title"], "meta": od["meta"], "kicker": kicker or od["service"].upper(), "service": od["service"],
                 "year": str(t["year"]), "type": t["type"], "state": ""}
        art = {"thumb": od["poster"] or "DefaultVideo.png", "poster": od["poster"], "landscape": od["backdrop"], "fanart": od["backdrop"]}
        url = kodi.build_url(action="info", title=t["title"], year=t["year"], kind=t["type"])
        plot = od["plot"]
    else:
        props = {"kind": "title", "title": t["title"], "meta": meta_extra or t["type"], "kicker": kicker, "service": "", "year": str(t["year"]), "type": t["type"], "state": ""}
        art = {"thumb": "DefaultVideo.png"}
        url = kodi.build_url(action="info", title=t["title"], year=t["year"], kind=t["type"])
        plot = ""
    ctx = [("Trakt: mark as watched", "RunPlugin(%s)" % kodi.build_url(action="trakt_watched", title=t["title"], year=t["year"], kind=t["type"]))]
    if od and od.get("play", {}).get("pkg"):
        ctx.insert(0, ("Play on %s" % od["service"], "RunPlugin(%s)" % kodi.build_url(action="play", **od["play"])))
    if tmdb.enabled():
        ctx.insert(0, ("Watch trailer", "RunPlugin(%s)" % kodi.build_url(action="trailer", title=t["title"], year=t["year"], kind=t["type"])))
    kodi.add_item(t["title"] if PLAIN else "%s [COLOR gray](%s)[/COLOR]" % (t["title"], meta_extra or t["year"]), url, False, art=art,
                  info={"title": t["title"], "plot": plot}, props=props, context=ctx)


def trakt_menu():
    kodi.set_content("videos")
    if not trakt.signed_in():
        kodi.add_item("Sign in to Trakt", kodi.build_url(action="trakt_signin"), False, props={"kind": "tile", "color": "FF8A1F2E", "meta": "Remember what you watch, get new-season alerts"})
        if not trakt.configured():
            kodi.add_item("Trakt setup", kodi.build_url(action="settings"), False, props={"kind": "tile", "color": "FF3B3F4A", "meta": "Enter your Trakt Client ID in settings"})
        kodi.end_directory()
        return
    for label, row, color, meta in [("Up Next", "upnext", "FF2F5D3A", "Next episode of shows you're watching"),
                                    ("New episodes", "calendar", "FF1F3F6E", "Your shows, next 2 weeks"),
                                    ("Watchlist", "watchlist", "FF6E3A1F", "Things you saved")]:
        kodi.add_item(label, kodi.build_url(action="trakt", row=row), True, props={"kind": "tile", "color": color, "meta": meta})
    kodi.add_item("Sign out of Trakt", kodi.build_url(action="trakt_signout"), False, props={"kind": "tile", "color": "FF3B3F4A", "meta": ""})
    kodi.end_directory()


def _on_service(t, svc):
    od = ondemand.lookup(t["title"], t["year"], t["type"])
    return bool(od) and any(o["code"] == svc for o in od.get("offers") or [])


def trakt_list(row, svc=""):
    kodi.set_content("videos")
    if row == "upnext":
        if not trakt.signed_in():
            # on the home screen this row would otherwise vanish, leaving no hint that Trakt exists
            if trakt.configured():
                kodi.add_item("Sign in[CR]to Trakt", kodi.build_url(action="trakt_signin"), False, props={"kind": "tile", "color": "FF8A1F2E", "title": "Sign in to Trakt", "meta": "Remember what you watch, get new-season alerts"})
            kodi.end_directory()
            return
        for t in trakt.up_next():
            if svc and not _on_service(t, svc):
                continue
            _trakt_item(t, "UP NEXT", "%s %s" % (t["next"], t["episode_title"]))
    elif row == "calendar":
        # one card per show: the earliest upcoming episode, plus how many are coming in the window
        by_show = {}
        for t in trakt.calendar():
            key = t["ids"].get("trakt") or t["title"]
            if key not in by_show:
                by_show[key] = dict(t, count=0)
            by_show[key]["count"] += 1
        import time as _time
        today = _time.strftime("%Y-%m-%d")
        for t in sorted(by_show.values(), key=lambda x: x["first_aired"]):
            when = t["first_aired"][:10]
            label = "Airs %s" % when if when > today else "Aired %s" % when
            more = " (+%d more)" % (t["count"] - 1) if t["count"] > 1 else ""
            _trakt_item(t, "NEW SEASON" if t.get("premiere") else "NEW EPISODE", "%s \u2022 %s %s%s" % (label, t["next"], t["episode_title"], more))
    elif row == "watchlist":
        for t in trakt.watchlist():
            _trakt_item(t, "WATCHLIST", t["type"])
    kodi.end_directory(view="posters")


def tvgroups():
    """Genres across the free services (news, movies, kids...), sports excluded."""
    kodi.set_content("videos")
    groups = fast.groups()
    palette = list(SPORT_COLORS.values())
    for i, (name, n) in enumerate(groups):
        kodi.add_item(name, kodi.build_url(action="tvgroup", name=name), True, art={"icon": ICON_FOLDER},
                      props={"kind": "tile", "color": palette[i % len(palette)], "meta": "%d channels" % n})
    kodi.end_directory()


def tvgroup(name):
    kodi.set_content("videos")
    for p in fast.live_now_group(name):
        _add_programme(p)
    kodi.end_directory()


def apps_menu():
    """Installed streaming apps, as a rail for the skin (and a list in the menu)."""
    kodi.set_content("videos")
    installed = health.installed_apps()
    shown = [n for n, p in apps.LAUNCHABLE if not installed or p in installed]
    kodi.log("apps: %d visible to Kodi, showing %d: %s | not visible: %s" % (len(installed), len(shown), ", ".join(shown),
             ", ".join(n for n, p in apps.LAUNCHABLE if installed and p not in installed)))
    for name, pkg in apps.LAUNCHABLE:
        if installed and pkg not in installed:
            continue
        kodi.add_item(name, kodi.build_url(action="play", src="app", id=pkg, name=name), False,
                      art={"thumb": "androidapp://sources/apps/%s.png" % pkg, "icon": "DefaultAddonProgram.png"},
                      info={"title": name, "plot": "Open %s" % name}, props={"kind": "app", "meta": "Open %s" % name, "package": pkg})
    kodi.end_directory()


def switch_skin(name):
    """Switch Kodi's skin (user-initiated from the menu / the skin's own 'classic look' card)."""
    kodi.resolve_none()
    # A skin that was copied into the add-ons folder is registered but disabled; enable it first.
    en = kodi.jsonrpc("Addons.SetAddonEnabled", {"addonid": name, "enabled": True})
    res = kodi.jsonrpc("Settings.SetSettingValue", {"setting": "lookandfeel.skin", "value": name})
    kodi.log("switch skin -> %s: enable=%s set=%s" % (name, en, res))
    # Kodi asks "keep this change?" (reverts after 10s) and only writes settings on exit or when the
    # Settings window closes - answer "yes" and flush so the choice survives a restart.
    mon = xbmc.Monitor()
    if mon.waitForAbort(3):
        return
    kodi.run_builtin("SendClick(11)")
    if mon.waitForAbort(2):
        return
    kodi.save_settings()


def refresh():
    kodi.resolve_none()
    n = cache.clear()
    health.warm_caches()
    kodi.notify("%s (%d files)" % (kodi.localized(30021), n))
    kodi.run_builtin("Container.Refresh")


def status():
    """Diagnostics: is each source reachable, is each app installed."""
    for name, ok, detail in health.source_status():
        mark = "[COLOR lime]OK[/COLOR]" if ok else "[COLOR red]--[/COLOR]"
        kodi.add_item("%s  %s [COLOR gray]- %s[/COLOR]" % (mark, name, detail), kodi.build_url(action="status"), False)
    apps_seen = health.installed_apps()
    kodi.add_item("[COLOR gray]%d Android apps visible to Kodi[/COLOR]" % len(apps_seen), kodi.build_url(action="status"), False)
    kodi.add_item("[COLOR gray]Add-on version %s[/COLOR]" % kodi.ADDON.getAddonInfo("version"), kodi.build_url(action="status"), False)
    kodi.end_directory()


# ---------------------------------------------------------------- router
def dispatch(params):
    global PLAIN
    action = params.get("action", "root")
    PLAIN = params.get("skin") == "1" or xbmc.getSkinDir() == "skin.sportshub"
    kodi.log("dispatch handle=%s %s" % (kodi.HANDLE, params))
    categories = {
        "root": "Menu", "live": "Live Now", "soon": "Starting Soon", "sports": "By Sport", "sport": params.get("name", "Sport"),
        "services": "By Service", "service": fast.SERVICES.get(params.get("id", ""), {}).get("name", "Service"),
        "channel": "Channel", "pvr": "Live TV", "pvr_all": "All Live TV channels", "tv": "TV Schedule",
        "games": "Today's Games" if not params.get("league") else espn.BY_ID.get(params.get("league"), ("", "", "Today's Games", ""))[2],
        "youtube": "YouTube", "apps": "Your Apps", "tvgroups": "Free Live TV", "ondemand": "What's Streaming", "search": "Search", "coming": "Coming soon", "trakt": "My Shows & Movies", "ondemand_search": "Where to watch", "tvgroup": params.get("name", "Free Live TV"), "status": "Status",
    }
    kodi.set_category(categories.get(action, ""))
    if action == "root":
        root()
    elif action == "live":
        live()
    elif action == "soon":
        soon()
    elif action == "sports":
        sports_menu()
    elif action == "sport":
        sport(params.get("name", "Other"))
    elif action == "services":
        services()
    elif action == "service":
        service(params.get("id", "pluto"))
    elif action == "channel":
        channel(params.get("src", ""), params.get("id", ""))
    elif action == "pvr":
        pvr_menu()
    elif action == "pvr_all":
        pvr_all()
    elif action == "games":
        league = params.get("league")
        games_list(league) if league else games_menu()
    elif action == "tv":
        tv()
    elif action == "youtube":
        youtube_menu()
    elif action == "apps":
        apps_menu()
    elif action == "tvgroups":
        tvgroups()
    elif action == "ondemand":
        row = params.get("row")
        ondemand_list(int(row), params.get("svc", "")) if row is not None else ondemand_menu()
    elif action == "providers":
        providers(params.get("svc", ""))
    elif action == "provider":
        kodi.resolve_none()
        pick_provider(params.get("code", ""))
    elif action == "info":
        kodi.resolve_none()
        req = {"title": params.get("title", ""), "year": params.get("year", ""), "kind": params.get("kind", "")}
        home = xbmcgui.Window(10000)
        if home.getProperty("sh_service_alive"):
            # the always-running service shows the card: no per-click Python start-up/shut-down
            home.setProperty("sh_info_request", json.dumps(req))
        else:
            infodialog.show_by_title(**req)
    elif action == "search":
        search(params.get("q"))
    elif action == "enable_addon":
        kodi.resolve_none()
        res = kodi.jsonrpc("Addons.SetAddonEnabled", {"addonid": params.get("id", ""), "enabled": True})
        kodi.log("enable %s: %s" % (params.get("id"), res))
    elif action == "coming":
        coming_soon_list(params.get("which", "movies"))
    elif action == "ondemand_search":
        kodi.set_content("videos")
        for t in ondemand.search(params.get("title", ""), params.get("kind", "")):
            _add_title(t)
        kodi.end_directory(view="posters")
    elif action == "trailer":
        kodi.resolve_none()
        url = tmdb.trailer_url(params.get("title", ""), params.get("year", ""), params.get("kind", "Show"))
        if url:
            launcher.play({"src": "app", "id": youtube.PACKAGE, "name": "YouTube"}) if False else kodi.start_android_activity(youtube.PACKAGE, action="android.intent.action.VIEW", data_uri=url)
        else:
            kodi.notify("No trailer found")
    elif action == "trakt":
        row = params.get("row")
        trakt_list(row, params.get("svc", "")) if row else trakt_menu()
    elif action == "trakt_signin":
        kodi.resolve_none()
        trakt.sign_in()
        kodi.run_builtin("Container.Refresh")
        kodi.run_builtin("SetProperty(sh_refresh,%d,home)" % time.time())  # home rows (Up Next) reload too
    elif action == "trakt_signout":
        kodi.resolve_none()
        trakt.sign_out()
        kodi.run_builtin("Container.Refresh")
        kodi.run_builtin("SetProperty(sh_refresh,%d,home)" % time.time())  # home rows (Up Next) reload too
    elif action in ("trakt_watched", "trakt_watchlist"):
        kodi.resolve_none()
        ids = trakt.search_ids(params.get("title", ""), params.get("year", ""), params.get("kind", "Show"))
        if not ids:
            kodi.notify("Trakt: title not found")
        elif action == "trakt_watched":
            kodi.notify("Marked as watched" if trakt.mark_watched(params.get("kind", "Show"), ids) else "Trakt: failed")
        else:
            kodi.notify("Added to watchlist" if trakt.add_watchlist(params.get("kind", "Show"), ids) else "Trakt: failed")
        cache.clear()
    elif action == "tvgroup":
        tvgroup(params.get("name", ""))
    elif action == "skin":
        switch_skin(params.get("name", "skin.sportshub"))
    elif action == "play":
        kodi.resolve_none()
        launcher.play(params)
    elif action == "refresh":
        refresh()
    elif action == "status":
        status()
    elif action == "settings":
        kodi.resolve_none()
        kodi.open_settings()
    else:
        kodi.notify("Unknown action %s" % action, icon=xbmcgui.NOTIFICATION_WARNING)
        root()
