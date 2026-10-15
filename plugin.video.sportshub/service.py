"""Background service.

* Optionally opens Sports Hub as soon as Kodi has started, so Kodi behaves like a dedicated
  sports box (press Back to reach the normal Kodi home).
* Keeps the guide data warm on a timer and prunes stale cache files, so menus open instantly
  and nothing accumulates. Data is always re-pulled from upstream; there are no stored stream
  links that can go dead.
"""
import os
import sys
import time

import xbmc
import xbmcaddon

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

    from resources.lib import health, kodi

    cmd_file = os.path.join(kodi.ensure_profile_dir(), "cmd")

    # Refresh a little before the cache expires so the UI never has to wait on the network.
    next_refresh = 0
    while not monitor.abortRequested():
        now = time.time()
        if now >= next_refresh:
            try:
                health.warm_caches()
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
            break


if __name__ == "__main__":
    main()
