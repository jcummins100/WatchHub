#!/usr/bin/env python3
"""Open a real browser window for a streaming service's watch history and save the export.

    python3 tools/history_browser.py netflix     # log in, pick a profile, click "Download all" (once per profile)
    python3 tools/history_browser.py prime       # log in; the watch history is scrolled, expanded and saved for you

Each service keeps its own browser profile in ~/.config/watchhub/browser/<service> (this user only, never
in git), so you log in once and the nightly sync can reuse the session. If a site asks for a code or a
captcha, deal with it in the window - this tool never tries to get around it.
Exports land in ~/WatchHub-exports/. Close the window when you're done.
"""
import argparse
import os
import sys
import time

from playwright.sync_api import sync_playwright

URLS = {
    "netflix": "https://www.netflix.com/viewingactivity",
    "prime": "https://www.amazon.com/gp/video/settings/watch-history",
}
PROFILE_ROOT = os.path.expanduser("~/.config/watchhub/browser")
OUT = os.path.expanduser("~/WatchHub-exports")
MONTH = r"(January|February|March|April|May|June|July|August|September|October|November|December) \d+, 20\d\d"


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def save_prime(page):
    """Scroll until the whole history has loaded, open every 'Episodes watched' list, save the text."""
    log("Prime: loading the full watch history (scrolling to the end)...")
    last, still = -1, 0
    while still < 4:
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(1500)
        h = page.evaluate("document.body.scrollHeight")
        still = still + 1 if h == last else 0
        last = h
    opened, failed = 0, 0
    for el in page.get_by_text("Episodes watched", exact=True).all():
        try:
            el.scroll_into_view_if_needed(timeout=3000)
            el.click(timeout=3000)
            opened += 1
            page.wait_for_timeout(250)
        except Exception:
            failed += 1
    if failed:
        log("Prime: %d episode lists could not be opened - those days import as 'show only' (see the report)" % failed)
    page.wait_for_timeout(2000)
    text = page.evaluate("document.body.innerText")
    path = os.path.join(OUT, "prime-watch-history-%s.txt" % time.strftime("%Y%m%d-%H%M"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    log("Prime: saved %s (%d lines, %d episode lists opened)" % (path, text.count("\n"), opened))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("service", choices=sorted(URLS))
    ap.add_argument("--minutes", type=int, default=30, help="close automatically after this long")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    profile = os.path.join(PROFILE_ROOT, a.service)
    os.makedirs(profile, mode=0o700, exist_ok=True)
    os.chmod(PROFILE_ROOT, 0o700)
    with sync_playwright() as p:
        # the installed Google Chrome (Playwright's own Chromium build didn't match its version here)
        ctx = p.chromium.launch_persistent_context(profile, channel="chrome", headless=False, accept_downloads=True,
                                                   viewport={"width": 1280, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        pending = []  # Playwright can't save from inside its event callback; the loop below saves them

        def watch(pg):
            pg.on("download", lambda dl: pending.append(dl))
        for pg in ctx.pages:
            watch(pg)
        ctx.on("page", watch)

        def save_pending():
            while pending:
                dl = pending.pop(0)
                name = "%s-%s-%s" % (a.service, time.strftime("%Y%m%d-%H%M%S"), dl.suggested_filename or "export")
                try:
                    dl.save_as(os.path.join(OUT, name))
                    log("saved download: %s" % name)
                except Exception as exc:
                    log("download not saved: %s" % exc)
        try:
            page.goto(URLS[a.service], timeout=60000)
        except Exception as exc:  # keep the window: the user can still navigate; log why
            log("could not open %s: %s" % (URLS[a.service], exc))
        ctx.on("close", lambda *_: log("browser context closed"))
        if a.service == "netflix":
            log("Netflix: log in if asked, choose a profile, then click 'Download all' at the bottom of Viewing activity.")
            log("For another profile: Account > Profiles > that profile > Viewing activity > Download all. Close the window when done.")
        else:
            log("Prime: log in if asked. Once your watch history shows, it is saved automatically.")
        saved_prime = False
        end = time.time() + a.minutes * 60
        gone = 0  # seconds with no open tab: logins and redirects can briefly leave none
        while time.time() < end:
            pages = [pg for pg in ctx.pages if not pg.is_closed()]
            if not pages:
                gone += 2
                if gone >= 8:
                    break
                time.sleep(2)
                continue
            gone = 0
            save_pending()
            pg = pages[-1]
            if a.service == "prime" and not saved_prime:
                try:
                    if "watch-history" in pg.url and pg.get_by_text(__import__("re").compile(MONTH)).count() > 0:
                        save_prime(pg)
                        saved_prime = True
                        log("Prime: done - you can close the window.")
                except Exception as exc:
                    log("Prime: page not ready yet (%s)" % str(exc)[:80])
            time.sleep(2)
        save_pending()
        try:
            ctx.close()
        except Exception:
            pass
    log("browser closed; exports are in %s" % OUT)


if __name__ == "__main__":
    sys.exit(main())
