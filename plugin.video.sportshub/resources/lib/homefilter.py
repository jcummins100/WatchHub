"""The home screen's service filter: which service is picked, kept across Kodi restarts.

Window(Home) properties drive the skin (sh_provider = JustWatch code, sh_provider_name = label).
They die with Kodi, and on a 2 GB Shield Android kills Kodi whenever Netflix or Plex opens, so the
choice is also saved to a file in the add-on's profile and put back by the service at startup.
"""
import json
import os

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
