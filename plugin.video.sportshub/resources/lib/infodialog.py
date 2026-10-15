"""Detail page for a movie or show: artwork, synopsis, rating, cast, and the actions
(play on the service that has it, trailer, other services, Trakt watchlist / watched, episodes)."""
import time

import xbmc
import xbmcgui

from resources.lib import kodi
from resources.lib.sources import ondemand, tmdb, trakt, youtube

BTN_PLAY, BTN_TRAILER, BTN_EPISODES, BTN_WATCHLIST, BTN_WATCHED, BTN_ALTS, BTN_CLOSE, LIST_EPISODES = 101, 102, 103, 104, 105, 106, 199, 200


class TitleInfo(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.item = kwargs.pop("item")
        self.details = kwargs.pop("details", None) or {}
        self.episodes = []
        super().__init__(*args)

    def onInit(self):
        it, d = self.item, self.details
        self.setProperty("title", it["title"])
        self.setProperty("kicker", "%s • %s" % (it["type"].upper(), it["year"]) if it.get("year") else it["type"].upper())
        self.setProperty("poster", d.get("poster") or it.get("poster") or "")
        self.setProperty("backdrop", d.get("backdrop") or it.get("backdrop") or "")
        self.setProperty("plot", d.get("overview") or it.get("plot") or "")
        meta = [x for x in (d.get("genres"), d.get("runtime") or it.get("runtime"), d.get("seasons")) if x]
        self.setProperty("meta", " - ".join(meta) if meta else it.get("meta", ""))
        rating = []
        if it.get("imdb"):
            rating.append("IMDb %s" % it["imdb"])
        if d.get("vote"):
            rating.append("TMDB %s" % d["vote"])
        if d.get("certification") or it.get("certification"):
            rating.append(d.get("certification") or it.get("certification"))
        if it.get("runtime") and not meta:
            rating.append(it["runtime"])
        self.setProperty("rating", "   ".join(rating))
        cast = d.get("cast") or it.get("cast") or ""
        self.setProperty("cast", ("Cast: " + cast) if cast else "")
        self.setProperty("director", ("Director: " + it["director"]) if it.get("director") else "")
        offers = it.get("offers") or []
        self.setProperty("also", ("Also on: " + ", ".join(o["service"] for o in offers[1:])) if len(offers) > 1 else "")
        self.setProperty("alts", "1" if len(offers) > 1 else "")
        self.setProperty("playlabel", ("Play on %s" % it["service"]) if it.get("play", {}).get("pkg") else "")
        if not it.get("play", {}).get("pkg"):
            self.setProperty("also", it.get("service") or "Not on your services")
        self.setProperty("trailer", "1")
        self.setProperty("trakt", "1" if trakt.signed_in() else "")
        self.progress = {}
        if trakt.signed_in():
            try:
                if it["type"] == "Show":
                    self.progress = trakt.show_progress(it["title"], it.get("year", ""))
                    pr = self.progress
                    if pr.get("aired"):
                        full = sum(1 for sn in pr["seasons"].values() if sn["aired"] and sn["completed"] >= sn["aired"])
                        if pr["completed"] >= pr["aired"]:
                            self.setProperty("watched", "Watched every episode")
                        elif pr["completed"]:
                            self.setProperty("watched", "Watched %d of %d episodes - %d of %d seasons complete" % (pr["completed"], pr["aired"], full, len(pr["seasons"])))
                elif trakt.movie_watched(it["title"], it.get("year", "")):
                    self.setProperty("watched", "Watched")
            except Exception as exc:
                kodi.log("trakt progress failed: %s" % exc)
        self.setProperty("episodes", "1" if it["type"] == "Show" else "")
        rel = it.get("released") or ""
        if rel:
            self.setProperty("kicker", "%s \u2022 %s %s" % (it["type"].upper(), "PREMIERED" if it["type"] == "Show" else "RELEASED", _nice_date(rel)))
        self.getControl(LIST_EPISODES).reset()

    def onClick(self, control_id):
        it = self.item
        if control_id == BTN_PLAY:
            self.close()
            kodi.start_android_activity(it["play"]["pkg"], action="android.intent.action.VIEW", data_uri=it["play"]["url"])
        elif control_id == BTN_TRAILER:
            url = tmdb.trailer_url(it["title"], it.get("year", ""), it["type"]) if tmdb.enabled() else ""
            if not url:
                # No TMDB key (or no trailer on file): a YouTube search in the YouTube app is the next best thing.
                import urllib.parse
                url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote("%s %s official trailer" % (it["title"], it.get("year", "")))
            self.close()
            kodi.start_android_activity(youtube.PACKAGE, action="android.intent.action.VIEW", data_uri=url)
        elif control_id == BTN_ALTS:
            offers = it.get("offers") or []
            pick = xbmcgui.Dialog().select("Watch on...", ["%s (%s)" % (o["service"], o["monetization"]) for o in offers])
            if pick >= 0 and offers[pick].get("pkg"):
                self.close()
                kodi.start_android_activity(offers[pick]["pkg"], action="android.intent.action.VIEW", data_uri=offers[pick]["url"])
        elif control_id in (BTN_WATCHLIST, BTN_WATCHED):
            ids = trakt.search_ids(it["title"], it.get("year", ""), it["type"])
            if not ids:
                kodi.notify("Trakt: title not found")
            elif control_id == BTN_WATCHLIST:
                kodi.notify("Added to watchlist" if trakt.add_watchlist(it["type"], ids) else "Trakt: failed")
            else:
                kodi.notify("Marked as watched" if trakt.mark_watched(it["type"], ids) else "Trakt: failed")
        elif control_id == BTN_EPISODES:
            self._load_episodes()
        elif control_id == BTN_CLOSE:
            self.close()
        elif control_id == LIST_EPISODES:
            pos = self.getControl(LIST_EPISODES).getSelectedPosition()
            if 0 <= pos < len(self.episodes) and it.get("play", {}).get("pkg"):
                # Apps rarely deep-link to a specific episode; open the show and let the user pick.
                self.close()
                kodi.start_android_activity(it["play"]["pkg"], action="android.intent.action.VIEW", data_uri=it["play"]["url"])

    def _load_episodes(self):
        it, d = self.item, self.details
        seasons = []
        if d.get("tmdb_id"):
            seasons = [dict(x, episodes=None) for x in tmdb.seasons(d.get("tmdb_id"))]
        if not seasons:
            seasons = ondemand.seasons(it["title"], it.get("year", ""))
        if not seasons:
            kodi.notify("No episode data")
            return
        seasons.sort(key=lambda x: x["number"], reverse=True)
        prog = (getattr(self, "progress", {}) or {}).get("seasons", {})
        labels = []
        for sn in seasons:
            when = _nice_date(sn.get("released", "")) if sn.get("released") else ""
            p = prog.get(sn["number"])
            mark = ""
            if p and p["aired"]:
                if p["completed"] >= p["aired"]:
                    mark = "   [COLOR FF4CD27F]Watched[/COLOR]"
                elif p["completed"]:
                    mark = "   [COLOR FFFFD166]%d of %d watched[/COLOR]" % (p["completed"], p["aired"])
            labels.append("Season %s  (%s episodes%s)%s" % (sn["number"], sn.get("count", "?"), ", from %s" % when if when else "", mark))
        # preselect the first season that isn't finished, else the newest
        pre = 0
        for i, sn in enumerate(sorted(seasons, key=lambda x: x["number"])):
            p = prog.get(sn["number"])
            if not p or p["completed"] < p["aired"]:
                pre = len(seasons) - 1 - i
                break
        pick = xbmcgui.Dialog().select("Season", labels, preselect=pre)
        if pick < 0:
            return
        sn = seasons[pick]
        self.episodes = sn.get("episodes") if sn.get("episodes") is not None else tmdb.episodes(d.get("tmdb_id"), sn["number"])
        seen_map = (prog.get(sn["number"]) or {}).get("episodes") or {}
        p = prog.get(sn["number"])
        status = ""
        if p and p["aired"]:
            status = "  -  all watched" if p["completed"] >= p["aired"] else "  -  %d of %d watched" % (p["completed"], p["aired"])
        self.setProperty("season_label", "Season %s%s" % (sn["number"], status))
        lst = self.getControl(LIST_EPISODES)
        lst.reset()
        today = time.strftime("%Y-%m-%d")
        for e in self.episodes:
            aired = e.get("aired") or ""
            when = ("Airs %s" % _nice_date(aired)) if aired > today else (_nice_date(aired) if aired else "")
            seen = seen_map.get(e["number"])
            li = xbmcgui.ListItem(e["name"] or "Episode %s" % e["number"], " - ".join(x for x in (when, e.get("runtime")) if x))
            li.setArt({"thumb": e.get("still") or ""})
            li.setProperty("num", ("E%s  WATCHED" if seen else "E%s") % e["number"])
            li.setProperty("watched", "1" if seen else "")
            li.setProperty("overview", e.get("overview") or "")
            li.setProperty("upcoming", "1" if aired > today else "")
            lst.addItem(li)
        self.setFocusId(LIST_EPISODES)

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.close()


def _nice_date(iso):
    """2026-08-04 -> Aug 4, 2026"""
    try:
        t = time.strptime(iso[:10], "%Y-%m-%d")
        return time.strftime("%b %d, %Y", t).replace(" 0", " ")
    except (ValueError, TypeError):
        return iso or ""


def show(item):
    """Open the detail page for an on-demand item (dict from sources.ondemand)."""
    details = tmdb.details(item["title"], item.get("year", ""), item["type"]) if tmdb.enabled() else {}
    dlg = TitleInfo("TitleInfo.xml", kodi.ADDON_PATH, "Default", "1080i", item=item, details=details)
    dlg.doModal()
    del dlg


def show_by_title(title, year="", kind=""):
    item = ondemand.lookup(title, year, kind)
    if item:
        show(item)
    else:
        kodi.notify("No details found")
