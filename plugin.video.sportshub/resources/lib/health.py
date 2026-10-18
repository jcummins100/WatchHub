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

    t0 = time.time()
    try:
        fast.save_sports_slim()   # also fills each service's guide cache
        kodi.log("sports channels saved in %.1fs" % (time.time() - t0))
    except Exception as exc:
        kodi.log("warm sports channels failed: %s" % exc)
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
    try:
        from resources.lib import rediscover
        rediscover.today()  # picks the day's row in the background (pool, TMDB collections)
        rediscover.prepare_next()  # and the next 20, for "Show me 20 different movies"
    except Exception as exc:
        kodi.log("warm rediscover failed: %s" % exc)
    if kodi.setting_bool("src_sportsdb", False):
        try:
            sportsdb.tv_today()
        except Exception as exc:
            kodi.log("warm sportsdb failed: %s" % exc)
    _warm_service_views()
    _warm_schedules()


def _warm_schedules():
    """The Sports page's calendars: standings (daily) and this week's games, so a league opens at once."""
    import threading

    def work():
        from resources.lib import schedule
        for lid in schedule.ORDER:
            try:
                schedule.week(lid, 0)
            except Exception as exc:
                kodi.log("warm schedule %s failed: %s" % (lid, exc))
    threading.Thread(target=work, name="sh-schedules", daemon=True).start()


_service_warm = {"running": False}


def _warm_service_views():
    """Fill the caches behind the per-service views (Up Next / New This Week / Trending for one
    service) so switching services in the Services row reads from cache instead of making ~70
    requests while you wait. Runs on its own thread: the first fill is slow, later ones are cache hits."""
    import threading

    if _service_warm["running"]:
        return

    def work():
        _service_warm["running"] = True
        t0 = time.time()
        try:
            from resources.lib.sources import ondemand, trakt
            if trakt.signed_in():
                for t in trakt.up_next(limit=60):
                    ondemand.lookup(t["title"], t["year"], t["type"])
            for code in ondemand.installed_codes():
                ondemand.titles([code], ("MOVIE", "SHOW"), first=40)
                ondemand.new_titles([code])
            kodi.log("service views warmed in %.0fs" % (time.time() - t0))
        except Exception as exc:
            kodi.log("warm service views failed: %s" % exc)
        finally:
            _service_warm["running"] = False

    threading.Thread(target=work, name="sh-warm-services", daemon=True).start()


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
