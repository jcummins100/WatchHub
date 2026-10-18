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
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ADDON_ID = "plugin.video.sportshub"


def _warm_sports_page(r):
    def work():
        from resources.lib import kodi
        try:
            from resources.lib import ui
            ui.warm_sports_page(r)
        except Exception as exc:
            kodi.log("sports page warm failed: %s" % exc)
    threading.Thread(target=work, name="sh-warm-sports", daemon=True).start()


def _detect_location():
    """Only when Your local stations is Automatic; a typed-in market is left alone."""
    from resources.lib import kodi
    try:
        if kodi.setting("local_market", "auto").strip().lower() == "auto":
            from resources.lib import location
            location.detect()
    except Exception as exc:
        kodi.log("location: %s" % exc)


_vpn = {"busy": False, "focused": False, "at": 0}


def _vpn_status(home, max_age=120):
    """Checked on its own thread (the lookup can take a few seconds); the skin reads the sh_vpn_* properties."""
    if _vpn["busy"]:
        return
    _vpn.update(busy=True, at=time.time())

    def work():
        from resources.lib import location
        try:
            st = location.vpn_status(max_age=max_age)
            for k in ("state", "kicker", "where", "how", "local", "tip"):
                home.setProperty("sh_vpn_" + k, st.get(k, ""))
        finally:
            _vpn["busy"] = False
    threading.Thread(target=work, name="sh-vpn", daemon=True).start()


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

    from resources.lib import finish, health, homefilter, kodi

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
            if code and not homefilter.pending_spot():
                homefilter.focus(code, timeout_s=30)

    # Kodi was killed while an app launched from a Home card was open: back to that row and card.
    if xbmc.getSkinDir() == "skin.sportshub":
        from resources.lib import guide
        spot = homefilter.pending_spot()
        if spot and guide.pending_return() is None:
            def back_to_card(spot=spot):
                # its own thread: Up Next can take a while to load, and the service has other work to start
                for _ in range(60):
                    if xbmc.getCondVisibility("Window.IsActive(home)") or monitor.waitForAbort(0.5):
                        break
                homefilter.restore_spot(spot)
                homefilter.forget_spot()  # one try; an old spot must never pull focus later
            threading.Thread(target=back_to_card, name="sh-back-to-card", daemon=True).start()

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
    # your home row order (a skin update ships the default one)
    try:
        from resources.lib import homerows
        homerows.apply_saved()
    except Exception as exc:
        kodi.log("home rows not applied: %s" % exc)
    # where this Shield is, for the guide's Local stations (cached; looked up again every few hours)
    _detect_location()
    # the channel list first, from whatever listings are cached: the home rows read the copy it saves
    uiworker.warm_guide()
    if pending_guide:
        uiworker.request(pending_guide)
    next_refresh = 0
    first_refresh_done = False
    reload_pending = 0  # time the fresh data became ready, 0 = nothing waiting
    while not monitor.abortRequested():
        now = time.time()
        # Reloading the rows resets each row to its first card, so don't do it under someone who is
        # browsing: wait until Home isn't showing or the remote has been idle for 90 s - but never hold
        # back more than 15 minutes, or scores and "on now" listings go stale.
        if reload_pending and (not xbmc.getCondVisibility("Window.IsActive(home)") or xbmc.getCondVisibility("System.IdleTime(90)")
                               or now - reload_pending > 15 * 60):
            r = str(int(time.time()))
            home.setProperty("sh_refresh", r)
            reload_pending = 0
            # the Sports page isn't on screen: have its rows ready for when it opens (built off-screen)
            if not xbmc.getCondVisibility("Window.IsActive(1120)"):
                _warm_sports_page(r)
            # the reload puts every row back on its first card: someone off in an app comes back to theirs
            # (only while no key has been pressed in Kodi since that app was launched)
            spot = homefilter.pending_spot()
            if spot and xbmc.getCondVisibility("System.IdleTime(%d)" % max(1, int(time.time() - spot["at"]) - 5)):
                homefilter.restore_spot(spot, timeout_s=20, after_reload=True)
        # a home row shown from its snapshot at start-up came out different when rebuilt: reload the rows
        # (under the same don't-move-me rules as a data refresh)
        if home.getProperty("sh_rows_stale"):
            home.clearProperty("sh_rows_stale")
            reload_pending = reload_pending or now
        # the VPN button is highlighted: say whether the VPN is on and where the internet puts you
        # the VPN button: its badge (checked every 2 minutes) and, while highlighted, the status panel above the rows
        focused = xbmc.getCondVisibility("Control.HasFocus(808)")
        if focused and not _vpn["focused"]:
            _vpn_status(home, max_age=3)   # just highlighted (maybe back from IPVanish): ask again
        elif now - _vpn["at"] > 120:
            _vpn_status(home, max_age=120)
        _vpn["focused"] = focused
        # starred or unstarred a channel somewhere: refresh the ★ rows the home Live row reads
        try:
            from resources.lib import guide
            guide.publish_favorites()
        except Exception as exc:
            kodi.debug("favorites publish failed: %s" % exc)
        # someone is using Kodi again after an app: the remembered card has done its job
        spot = homefilter.pending_spot()
        if spot and now - spot["at"] > 60 and not xbmc.getCondVisibility("System.IdleTime(2)"):
            homefilter.forget_spot()
        if now >= next_refresh:
            try:
                _detect_location()
                health.warm_caches()
                uiworker.warm_guide()
                uiworker.fill_show_genres()
                # the rows that just loaded at start-up already fetched anything out of date: reloading them
                # all again a few seconds later only doubles the start-up work
                if first_refresh_done:
                    reload_pending = reload_pending or time.time()
                first_refresh_done = True
                pruned = health.prune_cache()
                if pruned:
                    kodi.log("pruned %d stale cache files" % pruned)
            except Exception as exc:
                kodi.log("background refresh failed: %s" % exc)
            # Channel guides are hourly-ish; scores need a few minutes. Refresh at the faster cadence.
            next_refresh = now + min(10, max(3, _int_setting(xbmcaddon.Addon(ADDON_ID), "cache_minutes", 60) - 5)) * 60
        # Back from an app after an episode: "Did you finish S02E04?" (asks once, on the next key press)
        try:
            finish.check()
        except Exception as exc:
            kodi.log("finish check failed: %s" % exc)
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
    try:
        main()
    finally:
        # clicks fall back to opening windows themselves once no service is listening
        xbmcgui.Window(10000).clearProperty("sh_service_alive")
