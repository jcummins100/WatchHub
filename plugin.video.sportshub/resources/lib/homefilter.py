"""The home screen's service filter: which service is picked, kept across Kodi restarts.

Window(Home) properties drive the skin (sh_provider = JustWatch code, sh_provider_name = label).
They die with Kodi, and on a 2 GB Shield Android kills Kodi whenever Netflix or Plex opens, so the
choice is also saved to a file in the add-on's profile and put back by the service at startup.
"""
import json
import os
import time

import xbmc
import xbmcgui

from resources.lib import kodi
from resources.lib.sources import ondemand

ALL_ROW, PROVIDER_ROW = 9050, 9051  # the Services row in the All view / the provider view (Home.xml)


def _path():
    return os.path.join(kodi.ensure_profile_dir(), "home_filter.json")


def saved():
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    code = data.get("code") if isinstance(data, dict) else None
    return code if isinstance(code, str) else ""


def save(code):
    """Write via a temp file + rename, so a kill mid-write never leaves a half-written state file."""
    path = _path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"code": code}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        kodi.log("home filter not saved: %s" % exc)


def current():
    return xbmcgui.Window(10000).getProperty("sh_provider")


def apply(code):
    """Show the provider view for `code` ("" = All). Unknown or uninstalled codes fall back to All."""
    if code and code not in ondemand.installed_codes():
        code = ""
    home = xbmcgui.Window(10000)
    home.setProperty("sh_provider_name", ondemand.short_name(code).upper() if code else "")
    home.setProperty("sh_provider", code)
    return code


def focus(code, timeout_s=8.0):
    """Put focus on `code`'s tile in whichever Services row is showing, once that row has reloaded.

    Waits (instead of a fixed sleep) until the row is visible, finished updating and its list marks
    `code` as selected, then focuses the tile by its code, not a remembered position. Gives up
    quietly if the user has moved focus off the Services rows/header in the meantime.
    """
    row = PROVIDER_ROW if code else ALL_ROW
    home = xbmcgui.Window(10000)
    # each request gets a number; a newer pick (or the user leaving Home) cancels this one
    req = str(int(home.getProperty("sh_focus_req") or 0) + 1)
    home.setProperty("sh_focus_req", req)
    mon = xbmc.Monitor()
    waited = 0.0
    while waited < timeout_s:
        if home.getProperty("sh_focus_req") != req or current() != code or not xbmc.getCondVisibility("Window.IsActive(home)"):
            return False
        if xbmc.getCondVisibility("Control.IsVisible(%d) + !Container(%d).IsUpdating" % (row, row)):
            n = int(xbmc.getInfoLabel("Container(%d).NumItems" % row) or 0)
            codes = [xbmc.getInfoLabel("Container(%d).ListItemAbsolute(%d).Property(code)" % (row, i)) for i in range(n)]
            marked = [i for i in range(n) if xbmc.getInfoLabel("Container(%d).ListItemAbsolute(%d).Property(selected)" % (row, i)) == "1"]
            if code in codes and marked and codes[marked[0]] == code:
                focused = xbmc.getInfoLabel("System.CurrentControlId")
                # Move focus unless the user is already browsing the view that's showing, or is up in the
                # header. A control inside the hidden view still reports itself "visible", so test the
                # view group (9001 provider / 9000 All) rather than the focused control.
                view = 9001 if code else 9000
                if focused in ("", "0", str(ALL_ROW), str(PROVIDER_ROW)) or not (
                        xbmc.getCondVisibility("ControlGroup(%d).HasFocus" % view) or xbmc.getCondVisibility("ControlGroup(700).HasFocus")):
                    kodi.run_builtin("SetFocus(%d,%d,absolute)" % (row, codes.index(code)))
                return True
        if mon.waitForAbort(0.1):
            return False
        waited += 0.1
    kodi.log("home filter: gave up focusing '%s' after %.0fs" % (code, timeout_s))
    return False


# ---------------------------------------------------------------- back to the same card after an app
SPOT_WINDOW = 3 * 3600  # a return this long after launching an app still goes back to its card


def _spot_path():
    return os.path.join(kodi.ensure_profile_dir(), "home_spot.json")


def remember_spot():
    """Before an app opens: note Home's focused row and card (position and label). Skipped when Home
    isn't underneath (the guide keeps its own return), or focus is on the header."""
    try:
        if not xbmc.getCondVisibility("Window.IsVisible(home)"):
            return
        row = xbmcgui.Window(10000).getFocusId()
    except RuntimeError:
        return
    if not row or row in (ALL_ROW, PROVIDER_ROW) or not xbmc.getCondVisibility("Control.IsVisible(%d)" % row):
        return
    pos = int(xbmc.getInfoLabel("Container(%d).CurrentItem" % row) or 0)
    if pos < 1:
        return
    spot = {"at": int(time.time()), "row": row, "pos": pos, "provider": current(),
            "label": xbmc.getInfoLabel("Container(%d).ListItem.Label" % row)}
    try:
        with open(_spot_path(), "w", encoding="utf-8") as fh:
            json.dump(spot, fh)
    except OSError as exc:
        kodi.log("home spot not saved: %s" % exc)


def pending_spot():
    try:
        with open(_spot_path(), encoding="utf-8") as fh:
            spot = json.load(fh)
        if isinstance(spot, dict) and time.time() - float(spot.get("at", 0)) < SPOT_WINDOW:
            return spot
    except (OSError, ValueError, TypeError):
        pass
    return None


def forget_spot():
    try:
        os.remove(_spot_path())
    except OSError:
        pass


def restore_spot(spot, timeout_s=30.0):
    """Focus the remembered card once its row has loaded: by label (rows may have been rebuilt meanwhile),
    else by position. Gives up if the user is already somewhere else on Home, or the service filter changed."""
    row = int(spot["row"])
    mon = xbmc.Monitor()
    waited = 0.0
    while waited < timeout_s:
        if current() != spot.get("provider", ""):
            return False
        if xbmc.getCondVisibility("Window.IsActive(home) + Control.IsVisible(%d) + !Container(%d).IsUpdating" % (row, row)):
            n = int(xbmc.getInfoLabel("Container(%d).NumItems" % row) or 0)
            if n:
                labels = [xbmc.getInfoLabel("Container(%d).ListItemAbsolute(%d).Label" % (row, i)) for i in range(n)]
                idx = labels.index(spot["label"]) if spot.get("label") in labels else min(int(spot["pos"]), n) - 1
                kodi.run_builtin("SetFocus(%d,%d,absolute)" % (row, idx))
                kodi.log("home: back to row %d card %d (%s)" % (row, idx + 1, spot.get("label", "")))
                return True
        if mon.waitForAbort(0.25):
            return False
        waited += 0.25
    kodi.log("home: row %d never loaded, card not restored" % row)
    return False
