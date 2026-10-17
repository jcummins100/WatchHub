"""The sports calendar window (Calendar.xml): divisions / conferences on the left, that group's games for the
week on the right, previous / next week buttons. Opened by the service (uiworker, action=calendar)."""
import threading
import time

import xbmcgui

from resources.lib import kodi, launcher, schedule

GROUPS, GAMES, PREV, NEXT = 100, 200, 301, 302
ACTION_BACK, ACTION_NAV_BACK = 10, 92


def _clock(t):
    return time.strftime("%I:%M %p", time.localtime(t)).lstrip("0")


class Calendar(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        self.lid = kwargs.get("league") or "nfl"
        self.offset = 0
        self.groups = []
        self.shown = -1
        self.closed = threading.Event()
        super().__init__(*args)
        self.setProperty("title", schedule.LEAGUES[self.lid][0])
        self.setProperty("message", "Loading the schedule…")

    def onInit(self):
        self._load()
        threading.Thread(target=self._follow, name="sh-calendar", daemon=True).start()

    def _load(self):
        t = time.time()
        self.setProperty("message", "Loading the schedule…")
        try:
            data = schedule.week(self.lid, self.offset)
        except Exception as exc:
            kodi.log("calendar: %s failed: %s" % (self.lid, exc))
            data = {"range": "", "groups": []}
        self.groups = [(n, g) for n, g in data["groups"] if g]
        self.setProperty("range", data["range"])
        lst = self.getControl(GROUPS)
        lst.reset()
        items = []
        for name, games in self.groups:
            li = xbmcgui.ListItem(name)
            li.setProperty("count", str(len(games)))
            items.append(li)
        lst.addItems(items)
        self.shown = -1
        if self.groups:
            self.setProperty("message", "")
            self._show(0)
            self.setFocusId(GAMES)
        else:
            self.getControl(GAMES).reset()
            self.setProperty("message", "No %s games this week" % schedule.LEAGUES[self.lid][0])
            self.setFocusId(NEXT)
        kodi.log("calendar: %s week %+d drawn in %.2fs" % (self.lid, self.offset, time.time() - t))

    def _show(self, pos):
        if pos == self.shown or not 0 <= pos < len(self.groups):
            return
        self.shown = pos
        now = time.time()
        lst = self.getControl(GAMES)
        lst.reset()
        items = []
        for g in self.groups[pos][1]:
            li = xbmcgui.ListItem(g["short"] or g["title"])
            day = time.strftime("%a %b %d", time.localtime(g["start"])).replace(" 0", " ") if g["start"] else ""
            if g["state"] == "in":
                status, when = "[COLOR FFE0162B]LIVE[/COLOR]  %s" % (g["score"] or ""), g["detail"]
            elif g["state"] == "post":
                status, when = "Final  %s" % (g["score"] or ""), _clock(g["start"]) if g["start"] else ""
            else:
                status, when = ("Today" if g["start"] and g["start"] - now < 86400 and day == time.strftime("%a %b %d").replace(" 0", " ") else ""), _clock(g["start"]) if g["start"] else "TBD"
            li.setProperty("day", day)
            li.setProperty("time", when)
            li.setProperty("status", status)
            li.setProperty("network", g["channel"] or "No TV listed")
            li.setProperty("away_logo", g["away_logo"])
            li.setProperty("home_logo", g["home_logo"])
            li.setProperty("mine", "1" if g.get("mine") else "")
            items.append(li)
        lst.addItems(items)

    def _follow(self):
        """The games follow the group picked on the left (Kodi tells Python nothing when a list's selection moves)."""
        while not self.closed.is_set():
            try:
                if self.getFocusId() == GROUPS:
                    self._show(self.getControl(GROUPS).getSelectedPosition())
            except RuntimeError:
                return
            self.closed.wait(0.15)

    def onAction(self, action):
        if action.getId() in (ACTION_BACK, ACTION_NAV_BACK):
            self.close()

    def onClick(self, control_id):
        if control_id in (PREV, NEXT):
            self.offset += -1 if control_id == PREV else 1
            self._load()
            self.setFocusId(control_id if not self.groups else GAMES)
        elif control_id == GROUPS:
            self._show(self.getControl(GROUPS).getSelectedPosition())
            self.setFocusId(GAMES)
        elif control_id == GAMES and 0 <= self.shown < len(self.groups):
            pos = self.getControl(GAMES).getSelectedPosition()
            games = self.groups[self.shown][1]
            if not 0 <= pos < len(games):
                return
            g = games[pos]
            if g["state"] == "post":
                kodi.notify("%s - Final %s" % (g["short"], g["score"]), time_ms=3000)
            elif g["playable"]:
                launcher.play(g["play"])
            else:
                kodi.notify("No TV listed for %s yet" % g["short"], time_ms=3000)


def show(league):
    kodi.log("calendar: open %s" % league)
    win = Calendar("Calendar.xml", kodi.ADDON_PATH, "Default", "1080i", league=league if league in schedule.LEAGUES else "nfl")
    try:
        win.doModal()
    finally:
        win.closed.set()
    del win
