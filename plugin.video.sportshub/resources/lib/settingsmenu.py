"""WatchHub settings from the header's gear, in plain words (Sprint C: settings inside the skin).

The everyday choices (your subscriptions, Prime Video channels, which free live-TV services feed the
guide and in what order, Spanish channels, your local stations, Rediscover, Trakt) without Kodi's
settings screen; "All settings" still opens it. Runs in the background service (uiworker), so a
change to the guide's sources rebuilds the guide right away.
"""
import time

import xbmcgui

from resources.lib import kodi
from resources.lib.sources import espn, fast, ondemand, trakt

LIVE_SERVICES = [sid for sid in fast.SERVICES if fast.SERVICES[sid]["package"]]


BY_LEAGUE = {"nfl": "NFL", "nba": "NBA", "mlb": "MLB", "nhl": "NHL"}
_teams = []


def _team_names():
    if not _teams:
        try:
            _teams.extend(espn.all_teams())
        except Exception as exc:
            kodi.log("settings: team list failed: %s" % exc)
    return _teams


# the free services WatchHub uses; the agreed app set for every Shield (Oct 15) has the first three
FREE_APPS = [("Pluto TV", "tv.pluto.android"), ("Plex", "com.plexapp.android"), ("The Roku Channel", "com.roku.web.trc"),
             ("Tubi", "com.tubitv"), ("Xumo Play", "com.xumo.xumo.tv"), ("YouTube", "com.google.android.youtube.tv")]


def _local_line():
    """'Automatic - Pittsburgh (KDKA, WPXI...)' or the words typed in."""
    words = kodi.setting("local_market", "auto")
    if words.strip().lower() != "auto":
        return words or "none"
    from resources.lib import location
    data = location.load()
    if not data.get("market"):
        return "Automatic - finding where this Shield is"
    calls = data.get("calls") or []
    return "Automatic - %s%s (where this Shield appears to be)" % (data["market"], " · " + ", ".join(calls[:6]) if calls else "")


def free_apps():
    """The free services' apps, installed or not; picking a missing one opens its Play Store page (True)."""
    from resources.lib import health
    rows = [(name, pkg, health.app_installed(pkg)) for name, pkg in FREE_APPS]
    labels = ["%s  -  %s" % (n, "installed" if ok is not False else "not installed: choose to get it") for n, p, ok in rows]
    i = xbmcgui.Dialog().select("Free apps (the same on every Shield)", labels)
    if i >= 0 and rows[i][2] is False:
        health.open_play_store(rows[i][1])
        return True
    return False


def missing_free_apps():
    from resources.lib import health
    return [n for n, p in FREE_APPS if health.app_installed(p) is False]


def _free_apps_line():
    from resources.lib import health
    missing = [n for n, p in FREE_APPS if health.app_installed(p) is False]
    return ("All %d installed" % len(FREE_APPS)) if not missing else "Missing: %s" % ", ".join(missing)


def _names(codes):
    return ", ".join(ondemand.short_name(c) for c in codes) or "none"


def _rows_line():
    from resources.lib import homerows
    d = homerows.load()
    shown = [homerows.ROWS[r] for r in d["order"] if r not in d["hidden"]]
    return "Order: " + ", ".join(shown) + (" (%d hidden)" % len(d["hidden"]) if d["hidden"] else "")


def _on(flag):
    return "On" if flag else "Off"


def show():
    changed_guide = False
    changed_rows = False
    pos = 0
    for _ in range(100):  # back to the list after each change; Back leaves
        subs = [c for c in ondemand.installed_codes() if c in ondemand.subscriptions()]
        prime = [x.strip() for x in kodi.setting("amazon_channels").split(",") if x.strip()]
        live = [sid for sid in LIVE_SERVICES if kodi.setting_bool(fast.SERVICES[sid]["setting"], True)]
        from resources.lib import health
        missing = {sid for sid in LIVE_SERVICES if health.app_installed(fast.SERVICES[sid]["package"]) is False}
        order = fast.service_priority()
        entries = [
            ("rows", "Home screen rows", _rows_line()),
            ("subs", "Your subscriptions", _names(subs)),
            ("prime", "Prime Video channels you pay for", ", ".join(n.replace(" (Prime)", "") for c, n in ondemand.AMAZON_CHANNELS if c in prime) or "none"),
            ("live", "Free live TV in the guide", ", ".join(fast.SERVICES[s]["name"] + (" (no app)" if s in missing else "") for s in live) or "none"),
            ("order", "When a channel is on several services, play it on", " → ".join(fast.SERVICES[s]["name"] for s in order if s in LIVE_SERVICES)),
            ("spanish", "Hide Spanish-language channels", _on(kodi.setting_bool("hide_spanish", True))),
            ("local", "Your local stations", _local_line()),
            ("teams", "Your teams (first in Today's Games)", ", ".join(n for lid, a, n in _team_names() if (lid, a) in set(espn.my_teams())) or "none"),
            ("unseen", "Rediscover: only movies I haven't seen", _on(kodi.setting_bool("rediscover_unseen_only", False))),
            ("free", "Free apps on this Shield", _free_apps_line()),
            ("trakt", "Trakt", "Signed in" if trakt.signed_in() else "Not signed in - choose to sign in"),
            ("all", "All settings", "Kodi's full settings screen for WatchHub"),
            ("about", "About WatchHub", "Version %s - what's new in each release" % kodi.ADDON.getAddonInfo("version")),
        ]
        items = []
        for _, label, value in entries:
            li = xbmcgui.ListItem(label, value)
            items.append(li)
        pick = xbmcgui.Dialog().select("WatchHub settings", items, preselect=pos, useDetails=True)
        if pick < 0:
            break
        pos = pick
        key = entries[pick][0]
        if key == "rows":
            from resources.lib import homerows
            homerows.edit()
            break  # the skin reloads with the new order
        elif key == "subs":
            from resources.lib import ui
            ui.pick_subscriptions()
            changed_rows = True
        elif key == "prime":
            names = [n.replace(" (Prime)", "") for _, n in ondemand.AMAZON_CHANNELS]
            sel = xbmcgui.Dialog().multiselect("Prime Video channels you pay for", names,
                                               preselect=[i for i, (c, _) in enumerate(ondemand.AMAZON_CHANNELS) if c in prime])
            if sel is not None:
                kodi.ADDON.setSetting("amazon_channels", ",".join(ondemand.AMAZON_CHANNELS[i][0] for i in sel))
                changed_rows = True
        elif key == "live":
            names = [fast.SERVICES[s]["name"] + (" (app not on this Shield)" if s in missing else "") for s in LIVE_SERVICES]
            sel = xbmcgui.Dialog().multiselect("Free live TV in the guide", names,
                                               preselect=[i for i, s in enumerate(LIVE_SERVICES) if s in live])
            if sel is not None:
                for i, s in enumerate(LIVE_SERVICES):
                    kodi.ADDON.setSetting(fast.SERVICES[s]["setting"], "true" if i in sel else "false")
                changed_guide = True
        elif key == "order":
            left = [s for s in order if s in LIVE_SERVICES]
            new = []
            while len(left) > 1:
                i = xbmcgui.Dialog().select("Play on which first? (%d of %d)" % (len(new) + 1, len(new) + len(left)),
                                            [fast.SERVICES[s]["name"] for s in left])
                if i < 0:
                    new = []
                    break
                new.append(left.pop(i))
            if new:
                rest = [s for s in order if s not in new + left]
                kodi.ADDON.setSetting("service_priority", ",".join(new + left + rest))
                changed_guide = True
        elif key == "spanish":
            kodi.ADDON.setSetting("hide_spanish", "false" if kodi.setting_bool("hide_spanish", True) else "true")
            changed_guide = True
        elif key == "local":
            auto = kodi.setting("local_market", "auto").strip().lower() == "auto"
            how = xbmcgui.Dialog().select("Your local stations", [
                "Automatic: wherever this Shield is (%s)" % (_local_line() if auto else "follows the internet connection; a VPN counts"),
                "Type my own city and call letters"])
            if how == 0 and not auto:
                kodi.ADDON.setSetting("local_market", "auto")
                from resources.lib import location
                location.detect(force=True)
                changed_guide = True
            elif how == 1:
                text = xbmcgui.Dialog().input("Your city and stations' call letters, comma-separated",
                                              "" if auto else kodi.setting("local_market", ""))
                if text and text != kodi.setting("local_market", ""):
                    kodi.ADDON.setSetting("local_market", text)
                    changed_guide = True
        elif key == "teams":
            teams = _team_names()
            mine = set(espn.my_teams())
            sel = xbmcgui.Dialog().multiselect("Your teams", ["%s (%s)" % (n, BY_LEAGUE.get(lid, lid)) for lid, a, n in teams],
                                               preselect=[i for i, (lid, a, n) in enumerate(teams) if (lid, a) in mine])
            if sel is not None:
                kodi.ADDON.setSetting("my_teams", ",".join("%s:%s" % (teams[i][0], teams[i][1].lower()) for i in sel))
                changed_rows = True
        elif key == "unseen":
            kodi.ADDON.setSetting("rediscover_unseen_only", "false" if kodi.setting_bool("rediscover_unseen_only", False) else "true")
            _new_rediscover_day()
            changed_rows = True
        elif key == "free":
            if free_apps():
                break
        elif key == "trakt":
            if not trakt.signed_in():
                kodi.run_builtin("RunPlugin(%s)" % kodi.build_url(action="trakt_signin"))
                break
            kodi.notify("Trakt is signed in on this Shield")
        elif key == "all":
            kodi.run_builtin("Addon.OpenSettings(%s)" % kodi.ADDON_ID)
            break
        elif key == "about":
            xbmcgui.Dialog().textviewer("About WatchHub", about_text())
    if changed_guide:
        from resources.lib import guide
        guide._rebuild_in_background()
    if changed_guide or changed_rows:
        kodi.run_builtin("SetProperty(sh_refresh,%d,home)" % time.time())


def about_text():
    """Versions, this Shield, then resources/changelog.txt (newest release first)."""
    import os
    import xbmc
    import xbmcaddon
    try:
        skin = xbmcaddon.Addon("skin.sportshub").getAddonInfo("version")
    except RuntimeError:
        skin = "not installed"
    lines = ["[B]WatchHub %s[/B]   (skin %s)" % (kodi.ADDON.getAddonInfo("version"), skin),
             "This Shield: %s  -  Kodi %s" % (xbmc.getInfoLabel("System.FriendlyName") or "?",
                                              (xbmc.getInfoLabel("System.BuildVersion") or "?").split(" ")[0]),
             "Updates itself from github.com/jcummins100/WatchHub", "", "[B]What's new[/B]", ""]
    try:
        with open(os.path.join(kodi.ADDON_PATH, "resources", "changelog.txt"), encoding="utf-8") as fh:
            for line in fh.read().splitlines():
                # release headers ("0.7.5 - Oct 16") in bold
                lines.append("[B]%s[/B]" % line if line[:1].isdigit() and " - " in line else line)
    except OSError:
        lines.append("(release notes missing)")
    return "\n".join(lines)


def _new_rediscover_day():
    """Re-pick today's Rediscover row (the unseen-only switch changes who's in it)."""
    from resources.lib import rediscover
    state = rediscover._load()
    picks = set(state.pop("picks", None) or [])
    state["shown"] = {k: v for k, v in (state.get("shown") or {}).items() if k not in picks}  # they may stay
    state.pop("day", None)
    rediscover._save(state)
