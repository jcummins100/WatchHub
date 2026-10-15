"""Self-healing helpers: which Android apps are installed, source status, cache upkeep.

Kodi on Android exposes installed apps through the `androidapp://` virtual file system,
so we can tell whether Pluto / Plex / YouTube etc. actually exist on this device before
offering to launch them, and point to the Play Store when they don't.
"""
import os
import time

import xbmcvfs

from resources.lib import kodi

_apps_cache = {"at": 0, "apps": None}
APPS_TTL = 300


def installed_apps():
    """Set of installed Android package names (empty set when not on Android or unknown)."""
    if not kodi.is_android():
        return set()
    now = time.time()
    if _apps_cache["apps"] is not None and now - _apps_cache["at"] < APPS_TTL:
        return _apps_cache["apps"]
    apps = set()
    try:
        dirs, files = xbmcvfs.listdir("androidapp://sources/apps/")
        for entry in list(dirs) + list(files):
            pkg = entry.rstrip("/").split("/")[-1]
            if pkg:
                apps.add(pkg)
    except Exception as exc:
        # an empty result means "can't tell" to every caller; don't remember a failure for 5 minutes
        kodi.log("androidapp:// listing failed: %s" % exc)
        return apps
    _apps_cache.update(at=now, apps=apps)
    return apps


def app_installed(package):
    """True if installed, False if definitely not, None if we can't tell."""
    if not package or not kodi.is_android():
        return None
    apps = installed_apps()
    if not apps:
        return None
    return package in apps


def open_play_store(package):
    kodi.start_android_activity("com.android.vending", action="android.intent.action.VIEW",
                                data_uri="market://details?id=%s" % package)


def prune_cache(max_age_days=7):
    """Delete cache files nothing has touched in a week (old regions, old API dates...)."""
    d = os.path.join(kodi.ensure_profile_dir(), "cache")
    if not os.path.isdir(d):
        return 0
    cutoff = time.time() - max_age_days * 86400
    n = 0
    for f in os.listdir(d):
        p = os.path.join(d, f)
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n


def warm_caches():
    """Pre-fetch everything the main screens need so they open instantly."""
    from resources.lib.sources import espn, fast, sportsdb

    for sid in fast.enabled_services():
        try:
            fast.channels(sid)
        except Exception as exc:
            kodi.log("warm %s failed: %s" % (sid, exc))
    if kodi.setting_bool("src_scores", True):
        try:
            espn.games()
        except Exception as exc:
            kodi.log("warm espn failed: %s" % exc)
    try:
        from resources.lib.sources import ondemand
        ondemand.titles()
    except Exception as exc:
        kodi.log("warm ondemand failed: %s" % exc)
    if kodi.setting_bool("src_sportsdb", False):
        try:
            sportsdb.tv_today()
        except Exception as exc:
            kodi.log("warm sportsdb failed: %s" % exc)


def source_status():
    """[(name, ok, detail)] for the diagnostics screen."""
    from resources.lib import cache
    from resources.lib.sources import fast, pvr

    rows = []
    for sid in fast.enabled_services():
        svc = fast.SERVICES[sid]
        chans = fast.channels(sid)
        fresh = cache.get(svc["url"], 10 * 365 * 86400) is not None
        inst = app_installed(svc["package"]) if svc["package"] else None
        app = "no app on this device" if not svc["package"] else {True: "app installed", False: "app NOT installed", None: "app status unknown"}[inst]
        rows.append((svc["name"], bool(chans), "%d sports channels, %s%s" % (len(chans), app, "" if fresh else ", no data")))
    rows.append(("Kodi Live TV / PVR", pvr.available(), "enabled" if pvr.available() else "no PVR client enabled"))
    return rows
