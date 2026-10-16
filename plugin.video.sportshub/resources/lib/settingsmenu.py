"""WatchHub settings from the header's gear, in plain words (Sprint C: settings inside the skin).

The everyday choices (your subscriptions, Prime Video channels, which free live-TV services feed the
guide and in what order, Spanish channels, your local stations, Rediscover, Trakt) without Kodi's
settings screen; "All settings" still opens it. Runs in the background service (uiworker), so a
change to the guide's sources rebuilds the guide right away.
"""
import time

import xbmcgui

from resources.lib import kodi
from resources.lib.sources import fast, ondemand, trakt

LIVE_SERVICES = [sid for sid in fast.SERVICES if fast.SERVICES[sid]["package"]]


def _names(codes):
    return ", ".join(ondemand.short_name(c) for c in codes) or "none"


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
            ("subs", "Your subscriptions", _names(subs)),
            ("prime", "Prime Video channels you pay for", ", ".join(n.replace(" (Prime)", "") for c, n in ondemand.AMAZON_CHANNELS if c in prime) or "none"),
            ("live", "Free live TV in the guide", ", ".join(fast.SERVICES[s]["name"] + (" (no app)" if s in missing else "") for s in live) or "none"),
            ("order", "When a channel is on several services, play it on", " → ".join(fast.SERVICES[s]["name"] for s in order if s in LIVE_SERVICES)),
            ("spanish", "Hide Spanish-language channels", _on(kodi.setting_bool("hide_spanish", True))),
            ("local", "Your local stations", kodi.setting("local_market", "") or "none"),
            ("unseen", "Rediscover: only movies I haven't seen", _on(kodi.setting_bool("rediscover_unseen_only", False))),
            ("trakt", "Trakt", "Signed in" if trakt.signed_in() else "Not signed in - choose to sign in"),
            ("all", "All settings", "Kodi's full settings screen for WatchHub"),
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
        if key == "subs":
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
            text = xbmcgui.Dialog().input("Your city and stations' call letters, comma-separated",
                                          kodi.setting("local_market", ""))
            if text is not None and text != kodi.setting("local_market", ""):
                kodi.ADDON.setSetting("local_market", text)
                changed_guide = True
        elif key == "unseen":
            kodi.ADDON.setSetting("rediscover_unseen_only", "false" if kodi.setting_bool("rediscover_unseen_only", False) else "true")
            _new_rediscover_day()
            changed_rows = True
        elif key == "trakt":
            if not trakt.signed_in():
                kodi.run_builtin("RunPlugin(%s)" % kodi.build_url(action="trakt_signin"))
                break
            kodi.notify("Trakt is signed in on this Shield")
        elif key == "all":
            kodi.run_builtin("Addon.OpenSettings(%s)" % kodi.ADDON_ID)
            break
    if changed_guide:
        from resources.lib import guide
        guide._rebuild_in_background()
    if changed_guide or changed_rows:
        kodi.run_builtin("SetProperty(sh_refresh,%d,home)" % time.time())


def _new_rediscover_day():
    """Re-pick today's Rediscover row (the unseen-only switch changes who's in it)."""
    from resources.lib import rediscover
    state = rediscover._load()
    picks = set(state.pop("picks", None) or [])
    state["shown"] = {k: v for k, v in (state.get("shown") or {}).items() if k not in picks}  # they may stay
    state.pop("day", None)
    rediscover._save(state)
