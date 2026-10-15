"""Turn a programme's `play` dict into an action: launch an app, tune a PVR channel, etc."""
import xbmcgui

from resources.lib import apps, health, kodi
from resources.lib.sources import fast, pvr, youtube


def play(params):
    src = params.get("src")
    name = params.get("name") or ""
    if src in fast.SERVICES:
        return _launch_fast(src, params.get("id", ""), name)
    if src == "pvr":
        return _play_pvr(params.get("id"))
    if src == "app":
        return _launch_app(params.get("id", ""), "", name)
    if src == "ondemand":
        return _launch_app(params.get("pkg", ""), params.get("url", ""), name)
    if src == "youtube":
        return _launch_app(youtube.PACKAGE, youtube.url_for(params.get("id", "")), name)
    if src in ("sportsdb", "game"):
        return _play_sportsdb(params)
    kodi.notify("Unknown source: %s" % src, icon=xbmcgui.NOTIFICATION_WARNING)
    return False


def _slug(name):
    """'beIN SPORTS XTRA' -> 'bein-sports-xtra' (the form Plex uses in its channel URLs)."""
    import re
    s = re.sub(r"[^a-z0-9]+", "-", name.lower().replace("&", " and ").replace("+", " plus "))
    return s.strip("-")


def _launch_fast(sid, cid, name):
    svc = fast.SERVICES[sid]
    if not svc["package"]:
        kodi.notify(kodi.localized(30023, svc["name"]), icon=xbmcgui.NOTIFICATION_WARNING)
        return False
    link = svc["deeplink"].format(id=cid, slug=_slug(name)) if svc["deeplink"] and cid else ""
    return _launch_app(svc["package"], link, name or svc["name"])


def _launch_app(package, link, name):
    if not kodi.is_android():
        kodi.notify(kodi.localized(30025), icon=xbmcgui.NOTIFICATION_WARNING)
        return False
    if health.app_installed(package) is False:
        if xbmcgui.Dialog().yesno(kodi.ADDON_NAME, "%s is not installed on this device.\n\nOpen it in the Play Store?" % name):
            health.open_play_store(package)
        return False
    kodi.notify(kodi.localized(30022, name), time_ms=2000)
    if link:
        kodi.start_android_activity(package, action="android.intent.action.VIEW", data_uri=link)
    else:
        kodi.start_android_activity(package)
    return True


def _play_pvr(channel_id):
    if not channel_id:
        kodi.notify(kodi.localized(30024), icon=xbmcgui.NOTIFICATION_WARNING)
        return False
    kodi.player_open({"channelid": int(channel_id)})
    return True


def _play_sportsdb(params):
    """TV schedule entries don't carry a stream. Try to match the listed network to a PVR channel."""
    channels = [c.strip() for c in (params.get("channel") or "").split(",") if c.strip()]
    # 1. Free over-the-air / PVR channel already in Kodi?
    if pvr.available():
        for c in channels:
            cid = pvr.find_channel(c)
            if cid:
                return _play_pvr(cid)
    # 2. A streaming app on this device that carries that network (needs your own subscription).
    options = []
    for c in channels:
        pkg, friendly = apps.for_network(c)
        if pkg and pkg not in [o[1] for o in options]:
            options.append((friendly, pkg, c))
    if options and kodi.is_android():
        if len(options) == 1:
            choice = 0
        else:
            choice = xbmcgui.Dialog().select("Watch on...", ["%s (%s)" % (o[0], o[2]) for o in options])
        if choice is not None and choice >= 0:
            friendly, pkg, _ = options[choice]
            return _launch_app(pkg, "", friendly)
        return False
    xbmcgui.Dialog().ok(
        kodi.ADDON_NAME,
        "%s\n\nOn: %s\n\nNo matching Live TV channel or app found on this device."
        % (params.get("title", ""), ", ".join(channels) or "unknown"),
    )
    return False
