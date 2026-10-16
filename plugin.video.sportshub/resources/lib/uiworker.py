"""WatchHub's own windows (info page, TV Guide), opened by the always-running service.

A click sets the Home window property sh_ui_request to the item's plugin URL (the skin does it directly,
the add-on does it for menu entries). A worker thread here picks it up within ~50 ms and opens the window:
no Python start-up per click, the guide's channel list is already built, and the service's own loop
(data refresh, dev hook) keeps running while a window is open.
"""
import threading
import time
from urllib.parse import parse_qsl, urlparse

import xbmcgui

from resources.lib import kodi

REQUEST = "sh_ui_request"


def request(url):
    """Ask the service to open a window; False if no service is running (caller opens it itself)."""
    home = xbmcgui.Window(10000)
    if not home.getProperty("sh_service_alive"):
        return False
    home.setProperty(REQUEST, url)
    return True


class Worker(threading.Thread):
    def __init__(self, monitor):
        super().__init__(name="sh-ui", daemon=True)
        self.monitor = monitor

    def run(self):
        home = xbmcgui.Window(10000)
        while not self.monitor.abortRequested():
            req = home.getProperty(REQUEST)
            if req:
                home.clearProperty(REQUEST)
                try:
                    self.handle(req)
                except Exception as exc:
                    kodi.log("window request failed (%s): %s" % (req, exc))
            if self.monitor.waitForAbort(0.05):
                break

    @staticmethod
    def handle(req):
        params = dict(parse_qsl(urlparse(req).query))
        action = params.get("action")
        t = time.time()
        if action == "info":
            from resources.lib import infodialog
            kodi.log("info: request for %s" % params.get("title", ""))
            infodialog.show_by_title(params.get("title", ""), params.get("year", ""), params.get("kind", ""))
        elif action == "guide":
            from resources.lib import guide
            guide.show(params.get("tab") or None)
        else:
            kodi.log("unknown window request: %s" % req)
            return
        kodi.log("%s window closed after %.0fs" % (action, time.time() - t))


def warm_guide():
    """Build the guide's channel list ahead of time (after each data refresh), on its own thread."""
    def work():
        try:
            from resources.lib import guide
            guide.channels(rebuild=True)
        except Exception as exc:
            kodi.log("guide prebuild failed: %s" % exc)
    threading.Thread(target=work, name="sh-guide-build", daemon=True).start()
