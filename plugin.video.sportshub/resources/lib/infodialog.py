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
        d = self.details
        seasons = tmdb.seasons(d.get("tmdb_id"))
        if not seasons:
            kodi.notify("No episode data")
            return
        pick = xbmcgui.Dialog().select("Season", ["Season %s (%s episodes)" % (s["number"], s["count"]) for s in seasons], preselect=len(seasons) - 1)
        if pick < 0:
            return
        self.episodes = tmdb.episodes(d.get("tmdb_id"), seasons[pick]["number"])
        lst = self.getControl(LIST_EPISODES)
        lst.reset()
        for e in self.episodes:
            li = xbmcgui.ListItem("%s. %s" % (e["number"], e["name"]), e["aired"] + (" • %s" % e["runtime"] if e.get("runtime") else ""))
            li.setArt({"thumb": e["still"]})
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
