"""Detail page for a movie or show: artwork, synopsis, rating, cast, and the actions
(play on the service that has it, trailer, other services, Trakt watchlist / watched, episodes)."""
import threading
import time

import xbmc
import xbmcgui

from resources.lib import kodi
from resources.lib import finish
from resources.lib.sources import ondemand, tmdb, trakt, youtube

BTN_PLAY, BTN_TRAILER, BTN_EPISODES, BTN_WATCHLIST, BTN_WATCHED, BTN_ALTS, BTN_CLOSE, LIST_EPISODES = 101, 102, 103, 104, 105, 106, 199, 200


class TitleInfo(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.item = kwargs.pop("item")
        self.focus_ep = kwargs.pop("focus_ep", None)  # (season, episode): open on that episode (Up Next)
        self.focus_name = ""                          # that episode's title, once the season is loaded
        self.season_shown = None                      # season number in the episode list
        self.details = kwargs.pop("details", None) or {}
        self.episodes = []
        self.progress = {}
        self.seasons = None            # filled in the background after the page opens
        self.season_eps = {}           # season number -> episodes, prefetched for the likely pick
        self.enriched = threading.Event()
        self.closed = threading.Event()   # set when the page closes: background work stops touching it
        self.season_lock = threading.Lock()
        super().__init__(*args)
        # Everything that decides the button row comes from the card itself, so the buttons are in place
        # from the first frame and never appear late or push each other along.
        self._fill_props()

    def _fill_props(self):
        it, d = self.item, self.details
        self.setProperty("title", it["title"])
        self.setProperty("kicker", "%s • %s" % (it["type"].upper(), it["year"]) if it.get("year") else it["type"].upper())
        rel = it.get("released") or ""
        if rel:
            self.setProperty("kicker", "%s \u2022 %s %s" % (it["type"].upper(), "PREMIERED" if it["type"] == "Show" else "RELEASED", _nice_date(rel)))
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
        self.setProperty("also", ("Also: " + ", ".join("%s (%s)" % (o["service"], o["label"]) for o in offers[1:])) if len(offers) > 1 else "")
        self.setProperty("alts", "1" if len(offers) > 1 else "")
        # "Included" is the usual case and the card already says it; the button only names the exceptions
        # (a long "Play on Paramount+ (Prime) · Included" pushed Mark watched and Close off the screen)
        extra = " · " + it["label"] if it.get("label") and it["label"] != "Included" else ""
        self.setProperty("playlabel", ("Play on %s%s" % (it["service"], extra)) if it.get("play", {}).get("pkg") else "")
        if not it.get("play", {}).get("pkg"):
            self.setProperty("also", it.get("service") or "Not on your services")
        self.setProperty("trailer", "1")
        self.setProperty("trakt", "1" if trakt.signed_in() else "")
        self.setProperty("episodes", "1" if it["type"] == "Show" else "")

    def onInit(self):
        kodi.log("info: page on screen")
        self.getControl(LIST_EPISODES).reset()
        threading.Thread(target=self._enrich, name="sh-info-enrich", daemon=True).start()

    def _enrich(self):
        """After the page is up: TMDB extras, Trakt progress, then the seasons and the likely season's
        episodes, so pressing Episodes is instant."""
        it, t = self.item, time.time()
        try:
            if tmdb.enabled() and not self.details:
                self.details = tmdb.details(it["title"], it.get("year", ""), it["type"]) or {}
                if self.closed.is_set():
                    return
                self._fill_props()
            if trakt.signed_in() and not self.closed.is_set():
                if it["type"] == "Show":
                    self.progress = trakt.show_progress(it["title"], it.get("year", "")) or {}
                    pr = self.progress
                    if pr.get("aired"):
                        full = sum(1 for sn in pr["seasons"].values() if sn["aired"] and sn["completed"] >= sn["aired"])
                        if pr["completed"] >= pr["aired"]:
                            self.setProperty("watched", "Watched every episode")
                        elif pr["completed"]:
                            self.setProperty("watched", "Watched %d of %d episodes - %d of %d seasons complete" % (pr["completed"], pr["aired"], full, len(pr["seasons"])))
                elif trakt.movie_watched(it["title"], it.get("year", "")):
                    self.setProperty("watched", "Watched")
            kodi.log("info: details + Trakt filled in %.2fs" % (time.time() - t))
            if it["type"] == "Show" and not self.closed.is_set():
                self.seasons = self._fetch_seasons()
                pre = self._preselect(self.seasons)
                if self.seasons and not self.closed.is_set():
                    self._episodes_for(self.seasons[pre])
                kodi.log("info: seasons prefetched in %.2fs" % (time.time() - t))
                if self.focus_ep and self.seasons and not self.closed.is_set():
                    sn = next((x for x in self.seasons if str(x["number"]) == str(self.focus_ep[0])), None)
                    if sn:
                        self._show_season(sn, self.focus_ep[1], background=True)
        except Exception as exc:
            kodi.log("info enrich failed: %s" % exc)
        finally:
            self.enriched.set()

    def _fetch_seasons(self):
        it, d = self.item, self.details
        seasons = []
        if d.get("tmdb_id"):
            seasons = [dict(x, episodes=None) for x in tmdb.seasons(d.get("tmdb_id"))]
        if not seasons:
            seasons = ondemand.seasons(it["title"], it.get("year", ""))
        seasons.sort(key=lambda x: x["number"], reverse=True)
        return seasons

    def _episodes_for(self, sn):
        """One fetch per season, shared by the background prefetch and the Episodes button."""
        with self.season_lock:
            if sn["number"] not in self.season_eps:
                self.season_eps[sn["number"]] = self._fetch_episodes(sn)
            return self.season_eps[sn["number"]]

    def _fetch_episodes(self, sn):
        return sn.get("episodes") if sn.get("episodes") is not None else tmdb.episodes(self.details.get("tmdb_id"), sn["number"])

    def _preselect(self, seasons):
        """The first season that isn't finished, else the newest (index into the newest-first list)."""
        prog = (self.progress or {}).get("seasons", {})
        for i, sn in enumerate(sorted(seasons, key=lambda x: x["number"])):
            p = prog.get(sn["number"])
            if not p or p["completed"] < p["aired"]:
                return len(seasons) - 1 - i
        return 0

    def onClick(self, control_id):
        it = self.item
        if control_id == BTN_PLAY:
            self.close()
            if self.focus_ep:  # opened from Up Next: that's the episode being watched
                finish.remember(it["title"], it.get("year", ""), self.focus_ep[0], self.focus_ep[1], self.focus_name)
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
            pick = xbmcgui.Dialog().select("Watch on...", ["%s · %s" % (o["service"], o["label"]) for o in offers])
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
                e = self.episodes[pos]
                finish.remember(it["title"], it.get("year", ""), self.season_shown, e["number"], e.get("name", ""))
                kodi.start_android_activity(it["play"]["pkg"], action="android.intent.action.VIEW", data_uri=it["play"]["url"])

    def _focus_id(self):
        try:
            return self.getFocusId()
        except RuntimeError:
            return 0

    def _busy(self, fn):
        """Run fn with Kodi's spinner showing, so a slow fetch never looks like a dead button."""
        xbmc.executebuiltin("ActivateWindow(busydialognocancel)")
        try:
            return fn()
        finally:
            xbmc.executebuiltin("Dialog.Close(busydialognocancel)")

    def _load_episodes(self):
        it, d = self.item, self.details
        t = time.time()
        if not self.enriched.is_set():
            self._busy(lambda: self.enriched.wait(8))
        seasons = self.seasons if self.seasons is not None else self._busy(self._fetch_seasons)
        if not seasons:
            kodi.notify("No episode data")
            return
        kodi.log("info: %d seasons ready in %.2fs" % (len(seasons), time.time() - t))
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
        pre = self._preselect(seasons)
        pick = xbmcgui.Dialog().select("Season", labels, preselect=pre)
        if pick < 0:
            return
        self._show_season(seasons[pick])

    def _show_season(self, sn, focus_episode=None, background=False):
        """Fill the episode list with one season; focus_episode (its number) selects that one.
        background: filled in by itself after the page opened, so focus only moves if nobody has moved it
        (still on Play, the page's first button) and no picker is open."""
        it = self.item
        prog = (getattr(self, "progress", {}) or {}).get("seasons", {})
        t = time.time()
        self.episodes = self.season_eps.get(sn["number"])
        if self.episodes is None:
            self.episodes = self._busy(lambda: self._episodes_for(sn))
        kodi.log("info: season %s episodes (%d) in %.2fs" % (sn["number"], len(self.episodes or []), time.time() - t))
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
        if not background or (self._focus_id() in (BTN_PLAY, 0) and not xbmc.getCondVisibility("System.HasActiveModalDialog")):
            self.setFocusId(LIST_EPISODES)
        self.season_shown = sn["number"]
        if focus_episode:
            pos = next((i for i, e in enumerate(self.episodes or []) if str(e["number"]) == str(focus_episode)), None)
            if pos is not None:
                lst.selectItem(pos)
                self.focus_name = self.episodes[pos].get("name") or ""

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


def show(item, focus_ep=None):
    """Open the detail page for an on-demand item (dict from sources.ondemand)."""
    dlg = TitleInfo("TitleInfo.xml", kodi.ADDON_PATH, "Default", "1080i", item=item, focus_ep=focus_ep)
    try:
        dlg.doModal()
    finally:
        dlg.closed.set()
    del dlg


def show_by_title(title, year="", kind="", season="", episode=""):
    t = time.time()
    item = ondemand.lookup(title, year, kind)
    kodi.log("info: JustWatch lookup for %s in %.2fs" % (title, time.time() - t))
    if item:
        show(item, (season, episode) if season and episode else None)
    else:
        kodi.notify("No details found")
