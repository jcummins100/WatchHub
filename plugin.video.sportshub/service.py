"""Background service.

* Optionally opens Sports Hub as soon as Kodi has started, so Kodi behaves like a dedicated
  sports box (press Back to reach the normal Kodi home).
* Keeps the guide data warm on a timer and prunes stale cache files, so menus open instantly
  and nothing accumulates. Data is always re-pulled from upstream; there are no stored stream
  links that can go dead.
"""
import json
import os
import sys
import time

import xbmc
import xbmcaddon
import xbmcgui

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ADDON_ID = "plugin.video.sportshub"


def _int_setting(addon, key, default):
    try:
        return int(addon.getSetting(key) or default)
    except ValueError:
        return default


def main():
    addon = xbmcaddon.Addon(ADDON_ID)
    monitor = xbmc.Monitor()

    if addon.getSetting("open_on_start") == "true":
        if monitor.waitForAbort(_int_setting(addon, "start_delay", 3)):
            return
        # With the Sports Hub skin the home screen *is* the hub; only the classic skin needs the list.
        skin = xbmc.getSkinDir()
        xbmc.log("[%s] service: skin=%s" % (ADDON_ID, skin), xbmc.LOGINFO)
        if skin != "skin.sportshub":
            xbmc.executebuiltin("ActivateWindow(Videos,plugin://%s/,return)" % ADDON_ID)

    from resources.lib import health, homefilter, kodi

    cmd_file = os.path.join(kodi.ensure_profile_dir(), "cmd")

    if xbmc.getSkinDir() == "skin.sportshub":
        # Lists open on their first real item, not a "< Back" (parent folder) tile: Back on the remote does that.
        if (kodi.jsonrpc("Settings.GetSettingValue", {"setting": "filelists.showparentdiritems"}) or {}).get("value"):
            kodi.jsonrpc("Settings.SetSettingValue", {"setting": "filelists.showparentdiritems", "value": False})
            kodi.log("turned off Kodi's parent-folder items for the WatchHub skin")

    # Put back the service filter the user had picked (Kodi may have been killed while an app ran).
    if xbmc.getSkinDir() == "skin.sportshub":
        code = homefilter.saved()
        if code:
            # properties first, so Home builds the provider view from the start; then fix focus once it's up
            code = homefilter.apply(code)
            kodi.log("home filter restored: %s" % (code or "All"))
            for _ in range(60):
                if xbmc.getCondVisibility("Window.IsActive(home)") or monitor.waitForAbort(0.5):
                    break
            if code:
                homefilter.focus(code, timeout_s=30)

    pending_guide = ""
    # Kodi was killed while a channel launched from the TV Guide was playing: put the guide back.
    if xbmc.getSkinDir() == "skin.sportshub":
        from resources.lib import guide
        tab = guide.pending_return()
        if tab is not None:
            for _ in range(60):
                if xbmc.getCondVisibility("Window.IsActive(home)") or monitor.waitForAbort(0.5):
                    break
            kodi.log("reopening the TV Guide after a restart (tab %s)" % (tab or "default"))
            from urllib.parse import quote_plus
            pending_guide = "plugin://%s/?action=guide&tab=%s" % (ADDON_ID, quote_plus(tab))

    # Info pages and the TV Guide open from here, on their own thread (see uiworker).
    from resources.lib import uiworker
    uiworker.Worker(monitor).start()
    if xbmc.getSkinDir() == "skin.sportshub":
        uiworker.install_keymap()
    else:
        uiworker.remove_keymap()   # the classic Kodi look keeps Kodi's own long-press menu
    # Refresh a little before the cache expires so the UI never has to wait on the network.
    home = xbmcgui.Window(10000)
    home.setProperty("sh_service_alive", "1")
    if pending_guide:
        uiworker.request(pending_guide)
    next_refresh = 0
    reload_pending = 0  # time the fresh data became ready, 0 = nothing waiting
    while not monitor.abortRequested():
        now = time.time()
        # Reloading the rows resets each row to its first card, so don't do it under someone who is
        # browsing: wait until Home isn't showing or the remote has been idle for 90 s - but never hold
        # back more than 15 minutes, or scores and "on now" listings go stale.
        if reload_pending and (not xbmc.getCondVisibility("Window.IsActive(home)") or xbmc.getCondVisibility("System.IdleTime(90)")
                               or now - reload_pending > 15 * 60):
            home.setProperty("sh_refresh", str(int(time.time())))
            reload_pending = 0
        if now >= next_refresh:
            try:
                health.warm_caches()
                uiworker.warm_guide()
                reload_pending = reload_pending or time.time()
                pruned = health.prune_cache()
                if pruned:
                    kodi.log("pruned %d stale cache files" % pruned)
            except Exception as exc:
                kodi.log("background refresh failed: %s" % exc)
            # Channel guides are hourly-ish; scores need a few minutes. Refresh at the faster cadence.
            next_refresh = now + min(10, max(3, _int_setting(xbmcaddon.Addon(ADDON_ID), "cache_minutes", 60) - 5)) * 60
        # Developer hook: builtins written to <profile>/cmd (e.g. "ReloadSkin()") are run and the file removed.
        if os.path.exists(cmd_file):
            try:
                with open(cmd_file, "r", encoding="utf-8") as fh:
                    lines = [ln.strip() for ln in fh if ln.strip()]
                os.remove(cmd_file)
                for ln in lines:
                    kodi.log("cmd: %s" % ln)
                    xbmc.executebuiltin(ln)
            except Exception as exc:
                kodi.log("cmd failed: %s" % exc)
        if monitor.waitForAbort(2):
            return


if __name__ == "__main__":
    main()
