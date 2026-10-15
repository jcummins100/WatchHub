"""Thin wrapper around the Kodi Python API.

Everything that touches xbmc* lives here so the data layer can be run and
tested on a desktop machine with the stubs in tools/dev_run.py.
"""
import json
import os
import sys
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")
ADDON_NAME = ADDON.getAddonInfo("name")
ADDON_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))

HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].lstrip("-").isdigit() else -1
BASE_URL = sys.argv[0] if sys.argv else "plugin://%s/" % ADDON_ID


def ensure_profile_dir():
    if not os.path.isdir(PROFILE_PATH):
        os.makedirs(PROFILE_PATH, exist_ok=True)
    return PROFILE_PATH


# ---------------------------------------------------------------- settings
def setting(key, default=""):
    try:
        return ADDON.getSetting(key) or default
    except Exception:
        return default


def setting_bool(key, default=False):
    v = setting(key, None)
    if v is None or v == "":
        return default
    return str(v).lower() == "true"


def setting_int(key, default=0):
    try:
        return int(setting(key, default))
    except (TypeError, ValueError):
        return default


def localized(string_id, *fmt):
    s = ADDON.getLocalizedString(string_id) or ""
    if fmt:
        try:
            s = s % fmt
        except TypeError:
            pass
    return s


# ---------------------------------------------------------------- logging
def log(msg, level=xbmc.LOGINFO):
    xbmc.log("[%s] %s" % (ADDON_ID, msg), level)


def debug(msg):
    if setting_bool("debug"):
        xbmc.log("[%s] %s" % (ADDON_ID, msg), xbmc.LOGINFO)


def notify(msg, title=None, icon=xbmcgui.NOTIFICATION_INFO, time_ms=3000):
    xbmcgui.Dialog().notification(title or ADDON_NAME, msg, icon, time_ms)


# ---------------------------------------------------------------- routing
def build_url(**params):
    clean = {k: v for k, v in params.items() if v is not None and v != ""}
    return BASE_URL + "?" + urlencode(clean)


def parse_params():
    qs = sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith("?") else ""
    return dict(parse_qsl(qs))


# ---------------------------------------------------------------- platform
def is_android():
    return xbmc.getCondVisibility("System.Platform.Android")


def run_builtin(cmd):
    debug("builtin: %s" % cmd)
    xbmc.executebuiltin(cmd)


def start_android_activity(package, action="", data_uri="", data_type="", class_name=""):
    """Launch an Android app, optionally with a VIEW intent to a deep link.

    Kodi signature (Kodi 21): StartAndroidActivity(package,[intent,dataType,dataURI,flags,extras,action,category,className])
    """
    # Quote each arg; Kodi's builtin parser accepts quoted comma-separated params.
    def q(s):
        return '"%s"' % str(s).replace('"', "")

    # Verified on the Shield (Kodi 21): the action must go in the dedicated 'action' slot; putting it in
    # the 'intent' slot opens the app but never delivers the data URI.
    # FLAG_ACTIVITY_NEW_TASK | FLAG_ACTIVITY_CLEAR_TOP: a target app left on a dialog or deep in its UI
    # otherwise ignores the new link and just comes to the front.
    flags = "0x14000000" if data_uri else ""
    parts = [q(package), q(""), q(data_type), q(data_uri), q(flags), q(""), q(action), q(""), q(class_name)]
    while len(parts) > 4 and parts[-1] == q(""):
        parts.pop()
    run_builtin("StartAndroidActivity(%s)" % ",".join(parts))


def jsonrpc(method, params=None, rpc_id=1):
    payload = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        payload["params"] = params
    raw = xbmc.executeJSONRPC(json.dumps(payload))
    try:
        resp = json.loads(raw)
    except ValueError:
        log("Bad JSON-RPC response for %s: %r" % (method, raw[:200]), xbmc.LOGWARNING)
        return None
    if "error" in resp:
        debug("JSON-RPC %s error: %s" % (method, resp["error"]))
        return None
    return resp.get("result")


# ---------------------------------------------------------------- listing
def set_content(content="videos"):
    xbmcplugin.setContent(HANDLE, content)


def set_category(name):
    """Breadcrumb shown by the skin (Container.PluginCategory)."""
    if HANDLE >= 0 and name:
        xbmcplugin.setPluginCategory(HANDLE, name)


def add_item(label, url, is_folder=False, playable=False, art=None, info=None, label2=None, context=None, props=None):
    li = xbmcgui.ListItem(label=label, label2=label2 or "")
    if art:
        li.setArt({k: v for k, v in art.items() if v})
    for k, v in (props or {}).items():
        li.setProperty(k, str(v))
    if info:
        _set_video_info(li, info)
    if playable:
        li.setProperty("IsPlayable", "true")
    if context:
        li.addContextMenuItems(context)
    xbmcplugin.addDirectoryItem(HANDLE, url, li, is_folder)
    return li


def _set_video_info(li, info):
    """Use InfoTagVideo on Kodi 20+, fall back to setInfo on older versions."""
    try:
        tag = li.getVideoInfoTag()
        if "title" in info:
            tag.setTitle(info["title"])
        if "plot" in info:
            tag.setPlot(info["plot"])
        if "genre" in info:
            g = info["genre"]
            tag.setGenres(g if isinstance(g, list) else [g])
        if "duration" in info:
            tag.setDuration(int(info["duration"]))
        if "premiered" in info:
            tag.setPremiered(info["premiered"])
        tag.setMediaType("video")
    except Exception:
        li.setInfo("video", info)


# Estuary view ids: 50 List, 51 Poster, 52 IconWall, 53 Shift, 54 InfoWall, 55 WideList, 500 Wall, 501 Banner, 502 Fanart
VIEWS = {"wall": 500, "widelist": 55, "infowall": 54, "list": 50, "shift": 53}


def end_directory(succeeded=True, cache=False, update_listing=False, view=None):
    log("end_directory handle=%s ok=%s" % (HANDLE, succeeded))
    if xbmc.getSkinDir() == "skin.sportshub" and HANDLE >= 0:
        # The WatchHub skin picks its layout from the content type (posters for "movies", channel/tile
        # cards otherwise) - SetViewMode alone races the window loading the list and sometimes loses.
        xbmcplugin.setContent(HANDLE, "movies" if view == "posters" else "videos")
    xbmcplugin.endOfDirectory(HANDLE, succeeded=succeeded, updateListing=update_listing, cacheToDisc=cache)
    if succeeded and xbmc.getSkinDir() == "skin.sportshub":
        xbmc.executebuiltin("Container.SetViewMode(%d)" % (601 if view == "posters" else 600))
        return
    view = view or setting("view_mode", "wall")
    if succeeded and view in VIEWS and view != "kodi":
        xbmc.executebuiltin("Container.SetViewMode(%d)" % VIEWS[view])


def resolve_none():
    """Tell Kodi a clicked item was handled without a stream (we launched an app / ran an action).

    Only meaningful when Kodi invoked us with a real handle; RunPlugin() calls pass -1.
    """
    if HANDLE >= 0:
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


def open_settings():
    ADDON.openSettings()


def player_open(item):
    return jsonrpc("Player.Open", {"item": item})


def save_settings():
    """Kodi persists guisettings.xml when the Settings window closes; open and close it quietly."""
    run_builtin("ActivateWindow(settings)")
    xbmc.Monitor().waitForAbort(1.5)
    run_builtin("Action(back)")
