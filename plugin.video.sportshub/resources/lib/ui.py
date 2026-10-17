"""Menu tree and list rendering."""
import json
import time

import xbmc
import xbmcgui

from resources.lib import apps, cache, health, kodi, launcher, sports
from resources.lib import homefilter, infodialog
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


def _add_programme(p, show_time=False, show_channel=True, kicker=None):
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
    if p["source"] in fast.SERVICES and p.get("channel"):
        from resources.lib import favorites
        ctx.append((_star(favorites.has_channel(p["channel"])), "RunPlugin(%s)" % kodi.build_url(action="fav", what="channel", name=p["channel"])))
    if p["source"] in fast.SERVICES or p["source"] == "pvr":
        ctx.append(("%s schedule" % p["channel"],
                    "ActivateWindow(Videos,%s,return)" % kodi.build_url(action="channel", src=p["source"], id=p["channel_id"])))
    ctx = ctx or None
    info["plot"] = "%s%s\n%s" % (_fmt_time(p["start"]) + " - " + _fmt_time(p["end"]) if p["start"] else "", _progress(p), info["plot"])
    props = _props(p)
    if kicker:
        props["kicker"] = kicker
    kodi.add_item(_label(p, show_time, show_channel), url, is_folder=False, art=art, info=info, context=ctx, props=props)


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
        ("TV Guide", "guide", "DefaultPVRGuide.png", "Free live channels: what's on now and later"),
        ("\u2605 Favorites", "favorites", "DefaultFavourites.png", "Your favorite channels, shows, movies and games"),
        ("Free Live TV", "tvgroups", "DefaultTVShows.png", "News, movies, kids and more"),
        ("By Service", "services", "DefaultNetwork.png", "Pluto, Plex, Roku..."),
        (kodi.localized(30004), "pvr", "DefaultTVShows.png", "Kodi Live TV") if pvr_has_channels() else None,
        (kodi.localized(30005), "tv", "DefaultPVRGuide.png", "TheSportsDB listings") if kodi.setting_bool("src_sportsdb", False) else None,
        ("Official YouTube Channels", "youtube", "DefaultAddonVideo.png", "League live streams") if kodi.setting_bool("src_youtube", True) else None,
        ("Your Apps", "apps", "DefaultAddonProgram.png", "Installed streaming apps"),
        ("WatchHub look (skin)", "skin", "DefaultAddonSkin.png", "Switch to the WatchHub skin"),
        (kodi.localized(30008), "refresh", "DefaultAddonsUpdates.png", "Re-download guide data"),
        ("Your subscriptions", "subscriptions", "DefaultAddonService.png", "Which paid services you have: their titles say Included"),
        ("Status", "status", "DefaultAddonService.png", "Sources and apps"),
        (kodi.localized(30007), "settings", "DefaultAddonService.png", "Sports Hub settings"),
    ]
    i = 0
    for t in tiles:
        if not t:
            continue
        label, action, icon, meta = t
        folder = action not in ("refresh", "settings", "skin", "guide", "subscriptions")
        kodi.add_item(label, kodi.build_url(action=action), folder, art={"icon": icon, "thumb": icon},
                      props={"kind": "tile", "color": MENU_COLORS[i % len(MENU_COLORS)], "meta": meta})
        i += 1
    kodi.end_directory()


def live(home=False):
    kodi.set_content("videos")
    # (no TV Guide card: the header's guide icon is right above this row on the Sports page)
    favs = _favorite_channels_now() if home else []
    for p in favs:
        _add_programme(p, kicker="\u2605 " + (p.get("service") or "").upper())
    from resources.lib import guide
    fav_keys = {guide._key(p["channel"]) for p in favs}
    items = fast.live_now()
    if kodi.setting_bool("src_pvr", True) and pvr.available():
        items += pvr.live_now()
    items = [p for p in _filter_games(items) if guide._key(p["channel"]) not in fav_keys]
    if not items and not favs:
        kodi.add_item(kodi.localized(30020), kodi.build_url(action="root"), False, props={"kind": "tile", "color": "FF3B3F4A"})
    for p in _sorted_live(items):
        _add_programme(p)
    kodi.end_directory()


def _favorite_channels_now():
    """Your ★ sports channels (from the TV Guide's list) with what they're showing now, A-Z, first in Live sports now."""
    from resources.lib import guide
    now = time.time()
    out = []
    for c in guide.favorite_rows():
        if not c.get("sports"):  # the row lives on the Sports page now: ★ sports channels only
            continue
        progs = c["programs"]
        cur = next((i for i in range(len(progs) - 1, -1, -1) if progs[i][0] <= now), None)
        if cur is None:
            continue
        start, title = progs[cur]
        end = progs[cur + 1][0] if cur + 1 < len(progs) else 0
        out.append({"source": c["sid"], "service": c["service"], "channel_id": c["play"].get("id", ""), "channel": c["name"],
                    "title": title, "start": start, "end": end, "sport": "", "logo": c["logo"], "art": c["logo"],
                    "plot": "", "playable": True, "play": c["play"], "alts": c.get("alts") or []})
    keys_seen = set()
    uniq = []
    for p in sorted(out, key=lambda p: p["channel"].lower()):
        k = guide._key(p["channel"])
        if k not in keys_seen:  # same-named regional feeds: the first is enough here
            keys_seen.add(k)
            uniq.append(p)
    return uniq


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


def upnext_action(action, params):
    """Long-press on Up Next: move to the end / back to the front, hide for now; the Hidden card brings back."""
    from resources.lib import upnext
    title, year = params.get("title", ""), params.get("year", "")
    if action == "upnext_top":
        upnext.move_top(title, year)
        kodi.notify("%s moved to the top of Up Next" % title, time_ms=2500)
    elif action == "upnext_up":
        current = [upnext.key(t["title"], t["year"]) for t in upnext.arrange(trakt.up_next(limit=30))]
        upnext.move_up(title, year, current)
        kodi.notify("%s moved up" % title, time_ms=2000)
    elif action == "upnext_back":
        upnext.move_back(title, year)
        kodi.notify("%s moved to the end of Up Next" % title, time_ms=2500)
    elif action == "upnext_front":
        upnext.move_front(title, year)
        kodi.notify("%s is back in its usual place" % title, time_ms=2500)
    elif action == "upnext_hide":
        upnext.hide(title, year, params.get("next", ""))
        kodi.notify("%s hidden - it comes back when you watch an episode" % title, time_ms=3000)
    else:
        hid = upnext.hidden()
        if not hid:
            return
        sel = xbmcgui.Dialog().multiselect("Bring back to Up Next", [n for _, n in hid])
        if not sel:
            return
        upnext.unhide([hid[i][0] for i in sel])
    kodi.run_builtin("SetProperty(sh_refresh,%d,home)" % time.time())  # Up Next reloads in the new order


CAL_COLORS = {"nfl": "FF13294B", "ncaaf": "FF5A1F1F", "nba": "FF1D428A", "ncaab": "FF2F5D3A", "mlb": "FF0E3386", "nhl": "FF2A2A2A"}


def calendars():
    """Sports page row SCHEDULES: one tile per league; each opens the week's calendar (calendarwin)."""
    kodi.set_content("videos")
    from resources.lib import schedule
    mine = {}
    for lid, abbr in espn.my_teams():
        mine.setdefault(lid, []).append(abbr)
    for lid in schedule.ORDER:
        label, _, _, by_week = schedule.LEAGUES[lid]
        meta = ("Your teams: %s" % ", ".join(mine[lid]) if lid in mine else "") or ("By week, by conference" if lid.startswith("ncaa") else "This week, by division")
        kodi.add_item(label, kodi.build_url(action="calendar", league=lid), False, art={"icon": ICON_FOLDER},
                      props={"kind": "tile", "color": CAL_COLORS.get(lid, "FF2A3550"), "title": "%s schedule" % label, "meta": meta})
    kodi.end_directory()


def sports_page():
    """The header's Sports icon: everything sports in one place (Live now and Starting soon left Home)."""
    kodi.set_content("videos")
    stats = espn.counts() if kodi.setting_bool("src_scores", True) else {}
    games = sum(t for _, t, _ in stats.values())
    playing = sum(l for _, _, l in stats.values())
    tiles = [
        ("Live sports now", kodi.build_url(action="live"), "FFE0162B", "Every channel showing sports right now"),
        ("Today's games", kodi.build_url(action="games"), "FF1F3F6E",
         "%d games today, %d live" % (games, playing) if games else "Scores and where to watch"),
        ("Starting soon", kodi.build_url(action="soon"), "FF6E3A1F", "Next %d minutes" % kodi.setting_int("soon_minutes", 120)),
        ("By sport", kodi.build_url(action="sports"), "FF2F5D3A", "Football, basketball, golf... on now"),
    ]
    for label, url, color, meta in tiles:
        kodi.add_item(label, url, True, art={"icon": ICON_FOLDER}, props={"kind": "tile", "color": color, "title": label, "meta": meta})
    kodi.add_item("TV Guide: Sports", kodi.build_url(action="guide", tab="Sports"), False, art={"icon": "DefaultPVRGuide.png"},
                  props={"kind": "guide", "color": "FF8A1F2E", "title": "TV Guide: Sports", "meta": "Every sports channel, now and later"})
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
    from resources.lib import favorites
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
                      context=[(_star(favorites.has_channel(prog["channel"])), "RunPlugin(%s)" % kodi.build_url(action="fav", what="channel", name=prog["channel"])),
                               ("%s schedule" % prog["channel"],
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
        "kicker": ("YOUR TEAM \u2022 " if g.get("my_team") else "") + {"live": g["league"].upper(), "final": "FINAL \u2022 %s" % g["league"].upper(), "upcoming": "%s \u2022 STARTS %s" % (g["league"].upper(), when.upper())}[state],
        "my_team": "1" if g.get("my_team") else "",
        "away": g.get("away_abbr") or "", "home": g.get("home_abbr") or "",
        "meta": " \u2022 ".join(x for x in (g["league"], g["channel"], g["detail"] if g["state"] != "pre" else "") if x),
        "league_logo": g.get("league_logo") or "",
    }
    # which streaming apps carry this game's networks, and are any of them on this device?
    ctx, need = [], ""
    seen_pkgs = set()
    for net in [c.strip() for c in (g["channel"] or "").split(",") if c.strip()]:
        pkg, friendly = apps.for_network(net)
        if not pkg or pkg in seen_pkgs:
            continue
        seen_pkgs.add(pkg)
        ctx.append(("Watch on %s (%s)" % (friendly, net), "RunPlugin(%s)" % kodi.build_url(action="play", src="app", id=pkg, name=friendly)))
        if not need:
            need = friendly
    if seen_pkgs and not any(health.app_installed(p) is not False for p in seen_pkgs):
        props["network"] = "%s • needs %s app" % (props["network"], need)
        props["meta"] = "%s • needs the %s app" % (props["meta"], need)
    from resources.lib import favorites
    gkey = favorites.game_key(g["title"])
    ctx.append((_star(favorites.has(gkey)), "RunPlugin(%s)" % kodi.build_url(action="fav", what="game", key=gkey, label=g["short"] or g["title"],
                                                                               league=g["league"], logo=g["logo"] or "")))
    if PLAIN:
        label = g["short"] or g["title"]
    if g["playable"]:
        kodi.add_item(label, kodi.build_url(action="play", **g["play"]), False, art=art, info=info, props=props, context=ctx)
    else:
        kodi.add_item(label, kodi.build_url(action="games"), False, art=art, info=info, props=props, context=ctx)
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
    if not kodi.setting_bool("src_scores", True):
        # the home row can't vanish (fixed slots), so it says why it's empty and how to change that
        kodi.add_item("Live scores are off", kodi.build_url(action="settings"), False,
                      props={"kind": "tile", "color": "FF3B3F4A", "title": "Live scores are off", "meta": "Turn them on in WatchHub settings > Sources"})
        kodi.end_directory()
        return
    items = espn.games(None if league == "all" else [league])
    if league == "all":
        # your teams lead the row, with their next game even when it isn't today (Sprint D: My teams)
        mine = espn.my_games()
        ids = {g["channel_id"] for g in mine}
        items = mine + [g for g in items if g["channel_id"] not in ids]
    if not items:
        kodi.add_item("No games scheduled", kodi.build_url(action="games"), False,
                      props={"kind": "tile", "color": "FF3B3F4A", "title": "No games scheduled", "meta": "Nothing on today in the leagues WatchHub follows"})
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


def _star(on):
    return "\u2605 Remove from Favorites" if on else "\u2605 Add to Favorites"


def _title_star(t):
    from resources.lib import favorites
    key = favorites.title_key(t["title"], t["year"])
    return (_star(favorites.has(key)), "RunPlugin(%s)" % kodi.build_url(action="fav", what="title", key=key, label=t["title"], year=t["year"],
                                                                        kind=t["type"], poster=t.get("poster") or "", backdrop=t.get("backdrop") or "",
                                                                        service=t.get("service") or ""))


def toggle_favorite(params):
    from resources.lib import favorites
    what = params.get("what")
    if what == "channel":
        added = favorites.toggle_channel(params.get("name", ""))
        name = params.get("name", "")
    else:
        item = {"kind": what, "key": params.get("key", ""), "label": params.get("label", "")}
        for k in ("year", "kind", "poster", "backdrop", "service", "league", "logo"):
            if params.get(k):
                item["type" if k == "kind" else k] = params[k]
        item["kind"] = what
        added = favorites.toggle(item)
        name = item["label"]
    kodi.notify(("Added %s to Favorites" if added else "Removed %s from Favorites") % name, time_ms=2500)
    xbmc.executebuiltin("Container.Refresh")


def favorites_list():
    """The \u2605 screen: favorite channels with what's on now, then shows/movies, games, and Kodi's own favourites."""
    from resources.lib import favorites, guide
    kodi.set_content("videos")
    kodi.set_category("Favorites")
    count = 0
    keys = favorites.channel_keys()
    if keys:
        now = time.time()
        rows = sorted((c for c in guide.channels() if c["key"] in keys), key=lambda c: c["name"].lower())
        shown = set()
        for c in rows:
            if c["key"] in shown:
                continue
            shown.add(c["key"])
            cur, end = None, 0
            for i, (st, title) in enumerate(c["programs"]):
                if st <= now:
                    cur, end = (st, title), (c["programs"][i + 1][0] if i + 1 < len(c["programs"]) else 0)
            p = {"title": cur[1] if cur else c["name"], "start": cur[0] if cur else 0, "end": end, "logo": c["logo"], "art": "",
                 "source": c["sid"], "channel": c["name"], "channel_id": c["play"]["id"], "service": c["service"], "play": c["play"],
                 "alts": c.get("alts") or [], "sport": "", "plot": ""}
            _add_programme(p, kicker="LIVE TV CHANNEL")
            count += 1
    # Live TV channels first (above), then TV shows, movies and games, each A-Z
    group = {"Show": 0, "Movie": 1}
    for it in sorted(favorites.items(), key=lambda x: (2 if x["kind"] == "game" else group.get(x.get("type"), 1), x.get("label", "").lower())):
        star = (_star(True), "RunPlugin(%s)" % kodi.build_url(action="fav", what=it["kind"], key=it["key"], label=it.get("label", "")))
        if it["kind"] == "title":
            props = {"kind": "title", "title": it["label"], "meta": " \u2022 ".join(x for x in (it.get("service"), it.get("type"), it.get("year")) if x),
                     "kicker": "TV SHOW" if it.get("type") == "Show" else "MOVIE", "service": it.get("service") or "", "year": it.get("year") or "", "type": it.get("type") or "", "state": ""}
            art = {"thumb": it.get("poster") or "DefaultVideo.png", "poster": it.get("poster") or "", "fanart": it.get("backdrop") or "",
                   "landscape": it.get("backdrop") or ""}
            kodi.add_item(it["label"], kodi.build_url(action="info", title=it["label"], year=it.get("year", ""), kind=it.get("type", "")), False,
                          art=art, info={"title": it["label"]}, props=props, context=[star])
        else:
            kodi.add_item(it["label"], kodi.build_url(action="games"), True, art={"thumb": it.get("logo") or ICON_LIVE, "icon": it.get("logo") or ICON_LIVE},
                          props={"kind": "tile", "color": "FF22543A", "title": it["label"], "meta": it.get("league") or "Game", "kicker": "GAME"},
                          context=[star])
        count += 1
    for f in favorites.kodi_favourites():
        kodi.add_item(f.get("title") or "Favourite", kodi.build_url(action="exec", cmd=f.get("path") or ""), False,
                      art={"thumb": f.get("thumbnail") or ""}, props={"kind": "tile", "color": "FF3B3F4A", "title": f.get("title") or "",
                                                                       "meta": "From Kodi's favourites"})
        count += 1
    if not count:
        kodi.add_item("No favorites yet", kodi.build_url(action="guide"), False,
                      props={"kind": "tile", "color": "FF3B3F4A", "title": "No favorites yet",
                             "meta": "Long-press a channel, show, movie or game and choose \u2605 Add to Favorites"})
    kodi.end_directory()


def _nice_day(iso):
    """2026-10-16 -> Oct 16"""
    try:
        return time.strftime("%b %d", time.strptime(iso[:10], "%Y-%m-%d")).replace(" 0", " ")
    except (ValueError, TypeError):
        return ""


def _chips(t):
    """The details line under the hero (like Up Next's): service, kind, year, genres, IMDb, length, rating -
    without the row's own prefixes ("Added ...", "Seen")."""
    parts = [x.strip() for x in (t.get("meta") or "").split("\u2022")]
    parts = [x for x in parts if x and not x.startswith(("Added ", "Seen"))]
    parts += [x for x in (t.get("runtime"), t.get("certification")) if x]
    return " \u2022 ".join(parts)


def _add_title(t, extra_ctx=None):
    props = {"kind": "title", "title": t["title"], "meta": t["meta"], "kicker": t.get("kicker") or t["service"].upper(), "service": t["service"],
             "year": str(t["year"]), "type": t["type"], "state": "", "seen": "1" if t.get("seen") else "",
             # the hero's three lines (same layout as Up Next): headline, one-line summary, details
             "episode": t.get("headline") or "", "summary": (t.get("plot") or "").replace("\n", " "), "chips": _chips(t)}
    art = {"thumb": t["poster"] or "DefaultVideo.png", "poster": t["poster"], "landscape": t["backdrop"], "fanart": t["backdrop"]}
    info = {"title": t["title"], "plot": t["plot"], "genre": t["type"]}
    label = t["title"] if PLAIN else "%s [COLOR gray](%s, %s)[/COLOR]" % (t["title"], t["year"], t["service"])
    ctx = [("Play on %s" % t["service"], "RunPlugin(%s)" % kodi.build_url(action="play", **t["play"]))] if t["play"].get("pkg") else []
    for o in (t.get("offers") or [])[(1 if t["play"].get("pkg") else 0):]:
        ctx.append(("Watch on %s · %s" % (o["service"], o["label"]), "RunPlugin(%s)" % kodi.build_url(action="play", src="ondemand", pkg=o["pkg"], url=o["url"], name=o["service"])))
    if tmdb.enabled():
        ctx.append(("Watch trailer", "RunPlugin(%s)" % kodi.build_url(action="trailer", title=t["title"], year=t["year"], kind=t["type"])))
    if trakt.signed_in():
        ctx.append(("Trakt: add to watchlist", "RunPlugin(%s)" % kodi.build_url(action="trakt_watchlist", title=t["title"], year=t["year"], kind=t["type"])))
        if t.get("seen"):  # a SEEN card offers the opposite
            ctx.append(("Trakt: unmark as watched", "RunPlugin(%s)" % kodi.build_url(action="trakt_unwatched", title=t["title"], year=t["year"], kind=t["type"])))
        else:
            ctx.append(("Trakt: mark as watched", "RunPlugin(%s)" % kodi.build_url(action="trakt_watched", title=t["title"], year=t["year"], kind=t["type"])))
    ctx.append(_title_star(t))
    ctx += extra_ctx or []
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
    ctx.append(_title_star(t))
    kodi.add_item(t["title"] if PLAIN else "%s [COLOR gray](%s)[/COLOR]" % (t["title"], nice), kodi.build_url(action="info", title=t["title"], year=t["year"], kind=t["type"]), False,
                  art=art, info={"title": t["title"], "plot": t["plot"]}, props=props, context=ctx)


def trailers_list():
    """Home row TRAILERS: upcoming movies (on your services, then in theaters) that have a trailer; OK plays
    the trailer in YouTube, like the old Apple Trailers app. The hero says when and where it's coming."""
    kodi.set_content("videos")
    streaming = [dict(t, where="on %s" % t["service"]) for t in ondemand.upcoming()]   # JustWatch: names the service
    codes = ondemand.installed_codes()
    for t in (tmdb.coming_soon(codes, "Movie") if tmdb.enabled() else []):
        code = tmdb.service_for(t.get("tmdb_id"), codes) if t.get("tmdb_id") else ""
        streaming.append(dict(t, where="on %s" % ondemand.short_name(code) if code else "on your services"))
    theaters = [dict(t, where="in theaters") for t in (tmdb.upcoming("Movie") if tmdb.enabled() else [])]
    items, seen = [], set()
    today = time.strftime("%Y-%m-%d")
    for rows in (streaming, theaters):
        for t in rows:
            k = (t["title"].lower(), t["year"])
            # TMDB's "upcoming" list keeps films for weeks after they open: only what's still to come
            if k not in seen and t.get("poster") and (t.get("date") or "") > today:
                seen.add(k)
                items.append(t)
    items.sort(key=lambda t: t["date"])
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        urls = list(pool.map(lambda t: tmdb.trailer_url(t["title"], t["year"], "Movie"), items[:60]))
    shown = 0
    for t, url in zip(items, urls):
        if not url:
            continue
        nice = _nice_day(t["date"])
        props = {"kind": "title", "title": t["title"], "kicker": "TRAILER", "state": "upcoming", "type": "Movie", "year": str(t["year"]),
                 "service": "Coming %s" % nice if nice else "Coming soon",
                 "meta": "Coming %s \u2022 %s" % (nice, t["where"]),
                 "episode": "Coming %s \u00b7 %s" % (nice, t["where"]) if nice else "Coming soon \u00b7 %s" % t["where"],
                 "summary": (t.get("plot") or "").replace("\n", " "),
                 "chips": " \u2022 ".join(x for x in ("Movie", str(t["year"]), ("TMDB %.1f" % t["vote"]) if t.get("vote") else "") if x)}
        ctx = [("Watch trailer", "RunPlugin(%s)" % kodi.build_url(action="trailer", title=t["title"], year=t["year"], kind="Movie"))]
        if trakt.signed_in():
            ctx.append(("Trakt: add to watchlist", "RunPlugin(%s)" % kodi.build_url(action="trakt_watchlist", title=t["title"], year=t["year"], kind="Movie")))
        ctx.append(_title_star(t))
        kodi.add_item(t["title"], kodi.build_url(action="trailer", title=t["title"], year=t["year"], kind="Movie"), False,
                      art={"thumb": t["poster"], "poster": t["poster"], "fanart": t.get("backdrop") or "", "landscape": t.get("backdrop") or ""},
                      info={"title": t["title"], "plot": t.get("plot") or ""}, props=props, context=ctx)
        shown += 1
        if shown >= 25:
            break
    kodi.end_directory(view="posters")


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


def _empty_service_tile(svc, what):
    """A provider-view row with nothing in it says so and offers the app, instead of 'Nothing right now'."""
    name = ondemand.short_name(svc)
    pkg = ondemand.BY_CODE[svc][1]
    # the card itself is narrow: "Nothing here / Open Peacock"; the hero above spells out "Nothing to resume on Peacock"
    kodi.add_item("Nothing here[CR]Open %s" % name, kodi.build_url(action="play", src="app", id=pkg, name=name), False,
                  art={"thumb": "androidapp://sources/apps/%s.png" % pkg},
                  props={"kind": "tile", "color": "FF3B3F4A", "title": "%s on %s" % (what, name), "meta": "Open %s to browse it yourself" % name})


def _home_taken(row, svc=""):
    """JustWatch ids already on Home above this row: a title shows once, in its highest row (map 5.4):
    Up Next, then New this week (row 3), then Trending (row 0)."""
    taken = set()
    if trakt.signed_in():
        from resources.lib import upnext
        for t in upnext.arrange(trakt.up_next(limit=60 if svc else 30)):
            od = ondemand.lookup(t["title"], t["year"], t["type"])
            if od and od.get("jw_id"):
                taken.add(od["jw_id"])
    if row == 0:
        taken |= {t["jw_id"] for t in ondemand.row_items(3, svc) if t.get("jw_id")}
    return taken


def ondemand_list(row, svc="", home=False):
    kodi.set_content("videos")
    items = ondemand.row_items(row, svc)
    if home and items:
        taken = _home_taken(row, svc)
        items = [t for t in items if t.get("jw_id") not in taken]
    kind = ondemand.rows()[row][1] if 0 <= row < len(ondemand.rows()) else ""
    for i, t in enumerate(items):
        if kind == "new":
            head = "New on %s" % t["service"] + (" \u00b7 added %s" % _nice_day(t["added"]) if t.get("added") else "")
        elif kind == "trending":
            head = "#%d trending on your services" % (i + 1)
        else:
            head = ""
        _add_title(dict(t, headline=head))
    if not items:
        # a filtered row, or a menu row for one service ("New on Pluto TV"): say so and offer the app
        rows = ondemand.rows()
        codes = rows[row][2]["codes"] if 0 <= row < len(rows) else []
        one = svc or (codes[0] if len(codes) == 1 else "")
        if one in ondemand.BY_CODE:
            _empty_service_tile(one, "Nothing new this week" if rows[row][1] == "new" else "Nothing trending")
    kodi.end_directory(view="posters")


def providers(svc=""):
    """The home screen's Services row: All + each installed service. `svc` = the one selected now; it's
    marked SHOWING and a separate "Open <service>" card follows it (map 3: no "press again to open")."""
    kodi.set_content("videos")
    items = [("", "All services", "", "DefaultVideo.png")] + [
        (c, ondemand.short_name(c), ondemand.BY_CODE[c][1], "androidapp://sources/apps/%s.png" % ondemand.BY_CODE[c][1]) for c in ondemand.installed_codes()]
    for code, name, pkg, thumb in items:
        selected = code == svc
        if selected:
            kicker = "SHOWING"
            meta = ("Showing only %s - Open %s is right next to it" % (name, name)) if code else "Showing everything - pick a service to narrow the rows"
        else:
            kicker = "SERVICES"
            meta = ("Show only %s" % name) if code else "Clear: show every service again"
        kodi.add_item(name, kodi.build_url(action="provider", code=code), False, art={"thumb": thumb, "icon": "DefaultAddonProgram.png"},
                      info={"title": name}, props={"kind": "app", "meta": meta, "kicker": kicker, "selected": "1" if selected else "", "code": code})
        if selected and code:
            label = "Open %s" % name
            kodi.add_item(label, kodi.build_url(action="play", src="app", id=pkg, name=name), False,
                          art={"thumb": thumb, "icon": "DefaultAddonProgram.png"}, info={"title": label},
                          props={"kind": "app", "open": "1", "kicker": "OPEN APP", "code": "open:" + code,
                                 "meta": "Go to the %s app to browse its own menus" % name})
    if not svc:
        from resources.lib import settingsmenu
        missing = settingsmenu.missing_free_apps()
        if missing:  # F5: a free service this Shield could have
            kodi.add_item("Free services", kodi.build_url(action="free_apps"), False, art={"thumb": "DefaultAddSource.png", "icon": "DefaultAddSource.png"},
                          info={"title": "Free services"}, props={"kind": "app", "kicker": "ADD", "code": "free",
                                                                 "meta": "Not on this Shield yet: %s - choose one to get it" % ", ".join(missing)})
    kodi.end_directory()


def pick_provider(code):
    """Services row click: narrow the home rows to one service (or back to All). Pressing the selected one
    again still opens its app (the Open card next to it is the visible way)."""
    if code and code == homefilter.current():
        launcher.play({"src": "app", "id": ondemand.BY_CODE[code][1], "name": ondemand.short_name(code)})
        return
    code = homefilter.apply(code)
    homefilter.save(code)
    homefilter.focus(code)


def search(query=None):
    """Search movies/shows on the user's services and live channels by name."""
    kodi.set_content("videos")
    if query is None:
        query = xbmcgui.Dialog().input("Search", type=xbmcgui.INPUT_ALPHANUM)
        if not query:
            kodi.end_directory(succeeded=False)
            return
        # show the results right here: ending this listing as "failed" and re-entering with
        # Container.Update sent Kodi back to its generic Videos page when Search was opened from home
    q = query.lower()
    # Live now, then shows and movies you can watch, then the ones that aren't on your services (map 2: Search)
    for p in fast.live_now():
        if q in p["channel"].lower() or q in p["title"].lower():
            _add_programme(p)
    found = ondemand.search(query)
    mine = [t for t in found if t["playable"]]
    for t in [t for t in mine if t["type"] == "Show"] + [t for t in mine if t["type"] != "Show"]:
        _add_title(t)
    for t in [t for t in found if not t["playable"]]:
        rent = next((o for o in t.get("offers") or [] if o["label"].startswith(("Rent", "Buy"))), None)
        where = ("%s \u00b7 %s" % (rent["label"], rent["service"]) if rent else
                 "On %s" % ", ".join(t["where"][:2]) if t.get("where") else "Not on your services")
        _add_title(dict(t, service=where, kicker="NOT ON YOUR SERVICES"))
    kodi.end_directory(view="posters")


def _trakt_item(t, kicker, meta_extra="", extra_props=None, url_extra=None, extra_ctx=None):
    """A Trakt title -> card. Availability/deep link comes from JustWatch by name; falls back to a search."""
    od = ondemand.lookup(t["title"], t["year"], t["type"])
    if od:
        od = dict(od)
        chips = od["meta"]  # the title's own line, without the episode in front (Up Next hero)
        od["meta"] = " \u2022 ".join(x for x in (meta_extra, od["meta"]) if x)
        od["service"] = od["service"]
        props = {"kind": "title", "title": t["title"], "meta": od["meta"], "kicker": kicker or od["service"].upper(), "service": od["service"],
                 "year": str(t["year"]), "type": t["type"], "state": "", "chips": chips}
        art = {"thumb": od["poster"] or "DefaultVideo.png", "poster": od["poster"], "landscape": od["backdrop"], "fanart": od["backdrop"]}
        plot = od["plot"]
    else:
        props = {"kind": "title", "title": t["title"], "meta": meta_extra or t["type"], "kicker": kicker, "service": "", "year": str(t["year"]), "type": t["type"], "state": ""}
        art = {"thumb": "DefaultVideo.png"}
        plot = ""
    url = kodi.build_url(action="info", title=t["title"], year=t["year"], kind=t["type"], **(url_extra or {}))
    props.update(extra_props or {})
    # same order as every other poster: Play, trailer, Trakt, Favorites
    ctx = []
    if od and od.get("play", {}).get("pkg"):
        ctx.append(("Play on %s" % od["service"], "RunPlugin(%s)" % kodi.build_url(action="play", **od["play"])))
    ctx += extra_ctx or []
    if tmdb.enabled():
        ctx.append(("Watch trailer", "RunPlugin(%s)" % kodi.build_url(action="trailer", title=t["title"], year=t["year"], kind=t["type"])))
    ctx.append(("Trakt: mark as watched", "RunPlugin(%s)" % kodi.build_url(action="trakt_watched", title=t["title"], year=t["year"], kind=t["type"])))
    ctx.append(_title_star({"title": t["title"], "year": t["year"], "type": t["type"], "poster": art.get("poster") or "",
                            "backdrop": art.get("fanart") or "", "service": props.get("service") or ""}))
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


def _episode_summary(t):
    """One line about the next episode (JustWatch's season data, cached a day), or ""."""
    try:
        for sn in ondemand.seasons(t["title"], t["year"]):
            if sn["number"] == t["season"]:
                for e in sn["episodes"]:
                    if e["number"] == t["number"]:
                        return e["overview"]
    except Exception as exc:
        kodi.log("episode summary for %s failed: %s" % (t["title"], exc))
    return ""


def _recommended(svc=""):
    """Home row "Recommended for you": Trakt's picks from your history, only titles on your services, none
    already in Up Next or New this week, no movies you've seen; shows and movies taking turns."""
    shows = trakt.recommendations("shows")
    movies = trakt.recommendations("movies")
    mixed = [x for pair in zip(shows, movies) for x in pair] + shows[len(movies):] + movies[len(shows):]
    seen = trakt.watched_movie_ids()
    taken = _home_taken(3, svc) | {t["jw_id"] for t in ondemand.row_items(3, svc) if t.get("jw_id")}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        found = list(pool.map(lambda x: ondemand.lookup(x["title"], x["year"], x["type"]), mixed))
    shown = 0
    for x, od in zip(mixed, found):
        if not od or not od.get("playable") or not od.get("play", {}).get("pkg") or od.get("jw_id") in taken:
            continue
        if svc and not _on_service({"title": x["title"], "year": x["year"], "type": x["type"]}, svc):
            continue
        ids = x["ids"]
        if x["type"] == "Movie" and (str(ids.get("tmdb") or "") in seen["tmdb"] or (ids.get("imdb") or "") in seen["imdb"]):
            continue
        taken.add(od.get("jw_id"))
        head = "Picked for you by Trakt" + (" \u00b7 rated %.1f" % x["rating"] if x["rating"] else "")
        _add_title(dict(od, headline=head, kicker="RECOMMENDED FOR YOU"))
        shown += 1
        if shown >= 20:
            break
    kodi.end_directory(view="posters")


def trakt_list(row, svc=""):
    kodi.set_content("videos")
    if row == "upnext":
        if not trakt.signed_in():
            # on the home screen this row would otherwise vanish, leaving no hint that Trakt exists
            if trakt.configured():
                kodi.add_item("Sign in[CR]to Trakt", kodi.build_url(action="trakt_signin"), False, props={"kind": "tile", "color": "FF8A1F2E", "title": "Sign in to Trakt", "meta": "Remember what you watch, get new-season alerts"})
            kodi.end_directory()
            return
        # a service view filters the list, so look further down the history first (the All view's top 20
        # can easily contain nothing from that service)
        picks = []
        from resources.lib import upnext
        for t in upnext.arrange(trakt.up_next(limit=60 if svc else 30)):
            if svc and not _on_service(t, svc):
                continue
            picks.append(t)
            if len(picks) >= 20:
                break
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            summaries = list(pool.map(_episode_summary, picks))
        shown = 0
        for t, summary in zip(picks, summaries):
            # the hero (map 5.3): "Season 2 · Episode 4 — The Bigger Picture", its summary, "Watched 11 of 16 episodes"
            ep = "Season %s \u00b7 Episode %s" % (t["season"], t["number"]) + (" \u2014 %s" % t["episode_title"] if t["episode_title"] else "")
            props = {"episode": ep, "summary": summary,
                     "progress_text": "Watched %d of %d episodes" % (t["completed"], t["aired"]) if t["aired"] else "",
                     "progress": str(int(100 * t["completed"] / t["aired"])) if t["aired"] else ""}
            ty = {"title": t["title"], "year": t["year"]}
            order = [("Move to the top of Up Next", "RunPlugin(%s)" % kodi.build_url(action="upnext_top", **ty)),
                     ("Move up one", "RunPlugin(%s)" % kodi.build_url(action="upnext_up", **ty)),
                     ("Move to the end of Up Next", "RunPlugin(%s)" % kodi.build_url(action="upnext_back", **ty))]
            if upnext.is_moved(t["title"], t["year"]):
                order.append(("Put back in its usual place", "RunPlugin(%s)" % kodi.build_url(action="upnext_front", **ty)))
            order.append(("Hide from Up Next for now", "RunPlugin(%s)" % kodi.build_url(action="upnext_hide", next=t["next"], **ty)))
            _trakt_item(t, "UP NEXT", "%s %s" % (t["next"], t["episode_title"]), extra_props=props,
                        url_extra={"season": t["season"], "episode": t["number"]}, extra_ctx=order)
            shown += 1
        hid = upnext.hidden()
        if hid and not svc:
            kodi.add_item("Hidden (%d)[CR]from Up Next" % len(hid), kodi.build_url(action="upnext_hidden"), False,
                          art={"icon": ICON_FOLDER},
                          props={"kind": "tile", "color": "FF3B3F4A", "title": "Hidden from Up Next",
                                 "meta": "Bring back: " + ", ".join(n for _, n in hid[:4]) + ("..." if len(hid) > 4 else "")})
        if svc and not shown and svc in ondemand.BY_CODE:
            _empty_service_tile(svc, "Nothing to resume")
    elif row == "recommended":
        _recommended(svc)
        return
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
    # first card: the full guide (kind "guide": the home row runs it instead of opening a folder)
    kodi.add_item("TV Guide", kodi.build_url(action="guide"), False, art={"icon": "DefaultPVRGuide.png"},
                  props={"kind": "guide", "color": "FF8A1F2E", "title": "TV Guide", "meta": "Every free channel - what's on now and later"})
    for i, (name, n) in enumerate(groups):
        kodi.add_item(name, kodi.build_url(action="tvgroup", name=name), True, art={"icon": ICON_FOLDER},
                      props={"kind": "tile", "color": palette[i % len(palette)], "meta": "%d channels" % n})
    kodi.end_directory()


def browse_tiles():
    """Home row BROWSE: the TV Guide, then one tile per category (Browse screen: live now + on your services)."""
    kodi.set_content("videos")
    from resources.lib import browse, guide
    kodi.add_item("TV Guide", kodi.build_url(action="guide"), False, art={"icon": "DefaultPVRGuide.png"},
                  props={"kind": "guide", "color": "FF8A1F2E", "title": "TV Guide", "meta": "Every free channel - what's on now and later"})
    for cat, n, on_demand in browse.tiles():
        meta = ", ".join(x for x in ("%d channel%s" % (n, "" if n == 1 else "s") if n else "", "shows & movies" if on_demand else "") if x)
        kodi.add_item(cat, kodi.build_url(action="browse", cat=cat), False, art={"icon": ICON_FOLDER},
                      props={"kind": "tile", "color": guide.TILE_COLORS.get(cat, "FF2A3550"), "meta": meta})
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
    counts = apps.launch_counts()
    wanted = sorted(((v.get("count", 0), k[len("needed:"):]) for k, v in counts.items() if k.startswith("needed:")), reverse=True)
    if wanted:
        names = dict((p, n) for n, p in apps.LAUNCHABLE)
        kodi.log("apps wanted but not installed: %s" % ", ".join("%s x%d" % (names.get(p, p), c) for c, p in wanted))
    for name, pkg in apps.LAUNCHABLE:
        if installed and pkg not in installed:
            continue
        n = (counts.get(pkg) or {}).get("count", 0)
        used = ("Opened from WatchHub %d time%s, last %s" % (n, "" if n == 1 else "s", time.strftime("%b %d", time.localtime(counts[pkg]["last"])).replace(" 0", " "))
                if n else "Not opened from WatchHub yet")
        kodi.add_item(name, kodi.build_url(action="play", src="app", id=pkg, name=name), False,
                      art={"thumb": "androidapp://sources/apps/%s.png" % pkg, "icon": "DefaultAddonProgram.png"},
                      info={"title": name, "plot": "Open %s" % name}, props={"kind": "app", "meta": "Open %s - %s" % (name, used), "package": pkg})
    kodi.end_directory()


def switch_skin(name):
    """Switch Kodi's skin (user-initiated from the menu / the skin's own 'classic look' card)."""
    kodi.resolve_none()
    if name != "skin.sportshub" and not xbmcgui.Dialog().yesno(
            "Classic Kodi look", "Switch to Kodi's standard look (Estuary)?\n\n"
            "To come back: open the WatchHub add-on and choose \"WatchHub look (skin)\"."):
        return
    if name != "skin.sportshub":
        # WatchHub turned off Kodi's "< Back" list items for its own skin; the classic look expects them
        kodi.jsonrpc("Settings.SetSettingValue", {"setting": "filelists.showparentdiritems", "value": True})
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


def pick_subscriptions():
    """Tick the paid services you have; titles on them are labelled Included and play first."""
    codes = [c for c in ondemand.installed_codes() if c not in ondemand.FREE_CODES]
    if not codes:
        kodi.notify("No paid streaming apps on this device")
        return
    have = ondemand.subscriptions()
    names = [ondemand.short_name(c) for c in codes]
    picked = xbmcgui.Dialog().multiselect("Your subscriptions", names, preselect=[i for i, c in enumerate(codes) if c in have])
    if picked is None:
        return
    # keep confirmed services whose app isn't on this device (another Shield may have it)
    keep = sorted(c for c in have if c not in codes)
    kodi.ADDON.setSetting("subscriptions", ",".join(keep + [codes[i] for i in picked]))
    kodi.notify("Subscriptions saved")
    kodi.run_builtin("SetProperty(sh_refresh,%d,home)" % time.time())  # home rows reload with the new labels


def rediscover_list():
    """Home's Rediscover row: today's 1985-2015 picks; long-press adds More like this / Hide (and Undo)."""
    from resources.lib import rediscover
    kodi.set_content("videos")
    undo = rediscover.undo_candidate()
    for t in rediscover.today():
        t = dict(t, meta=("Seen \u2022 " if t["seen"] else "") + t["meta"],
                 headline="From %s" % t["year"] + (" \u00b7 you've seen it" if t["seen"] else " \u00b7 one you haven't seen"))
        ctx = [("Show me 20 different movies", "RunPlugin(%s)" % kodi.build_url(action="rediscover_new", id=t["jw_id"])),
               ("More like this", "RunPlugin(%s)" % kodi.build_url(action="rediscover_like", id=t["jw_id"])),
               ("Hide this movie", "RunPlugin(%s)" % kodi.build_url(action="rediscover_hide", id=t["jw_id"]))]
        if undo:
            ctx.append(("Undo hide (%s)" % undo[1], "RunPlugin(%s)" % kodi.build_url(action="rediscover_unhide", id=undo[0])))
        _add_title(t, ctx)
    kodi.end_directory(view="posters")


def rediscover_feedback(action, jw_id):
    from resources.lib import rediscover
    if action == "rediscover_like":
        t = rediscover.like(jw_id)
        kodi.notify("Rediscover: more like %s from tomorrow" % t["title"] if t else "Rediscover: movie not found")
        return
    if action == "rediscover_new":
        # the next 20 are normally ready (the service keeps a set): swap them in and reload just this row
        ready = rediscover.reshuffle()
        if not ready:
            kodi.run_builtin("ActivateWindow(busydialognocancel)")
            try:
                rediscover.today()
            finally:
                kodi.run_builtin("Dialog.Close(busydialognocancel)")
        kodi.run_builtin("SetProperty(sh_rediscover,%d,home)" % time.time())  # only the Rediscover row reloads
        kodi.notify("Rediscover: 20 different movies", time_ms=2500)
        rediscover.prepare_next()  # and the set after that, while you look at these
        return
    if action == "rediscover_hide":
        t = rediscover.find(jw_id)
        rediscover.hide(jw_id)
        kodi.notify("%s hidden. Undo: long-press a Rediscover movie" % (t["title"] if t else "Movie"), time_ms=6000)
    else:
        rediscover.unhide(jw_id)
        kodi.notify("Back in Rediscover")
    # reload the rows, then put focus back on the same row and place (the hidden card's neighbour)
    homefilter.remember_spot()
    spot = homefilter.pending_spot()
    kodi.run_builtin("SetProperty(sh_refresh,%d,home)" % time.time())
    if spot:
        if action == "rediscover_hide":
            spot["label"] = ""  # that card is gone: its neighbour takes the same place
        homefilter.restore_spot(spot, timeout_s=10, after_reload=True)
        homefilter.forget_spot()


# ---------------------------------------------------------------- router
# Home rows that keep a snapshot, and how old a snapshot may be when Kodi starts (live rows go stale fast).
ROW_MAX_AGE = {"live": 600, "soon": 600, "games": 600, "sports": 600, "trakt": 2 * 86400, "ondemand": 2 * 86400,
               "rediscover": 2 * 86400, "browse_tiles": 2 * 86400, "providers": 2 * 86400, "trailers": 86400}


def _inputs_stamp():
    """Changes whenever a setting or a favorites/hidden list changes, from anywhere (Kodi's settings screen
    doesn't bump the Home refresh counter): a snapshot made before that can't be shown."""
    import os
    parts = ["v" + kodi.ADDON.getAddonInfo("version")]  # an update changes what rows show: rebuild them once
    for name in ("settings.xml", "favorites.json", "upnext_order.json", "guide_favorites.json", "guide_hidden.json", "rediscover.json"):
        try:
            parts.append("%s:%d" % (name, os.path.getmtime(os.path.join(kodi.PROFILE_PATH, name))))
        except OSError:
            parts.append("%s:-" % name)
    # off-device runs (tools/dev_run.py) set settings and installed apps through SH_* variables
    parts += sorted("%s=%s" % kv for kv in os.environ.items() if kv[0].startswith("SH_"))
    return "|".join(parts)


def _home_row(params):
    """A home row from its snapshot, rebuilt behind it when that helps.

    r (the Home refresh counter) is empty right after Kodi starts: then any snapshot young enough is shown
    at once and the row is rebuilt quietly afterwards; if it changed, the service reloads the rows when
    nobody is scrolling. A row asked for again with the same r (back on Home) shows its snapshot. A new r
    means something changed on purpose (marked watched, a filter, a setting, fresh data): build as usual."""
    action = params["action"]
    key = json.dumps({k: v for k, v in sorted(params.items()) if k != "r"})
    r = params.get("r", "")
    snap = kodi.load_row(key)
    stamp = _inputs_stamp()
    age = time.time() - snap["at"] if snap else None
    usable = snap is not None and snap.get("stamp") == stamp and age < ROW_MAX_AGE[action] and (
        r == "" or snap.get("r") == r or (snap.get("fresh") and age < 300))
    if usable:
        t = time.time()
        kodi.replay_row(snap)
        kodi.log("row %s from its snapshot (%d s old) in %.2fs" % (action, age, time.time() - t))
        if r != "":
            if snap.get("r") != r:
                kodi.save_row(key, dict(snap, r=r, fresh=False))
            return
        # start-up: let every row get on screen first; ten rows rebuilding at once slowed the others' replays
        if xbmc.Monitor().waitForAbort(20):
            return
    kodi.record_start(dry=usable)
    try:
        dispatch(dict(params, _norow="1"))
    finally:
        items, view = kodi.record_stop()
    kodi.save_row(key, {"at": time.time(), "r": r, "stamp": stamp, "items": items, "view": view, "fresh": usable})
    if usable and [i[:2] for i in items] != [i[:2] for i in snap["items"]]:
        xbmcgui.Window(10000).setProperty("sh_rows_stale", str(int(time.time())))
        kodi.log("row %s changed since its snapshot: reload asked" % action)


def dispatch(params):
    global PLAIN
    action = params.get("action", "root")
    PLAIN = params.get("skin") == "1" or xbmc.getSkinDir() == "skin.sportshub"
    if params.get("skin") == "1" and action in ROW_MAX_AGE and kodi.HANDLE >= 0 and not params.get("_norow"):
        return _home_row(params)
    kodi.log("dispatch handle=%s %s" % (kodi.HANDLE, params))
    categories = {
        "root": "Menu", "sports_page": "Sports", "live": "Live Now", "soon": "Starting Soon", "sports": "By Sport", "sport": params.get("name", "Sport"),
        "services": "By Service", "service": fast.SERVICES.get(params.get("id", ""), {}).get("name", "Service"),
        "channel": "Channel", "pvr": "Live TV", "pvr_all": "All Live TV channels", "tv": "TV Schedule",
        "games": "Today's Games" if not params.get("league") else espn.BY_ID.get(params.get("league"), ("", "", "Today's Games", ""))[2],
        "youtube": "YouTube", "apps": "Your Apps", "tvgroups": "Free Live TV", "ondemand": "What's Streaming", "search": "Search", "coming": "Coming soon", "trakt": "My Shows & Movies", "ondemand_search": "Where to watch", "tvgroup": params.get("name", "Free Live TV"), "status": "Status",
    }
    kodi.set_category(categories.get(action, ""))
    if action == "root":
        root()
    elif action == "live":
        live(home=params.get("skin") == "1")
    elif action == "soon":
        soon()
    elif action == "sports":
        sports_menu()
    elif action == "sports_page":
        sports_page()
    elif action == "calendars":
        calendars()
    elif action == "trailers":
        trailers_list()
    elif action == "calendar":
        kodi.resolve_none()
        from resources.lib import calendarwin, uiworker
        if not uiworker.request(kodi.build_url(action="calendar", league=params.get("league", "nfl"))):
            calendarwin.show(params.get("league", "nfl"))
    elif action in ("upnext_top", "upnext_up", "upnext_back", "upnext_front", "upnext_hide", "upnext_hidden"):
        kodi.resolve_none()
        upnext_action(action, params)
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
        ondemand_list(int(row), params.get("svc", ""), home=params.get("home") == "1") if row is not None else ondemand_menu()
    elif action == "providers":
        providers(params.get("svc", ""))
    elif action == "provider":
        kodi.resolve_none()
        pick_provider(params.get("code", ""))
    elif action == "info":
        kodi.resolve_none()
        # the always-running service shows the page (the skin's poster rows ask it directly, without this step)
        from resources.lib import uiworker
        ep = {k: params[k] for k in ("season", "episode") if params.get(k)}
        if not uiworker.request(kodi.build_url(action="info", title=params.get("title", ""), year=params.get("year", ""), kind=params.get("kind", ""), **ep)):
            infodialog.show_by_title(params.get("title", ""), params.get("year", ""), params.get("kind", ""), **ep)
    elif action == "search":
        search(params.get("q"))
    elif action == "favorites":
        favorites_list()
    elif action == "fav":
        kodi.resolve_none()
        toggle_favorite(params)
    elif action == "exec":
        kodi.resolve_none()
        cmd = params.get("cmd", "")
        if cmd.startswith(("RunPlugin(", "ActivateWindow(", "PlayMedia(", "RunAddon(", "StartAndroidActivity(")):
            xbmc.executebuiltin(cmd)
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
    elif action in ("trakt_watched", "trakt_watchlist", "trakt_unwatched"):
        kodi.resolve_none()
        ids = trakt.search_ids(params.get("title", ""), params.get("year", ""), params.get("kind", "Show"))
        if not ids:
            kodi.notify("Trakt: title not found")
        elif action in ("trakt_watched", "trakt_unwatched"):
            seen = action == "trakt_watched"
            ok = (trakt.mark_watched if seen else trakt.unmark_watched)(params.get("kind", "Show"), ids)
            kodi.notify(("Marked as watched" if seen else "No longer marked as watched") if ok else "Trakt: failed")
            from resources.lib import rediscover
            if ok and params.get("kind") == "Movie" and rediscover.mark_seen(params.get("title", ""), params.get("year", ""), seen):
                # a Rediscover card: SEEN right away, only that row reloads, focus stays on the same poster
                homefilter.remember_spot()
                spot = homefilter.pending_spot()
                kodi.run_builtin("SetProperty(sh_rediscover,%d,home)" % time.time())
                if spot:
                    homefilter.restore_spot(spot, timeout_s=10, after_reload=True)
                    homefilter.forget_spot()
                trakt.forget_watched()
                return
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
    elif action == "free_apps":
        kodi.resolve_none()
        from resources.lib import settingsmenu
        settingsmenu.free_apps()
    elif action == "subscriptions":
        kodi.resolve_none()
        pick_subscriptions()
    elif action == "guide":
        kodi.resolve_none()
        from resources.lib import guide, uiworker
        if not uiworker.request(kodi.build_url(action="guide", tab=params.get("tab") or "")):
            guide.show(params.get("tab") or None)
    elif action == "rediscover":
        rediscover_list()
    elif action in ("rediscover_like", "rediscover_hide", "rediscover_unhide", "rediscover_new"):
        kodi.resolve_none()
        rediscover_feedback(action, params.get("id", ""))
    elif action == "browse_tiles":
        browse_tiles()
    elif action == "browse":
        kodi.resolve_none()
        from resources.lib import browse, uiworker
        if not uiworker.request(kodi.build_url(action="browse", cat=params.get("cat", ""))):
            browse.show(params.get("cat", ""))
    elif action == "settings":
        kodi.resolve_none()
        # WatchHub's own settings (plain words); its last entry opens Kodi's full settings screen
        from resources.lib import uiworker
        if not uiworker.request(kodi.build_url(action="wh_settings")):
            from resources.lib import settingsmenu
            settingsmenu.show()
    else:
        kodi.notify("Unknown action %s" % action, icon=xbmcgui.NOTIFICATION_WARNING)
        root()
