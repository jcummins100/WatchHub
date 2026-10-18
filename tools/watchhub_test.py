#!/usr/bin/env python3
"""WatchHub full test run: every row, card type, service filter, menu, action and setting.

It RECORDS what happens; it never fixes anything. Output goes to test-results/<timestamp>/:
report.md (results table + issues/recommendations), results.json, and a screenshot per step.

    python3 tools/watchhub_test.py --ip 10.100.1.200            # everything
    python3 tools/watchhub_test.py --ip 10.100.1.200 --only A    # off-device logic only
    python3 tools/watchhub_test.py --ip 10.100.1.200 --only B    # on-device UI only

Part A (off-device) runs the add-on on this computer through tools/dev_run.py, with the device's own
app list and API keys, so every action/menu/filter/setting combination can be exercised quickly.
Part B (on-device) drives the Shield over adb and reads Kodi's state over JSON-RPC (Kodi's web
server is switched on for the run with a one-off password and switched off again at the end).

Never run: anything that changes the user's Trakt data (mark watched, watchlist, sign out) or that
needs a human (Trakt sign-in code, power off). Those are recorded as SKIP with the reason.
"""
import argparse
import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KODI_PKG = "org.xbmc.kodi"
KODI_HOME = "/sdcard/Android/data/%s/files/.kodi" % KODI_PKG
SETTINGS = KODI_HOME + "/userdata/addon_data/plugin.video.sportshub/settings.xml"
GUISETTINGS = KODI_HOME + "/userdata/guisettings.xml"
LOG = KODI_HOME + "/temp/kodi.log"
FILTER_FILE = KODI_HOME + "/userdata/addon_data/plugin.video.sportshub/home_filter.json"

# Home rows, top to bottom, as Home.xml lays them out (id, name)
FIXED_GUIDE_TABS = ["All", "Favorites", "Categories", "Sports", "News", "Movies", "Game Shows", "Kids", "Search"]
# Live Now and Sports Starting Soon moved to the header's Sports page (0.7.9)
ALL_ROWS = [(9050, "Services"), (9960, "Up Next"), (9200, "Today's Games"),
            (9950, "New This Week"), (9450, "Recommended"), (9800, "Trending"), (9400, "Rediscover"), (9470, "Trailers"), (9700, "Browse"), (9600, "More")]
PROVIDER_ROWS = [(9051, "Services"), (9961, "Up Next on <svc>"), (9951, "New This Week on <svc>"), (9801, "Trending on <svc>")]
# actions the crawler must never run (they change user data, need a human, or switch the skin)
NEVER = {"trakt_watched", "trakt_watchlist", "trakt_signout", "trakt_signin", "settings", "skin", "enable_addon", "refresh", "provider"}


# ====================================================================== report
class Report:
    def __init__(self, out):
        self.out, self.rows, self.notes, self.t0 = out, [], [], time.time()
        os.makedirs(out, exist_ok=True)

    def add(self, area, case, result, detail="", shot=""):
        """result: PASS / FAIL / ISSUE (works, but something is wrong or odd) / INFO / SKIP"""
        self.rows.append({"id": "%s-%03d" % (area.split()[0][:3].upper(), len(self.rows) + 1), "area": area, "case": case,
                          "result": result, "detail": detail, "shot": shot, "t": round(time.time(), 1)})
        print("[%-5s] %s | %s | %s" % (result, area, case, detail[:150]), flush=True)
        print("  @%d" % time.time(), flush=True)  # read by the board's progress panel for stage times
        self.save()

    def note(self, kind, text):
        """kind: Issue / Recommendation / Observation"""
        self.notes.append({"kind": kind, "text": text})
        print("  NOTE %s: %s" % (kind, text), flush=True)
        self.save()

    def save(self):
        with open(os.path.join(self.out, "results.json"), "w") as fh:
            json.dump({"rows": self.rows, "notes": self.notes}, fh, indent=1)
        counts = {}
        for r in self.rows:
            counts[r["result"]] = counts.get(r["result"], 0) + 1
        md = ["# WatchHub test run", "", "Run %s, %d min. Results: %s" % (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(self.t0)), (time.time() - self.t0) // 60,
            ", ".join("%s %d" % kv for kv in sorted(counts.items()))), ""]
        if self.notes:
            md += ["## Issues and recommendations (recorded, not fixed)", "", "| # | Kind | Note |", "| --- | --- | --- |"]
            md += ["| %d | %s | %s |" % (i + 1, n["kind"], n["text"].replace("|", "/")) for i, n in enumerate(self.notes)]
            md += [""]
        md += ["## All results", "", "| ID | Area | Case | Result | Detail | Shot |", "| --- | --- | --- | --- | --- | --- |"]
        for r in self.rows:
            md.append("| %s | %s | %s | %s | %s | %s |" % (r["id"], r["area"], r["case"].replace("|", "/"), r["result"],
                                                          r["detail"].replace("|", "/").replace("\n", " ")[:400],
                                                          "[png](%s)" % r["shot"] if r["shot"] else ""))
        with open(os.path.join(self.out, "report.md"), "w") as fh:
            fh.write("\n".join(md) + "\n")


# ====================================================================== part A: off-device
class Offline:
    def __init__(self, rep, env):
        self.rep, self.env = rep, env

    def run(self, query, **overrides):
        env = dict(os.environ, SH_JSON="1", SH_skin="skin.sportshub", **self.env)
        env.update({"SH_" + k: v for k, v in overrides.items()})
        t = time.time()
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools/dev_run.py"), query], capture_output=True, text=True, env=env, timeout=180)
        took = time.time() - t
        items = None
        for line in p.stdout.splitlines():
            if line.startswith("@@JSON "):
                items = json.loads(line[7:])
        builtins = [l.split("BUILTIN:", 1)[1].strip() for l in p.stdout.splitlines() if "BUILTIN:" in l]
        dialogs = [l.strip() for l in p.stdout.splitlines() if l.strip().startswith(("NOTIFY:", "YESNO:", "DIALOG", "SELECT:", "MULTISELECT:"))]
        err = p.stderr[p.stderr.find("Traceback"):] if "Traceback" in p.stderr else ""
        return {"items": items if items is not None else [], "builtins": builtins, "dialogs": dialogs, "err": err, "took": took,
                "log": [l for l in p.stderr.splitlines() if "LOG:" in l]}

    def suite(self):
        A = "A Logic"
        # A1: every home row, as the skin asks for it
        for name, q in [("Services row", "action=providers&skin=1"), ("Up Next (signed out offline)", "action=trakt&row=upnext&skin=1"),
                        ("Live Sports Now", "action=live&skin=1"), ("Today's Games", "action=games&league=all&skin=1"),
                        ("New This Week", "action=ondemand&row=3&skin=1"), ("Rediscover", "action=rediscover&skin=1"),
                        ("Trending", "action=ondemand&row=0&skin=1"),
                        ("Browse", "action=browse_tiles&skin=1"), ("Starting Soon", "action=soon&skin=1"),
                        ("By sport (More)", "action=sports&skin=1"), ("Your apps (More)", "action=apps&skin=1")]:
            r = self.run(q)
            n = len(r["items"])
            res = "FAIL" if r["err"] else ("ISSUE" if n == 0 else "PASS")
            self.rep.add(A, "Home row: %s" % name, res, "%d items in %.1fs%s" % (n, r["took"], (" | " + r["err"][-300:]) if r["err"] else ""))
            if r["took"] > 15:
                self.rep.note("Issue", "Home row '%s' took %.0fs to build off-device (cold cache) - slow first load on the Shield." % (name, r["took"]))
            missing_art = [i["label"] for i in r["items"] if not (i["art"].get("thumb") or i["art"].get("poster") or i["props"].get("color"))]
            if missing_art:
                self.rep.add(A, "Art present: %s" % name, "ISSUE", "%d cards without artwork: %s" % (len(missing_art), ", ".join(missing_art[:6])))
            empty_label = [i for i in r["items"] if not i["label"].strip()]
            if empty_label:
                self.rep.add(A, "Labels present: %s" % name, "ISSUE", "%d cards with an empty label" % len(empty_label))

        # One card per title on Home (map 5.4): Trending doesn't repeat New This Week
        new_ = {i["label"] for i in self.run("action=ondemand&row=3&home=1&skin=1")["items"]}
        trend = {i["label"] for i in self.run("action=ondemand&row=0&home=1&skin=1")["items"]}
        self.rep.add(A, "Home: Trending doesn't repeat New This Week", "PASS" if trend and not (new_ & trend) else "FAIL",
                     "%d trending, repeats: %s" % (len(trend), sorted(new_ & trend)[:5] or "none"))
        # Rediscover: 1985-2015 movies, a mix of decades, nothing already in New This Week or Trending
        red = self.run("action=rediscover&skin=1")["items"]
        others = {i["label"] for q in ("action=ondemand&row=3&skin=1", "action=ondemand&row=0&skin=1") for i in self.run(q)["items"]}
        years = [int(i["props"].get("year") or 0) for i in red]
        decades = {y // 10 * 10 for y in years}
        dup = sorted({i["label"] for i in red} & others)
        ok = red and all(1985 <= y <= 2015 for y in years) and len(decades) >= 3 and not dup
        self.rep.add(A, "Rediscover: 1985-2015, mixed decades, not repeating other rows", "PASS" if ok else "FAIL",
                     "%d movies, decades %s%s" % (len(red), sorted(decades), (", also in other rows: %s" % dup) if dup else ""))
        # A2: crawl the WatchHub menu (list mode) from the root
        seen, queue, listings, plays = set(), [("action=root", "Menu", 0)], 0, {}
        while queue and listings < 250:
            q, path, depth = queue.pop(0)
            if q in seen:
                continue
            seen.add(q)
            r = self.run(q)
            listings += 1
            n = len(r["items"])
            res = "FAIL" if r["err"] else ("ISSUE" if n == 0 else "PASS")
            if res != "PASS" or depth <= 1:
                self.rep.add(A, "Menu: %s" % path, res, "%d items, %.1fs%s" % (n, r["took"], (" | " + r["err"][-300:]) if r["err"] else ""))
            for it in r["items"]:
                sub = it["url"].split("?", 1)[1] if "?" in it["url"] else ""
                act = re.search(r"action=([a-z_]+)", sub)
                act = act.group(1) if act else ""
                if act in NEVER or not sub:
                    continue
                if it["folder"] and depth < 3:
                    queue.append((sub, "%s > %s" % (path, it["label"][:40]), depth + 1))
                elif not it["folder"]:
                    key = act + ":" + (re.search(r"src=([a-z]+)", sub).group(1) if "src=" in sub else "")
                    plays.setdefault(key, []).append((sub, "%s > %s" % (path, it["label"][:40])))
        r = self.run("action=search&q=ted lasso")
        self.rep.add(A, "Search results for 'ted lasso'", "FAIL" if r["err"] or not r["items"] else "PASS",
                     "%d results: %s" % (len(r["items"]), ", ".join(i["label"] for i in r["items"][:4])))
        self.rep.add(A, "Menu crawl coverage", "INFO", "%d listings opened, %d distinct click types found: %s" % (listings, len(plays), ", ".join(sorted(plays))))

        # A3: every kind of click, 3 samples each: what would actually launch?
        for key, samples in sorted(plays.items()):
            for sub, path in samples[:3]:
                if key.startswith(("search", "ondemand_search", "info")):
                    continue  # needs a keyboard / opens the info dialog: covered on-device
                r = self.run(sub)
                launch = r["builtins"][-1] if r["builtins"] else ""
                if r["err"]:
                    self.rep.add(A, "Click %s: %s" % (key, path), "FAIL", r["err"][-300:])
                elif "market://" in launch:
                    self.rep.add(A, "Click %s: %s" % (key, path), "INFO", "App not installed -> offers Play Store")
                elif "StartAndroidActivity" in launch:
                    deep = re.findall(r'"([^"]*)"', launch)
                    data = deep[3] if len(deep) > 3 else ""
                    self.rep.add(A, "Click %s: %s" % (key, path), "PASS", ("Deep link: %s %s" % (deep[0], data[:90])) if data else "Opens app only: %s" % deep[0])
                elif r["dialogs"]:
                    self.rep.add(A, "Click %s: %s" % (key, path), "INFO", " / ".join(r["dialogs"])[:200])
                elif launch:
                    self.rep.add(A, "Click %s: %s" % (key, path), "PASS", launch[:150])
                else:
                    self.rep.add(A, "Click %s: %s" % (key, path), "ISSUE", "Nothing happens (no launch, no dialog)")

        # A4: every service filter: rows only contain that service
        prov = [i for i in self.run("action=providers&skin=1")["items"] if i["props"].get("code") != "free"]  # "+ Free services" is All-view only
        codes = [re.search(r"code=([a-z]+)", i["url"]).group(1) for i in prov if "code=" in i["url"]]
        self.rep.add(A, "Services row lists", "INFO", ", ".join(i["label"] for i in prov))
        for code in codes:
            name = [i["label"] for i in prov if "code=%s" % code in i["url"]][0]
            sel = self.run("action=providers&skin=1&svc=%s" % code)["items"]
            marked = [i["label"] for i in sel if i["props"].get("selected") == "1"]
            at = [n for n, i in enumerate(sel) if i["props"].get("selected") == "1"]
            nxt = sel[at[0] + 1] if at and at[0] + 1 < len(sel) else {"label": "", "props": {}}
            ok = marked == [name] and nxt["label"] == "Open %s" % name and nxt["props"].get("open") == "1" and len(sel) == len(prov) + 1
            self.rep.add(A, "Filter %s: Services row (picked tile marked, separate 'Open %s' card right after it)" % (name, name),
                         "PASS" if ok else "FAIL", "selected=%s, next=%s, %d tiles (All view %d)" % (marked, nxt["label"], len(sel), len(prov)))
            up = self.run("action=trakt&row=upnext&skin=1&svc=%s" % code)
            self.rep.add(A, "Filter %s: Up Next row (signed out offline)" % name, "FAIL" if up["err"] else "INFO", ", ".join(i["label"] for i in up["items"])[:120] or "empty")
            for row, rname in ((3, "New This Week"), (0, "Trending")):
                r = self.run("action=ondemand&row=%d&skin=1&svc=%s" % (row, code))
                other = sorted({i["props"].get("service") for i in r["items"] if i["props"].get("service") and
                                i["props"].get("service").replace(" channel)", ")") != name})
                n = len(r["items"])
                res = "FAIL" if r["err"] or other else ("FAIL" if n == 0 else "PASS")  # an empty row must explain itself now
                tile = [i["label"].replace("[CR]", " ") for i in r["items"] if i["props"].get("kind") == "tile"]
                self.rep.add(A, "Filter %s: %s" % (name, rname), res, "%d items%s%s%s" % (
                    n, (", other services leaked in: %s" % other) if other else "", (" | tile: %s" % tile[0]) if tile else "",
                    (" | " + r["err"][-200:]) if r["err"] else ""))

        # A5: settings matrix (each compared with the defaults)
        base = {q: self.run(q) for q in ("action=live&skin=1", "action=soon&skin=1", "action=providers&skin=1", "action=root", "action=ondemand")}

        def labels(r):
            return [i["label"] for i in r["items"]]

        def check(case, q, expect, **ov):
            r = self.run(q, **ov)
            ok, why = expect(r, base.get(q))
            self.rep.add(A, "Setting %s" % case, "FAIL" if r["err"] else ("PASS" if ok else "FAIL"), why if not r["err"] else r["err"][-300:])

        def src_gone(tag):
            return lambda r, b: (not any(tag in json.dumps(i).lower() for i in r["items"]),
                                 "%d live items (default %d); %s items left: %d" % (len(r["items"]), len(b["items"]), tag,
                                                                                  sum(tag in json.dumps(i).lower() for i in r["items"])))
        check("src_pluto=false hides Pluto channels", "action=live&skin=1", src_gone("pluto"), src_pluto="false")
        check("src_plex=false hides Plex channels", "action=live&skin=1", src_gone("plex"), src_plex="false")
        check("src_roku=false hides Roku channels", "action=live&skin=1", src_gone("roku"), src_roku="false")
        check("src_samsung=true adds Samsung TV Plus", "action=live&skin=1",
              lambda r, b: (any("samsung" in json.dumps(i).lower() for i in r["items"]), "%d live items vs %d default" % (len(r["items"]), len(b["items"]))),
              src_samsung="true")
        check("games_only=true trims live sports", "action=live&skin=1",
              lambda r, b: (len(r["items"]) <= len(b["items"]), "%d items vs %d default" % (len(r["items"]), len(b["items"]))), games_only="true")
        check("soon_minutes=30 narrows Starting Soon", "action=soon&skin=1",
              lambda r, b: (len(r["items"]) <= len(b["items"]), "%d items vs %d at 120 min" % (len(r["items"]), len(b["items"]))), soon_minutes="30")
        check("amazon_channels empty drops Prime channels", "action=providers&skin=1",
              lambda r, b: (not any("(Prime)" in l for l in labels(r)), ", ".join(labels(r))), amazon_channels="")
        check("amazon_channels adds Starz", "action=providers&skin=1",
              lambda r, b: (any("Starz" in l for l in labels(r)), ", ".join(labels(r))), amazon_channels="aho,app,saz")
        check("src_youtube=false removes YouTube from menu", "action=root",
              lambda r, b: (not any("YouTube" in l for l in labels(r)), ", ".join(labels(r))), src_youtube="false")
        check("src_scores=false: Today's Games shows only 'Live scores are off'", "action=games&league=all&skin=1",
              lambda r, b: (labels(r) == ["Live scores are off"], ", ".join(labels(r)[:3]) or "empty"), src_scores="false")
        check("tmdb_key empty hides Coming Soon menus", "action=ondemand",
              lambda r, b: (not any("Coming soon" in l for l in labels(r)), ", ".join(labels(r))[:200]), tmdb_key="")
        check("region=gb changes catalog", "action=ondemand&row=0&skin=1",
              lambda r, b: (len(r["items"]) > 0, "%d items for GB" % len(r["items"])), region="gb")
        check("view_mode=list (menu still builds)", "action=root",
              lambda r, b: (len(r["items"]) > 0, "%d items" % len(r["items"])), view_mode="list")
        check("trakt_client_id empty: Up Next row empty (no sign-in card)", "action=trakt&row=upnext&skin=1",
              lambda r, b: (len(r["items"]) == 0, ", ".join(labels(r)) or "empty"), trakt_client_id="")
        roku_installed = "com.roku.web.trc" in self.env.get("SH_apps", "")
        check("Roku channels %s (Roku app %s)" % ("shown" if roku_installed else "hidden", "installed" if roku_installed else "missing"), "action=live&skin=1",
              lambda r, b: (any("roku" in json.dumps(i).lower() for i in r["items"]) == roku_installed,
                            "%d live items, %d mention Roku" % (len(r["items"]), sum("roku" in json.dumps(i).lower() for i in r["items"]))))
        check("Roku app missing (simulated): no Roku channels or 'Watch on The Roku Channel'", "action=live&skin=1",
              lambda r, b: (not any("roku" in json.dumps(i).lower() for i in r["items"]),
                            "%d live items, %d mention Roku" % (len(r["items"]), sum("roku" in json.dumps(i).lower() for i in r["items"]))),
              apps=",".join(a for a in self.env.get("SH_apps", "").split(",") if a != "com.roku.web.trc"))
        games = self.run("action=games&league=all&skin=1")["items"]
        with_ctx = [g for g in games if any(c.startswith("Watch on") for c in g["context"])]
        needs = [g for g in games if "needs" in g["props"].get("network", "")]
        self.rep.add(A, "Game cards offer 'Watch on <app>' and flag missing apps", "PASS" if with_ctx else "FAIL",
                     "%d/%d games have Watch-on choices, %d flagged 'needs ... app' (e.g. %s)" % (
                         len(with_ctx), len(games), len(needs), needs[0]["props"]["network"] if needs else "-"))
        check("hide_spanish=true (default): no En Español genre", "action=tvgroups&skin=1",
              lambda r, b: (not any("espa" in l.lower() for l in labels(r)), ", ".join(labels(r))[:200]))
        check("hide_spanish=false: En Español genre back", "action=tvgroups&skin=1",
              lambda r, b: (any("espa" in l.lower() for l in labels(r)), ", ".join(labels(r))[:200]), hide_spanish="false")
        check("Sports page Live sports now: no TV Guide card, only sports", "action=live&skin=1",
              lambda r, b: (bool(r["items"]) and all(i["props"].get("kind") != "guide" for i in r["items"]), ", ".join(labels(r)[:3])))
        check("service_priority plex first", "action=live&skin=1",
              lambda r, b: (len(r["items"]) > 0, "first 3 now: %s" % ", ".join(labels(r)[:3])), service_priority="plex,pluto,roku,samsung")


    def py(self, code):
        """Run a snippet against WatchHub's code with the dev stubs (a scratch profile); it prints one JSON line."""
        env = dict(os.environ, SH_skin="skin.sportshub", **self.env)
        env.pop("SH_JSON", None)
        src = ("import contextlib, io, json, os, runpy, sys, tempfile\n"
               "sys.argv = [sys.argv[0], 'action=__none__']\n"
               "with contextlib.redirect_stdout(io.StringIO()):\n"
               "    runpy.run_path(%r, run_name='x')\n"
               "sys.path.insert(0, %r)\n" % (os.path.join(ROOT, "tools/dev_run.py"), os.path.join(ROOT, "plugin.video.sportshub")) + code)
        src = src.replace("print(json.dumps(", "print('@@R ' + json.dumps(")
        p = subprocess.run([sys.executable, "-c", src], capture_output=True, text=True, env=env, timeout=300, cwd=ROOT)
        try:
            return json.loads([l[4:] for l in p.stdout.splitlines() if l.startswith("@@R ")][-1]), ""
        except (ValueError, IndexError):
            err = p.stderr[p.stderr.find("Traceback"):] if "Traceback" in p.stderr else (p.stderr or p.stdout)
            return None, err[-400:]

    def new_features(self):
        """A8: the features added in 0.6.1-0.7.28, checked against WatchHub's own code (no Shield needed)."""
        A = "A Logic"

        def add(name, code, judge):
            res, err = self.py(code)
            if res is None:
                self.rep.add(A, name, "FAIL", err)
                return
            ok, detail = judge(res)
            self.rep.add(A, name, ok if isinstance(ok, str) else ("PASS" if ok else "FAIL"), detail)

        add("Home rows: default order (Services ... Trailers, Browse, More)",
            "from resources.lib import homerows as h\nx=open(os.path.join(%r,'skin.sportshub/xml/Home.xml')).read()\n"
            "print(json.dumps({'cur':h.current(x),'default':h.DEFAULT,'same':h.render(x,h.DEFAULT,[])==x}))" % ROOT,
            lambda r: (r["cur"] == r["default"] and r["same"], "skin order %s, re-rendering the default changes nothing: %s" % (r["cur"], r["same"])))
        add("Home rows editor: move + hide renders, and back again exactly",
            "from resources.lib import homerows as h\nx=open(os.path.join(%r,'skin.sportshub/xml/Home.xml')).read()\n"
            "o=list(h.DEFAULT); o.insert(0,o.pop(o.index('9400')))\ny=h.render(x,o,['9200'])\n"
            "print(json.dumps({'cur':h.current(y),'off':'content_path_off' in y,'back':h.render(y,h.DEFAULT,[])==x}))" % ROOT,
            lambda r: (r["cur"][0] == "9400" and "9200" not in r["cur"] and r["off"] and r["back"], json.dumps(r)))
        add("Up Next order: move up / top / end / usual place / hide",
            "from resources.lib import upnext as u, kodi\nkodi.PROFILE_PATH=tempfile.mkdtemp()\n"
            "it=[{'title':t,'year':2020,'next':'S01E01'} for t in 'ABCDE']\nK=lambda:[x['title'] for x in u.arrange(it)]\nkey=lambda:[u.key(x['title'],2020) for x in u.arrange(it)]\n"
            "u.move_up('C',2020,key()); a=K(); u.move_top('E',2020); b=K(); u.move_back('A',2020); c=K(); u.hide('B',2020,'S01E01'); d=K()\n"
            "it[1]['next']='S01E02'; e=K()\nprint(json.dumps([a,b,c,d,e]))",
            lambda r: (r == [list("ACBDE"), list("EACBD"), list("ECBDA"), list("ECDA"), list("ECBDA")], json.dumps(r)))
        add("Recommended: daily set, different picks, pins first",
            "from resources.lib import recommend as r, kodi\nkodi.PROFILE_PATH=tempfile.mkdtemp()\nc=['k%02d'%i for i in range(45)]\n"
            "a=r.choose(c); r.reshuffle(); b=r.choose(c); r.pin('k44','',''); k=r.key('k44','',''); r.reshuffle(); d=r.choose(c+[k])\n"
            "print(json.dumps({'a':len(a),'overlap':len(set(a)&set(b)),'pin_first':d[0]==k,'n':len(d)}))",
            lambda r: (r["a"] == 20 and r["overlap"] == 0 and r["pin_first"] and r["n"] == 20, json.dumps(r)))
        add("Long-press menu: one order, Watch on / Move / Trakt grouped",
            "from resources.lib import uiworker as u\n"
            "L=['Hide this movie','Trakt: mark as watched','Pin (keep it when the row changes)','Watch on Hulu','Play on Netflix','Watch on Apple TV','Watch trailer','\u2605 Add to Favorites','Trakt: add to watchlist','Move up one','Move to the top of Up Next','More like this']\n"
            "e=[[l,'c'] for l in L]; e.sort(key=lambda x:u.menu_rank(x[0]))\nprint(json.dumps([[n, [x[0] for x in s] if isinstance(s,list) else ''] for n,s in u.group_menu(e)]))",
            lambda r: ([n for n, _ in r] == ["Play on Netflix", "Watch on\u2026", "Watch trailer", "Move\u2026", "More like this", "\u2605 Add to Favorites",
                                              "Trakt\u2026", "Pin (keep it when the row changes)", "Hide this movie"], " / ".join(n for n, _ in r)))
        add("Rediscover: Pin kept through \"Show me 20 different movies\"",
            "from resources.lib import rediscover as rd, kodi\nkodi.PROFILE_PATH=tempfile.mkdtemp()\n"
            "rd._save({'picks':['a','b','c'],'next':['x','y','z'],'pinned':['b'],'day':'d'})\nrd.reshuffle()\nprint(json.dumps(rd._load()['picks']))",
            lambda r: (r[0] == "b" and "x" in r and "a" not in r, json.dumps(r)))
        add("TV Guide: All first, Search last; a search shows under the Search tab",
            "from resources.lib import guide as g\nch=g.channels()\nr=g.in_tab(ch,'\u201cprice\u201d',[])\n"
            "print(json.dumps({'tabs':g.tabs('\u201cprice\u201d'),'n':len(r),'first':[c['name'] for c in r[:3]]}))",
            lambda r: (r["tabs"][0] == "All" and r["tabs"][-1] == "Search" and not any(t.startswith("\u201c") for t in r["tabs"]) and r["n"] > 0,
                       "tabs %s; 'price' finds %d: %s" % (r["tabs"], r["n"], r["first"])))
        add("Xumo: channel link tunes (deepLinkType=channel_no_ui with a path)",
            "from resources.lib.sources import fast\nprint(json.dumps(fast.SERVICES['xumo']['deeplink']))",
            lambda r: ("www.xumo.tv/live?" in r and "channel_no_ui" in r and "{id}" in r, r))
        add("Sports calendar: NFL week grouped by division",
            "from resources.lib import schedule\nw=schedule.week('nfl',0)\nprint(json.dumps({'range':w['range'],'groups':[[n,len(g)] for n,g in w['groups']]}))",
            lambda r: (len([g for g in r["groups"] if g[0].startswith(("AFC", "NFC"))]) >= 6 or "No games" in r["range"],
                       "%s: %s" % (r["range"], ", ".join("%s %d" % tuple(g) for g in r["groups"][:6]))))
        add("Episode links: MobLand S2E05 has its own link",
            "from resources.lib.sources import ondemand\nprint(json.dumps(ondemand.episode_link('MobLand','2025',2,5)))",
            lambda r: ("ISSUE" if not r else "watch" in r[1] or "/episode/" in r[1], json.dumps(r)))
        add("Info page: The Dark Knight series + You may also like",
            "from resources.lib.sources import tmdb\nok=tmdb.enabled()\nd=tmdb.details('The Dark Knight','2008','Movie') if ok else {}\n"
            "n,p,r=tmdb.related(d.get('media'),d.get('tmdb_id')) if ok else ('',[],[])\nprint(json.dumps({'key':ok,'series':[x['title'] for x in p],'recs':len(r)}))",
            lambda r: ("INFO" if not r["key"] else len(r["series"]) >= 3 and r["recs"] > 3,
                       "no TMDB key off-device" if not r["key"] else "%s; %d recommendations" % (r["series"], r["recs"])))
        add("About WatchHub: version and What's new",
            "from resources.lib import settingsmenu as m\nt=m.about_text()\nprint(json.dumps({'ok':\"What's new\" in t,'first':t.split('\\n')[6:8]}))",
            lambda r: (r["ok"], json.dumps(r["first"])))
        for name, q in [("Recommended for you", "action=trakt&row=recommended&skin=1"), ("Trailers", "action=trailers&skin=1"),
                        ("Sports page: Schedules", "action=calendars&skin=1")]:
            r = self.run(q)
            n = len(r["items"])
            res = "FAIL" if r["err"] else ("PASS" if n else "INFO")
            self.rep.add(A, "Home row: %s" % name, res, "%d items in %.1fs%s" % (n, r["took"], " (needs Trakt / TMDB, off-device has neither)" if not n else ""))


# ====================================================================== part B: on-device

    def favorites_check(self):
        """A7: the \u2605 Favorites screen: add a title, see it listed, remove it again (off-device profile only)."""
        A = "A Logic"
        key = "title:wh-test-show:2020"
        add = self.run("action=fav&what=title&key=%s&label=WH Test Show&year=2020&kind=Show" % key)
        listed = self.run("action=favorites&skin=1")
        has = any("WH Test Show" in i["label"] for i in listed["items"])
        self.run("action=fav&what=title&key=%s&label=WH Test Show" % key)
        after = self.run("action=favorites&skin=1")
        gone = not any("WH Test Show" in i["label"] for i in after["items"])
        ok = has and gone and not (add["err"] or listed["err"] or after["err"])
        self.rep.add(A, "Favorites: add a title, list it, remove it", "PASS" if ok else "FAIL",
                     "listed=%s removed=%s %s" % (has, gone, (add["err"] or listed["err"] or after["err"])[-200:]))

    def guide_data(self):
        """A6: the TV Guide's tabs as the Shield would build them (Game Shows, Plex/Roku genres, Spanish filter)."""
        A = "A Logic"
        env = dict(os.environ, **self.env)
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools/guide_report.py")], capture_output=True, text=True, env=env, timeout=300)
        try:
            g = json.loads(p.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            self.rep.add(A, "Guide data builds", "FAIL", (p.stderr or p.stdout)[-300:])
            return
        tabs = g["tabs"]
        self.rep.add(A, "Guide data builds", "PASS", "%d rows; %s" % (g["rows"], ", ".join("%s %d" % (t, v["total"]) for t, v in tabs.items())))
        gs = " | ".join(g["game_shows"]).lower()
        want = ["price is right", "family feud", "make a deal"]
        bad = [n for n in g["game_shows"] if any(w in n.lower() for w in ("dr. phil", "judge", "qvc", "hsn", "game & fish", "rap game", "game-on"))]
        missing = [w for w in want if w not in gs]
        self.rep.add(A, "Guide: Game Shows tab", "FAIL" if missing or bad else "PASS",
                     "%d channels%s%s: %s" % (len(g["game_shows"]), "; missing " + ", ".join(missing) if missing else "",
                                              "; should not be there: " + ", ".join(bad) if bad else "", ", ".join(g["game_shows"])[:250]))
        plex = {t: v["by_service"].get("Plex", 0) for t, v in tabs.items()}
        plex_total = sum(plex.values()) or 1
        ok = plex.get("News", 0) >= 8 and plex.get("Movies", 0) >= 15 and plex.get("Kids", 0) >= 10 and plex.get("Shows", 0) / plex_total < 0.7
        self.rep.add(A, "Guide: Plex channels sorted into genres", "PASS" if ok else "ISSUE", ", ".join("%s %d" % kv for kv in plex.items()))
        self.rep.add(A, "Guide: no Spanish channels by name", "FAIL" if g["spanish_shown"] else "PASS",
                     ", ".join(g["spanish_shown"])[:250] or "none shown")



class Device:
    def __init__(self, ip, adb, out):
        self.ip, self.adb_bin, self.out, self.serial = ip, adb, out, "%s:5555" % ip
        self.rpc_auth, self.n = None, 0

    def adb(self, *args, timeout=60, binary=False):
        p = subprocess.run([self.adb_bin, "-s", self.serial] + list(args), capture_output=True, timeout=timeout)
        return p.stdout if binary else p.stdout.decode("utf-8", "replace")

    def sh(self, cmd, timeout=60):
        return self.adb("shell", cmd, timeout=timeout)

    def fg(self):
        m = re.search(r"mCurrentFocus=Window\{\S+ \S+ ([^/ }]+)", self.sh("dumpsys window | grep mCurrentFocus"))
        return m.group(1) if m else ""

    def shot(self, name):
        self.n += 1
        fn = "%03d-%s.png" % (self.n, re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60])
        with open(os.path.join(self.out, fn), "wb") as fh:
            fh.write(self.adb("exec-out", "screencap -p", binary=True))
        return fn

    def log_lines(self):
        return int((self.sh("wc -l < %s" % LOG).strip() or "0"))

    def log_since(self, mark):
        return self.sh("tail -n +%d %s" % (mark + 1, LOG)).splitlines()

    # ---- JSON-RPC
    def rpc(self, method, params=None, timeout=10):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
        req = urllib.request.Request("http://%s:8080/jsonrpc" % self.ip, data=body, headers={
            "Content-Type": "application/json", "Authorization": "Basic " + base64.b64encode(self.rpc_auth.encode()).decode()})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()).get("result")

    def info(self, *labels):
        try:
            return self.rpc("XBMC.GetInfoLabels", {"labels": list(labels)}) or {}
        except Exception:
            return {}

    def is_(self, *bools):
        try:
            return self.rpc("XBMC.GetInfoBooleans", {"booleans": list(bools)}) or {}
        except Exception:
            return {}

    def builtin(self, cmd):
        """Run a Kodi builtin through WatchHub's service (its dev hook: <profile>/cmd, picked up within ~2 s)."""
        local = os.path.join(self.out, "_cmd.txt")
        with open(local, "w", encoding="utf-8") as fh:
            fh.write(cmd + "\n")
        self.adb("push", local, KODI_HOME + "/userdata/addon_data/plugin.video.sportshub/cmd")

    def key(self, name, times=1):
        for _ in range(times):
            try:
                self.rpc("Input." + name)
            except Exception:
                self.sh("input keyevent KEYCODE_%s" % {"Up": "DPAD_UP", "Down": "DPAD_DOWN", "Left": "DPAD_LEFT", "Right": "DPAD_RIGHT",
                                                       "Select": "DPAD_CENTER", "Back": "BACK", "ContextMenu": "MENU", "Home": "HOME"}[name])
            time.sleep(0.35)

    def focus(self):
        try:
            return int(self.info("System.CurrentControlId").get("System.CurrentControlId") or 0)
        except ValueError:
            return 0

    def wait(self, cond, secs=20, step=0.5):
        end = time.time() + secs
        while time.time() < end:
            v = cond()
            if v:
                return v
            time.sleep(step)
        return None

    def kodi_front(self):
        if self.fg() != KODI_PKG:
            self.sh("monkey -p %s -c android.intent.category.LAUNCHER 1" % KODI_PKG)
            self.wait(lambda: self.fg() == KODI_PKG, 20)
            time.sleep(1.5)
        # Android may have killed Kodi while the other app ran: then this was a cold start - wait for it
        pid = self.sh("pidof %s" % KODI_PKG).strip()
        cold = pid != getattr(self, "kodi_pid", pid) or not self.info("System.CurrentControlId").get("System.CurrentControlId")
        self.kodi_pid = pid
        if cold:
            self.restarts = getattr(self, "restarts", 0) + 1
            self.wait(lambda: any(int(v or 0) > 0 for v in self.info("Container(9050).NumItems", "Container(9051).NumItems").values()), 90, 1)
            if self.sh("cat %s 2>/dev/null" % FILTER_FILE).count('"code": "') and '"code": ""' not in self.sh("cat %s" % FILTER_FILE):
                # a saved filter is put back by the service a moment after the home screen appears
                self.wait(lambda: self.info("Window(Home).Property(sh_provider)").get("Window(Home).Property(sh_provider)"), 40, 1)
            self.wait(lambda: self.info("System.CurrentControlId").get("System.CurrentControlId"), 90, 1)
            self.wait(lambda: not any(self.is_(*["Container(%d).IsUpdating" % i for i, _ in ALL_ROWS[:-1]]).values()), 60, 1)

    def home(self):
        """Close dialogs/windows until the WatchHub home is showing."""
        self.kodi_front()
        for _ in range(6):
            if self.is_("Window.IsActive(home)").get("Window.IsActive(home)") and not self.is_("System.HasActiveModalDialog").get("System.HasActiveModalDialog"):
                return True
            self.key("Back")
            time.sleep(0.8)
        return bool(self.is_("Window.IsActive(home)").get("Window.IsActive(home)"))

    def goto_row(self, target, order):
        ids = [i for i, _ in order]
        for _ in range(25):
            cur = self.focus()
            if cur == target:
                return True
            if cur in ids:
                self.key("Down" if ids.index(cur) < ids.index(target) else "Up")
            else:  # header buttons, or nothing: step down into the rows
                self.key("Down")
        return self.focus() == target

    def goto_item(self, cid, n):
        """1-based position n in container cid."""
        for _ in range(60):
            pos = int(self.info("Container(%d).CurrentItem" % cid).get("Container(%d).CurrentItem" % cid) or 0)
            if pos == n:
                return True
            self.key("Right" if pos < n else "Left")
        return False

    def goto_code(self, cid, code):
        """Move to the Services tile for `code` ("" = All services); labels change ("Open Hulu") but codes don't."""
        n = int(self.info("Container(%d).NumItems" % cid).get("Container(%d).NumItems" % cid) or 0)
        for k in range(n):
            if self.info("Container(%d).ListItemAbsolute(%d).Property(code)" % (cid, k)).get("Container(%d).ListItemAbsolute(%d).Property(code)" % (cid, k)) == code:
                return self.goto_item(cid, k + 1)
        return False

    def goto_label(self, cid, label):
        """Move to the item whose label is `label` (positions shift when the Services row inserts its Open card)."""
        n = int(self.info("Container(%d).NumItems" % cid).get("Container(%d).NumItems" % cid) or 0)
        for k in range(n):
            if self.info("Container(%d).ListItemAbsolute(%d).Label" % (cid, k)).get("Container(%d).ListItemAbsolute(%d).Label" % (cid, k)) == label:
                return self.goto_item(cid, k + 1)
        return False

    def restart_kodi(self, rpc=True):
        self.sh("am force-stop %s" % KODI_PKG)
        time.sleep(2)
        t = time.time()
        self.sh("input keyevent KEYCODE_WAKEUP")
        self.sh("monkey -p %s -c android.intent.category.LAUNCHER 1" % KODI_PKG)
        if not rpc:  # JSON-RPC switched off: just give the home screen time to build
            self.wait(lambda: self.fg() == KODI_PKG, 30, 1)
            time.sleep(30)
            return time.time() - t
        ok = self.wait(lambda: self.info("System.CurrentControlId").get("System.CurrentControlId") not in (None, ""), 90, 1)
        # rows finished loading
        self.wait(lambda: not any(self.is_(*["Container(%d).IsUpdating" % i for i, _ in ALL_ROWS[:-1]]).values()), 60, 1)
        return time.time() - t if ok else None



class OnDevice:
    def __init__(self, rep, dev, keep_rpc):
        self.rep, self.d, self.keep_rpc = rep, dev, keep_rpc
        self.changed_settings = {}

    # ---- settings.xml edits that restore ONLY the keys we touched (the file also holds live Trakt tokens)
    def _pull(self, remote):
        local = os.path.join(self.d.out, "_tmp_" + os.path.basename(remote))
        self.d.adb("pull", remote, local)
        with open(local, encoding="utf-8") as fh:
            return fh.read(), local

    def _push(self, remote, text, local):
        with open(local, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.d.adb("push", local, remote)

    @staticmethod
    def _set(xml, sid, value):
        pat = re.compile(r'<setting id="%s"[^>]*?(/>|>[^<]*</setting>)' % re.escape(sid))
        new = '<setting id="%s">%s</setting>' % (sid, value) if value != "" else '<setting id="%s" />' % sid
        if pat.search(xml):
            return pat.sub(new, xml, 1)
        return xml.replace("</settings>", "    %s\n</settings>" % new)

    @staticmethod
    def _get(xml, sid):
        m = re.search(r'<setting id="%s"[^>]*?(?:/>|>([^<]*)</setting>)' % re.escape(sid), xml)
        return (m.group(1) or "") if m else None

    def set_addon_settings(self, **kv):
        """Kodi must be stopped. Remembers original values for restore."""
        xml, local = self._pull(SETTINGS)
        for k, v in kv.items():
            if k not in self.changed_settings:
                self.changed_settings[k] = self._get(xml, k)
            xml = self._set(xml, k, v)
        self._push(SETTINGS, xml, local)

    def restore_addon_settings(self):
        if not self.changed_settings:
            return
        self.d.sh("am force-stop %s" % KODI_PKG)
        time.sleep(2)
        xml, local = self._pull(SETTINGS)
        for k, v in self.changed_settings.items():
            if v is None:
                # the key wasn't in the file before the test: take it out again (an empty value makes Kodi
                # log "failed to load value" for it on every start)
                xml = re.sub(r'\s*<setting id="%s"[^>]*?(?:/>|>[^<]*</setting>)' % re.escape(k), "", xml, count=1)
            else:
                xml = self._set(xml, k, v)
        self._push(SETTINGS, xml, local)
        self.changed_settings = {}

    def set_gui(self, **kv):
        xml, local = self._pull(GUISETTINGS)
        for k, v in kv.items():
            pat = re.compile(r'<setting id="%s"[^>]*?(?:/>|>[^<]*</setting>)' % re.escape(k))
            new = '<setting id="%s">%s</setting>' % (k, v)
            xml = pat.sub(new, xml, 1) if pat.search(xml) else xml.replace("</settings>", "    %s\n</settings>" % new)
        self._push(GUISETTINGS, xml, local)

    # ---- one click, and what came of it
    def click(self, area, case, expect=None, back=True, settle=2.5):
        d = self.d
        mark = d.log_lines()
        d.key("Select")
        launched = d.wait(lambda: (lambda f: f if f and f != KODI_PKG else None)(d.fg()), 6, 0.5)
        time.sleep(settle if launched else 1.5)
        shot = d.shot(case)
        lines = d.log_since(mark)
        tb = [l for l in lines if "Traceback" in l or "EXCEPTION" in l or "Error Contents" in l]
        state = d.info("System.CurrentWindow", "Window(Home).Property(sh_provider)")
        dialogs = [k for k, v in d.is_("Window.IsActive(yesnodialog)", "Window.IsActive(contextmenu)", "Window.IsActive(busydialog)",
                                       "Window.IsActive(selectdialog)", "Window.IsActive(okdialog)", "Window.IsActive(addonsettings)",
                                       "Window.IsActive(virtualkeyboard)", "Window.IsActive(TitleInfo.xml)", "Window.IsActive(Browse.xml)", "Window.IsActive(videos)",
                                       "Window.IsActive(shutdownmenu)", "Window.IsActive(skinsettings)").items() if v]
        outcome = ("launched %s" % launched) if launched else ("window: %s %s" % (state.get("System.CurrentWindow"), ",".join(x[16:-1] for x in dialogs)))
        result = "FAIL" if tb else "PASS"
        if expect and not tb:
            ok = expect(launched, state, dialogs)
            result = "PASS" if ok else "FAIL"
        self.rep.add(area, case, result, outcome + ((" | " + tb[0][-200:]) if tb else ""), shot)
        if back:
            if launched:
                d.sh("am force-stop %s" % launched)
            d.home()
        return launched, state, dialogs

    def suite(self):
        d, rep = self.d, self.rep
        B = "B Device"
        # ---------------- setup: versions, apps, JSON-RPC for the run
        ver = d.sh("grep -o 'version=\"[0-9.]*\"' %s/addons/plugin.video.sportshub/addon.xml | sed -n 2p" % KODI_HOME).strip()
        rep.add(B, "Installed WatchHub version", "INFO", ver)
        apps = sorted(l.split(":", 1)[1] for l in d.sh("pm list packages -3").split() if ":" in l)
        rep.add(B, "Third-party apps on device", "INFO", ", ".join(apps))
        d.rpc_auth = "kodi:" + secrets.token_urlsafe(12)
        d.sh("am force-stop %s" % KODI_PKG)
        time.sleep(2)
        d.sh("rm -f %s" % FILTER_FILE)  # every run starts on All services
        self.set_gui(**{"services.webserver": "true", "services.webserverport": "8080", "services.webserverauthentication": "true",
                        "services.webserverusername": "kodi", "services.webserverpassword": d.rpc_auth.split(":", 1)[1]})
        took = d.restart_kodi()
        try:
            d.rpc("JSONRPC.Ping")
            rep.add(B, "Kodi started + JSON-RPC test channel up", "PASS", "home ready in %.0fs" % (took or -1))
        except Exception as exc:
            rep.add(B, "Kodi started + JSON-RPC test channel up", "FAIL", "JSON-RPC unreachable: %s (falling back to adb keys only)" % exc)
        try:
            self._ui_tests(B)
        finally:
            self.restore_addon_settings()
            d.sh("am force-stop %s" % KODI_PKG)
            d.sh("rm -f %s" % FILTER_FILE)
            if not self.keep_rpc:
                d.sh("am force-stop %s" % KODI_PKG)
                time.sleep(2)
                self.set_gui(**{"services.webserver": "false", "services.webserverpassword": ""})
            d.restart_kodi(rpc=self.keep_rpc)
            rep.add(B, "Cleanup: settings restored, JSON-RPC off, Kodi restarted", "INFO", "")

    def _ui_tests(self, B):
        d, rep = self.d, self.rep
        if os.environ.get("WH_ONLY_FILTERS"):
            return self._filters(B)
        gaps = bool(os.environ.get("WH_GAPS"))
        if gaps:
            return self._gaps(B)
        if os.environ.get("WH_SERVICES"):
            d.kodi_pid = d.sh("pidof %s" % KODI_PKG).strip()
            self._filters(B)
            return self._free_tv_and_power(B)
        # ---------------- startup
        st = d.info("System.CurrentControlId", "System.CurrentWindow", "Window(Home).Property(sh_provider)", "Skin.CurrentTheme", "System.BuildVersion")
        rep.add(B, "Startup lands on WatchHub home, Up Next focused", "PASS" if st.get("System.CurrentControlId") == "9960" else "ISSUE",
                json.dumps(st), d.shot("startup"))

        # ---------------- All view: every row reachable in order, counts, hero
        d.home()
        d.goto_row(9050, ALL_ROWS)
        prev = None
        for cid, name in ALL_ROWS:
            ok = d.goto_row(cid, ALL_ROWS)
            info = d.info("Container(%d).NumItems" % cid, "Container(%d).ListItem.Label" % cid, "Control.GetLabel(%d)" % cid)
            hero = d.info("$VAR[SH_HeroTitle]", "$VAR[SH_HeroKicker]", "$VAR[SH_HeroMeta]")
            n = int(info.get("Container(%d).NumItems" % cid) or 0)
            res = "PASS" if ok and (n > 0 or cid == 9600) else ("ISSUE" if ok else "FAIL")
            rep.add(B, "All view row: %s" % name, res, "reached=%s items=%s first='%s' hero='%s / %s'" % (
                ok, n, info.get("Container(%d).ListItem.Label" % cid, ""), hero.get("$VAR[SH_HeroKicker]", ""), hero.get("$VAR[SH_HeroTitle]", "")),
                d.shot("row-%s" % name))
            prev = cid
        # Down from the last row, Up from Services
        d.goto_row(9600, ALL_ROWS)
        d.key("Down")
        rep.add(B, "Down on last row (More) stays put", "PASS" if d.focus() == 9600 else "ISSUE", "focus=%s" % d.focus())
        d.goto_row(9050, ALL_ROWS)
        d.key("Up")
        rep.add(B, "Up from Services reaches header buttons", "PASS" if d.focus() not in [i for i, _ in ALL_ROWS] else "ISSUE",
                "focus=%s" % d.focus(), d.shot("header-focus"))
        # sideways through a row to the end and back
        d.goto_row(9700, ALL_ROWS)
        n = int(d.info("Container(9700).NumItems").get("Container(9700).NumItems") or 0)
        d.goto_item(9700, n)
        d.key("Right")
        end_ok = int(d.info("Container(9700).CurrentItem").get("Container(9700).CurrentItem") or 0) == n
        rep.add(B, "Right at end of a row stops (no wrap)", "PASS" if end_ok else "ISSUE", "%d items" % n, d.shot("row-end"))
        last = d.info("Container(9700).ListItem.Label", "Container(9700).ListItem.Property(kind)")
        if last.get("Container(9700).ListItem.Label") == "More..." and not last.get("Container(9700).ListItem.Property(kind)"):
            self.click(B, "Row end: 'See all' card opens the full Live Sports list", lambda l, s_, dl: "Window.IsActive(videos)" in dl)
            d.goto_row(9700, ALL_ROWS)
        d.goto_item(9700, 1)

        # ---------------- every card type: click and see what happens
        def row_clicks(cid, name, count, expect=None, first=1):
            d.home()
            if not d.goto_row(cid, ALL_ROWS):
                rep.add(B, "Click %s" % name, "FAIL", "row not reachable (empty?)")
                return
            total = int(d.info("Container(%d).NumItems" % cid).get("Container(%d).NumItems" % cid) or 0)
            if not total:
                rep.add(B, "Click %s" % name, "ISSUE", "row reached but has no items (or Kodi not answering)", d.shot("empty-%s" % name))
            for k in range(first, min(count + first - 1, total) + 1):
                d.goto_row(cid, ALL_ROWS)
                d.goto_item(cid, k)
                lab = d.info("Container(%d).ListItem.Label" % cid, "Container(%d).ListItem.Property(meta)" % cid)
                self.click(B, "Click %s #%d: %s" % (name, k, lab.get("Container(%d).ListItem.Label" % cid, "")[:50]), expect,
                           settle=14 if cid in (9100, 9300) else 2.5)  # live channels: wait past the app's splash

        self.row_clicks = row_clicks
        launched_ok = lambda l, s, dl: bool(l)
        row_clicks(9960, "Up Next", 2, lambda l, s, dl: "Window.IsActive(TitleInfo.xml)" in dl or bool(l))
        row_clicks(9200, "Today's Games", 6)
        row_clicks(9950, "New This Week", 2, lambda l, s, dl: "Window.IsActive(TitleInfo.xml)" in dl)
        row_clicks(9800, "Trending", 2, lambda l, s, dl: "Window.IsActive(TitleInfo.xml)" in dl)
        row_clicks(9700, "Browse category", 3, lambda l, s, dl: "Window.IsActive(Browse.xml)" in dl, first=2)  # card 1 = TV Guide
        self._browse(B, 2)
        d.home()

        self._guide_tests(B)
        self._new_features(B)

        # ---------------- More row: every tile
        d.goto_row(9600, ALL_ROWS)
        n = int(d.info("Container(9600).NumItems").get("Container(9600).NumItems") or 0)
        for k in range(1, n + 1):
            d.home(); d.goto_row(9600, ALL_ROWS); d.goto_item(9600, k)
            lab = d.info("Container(9600).ListItem.Label").get("Container(9600).ListItem.Label", "")
            if "Classic" in lab:
                launched, state, dl = self.click(B, "More: %s asks before switching" % lab, lambda l, s_, dl: "Window.IsActive(yesnodialog)" in dl, back=False)
                if d.is_("Window.IsActive(yesnodialog)").get("Window.IsActive(yesnodialog)"):
                    d.key("Back")  # = No
                    time.sleep(2)
                skin = (d.rpc("Settings.GetSettingValue", {"setting": "lookandfeel.skin"}) or {}).get("value")
                rep.add(B, "More: Classic look - answering No keeps WatchHub", "PASS" if skin == "skin.sportshub" else "FAIL", skin or "?")
                if skin != "skin.sportshub":
                    d.rpc("Settings.SetSettingValue", {"setting": "lookandfeel.skin", "value": "skin.sportshub"})
                    time.sleep(8)
                    if d.is_("Window.IsActive(yesnodialog)").get("Window.IsActive(yesnodialog)"):
                        d.key("Left"); d.key("Select")
                d.home()
                continue
            self.click(B, "More: %s" % lab)

        # ---------------- info page: every button except the Trakt-changing ones
        for cid, name in ((9800, "Trending"), (9960, "Up Next")):
            d.home(); d.goto_row(cid, ALL_ROWS); d.goto_item(cid, 1)
            title = d.info("Container(%d).ListItem.Property(title)" % cid).get("Container(%d).ListItem.Property(title)" % cid, "")
            d.key("Select")
            if not d.wait(lambda: d.is_("Window.IsActive(TitleInfo.xml)").get("Window.IsActive(TitleInfo.xml)"), 15):
                rep.add(B, "Info page (%s): %s" % (name, title), "FAIL", "did not open", d.shot("info-missing"))
                continue
            time.sleep(2)
            vis = {b: d.is_("Control.IsVisible(%d)" % b).get("Control.IsVisible(%d)" % b) for b in (101, 102, 103, 104, 105, 106, 199)}
            props = d.info("Window.Property(title)", "Window.Property(meta)", "Window.Property(watched)", "Window.Property(also)", "Window.Property(playlabel)")
            rep.add(B, "Info page (%s): %s" % (name, title), "PASS", "buttons visible: %s | %s" % (
                ", ".join({101: "Play", 102: "Trailer", 103: "Episodes", 104: "+Watchlist", 105: "Mark watched", 106: "Watch on", 199: "Close"}[b] for b, v in vis.items() if v),
                json.dumps(props)[:250]), d.shot("info-%s" % name))
            for bid, bname in ((103, "Episodes"), (106, "Watch on..."), (102, "Trailer"), (101, "Play")):
                if not vis.get(bid):
                    continue
                if not d.is_("Window.IsActive(TitleInfo.xml)").get("Window.IsActive(TitleInfo.xml)"):
                    d.home(); d.goto_row(cid, ALL_ROWS); d.goto_item(cid, 1); d.key("Select")
                    d.wait(lambda: d.is_("Window.IsActive(TitleInfo.xml)").get("Window.IsActive(TitleInfo.xml)"), 15)
                    time.sleep(1.5)
                for _ in range(10):
                    if d.focus() == bid:
                        break
                    d.key("Left" if d.focus() > bid and d.focus() < 199 else "Right")
                if d.focus() != bid:
                    rep.add(B, "Info %s: button %s" % (name, bname), "ISSUE", "could not focus it (focus=%s)" % d.focus())
                    continue
                self.click(B, "Info %s: %s" % (name, bname), back=bid in (101, 102))
                if bid == 101:
                    # Play from Up Next notes the episode for "Did you finish?"; a test run mustn't get that question
                    d.sh("rm -f %s/userdata/addon_data/plugin.video.sportshub/watching.json" % KODI_HOME)
                if bid in (103, 106):
                    rep.add(B, "Info %s: after %s" % (name, bname), "INFO", "episodes list items=%s" % d.info("Container(200).NumItems").get("Container(200).NumItems"), d.shot("info-after-%s" % bname))
                    d.key("Back")
            rep.add(B, "Info %s: + Watchlist / Mark watched" % name, "SKIP", "would change your Trakt data")
            d.home()

        # ---------------- long-press menu on a poster and on a live channel
        for cid, name in ((9800, "Trending poster"), (9200, "Game card")):
            d.home(); d.goto_row(cid, ALL_ROWS); d.goto_item(cid, 1)
            d.key("ContextMenu")
            time.sleep(1.5)
            open_ = d.is_("Window.IsActive(contextmenu)").get("Window.IsActive(contextmenu)")
            entries = []
            if open_:
                n = int(d.info("Container(996).NumItems").get("Container(996).NumItems") or 0)
                for k in range(n):
                    entries.append(d.info("Container(996).ListItemAbsolute(%d).Label" % k).get("Container(996).ListItemAbsolute(%d).Label" % k, ""))
            rep.add(B, "Long-press menu: %s" % name, "PASS" if open_ else "ISSUE", "; ".join(entries) or "no menu", d.shot("ctx-%s" % name))
            d.key("Back")
        rep.add(B, "Long-press: Trakt mark watched / add to watchlist", "SKIP", "would change your Trakt data")

        # ---------------- header buttons (807 Sports, 801 Search, 802 Settings, 804 Power; Right wraps around)
        for bname, bid in (("Sports", 807), ("Search", 801), ("Settings", 802), ("Power", 804)):
            d.home(); d.goto_row(9050, ALL_ROWS); d.key("Up")
            for _ in range(6):
                if d.focus() == bid:
                    break
                d.key("Right")
            if d.focus() != bid:
                rep.add(B, "Header: %s" % bname, "FAIL", "could not focus button %d (focus=%s)" % (bid, d.focus()))
                continue
            if bname == "Sports":
                self.click(B, "Header: Sports opens the Sports page", lambda l, s_, dl: "Window.IsActive(videos)" in dl, back=False)
                st = d.info("Container.NumItems", "Container.ListItemAbsolute(0).Label")
                rep.add(B, "Sports page: Live sports now, games, Starting soon, By sport, TV Guide", "PASS" if int(st.get("Container.NumItems") or 0) >= 5 else "FAIL",
                        json.dumps(st), d.shot("sports-page"))
                d.key("Back"); time.sleep(1.5)
                continue
            if bname == "Power":
                self.click(B, "Header: Power (menu only, nothing chosen)", lambda l, s_, dl: "Window.IsActive(shutdownmenu)" in dl, back=False)
                d.key("Back")
                continue
            if bname == "Settings":
                # the gear opens WatchHub's own settings list (a select dialog run by the service)
                self.click(B, "Header: Settings opens WatchHub settings", lambda l, s_, dl: "Window.IsActive(selectdialog)" in dl, back=False)
                n = int(d.info("Container(3).NumItems").get("Container(3).NumItems") or 0)
                rep.add(B, "WatchHub settings entries", "PASS" if n >= 8 else "FAIL", "%d entries" % n, d.shot("wh-settings"))
                d.key("Back"); time.sleep(1.5)
            if bname == "Search":
                self.click(B, "Header: Search opens WatchHub search (keyboard)", lambda l, s_, dl: "Window.IsActive(virtualkeyboard)" in dl, back=False)
                if d.is_("Window.IsActive(virtualkeyboard)").get("Window.IsActive(virtualkeyboard)"):
                    d.rpc("Input.SendText", {"text": "ted lasso", "done": True})
                    d.wait(lambda: int(d.info("Container.NumItems").get("Container.NumItems") or 0) > 0, 20)
                    time.sleep(2)
                    res = d.info("System.CurrentWindow", "Container.NumItems", "Container.FolderPath", "Container.ListItemAbsolute(0).Label")
                    ok = int(res.get("Container.NumItems") or 0) > 0 and "plugin.video.sportshub" in res.get("Container.FolderPath", "")
                    rep.add(B, "Search 'ted lasso' shows WatchHub results", "PASS" if ok else "FAIL", json.dumps(res), d.shot("search-results"))
            d.home()

        self._filters(B)
        self._after_filters(B)

    def _free_tv_and_power(self, B):
        d, rep = self.d, self.rep
        self._browse(B, 3)
        d.home(); d.goto_row(9050, ALL_ROWS); d.key("Up")
        for _ in range(4):
            if d.focus() == 803 or d.info("Control.GetLabel(%d)" % d.focus()):
                pass
            d.key("Right")
        rep.add(B, "Header: rightmost button focused", "INFO", "focus=%s" % d.focus(), d.shot("header-rightmost"))
        launched, state, dl = self.click(B, "Header: Power (menu only, nothing chosen)", back=False)
        d.key("Back")
        d.home()
        rep.add(B, "Kodi cold starts after returning from an app (this run)", "INFO", "%d" % getattr(d, "restarts", 0))

    def _guide_tests(self, B):
        """TV Guide: both ways in, time, tabs, favorites, schedule, watching a channel."""
        d, rep = self.d, self.rep
        G = "Window.IsActive(Guide.xml)"
        favfile = KODI_HOME + "/userdata/addon_data/plugin.video.sportshub/guide_favorites.json"
        d.sh("rm -f %s" % favfile)
        opened = lambda: d.wait(lambda: d.is_(G).get(G), 15)
        # 1. the first Live Sports Now card
        d.home(); d.goto_row(9700, ALL_ROWS); d.goto_item(9700, 1)
        lab = d.info("Container(9700).ListItem.Label", "Container(9700).ListItem.Property(kind)")
        d.key("Select")
        ok = opened(); time.sleep(2)
        st = d.info("Window(13000).Property(tab)", "Container(500).NumItems", "Window(13000).Property(slot0)", "Container(300).NumItems")
        rep.add(B, "Guide: Browse row first card opens it", "PASS" if ok and lab.get("Container(9700).ListItem.Property(kind)") == "guide" else "FAIL",
                "%s | %s" % (json.dumps(lab), json.dumps(st)), d.shot("guide-from-live-row"))
        if not ok:
            return
        rep.add(B, "Guide: opens on All with tabs", "PASS" if st.get("Window(13000).Property(tab)") == "All"
                and int(st.get("Container(300).NumItems") or 0) > 3 else "FAIL", json.dumps(st))
        # the rest needs a tab full of channels: reopen on Sports the way the service does after a restart
        d.key("Back"); time.sleep(1.5)
        d.builtin("SetProperty(sh_ui_request,plugin://plugin.video.sportshub/?action=guide&tab=Sports,home)")
        ok = opened(); time.sleep(2)
        st = d.info("Window(13000).Property(tab)", "Container(500).NumItems", "Window(13000).Property(slot0)", "Container(300).NumItems")
        rep.add(B, "Guide: opens on a given tab (Sports) with channels", "PASS" if ok and st.get("Window(13000).Property(tab)") == "Sports"
                and int(st.get("Container(500).NumItems") or 0) > 20 else "FAIL", json.dumps(st))
        if not ok:
            return
        tabs = [d.info("Container(300).ListItemAbsolute(%d).Label" % k).get("Container(300).ListItemAbsolute(%d).Label" % k) for k in range(int(st.get("Container(300).NumItems") or 0))]
        rep.add(B, "Guide: no Spanish tab (hide_spanish on)", "PASS" if not any("espa" in (t or "").lower() for t in tabs) else "FAIL", ", ".join(t or "" for t in tabs))
        # 2. time: Right x2 = +1 hour, then Left back (never before now)
        s0 = st.get("Window(13000).Property(slot0)")
        d.key("Right"); time.sleep(1.5); d.key("Right"); time.sleep(1.5)
        s2 = d.info("Window(13000).Property(slot0)").get("Window(13000).Property(slot0)")
        rep.add(B, "Guide: Right moves time forward", "PASS" if s2 and s2 != s0 else "FAIL", "%s -> %s" % (s0, s2), d.shot("guide-plus-1h"))
        for _ in range(3):
            d.key("Left"); time.sleep(1.5)
        s3 = d.info("Window(13000).Property(slot0)").get("Window(13000).Property(slot0)")
        rep.add(B, "Guide: Left back to now, never before it", "PASS" if s3 == s0 else "FAIL", "%s (start %s)" % (s3, s0))
        # 3. tabs
        d.key("Up"); time.sleep(1); d.key("Right"); time.sleep(1); d.key("Select"); time.sleep(3)
        st = d.info("Window(13000).Property(tab)", "Container(500).NumItems", "System.CurrentControlId")
        rep.add(B, "Guide: switching tab", "PASS" if st.get("Window(13000).Property(tab)") not in ("Sports", None, "") and int(st.get("Container(500).NumItems") or 0) > 0
                and st.get("System.CurrentControlId") == "500" else "FAIL", json.dumps(st), d.shot("guide-tab-2"))
        # 4. long-press menu -> Add to Favorites -> Favorites tab
        chan = d.info("Container(500).ListItem.Label").get("Container(500).ListItem.Label")
        d.rpc("Input.ContextMenu"); time.sleep(2)
        menu = d.is_("Window.IsActive(contextmenu)").get("Window.IsActive(contextmenu)")
        d.shot("guide-long-press-menu")

        def pick(prefix):
            """Select the menu entry starting with prefix (the menu follows uiworker.MENU_ORDER)."""
            n = int(d.info("Container(996).NumItems").get("Container(996).NumItems") or 0)
            labels = [d.info("Container(996).ListItemAbsolute(%d).Label" % k).get("Container(996).ListItemAbsolute(%d).Label" % k, "") for k in range(n)]
            idx = next((k for k, l in enumerate(labels) if l.startswith(prefix)), 0)
            d.key("Down", idx) if idx else None
            d.key("Select"); time.sleep(2)
        pick("Add to Favorites")
        favs = d.sh("cat %s 2>/dev/null" % favfile)
        first_tab = d.info("Container(300).ListItemAbsolute(1).Label").get("Container(300).ListItemAbsolute(1).Label")
        rep.add(B, "Guide: long-press > Add to Favorites", "PASS" if menu and first_tab == "Favorites" and favs.strip().startswith("[") else "FAIL",
                "channel %s, saved %s, first tab %s" % (chan, favs.strip()[:80], first_tab))
        # 5. full schedule
        d.rpc("Input.ContextMenu"); time.sleep(2); pick("Full schedule")
        sched = d.is_("Window.IsActive(selectdialog)").get("Window.IsActive(selectdialog)")
        rep.add(B, "Guide: long-press > Full schedule", "PASS" if sched else "FAIL", "", d.shot("guide-schedule"))
        d.key("Back"); time.sleep(1)
        # 5b. times carry am/pm; short programmes inside a column are flagged
        st = d.info("Window(13000).Property(slot0)", *["Container(500).ListItemAbsolute(%d).Property(s%d)" % (r, c) for r in range(8) for c in range(4)])
        more = sum(1 for k, v in st.items() if "more" in (v or ""))
        rep.add(B, "Guide: am/pm times, '+N more' flags", "PASS" if (st.get("Window(13000).Property(slot0)") or "").endswith(("am", "pm")) else "FAIL",
                "first column %s, %d cells flagged '+N more' in the first 8 rows" % (st.get("Window(13000).Property(slot0)"), more))
        # 5c. Hide this channel (last entry of the long-press menu)
        hfile = KODI_HOME + "/userdata/addon_data/plugin.video.sportshub/guide_hidden.json"
        d.sh("rm -f %s" % hfile)
        before = int(d.info("Container(500).NumItems").get("Container(500).NumItems") or 0)
        d.key("Down"); time.sleep(1)
        victim = d.info("Container(500).ListItem.Label").get("Container(500).ListItem.Label")
        d.rpc("Input.ContextMenu"); time.sleep(2)
        n = int(d.info("Container(996).NumItems").get("Container(996).NumItems") or 0)
        d.key("Down", max(n - 1, 0)); d.key("Select"); time.sleep(2)
        after = int(d.info("Container(500).NumItems").get("Container(500).NumItems") or 0)
        rep.add(B, "Guide: long-press > Hide this channel", "PASS" if after == before - 1 and d.sh("cat %s 2>/dev/null" % hfile).strip().startswith("[") else "FAIL",
                "%s: %d -> %d rows, saved %s" % (victim, before, after, d.sh("cat %s 2>/dev/null" % hfile).strip()[:60]), d.shot("guide-hidden"))
        d.sh("rm -f %s" % hfile)
        # 5d. Categories opens the tiles (Single Show first) and a tile picks that category
        for _ in range(12):
            if d.focus() == 300:
                break
            d.key("Up")
        for _ in range(14):
            if d.info("Container(300).ListItem.Label").get("Container(300).ListItem.Label") == "Categories":
                break
            d.key("Left")
        d.key("Select"); time.sleep(2)
        tiles = d.info("Container(600).NumItems", "Container(600).ListItem(0).Label")
        on_tiles = d.focus() == 600
        d.key("Down"); d.key("Select"); time.sleep(3)
        st = d.info("Window(13000).Property(tab)", "Container(500).NumItems")
        rep.add(B, "Guide: Categories tiles open a category", "PASS" if on_tiles and tiles.get("Container(600).ListItem(0).Label") == "Single Show"
                and st.get("Window(13000).Property(tab)") not in FIXED_GUIDE_TABS and int(st.get("Container(500).NumItems") or 0) > 0 else "FAIL",
                json.dumps(dict(tiles, **st)), d.shot("guide-genre"))
        tab_before = st.get("Window(13000).Property(tab)")
        # 6. OK watches the channel now - and after a Kodi restart the guide comes back on that tab
        chan = d.info("Container(500).ListItem.Label").get("Container(500).ListItem.Label")
        launched, _, _ = self.click(B, "Guide: OK on %s watches it" % chan, lambda l, s_, dl: bool(l), back=False, settle=12)
        if launched:
            d.sh("am force-stop %s" % launched)
        d.restart_kodi()
        ok = d.wait(lambda: d.is_(G).get(G), 30)
        time.sleep(2)
        st = d.info("Window(13000).Property(tab)")
        rep.add(B, "Guide: reopens on the same tab after Kodi restarts", "PASS" if ok and st.get("Window(13000).Property(tab)") == tab_before else "FAIL",
                "open=%s tab=%s (was %s)" % (ok, st.get("Window(13000).Property(tab)"), tab_before), d.shot("guide-reopened"))
        d.key("Back"); time.sleep(2)  # closing on purpose clears it
        d.home()
        # 7. the TV Guide icon in the top bar (leftmost); the guide opens on All
        d.goto_row(9050, ALL_ROWS); d.key("Up")
        for _ in range(5):
            if d.focus() == 805:
                break
            d.key("Left")
        ok = d.focus() == 805
        if ok:
            d.key("Select"); ok = opened(); time.sleep(2)
        st = d.info("Window(13000).Property(tab)", "Container(500).NumItems")
        rep.add(B, "Guide: top-bar TV Guide icon opens it on All", "PASS" if ok and st.get("Window(13000).Property(tab)") == "All" else "FAIL",
                json.dumps(st), d.shot("guide-from-header"))
        d.key("Back"); time.sleep(1)
        d.sh("rm -f %s" % favfile)  # leave no test favorites behind
        d.home()

    def _new_features(self, B):
        """B: what 0.6.1-0.7.28 added, on the TV. State the test changes (Rediscover picks, pins, Up Next order,
        Recommended) is backed up first and put back after; nothing is written to Trakt."""
        d, rep = self.d, self.rep
        prof = KODI_HOME + "/userdata/addon_data/plugin.video.sportshub/"
        keep = ["rediscover.json", "upnext_order.json", "recommended.json"]
        for f in keep:
            d.sh("cp %s%s %s%s.wh-test-bak 2>/dev/null" % (prof, f, prof, f))
        req = lambda url: d.builtin("SetProperty(sh_ui_request,%s,home)" % url)
        lab = lambda c, k: d.info("Container(%d).ListItemAbsolute(%d).Label" % (c, k)).get("Container(%d).ListItemAbsolute(%d).Label" % (c, k), "")
        prop = lambda c, k, p: d.info("Container(%d).ListItemAbsolute(%d).Property(%s)" % (c, k, p)).get("Container(%d).ListItemAbsolute(%d).Property(%s)" % (c, k, p), "")
        num = lambda c: int(d.info("Container(%d).NumItems" % c).get("Container(%d).NumItems" % c) or 0)
        active = lambda w: d.is_("Window.IsActive(%s)" % w).get("Window.IsActive(%s)" % w)
        try:
            # ---- Sports page (header ball icon) and its calendar
            d.home(); d.goto_row(9050, ALL_ROWS); d.builtin("SetFocus(807)"); time.sleep(1)
            t = time.time()
            d.key("Select")
            opened = d.wait(lambda: active(1120), 15)
            d.wait(lambda: num(9200) > 0 and num(9160) > 0, 30, 1)
            rows = {r: num(r) for r in (9100, 9200, 9160, 9300, 9150)}
            rep.add(B, "Sports page: opens from the ball icon with its rows", "PASS" if opened and rows[9160] >= 6 and rows[9200] > 0 else "FAIL",
                    "rows (live, games, schedules, soon, by sport) = %s, %.1fs" % (list(rows.values()), time.time() - t), d.shot("sports-page"))
            d.builtin("SetFocus(9160)"); time.sleep(2)
            d.key("Select")
            cal = d.wait(lambda: active("Calendar.xml"), 15)
            d.wait(lambda: num(100) > 0, 20)
            g, first = num(100), lab(200, 0)
            rep.add(B, "Calendar: a league's week, grouped", "PASS" if cal and g >= 5 else "FAIL",
                    "%d groups, first game %s" % (g, first), d.shot("calendar"))
            d.builtin("SetFocus(302)"); time.sleep(1.5); d.key("Select")
            changed = d.wait(lambda: lab(200, 0) and lab(200, 0) != first, 20)
            rep.add(B, "Calendar: Next week", "PASS" if changed else "ISSUE", "first game %s -> %s" % (first, lab(200, 0)), d.shot("calendar-next"))
            d.home()

            # ---- WatchHub's long-press menu on a Rediscover poster: one order, groups
            d.goto_row(9400, ALL_ROWS); d.goto_item(9400, 1)
            req("plugin://plugin.video.sportshub/?action=ctx")
            menu = d.wait(lambda: active("contextmenu"), 10)
            n = num(996)
            labels = [d.info("Container(996).ListItemAbsolute(%d).Label" % k).get("Container(996).ListItemAbsolute(%d).Label" % k, "") for k in range(n)]
            pin = next((k for k, l in enumerate(labels) if l.startswith(("Pin", "Unpin"))), -1)
            ok = menu and labels and labels[0].startswith(("Play", "Watch on")) and 0 < pin < len(labels) - 1 and labels[-1].startswith(("Hide", "Undo"))
            rep.add(B, "Long-press menu: WatchHub's own, in order, grouped", "PASS" if ok else "FAIL", " / ".join(labels), d.shot("ctx-grouped"))
            d.key("Back"); time.sleep(1)

            # ---- Pin: the first Rediscover card gets PINNED, focus stays
            picks = json.loads(d.sh("cat %srediscover.json" % prof) or "{}").get("picks") or []
            if picks:
                d.goto_row(9400, ALL_ROWS); d.goto_item(9400, 2)
                before = lab(9400, 1)
                d.builtin("RunPlugin(plugin://plugin.video.sportshub/?action=rediscover_pin&id=%s)" % picks[1])
                pinned = d.wait(lambda: any(lab(9400, k) == before and prop(9400, k, "pinned") == "1" for k in range(4)), 20)
                here = d.info("Container(9400).ListItem.Label").get("Container(9400).ListItem.Label")
                rep.add(B, "Rediscover: Pin (badge, focus stays on the card)", "PASS" if pinned and here == before else "FAIL",
                        "%s pinned=%s, focus on %s" % (before, bool(pinned), here), d.shot("rediscover-pinned"))
                d.builtin("RunPlugin(plugin://plugin.video.sportshub/?action=rediscover_unpin&id=%s)" % picks[1])
                d.wait(lambda: not any(lab(9400, k) == before and prop(9400, k, "pinned") == "1" for k in range(4)), 20)
            # ---- Show me 20 different movies: the row changes in place
            first = lab(9400, 0)
            t = time.time()
            d.builtin("RunPlugin(plugin://plugin.video.sportshub/?action=rediscover_new&id=x)")
            new = d.wait(lambda: lab(9400, 0) and lab(9400, 0) != first, 60)
            rep.add(B, "Rediscover: Show me 20 different movies", "PASS" if new else "FAIL",
                    "%s -> %s in %.1fs" % (first, lab(9400, 0), time.time() - t), d.shot("rediscover-new"))

            # ---- Up Next: Move to the end
            d.home(); d.goto_row(9960, ALL_ROWS)
            title, year = prop(9960, 0, "title"), prop(9960, 0, "year")
            if title:
                old = lab(9960, 0)
                d.builtin("RunPlugin(plugin://plugin.video.sportshub/?action=upnext_back&title=%s&year=%s)" % (title, year))
                moved = d.wait(lambda: lab(9960, 0) and lab(9960, 0) != old, 30)
                n = num(9960)
                tail = [lab(9960, k) for k in range(max(0, n - 2), n)]
                rep.add(B, "Up Next: Move to the end", "PASS" if moved and old in tail else "FAIL",
                        "%s moved; last cards now %s" % (old, tail), d.shot("upnext-moved"))

            # ---- WatchHub settings: Home screen rows and About
            d.home()
            req("plugin://plugin.video.sportshub/?action=wh_settings")
            d.wait(lambda: active("selectdialog"), 10); time.sleep(1)
            sel = 3 if num(3) else 6   # plain / detailed select list
            entries = [lab(sel, k) for k in range(num(sel))]
            rep.add(B, "WatchHub settings: Home screen rows and About listed", "PASS" if "Home screen rows" in entries and "About WatchHub" in entries else "FAIL",
                    ", ".join(entries))
            if "About WatchHub" in entries:
                d.builtin("SetFocus(%d,%d,absolute)" % (sel, entries.index("About WatchHub"))); time.sleep(1); d.key("Select")
                about = d.wait(lambda: active("textviewer"), 10)
                rep.add(B, "About WatchHub: version and What's new", "PASS" if about else "FAIL", "", d.shot("about"))
                d.key("Back"); time.sleep(1)
            d.key("Back"); time.sleep(1)

            # ---- TV Guide: opens on All with the tab bar focused; Search shows under the Search tab
            d.home()
            req("plugin://plugin.video.sportshub/?action=guide")
            d.wait(lambda: active("Guide.xml") and num(500) > 0, 30); time.sleep(1)
            st = d.info("Window(13000).Property(tab)", "System.CurrentControlId")
            rep.add(B, "Guide: opens on All, highlight on the tab bar", "PASS" if st.get("Window(13000).Property(tab)") == "All" and st.get("System.CurrentControlId") == "300" else "FAIL",
                    json.dumps(st))
            d.builtin("SetFocus(300)"); time.sleep(1)
            for _ in range(12):
                if d.info("Container(300).ListItem.Label").get("Container(300).ListItem.Label") == "Search":
                    break
                d.key("Right")
            d.key("Select")
            if d.wait(lambda: active("virtualkeyboard"), 10):
                d.rpc("Input.SendText", {"text": "price", "done": True})
            found = d.wait(lambda: "price" in (d.info("Window(13000).Property(tab)").get("Window(13000).Property(tab)") or "") and num(500) > 0, 20)
            rep.add(B, "Guide: Search 'price' shows under the Search tab", "PASS" if found else "FAIL",
                    "%s, %d channels" % (d.info("Window(13000).Property(tab)").get("Window(13000).Property(tab)"), num(500)), d.shot("guide-search"))
            d.key("Back"); time.sleep(2)
            back_all = d.info("Window(13000).Property(tab)").get("Window(13000).Property(tab)") == "All"
            rep.add(B, "Guide: Back clears the search", "PASS" if back_all else "FAIL", "")
            d.home()

            # ---- Info page: series row on screen fast (TMDB key is on the Shield)
            t = time.time()
            req("plugin://plugin.video.sportshub/?action=info&title=The Dark Knight&year=2008&kind=Movie")
            row = d.wait(lambda: num(300) >= 3, 15, 0.25)
            sec = prop(300, 0, "section")
            rep.add(B, "Info page: In the series + You may also like", "PASS" if row and "SERIES" in sec else "FAIL",
                    "%d posters, '%s', on screen %.1fs after asking" % (num(300), sec, time.time() - t), d.shot("info-series"))
            d.home()

            # ---- Episode link: MobLand S2E05 from its Up Next page goes to that episode in Prime (stops at Prime's profile screen)
            mark = d.log_lines()
            req("plugin://plugin.video.sportshub/?action=info&title=MobLand&year=2025&kind=Show&season=2&episode=5")
            if d.wait(lambda: active("TitleInfo.xml"), 15):
                time.sleep(2)
                d.key("Select")
                ok = d.wait(lambda: any("from its own link" in l for l in d.log_since(mark)), 20)
                rep.add(B, "Episode link: MobLand S2E05 opens the episode", "PASS" if ok else "FAIL",
                        next((l.split("] ", 1)[-1] for l in d.log_since(mark) if "episode link" in l or "own link" in l), ""), d.shot("episode-link"))
                time.sleep(4)
                d.sh("am force-stop com.amazon.amazonvideo.livingroom")
                d.kodi_front()

            # ---- Xumo: a channel plays directly
            d.home()
            d.builtin("RunPlugin(plugin://plugin.video.sportshub/?action=play&src=xumo&id=99951247&name=Saved by the Bell)")
            fg = d.wait(lambda: d.fg() == "com.xumo.xumo.tv", 25)
            playing = d.wait(lambda: "state=3" in d.sh("dumpsys media_session | grep -m3 'state=PlaybackState'"), 30, 1)
            rep.add(B, "Xumo: Saved by the Bell plays directly", "PASS" if fg and playing else ("ISSUE" if fg else "FAIL"),
                    "Xumo in front=%s, playing=%s" % (bool(fg), bool(playing)), d.shot("xumo-channel"))
            d.sh("am force-stop com.xumo.xumo.tv")
            d.kodi_front()
        finally:
            for f in keep:
                d.sh("if [ -f %s%s.wh-test-bak ]; then mv %s%s.wh-test-bak %s%s; fi" % (prof, f, prof, f, prof, f))
            d.builtin("SetProperty(sh_refresh,%d,home)" % time.time())
            d.home()

    def _speed(self, B):
        """Load times from this run's Kodi log (tools/perf_report.py): typical and worst per screen."""
        p = subprocess.run([sys.executable, os.path.join(ROOT, "tools/perf_report.py"), "--ip", self.d.ip], capture_output=True, text=True, timeout=120)
        lines = [l for l in p.stdout.splitlines() if l.strip()]
        self.rep.add(B, "Load times (this session)", "INFO", " | ".join(lines[1:])[:2000])
        slow = [l for l in lines if l.endswith("<- slow") and l.startswith(("list", "Info", "TV Guide", "Browse", "Calendar"))]
        self.rep.add(B, "Load times: nothing you wait on is slow (typical < 3 s)", "ISSUE" if slow else "PASS", " | ".join(slow)[:1500])

    def _gaps(self, B):
        """Re-run of the row clicks a first run lost to Kodi being killed, then every service filter."""
        d, rep = self.d, self.rep

        def row_clicks(cid, name, count, expect=None, first=1):
            d.home()
            if not d.goto_row(cid, ALL_ROWS):
                rep.add(B, "Click %s" % name, "FAIL", "row not reachable (empty?)")
                return
            total = int(d.info("Container(%d).NumItems" % cid).get("Container(%d).NumItems" % cid) or 0)
            if not total:
                rep.add(B, "Click %s" % name, "ISSUE", "row reached but has no items (or Kodi not answering)", d.shot("empty-%s" % name))
            for k in range(first, min(count + first - 1, total) + 1):
                d.home()
                d.goto_row(cid, ALL_ROWS)
                d.goto_item(cid, k)
                lab = d.info("Container(%d).ListItem.Label" % cid).get("Container(%d).ListItem.Label" % cid, "")
                self.click(B, "Click %s #%d: %s" % (name, k, lab[:50]), expect)
        info_ok = lambda l, s, dl: "Window.IsActive(TitleInfo.xml)" in dl
        row_clicks(9200, "Today's Games", 6)
        row_clicks(9950, "New This Week", 3, info_ok)
        row_clicks(9800, "Trending", 3, info_ok)
        row_clicks(9700, "Browse category", 3, lambda l, s, dl: "Window.IsActive(Browse.xml)" in dl, first=2)  # card 1 = TV Guide
        self._browse(B, 3)
        rep.add(B, "Kodi cold starts after returning from an app (this run)", "INFO", "%d" % getattr(d, "restarts", 0))
        self._filters(B)
        rep.add(B, "Kodi cold starts after returning from an app (incl. filters)", "INFO", "%d" % getattr(d, "restarts", 0))

    def _browse(self, B, channels=2):
        """Browse row: a category tile (Comedy) opens the Browse screen; its live channels tune in, a show opens its info page."""
        d = self.d

        def open_tile():
            d.home(); d.goto_row(9700, ALL_ROWS)
            n = int(d.info("Container(9700).NumItems").get("Container(9700).NumItems") or 0)
            for k in range(1, n + 1):
                d.goto_item(9700, k)
                if d.info("Container(9700).ListItem.Label").get("Container(9700).ListItem.Label") == "Comedy":
                    break
            d.key("Select"); time.sleep(5)
            return d.is_("Window.IsActive(Browse.xml)").get("Window.IsActive(Browse.xml)")

        for k in range(channels):
            if not open_tile():
                self.rep.add(B, "Browse: Comedy opens the Browse screen", "FAIL", "", d.shot("browse-missing"))
                return
            if k:
                d.key("Right", k)
            lab = d.info("Container(100).ListItem.Label").get("Container(100).ListItem.Label", "")
            launched, _, _ = self.click(B, "Browse > Comedy > live: %s" % lab[:50], lambda l, s, dl: bool(l), back=False, settle=14)
            if launched:
                d.sh("am force-stop %s" % launched)
            d.kodi_front()
        if open_tile():
            time.sleep(4)
            st = d.info("Container(100).NumItems", "Container(200).NumItems", "Container(300).NumItems")
            self.rep.add(B, "Browse: Comedy has live, shows and movies rows", "PASS" if all(int(v or 0) > 0 for v in st.values()) else "FAIL",
                         json.dumps(st), d.shot("browse-comedy"))
            d.key("Down")
            lab = d.info("Container(200).ListItem.Label").get("Container(200).ListItem.Label", "")
            self.click(B, "Browse > Comedy > show: %s" % lab[:50], lambda l, s, dl: "Window.IsActive(TitleInfo.xml)" in dl, back=False)
            d.key("Back"); time.sleep(1); d.key("Back"); time.sleep(1)
        d.home()

    def _filters(self, B):
        d, rep = self.d, self.rep
        # ---------------- Services filter: every service, its Open card, back to All
        d.home(); d.goto_row(9050, ALL_ROWS)
        n = int(d.info("Container(9050).NumItems").get("Container(9050).NumItems") or 0)
        names = [d.info("Container(9050).ListItemAbsolute(%d).Label" % k).get("Container(9050).ListItemAbsolute(%d).Label" % k, "") for k in range(n)]
        codes = [d.info("Container(9050).ListItemAbsolute(%d).Property(code)" % k).get("Container(9050).ListItemAbsolute(%d).Property(code)" % k, "") for k in range(n)]
        rep.add(B, "Services row entries", "INFO", ", ".join(names))
        only = [x.strip() for x in os.environ.get("WH_SERVICES", "").split(",") if x.strip()]
        for k, svc in enumerate(names):
            if k == 0 or (only and svc not in only):
                continue
            d.home()
            row = 9050 if not d.info("Window(Home).Property(sh_provider)").get("Window(Home).Property(sh_provider)") else 9051
            d.goto_row(row, ALL_ROWS if row == 9050 else PROVIDER_ROWS)
            code = codes[k]
            if not d.goto_code(row, code):
                rep.add(B, "Filter %s: find it in the Services row" % svc, "FAIL", "not found")
                continue
            d.key("Select")
            ok = d.wait(lambda: d.info("Window(Home).Property(sh_provider_name)").get("Window(Home).Property(sh_provider_name)"), 8)
            time.sleep(2)
            d.wait(lambda: not any(d.is_(*["Container(%d).IsUpdating" % i for i, _ in PROVIDER_ROWS]).values()), 40, 1)
            st = d.info("System.CurrentControlId", "Window(Home).Property(sh_provider)", "Window(Home).Property(sh_provider_name)",
                        *["Container(%d).NumItems" % i for i, _ in PROVIDER_ROWS], "Container(9051).ListItem.Label")
            counts = ", ".join("%s=%s" % (nm.replace("<svc>", svc), st.get("Container(%d).NumItems" % i)) for i, nm in PROVIDER_ROWS[1:])
            focus_ok = st.get("System.CurrentControlId") == "9051" and st.get("Container(9051).ListItem.Label") == svc  # the picked tile; "Open <svc>" follows it
            rep.add(B, "Filter %s: switch to provider view" % svc, "PASS" if ok and focus_ok else "FAIL",
                    "header=%s focus=%s on '%s' | %s" % (st.get("Window(Home).Property(sh_provider_name)"), st.get("System.CurrentControlId"),
                                                         st.get("Container(9051).ListItem.Label"), counts), d.shot("filter-%s" % svc))
            empties = [nm.replace("<svc>", svc) for i, nm in PROVIDER_ROWS[1:] if st.get("Container(%d).NumItems" % i) in ("0", "", None)]
            if empties:
                rep.note("Observation", "Provider view for %s has empty rows (show 'Nothing right now'): %s." % (svc, ", ".join(empties)))
            # the rows under the filter: every visible card's service
            def leaks(i):
                cnt = int(d.info("Container(%d).NumItems" % i).get("Container(%d).NumItems" % i) or 0)
                svcs = {d.info("Container(%d).ListItemAbsolute(%d).Property(service)" % (i, j)).get("Container(%d).ListItemAbsolute(%d).Property(service)" % (i, j), "") for j in range(min(cnt, 12))}
                return sorted(s for s in svcs if s and s.replace(" channel)", ")") != svc)
            first = {i: leaks(i) for i, _ in PROVIDER_ROWS[2:]}
            time.sleep(8)
            for i, nm in PROVIDER_ROWS[2:]:
                later = leaks(i)
                row = nm.replace("<svc>", svc)
                if later:
                    rep.add(B, "Filter %s: %s only %s" % (svc, row, svc), "FAIL", "still shows other services after 8s: %s" % later, d.shot("leak-%s-%s" % (svc, i)))
                elif first[i]:
                    rep.add(B, "Filter %s: %s only %s" % (svc, row, svc), "ISSUE", "showed the previous filter's titles at first (%s), correct 8s later" % first[i])
                else:
                    rep.add(B, "Filter %s: %s only %s" % (svc, row, svc), "PASS", "")
            # the separate "Open <svc>" card right after the picked tile opens the app
            d.goto_code(9051, "open:" + code)
            restarts_before = getattr(d, "restarts", 0)
            lab = d.info("Container(9051).ListItem.Label").get("Container(9051).ListItem.Label", "")
            launched, _, _ = self.click(B, "Filter %s: '%s' card" % (svc, lab), lambda l, s, dl: bool(l), back=False)
            if launched:
                d.sh("am force-stop %s" % launched)
                d.kodi_front()
                d.wait(lambda: d.info("Window(Home).Property(sh_provider)").get("Window(Home).Property(sh_provider)"), 40, 1)
                st2 = d.info("Window(Home).Property(sh_provider)", "System.CurrentControlId", "Container(9051).ListItem.Label")
                rep.add(B, "Filter %s: still on after returning from the app%s" % (svc, " (Kodi was restarted)" if getattr(d, "restarts", 0) > restarts_before else ""),
                        "PASS" if st2.get("Window(Home).Property(sh_provider)") == code and st2.get("System.CurrentControlId") == "9051"
                        and st2.get("Container(9051).ListItem.Label") in (svc, "Open %s" % svc) else "FAIL", json.dumps(st2))  # filter AND focus
        # back to All
        d.home(); d.goto_row(9051, PROVIDER_ROWS); d.goto_item(9051, 1)
        d.key("Select"); time.sleep(2.5)
        st = d.info("Window(Home).Property(sh_provider)", "System.CurrentControlId", "Container(9050).ListItem.Label")
        rep.add(B, "Pick 'All services' returns to All view", "PASS" if not st.get("Window(Home).Property(sh_provider)") and st.get("System.CurrentControlId") == "9050" else "FAIL",
                json.dumps(st), d.shot("back-to-all"))

    def _after_filters(self, B):
        d, rep = self.d, self.rep
        # Back key on home, in both views
        d.home(); d.goto_row(9960, ALL_ROWS); d.key("Back"); time.sleep(1.5)
        rep.add(B, "Back key on home (All view)", "INFO", json.dumps(d.info("System.CurrentWindow", "System.CurrentControlId")), d.shot("back-on-home"))
        d.home(); d.goto_row(9050, ALL_ROWS); d.goto_item(9050, 2); d.key("Select"); time.sleep(3)
        d.goto_row(9961, PROVIDER_ROWS); d.key("Back"); time.sleep(1.5)
        st = d.info("System.CurrentWindow", "Window(Home).Property(sh_provider)")
        st.update(d.info("System.CurrentControlId"))
        rep.add(B, "Back in provider view returns to All services", "PASS" if not st.get("Window(Home).Property(sh_provider)") and st.get("System.CurrentControlId") == "9050" else "FAIL",
                json.dumps(st), d.shot("back-in-provider"))
        # rapid picks: three services in a row, then check the final state is consistent
        d.home(); d.goto_row(9050, ALL_ROWS)
        for c in ("nfx", "hlu", "pct"):
            row = 9051 if d.info("Window(Home).Property(sh_provider)").get("Window(Home).Property(sh_provider)") else 9050
            d.goto_code(row, c); d.key("Select"); time.sleep(0.6)
        d.wait(lambda: d.info("Window(Home).Property(sh_provider)").get("Window(Home).Property(sh_provider)") == "pct", 10)
        time.sleep(3)
        st = d.info("Window(Home).Property(sh_provider)", "System.CurrentControlId", "Container(9051).ListItem.Label")
        rep.add(B, "Rapid picks Netflix -> Hulu -> Peacock end on Peacock", "PASS" if st.get("Window(Home).Property(sh_provider)") == "pct"
                and st.get("System.CurrentControlId") == "9051" and st.get("Container(9051).ListItem.Label") == "Peacock" else "FAIL", json.dumps(st), d.shot("rapid-picks"))
        # Back from the header while a service is picked
        d.goto_row(9051, PROVIDER_ROWS); d.key("Up"); d.key("Back"); time.sleep(2)
        st = d.info("Window(Home).Property(sh_provider)", "System.CurrentControlId")
        rep.add(B, "Back while in the header (provider view)", "INFO", json.dumps(st), d.shot("header-back-provider"))
        d.home(); d.goto_row(9051, PROVIDER_ROWS); d.goto_code(9051, ""); d.key("Select"); time.sleep(3)
        # Search -> open a title -> Back keeps the results
        d.home(); d.goto_row(9050, ALL_ROWS); d.key("Up")
        for _ in range(4):
            if d.focus() == 801:
                break
            d.key("Right")
        d.key("Select")
        if d.wait(lambda: d.is_("Window.IsActive(virtualkeyboard)").get("Window.IsActive(virtualkeyboard)"), 10):
            d.rpc("Input.SendText", {"text": "ted lasso", "done": True})
            d.wait(lambda: int(d.info("Container.NumItems").get("Container.NumItems") or 0) > 0, 20)
            time.sleep(2)
            d.key("Select")
            opened = d.wait(lambda: d.is_("Window.IsActive(TitleInfo.xml)").get("Window.IsActive(TitleInfo.xml)"), 15)
            d.key("Back"); time.sleep(2)
            res = d.info("Container.FolderPath", "Container.NumItems", "System.CurrentWindow")
            rep.add(B, "Search -> title -> Back keeps the results", "PASS" if opened and "sportshub" in res.get("Container.FolderPath", "") and int(res.get("Container.NumItems") or 0) > 0 else "FAIL",
                    json.dumps(res), d.shot("search-back"))
        d.home()
        # damaged state file: Kodi must still start, on All services
        d.sh("am force-stop %s" % KODI_PKG); time.sleep(2)
        d.sh("echo '[1,2' > %s" % FILTER_FILE)
        d.restart_kodi()
        st = d.info("Window(Home).Property(sh_provider)", "System.CurrentControlId")
        tb = d.sh("grep -c Traceback %s" % LOG).strip()
        rep.add(B, "Damaged filter file: starts on All, no errors", "PASS" if not st.get("Window(Home).Property(sh_provider)") and tb == "0" else "FAIL",
                "%s, tracebacks=%s" % (json.dumps(st), tb), d.shot("damaged-state"))
        d.sh("rm -f %s" % FILTER_FILE)
        # restart with a filter on: it should come back, focused on that service
        d.home(); d.goto_row(9050, ALL_ROWS); d.goto_code(9050, "hlu"); d.key("Select")
        d.wait(lambda: d.info("Window(Home).Property(sh_provider)").get("Window(Home).Property(sh_provider)") == "hlu", 10)
        took = d.restart_kodi()
        d.wait(lambda: d.info("Window(Home).Property(sh_provider)").get("Window(Home).Property(sh_provider)"), 40, 1)
        time.sleep(3)
        st = d.info("Window(Home).Property(sh_provider)", "System.CurrentControlId", "Container(9051).ListItem.Label")
        rep.add(B, "Kodi restart keeps the Hulu filter, focus on Hulu", "PASS" if st.get("Window(Home).Property(sh_provider)") == "hlu" and st.get("System.CurrentControlId") == "9051"
                and st.get("Container(9051).ListItem.Label") == "Hulu" else "FAIL", "%s, ready in %.0fs" % (json.dumps(st), took or -1), d.shot("restart-keeps-filter"))
        d.home(); d.goto_row(9051, PROVIDER_ROWS); d.goto_item(9051, 1); d.key("Select"); time.sleep(3)

        # ---------------- settings on the device (Kodi restarted for each)
        def with_settings(case, check, **kv):
            d.sh("am force-stop %s" % KODI_PKG)
            time.sleep(2)
            self.set_addon_settings(**kv)
            took = d.restart_kodi()
            ok, detail = check()
            rep.add(B, "Device setting: %s" % case, "PASS" if ok else "FAIL", "%s (ready in %.0fs)" % (detail, took or -1), d.shot("setting-%s" % case))
            self.restore_addon_settings()
            d.restart_kodi()

        def svc_labels():
            n = int(d.info("Container(9050).NumItems").get("Container(9050).NumItems") or 0)
            return [d.info("Container(9050).ListItemAbsolute(%d).Label" % k).get("Container(9050).ListItemAbsolute(%d).Label" % k, "") for k in range(n)]

        base_live = d.info("Container(9700).NumItems").get("Container(9700).NumItems")
        with_settings("src_pluto=false", lambda: (True, "Live Sports Now items %s -> %s" % (base_live, d.info("Container(9700).NumItems").get("Container(9700).NumItems"))), src_pluto="false")
        with_settings("amazon_channels empty", lambda: (not any("(Prime)" in l for l in svc_labels()), ", ".join(svc_labels())), amazon_channels="")
        with_settings("games_only=true", lambda: (True, "Live %s / Soon %s items" % (d.info("Container(9700).NumItems").get("Container(9700).NumItems"),
                                                                                      d.info("Container(9200).NumItems").get("Container(9200).NumItems"))), games_only="true")
        with_settings("src_scores=false", lambda: (d.info("Container(9200).ListItem.Label").get("Container(9200).ListItem.Label") == "Live scores are off",
                                                    "Today's Games first card: %s" % d.info("Container(9200).ListItem.Label").get("Container(9200).ListItem.Label")), src_scores="false")
        with_settings("open_on_start=false", lambda: (True, json.dumps(d.info("System.CurrentWindow", "System.CurrentControlId"))), open_on_start="false")

        # ---------------- health
        mem = re.search(r"TOTAL[ :]+(\d+)", d.sh("dumpsys meminfo %s | grep -m1 TOTAL" % KODI_PKG))
        df = d.sh("df -h /data | tail -1").split()
        cache = d.sh("du -sk %s/userdata/addon_data/plugin.video.sportshub/cache %s/userdata/Thumbnails 2>/dev/null" % (KODI_HOME, KODI_HOME)).split()
        rep.add(B, "Kodi memory / storage / caches", "INFO", "Kodi RAM %s MB, /data free %s, WatchHub cache %s KB, thumbnails %s KB" % (
            int(mem.group(1)) // 1024 if mem else "?", df[3] if len(df) > 3 else "?", cache[0] if cache else "?", cache[2] if len(cache) > 2 else "?"))
        full = d.sh("cat %s" % LOG)
        tbs = full.count("Traceback")
        errs = [l for l in full.splitlines() if " error <general>" in l and "GL_" not in l]
        rep.add(B, "Kodi log: tracebacks / errors this session", "PASS" if not tbs else "FAIL", "%d tracebacks, %d error lines. %s" % (tbs, len(errs), " || ".join(e[-160:] for e in errs[:5])))
        self._speed(B)
        slow = [l for l in full.splitlines() if "fetch failed" in l]
        if slow:
            rep.note("Observation", "%d failed fetches in the Kodi log this session (first: %s)" % (len(slow), slow[0][-160:]))


# ====================================================================== main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", required=True)
    ap.add_argument("--adb", default=os.environ.get("ADB") or shutil.which("adb") or "adb")
    ap.add_argument("--only", choices=["A", "B"])
    ap.add_argument("--out", default=os.path.join(ROOT, "test-results", time.strftime("%Y%m%d-%H%M")))
    ap.add_argument("--keep-rpc", action="store_true", help="leave Kodi's web server/JSON-RPC on afterwards")
    args = ap.parse_args()
    rep = Report(args.out)
    dev = Device(args.ip, args.adb, args.out)
    subprocess.run([args.adb, "connect", dev.serial], capture_output=True)

    # the device's app list and API keys make the off-device run match the Shield
    env = {"SH_apps": ",".join(l.split(":", 1)[1] for l in dev.sh("pm list packages").split() if ":" in l)}
    s = dev.sh("cat %s" % SETTINGS)
    for k in ("tmdb_key", "trakt_client_id", "amazon_channels", "region"):
        m = re.search(r'<setting id="%s"[^>]*>([^<]+)</setting>' % k, s)
        if m:
            env["SH_" + k] = m.group(1)
    if args.only != "B":
        off = Offline(rep, env)
        off.suite()
        off.guide_data()
        off.favorites_check()
        off.new_features()
    if args.only != "A":
        # app launches during a test run don't count toward WatchHub's usage counts (the lean app set)
        marker = KODI_HOME + "/userdata/addon_data/plugin.video.sportshub/testing"
        dev.sh("touch %s" % marker)
        try:
            OnDevice(rep, dev, args.keep_rpc).suite()
        finally:
            dev.sh("rm -f %s" % marker)
    rep.save()
    print("\nReport: %s" % os.path.join(args.out, "report.md"))


if __name__ == "__main__":
    main()
