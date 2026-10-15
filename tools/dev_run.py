#!/usr/bin/env python3
"""Run the add-on outside Kodi with stubbed xbmc modules, printing the resulting list.

    python3 tools/dev_run.py                      # root menu
    python3 tools/dev_run.py "action=live"
    python3 tools/dev_run.py "action=channel&src=pluto&id=<id>"
    python3 tools/dev_run.py "action=play&src=pluto&id=<id>"   # prints the builtin it would run

Settings can be overridden with env vars: SH_region=gb SH_games_only=true ...
"""
import os
import sys
import tempfile
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_DIR = os.path.join(ROOT, "plugin.video.sportshub")
PROFILE = os.path.join(tempfile.gettempdir(), "sportshub-dev-profile")

# ------------------------------------------------------------------ stubs
import re  # noqa: E402

_strings = {}
with open(os.path.join(ADDON_DIR, "resources/language/resource.language.en_gb/strings.po"), encoding="utf-8") as fh:
    for m in re.finditer(r'msgctxt "#(\d+)"\nmsgid "([^"]*)"', fh.read()):
        _strings[int(m.group(1))] = m.group(2)

_defaults = {}
with open(os.path.join(ADDON_DIR, "resources/settings.xml"), encoding="utf-8") as fh:
    for m in re.finditer(r'<setting id="([^"]+)"[^>]*>.*?<default>([^<]*)</default>', fh.read(), re.S):
        _defaults[m.group(1)] = m.group(2)

xbmc = types.ModuleType("xbmc")
xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = 0, 1, 2, 3
xbmc.log = lambda msg, level=1: print("  LOG:", msg, file=sys.stderr)
xbmc.getCondVisibility = lambda cond: os.environ.get("SH_android", "true") == "true" if "Android" in cond else False
xbmc.executebuiltin = lambda cmd: print("  BUILTIN:", cmd)
xbmc.getSkinDir = lambda: os.environ.get("SH_skin", "skin.estuary")
xbmc.executeJSONRPC = lambda payload: '{"id":1,"jsonrpc":"2.0","result":{"available":false}}'


class _Player:
    def play(self, item, *a, **k):
        print("  PLAY:", item)


xbmc.Player = _Player


class _Addon:
    def __init__(self, *a, **k):
        pass

    def getAddonInfo(self, key):
        return {"id": "plugin.video.sportshub", "name": "Sports Hub", "path": ADDON_DIR, "profile": PROFILE, "version": "0.1.0-dev"}.get(key, "")

    def getSetting(self, key):
        return os.environ.get("SH_" + key, _defaults.get(key, ""))

    def getLocalizedString(self, sid):
        return _strings.get(sid, "#%d" % sid)

    def openSettings(self):
        print("  OPEN SETTINGS")


xbmcaddon = types.ModuleType("xbmcaddon")
xbmcaddon.Addon = _Addon


class _ListItem:
    def __init__(self, label="", label2="", **k):
        self.label, self.label2, self.props, self.art, self.ctx = label, label2, {}, {}, []

    def setArt(self, art):
        self.art = art

    def setProperty(self, k, v):
        self.props[k] = v

    def addContextMenuItems(self, items):
        self.ctx = items

    def setInfo(self, *a):
        pass

    def getVideoInfoTag(self):
        return types.SimpleNamespace(**{n: (lambda *a, **k: None) for n in
                                        ("setTitle", "setPlot", "setGenres", "setDuration", "setPremiered", "setMediaType")})


class _Dialog:
    def notification(self, title, msg, *a, **k):
        print("  NOTIFY: %s - %s" % (title, msg))

    def ok(self, title, msg):
        print("  DIALOG: %s\n%s" % (title, msg))

    def yesno(self, title, msg, **k):
        print("  YESNO: %s\n%s" % (title, msg))
        return True

    def input(self, heading, *a, **k):
        q = os.environ.get("SH_input", "ted lasso")
        print("  INPUT: %s -> %s" % (heading, q))
        return q

    def select(self, title, options, **k):
        print("  SELECT: %s -> %s" % (title, options))
        return 0


class _WindowXMLDialog:
    def __init__(self, *a, **k):
        pass

    def doModal(self):
        print("  DIALOG(XML):", getattr(self, "item", {}).get("title"))

    def setProperty(self, k, v):
        pass

    def close(self):
        pass


xbmcgui = types.ModuleType("xbmcgui")
xbmcgui.ListItem, xbmcgui.Dialog = _ListItem, _Dialog
xbmcgui.WindowXMLDialog = _WindowXMLDialog
xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK, xbmcgui.INPUT_ALPHANUM = 10, 92, 0
xbmcgui.NOTIFICATION_INFO = xbmcgui.NOTIFICATION_WARNING = xbmcgui.NOTIFICATION_ERROR = "info"

_items = []
xbmcplugin = types.ModuleType("xbmcplugin")
xbmcplugin.setContent = lambda h, c: None
xbmcplugin.setPluginCategory = lambda h, c: None
xbmcplugin.addDirectoryItem = lambda h, url, li, folder=False: _items.append((url, li, folder)) or True
xbmcplugin.endOfDirectory = lambda h, **k: None
xbmcplugin.setResolvedUrl = lambda h, ok, li: None

xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = lambda p: p
# Pretend a few apps are installed so the "not installed" paths get exercised too.
# SH_apps="pkg1,pkg2,..." mirrors a real device's app list instead.
_apps = [a.strip() + "/" for a in os.environ.get("SH_apps", "").split(",") if a.strip()]
xbmcvfs.listdir = lambda p: (_apps or ["tv.pluto.android/", "com.google.android.youtube.tv/", "org.xbmc.kodi/"], [])

for name, mod in (("xbmc", xbmc), ("xbmcaddon", xbmcaddon), ("xbmcgui", xbmcgui), ("xbmcplugin", xbmcplugin), ("xbmcvfs", xbmcvfs)):
    sys.modules[name] = mod

# ------------------------------------------------------------------ run
query = sys.argv[1] if len(sys.argv) > 1 else ""
sys.argv = ["plugin://plugin.video.sportshub/", "1", "?" + query if query else ""]
sys.path.insert(0, ADDON_DIR)
import addon  # noqa: E402

addon.main()
strip = lambda s: re.sub(r"\[/?(COLOR[^\]]*|B)\]", "", s)  # noqa: E731
if os.environ.get("SH_JSON"):
    # machine-readable listing for tools/watchhub_test.py
    import json
    print("@@JSON " + json.dumps([{"url": url, "label": strip(li.label), "folder": folder, "props": li.props, "art": li.art,
                                   "context": [c[0] for c in li.ctx]} for url, li, folder in _items]))
    sys.exit(0)
print("%d items" % len(_items))
for url, li, folder in _items:
    print(" %s %-70s %s" % ("+" if folder else "-", strip(li.label)[:70], url.replace("plugin://plugin.video.sportshub/?", "")))
