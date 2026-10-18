"""Summarise a running watchhub_test.py log for the project board's live test panel.

    WH_OUT=test-results/<run> python3 tools/test_progress.py <log> <version> <device> <total> [final]

Writes test_progress.json next to the log (the status/tests document the board shows): counts, the step
running now, every stage with its checks and times, and an estimated finish. WH_PREV_TIMING points at an
earlier run's phase-times.json so the stages still to come get "about N min" estimates.
"""
import datetime, json, os, re, sys
log, version, device, total = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
final = len(sys.argv) > 5
rows = [l for l in open(log, encoding="utf-8", errors="replace") if l.startswith("[")]
cnt = lambda k: sum(1 for l in rows if l.startswith("[" + k))
_st = os.stat(log)
started = datetime.datetime.fromtimestamp(getattr(_st, "st_birthtime", None) or _st.st_ctime)  # Linux has no birth time
now = datetime.datetime.now()
done = len(rows)
eta = None
if done and not final:
    rate = (now - started).total_seconds() / done
    eta = now + datetime.timedelta(seconds=rate * max(total - done, 0))
cur = re.sub(r"^\[\w+\s*\]\s*", "", rows[-1]).split(" | ")[:2] if rows else []
notes = [re.sub(r"\s+", " ", l.strip())[:180] for l in rows if l.startswith(("[FAIL", "[ISSUE"))]
fail = cnt("FAIL")
iso = lambda d: d.astimezone().isoformat(timespec="seconds")
doc = {"state": ("failed" if fail else "passed") if final else "running", "version": version, "device": device,
       "total": max(total, done), "done": done, "pass": cnt("PASS"), "fail": fail, "issue": cnt("ISSUE"), "skip": cnt("SKIP"),
       "started": iso(started), "updated_at": iso(now), "eta": iso(eta) if eta else None,
       "current": " · ".join(x.strip() for x in cur), "notes": notes,
       "summary": "%d checks: %d pass, %d fail, %d issues, %d skipped. Screenshots being reviewed." % (done, cnt("PASS"), fail, cnt("ISSUE"), cnt("SKIP")) if final else ""}
PHASES = [  # (name, area, case prefixes) in the order the test runner works through them
    ("Home rows build (off-device)", "A", ("Home row", "Art present", "Labels present")),
    ("Menu crawl (off-device)", "A", ("Menu", "Search results")),
    ("Every kind of click (off-device)", "A", ("Click",)),
    ("Service filters (off-device)", "A", ("Services row", "Filter")),
    ("Settings matrix (off-device)", "A", ("Setting", "Game cards")),
    ("TV Guide data + Favorites (off-device)", "A", ("Guide data", "Guide:", "Favorites")),
    ("New features: logic (off-device)", "A", ("Home rows", "Up Next order", "Recommended:", "Long-press menu:", "Rediscover:", "TV Guide:",
                                                "Xumo:", "Sports calendar", "Episode links", "Info page:", "About WatchHub", "Home row: ")),
    ("Setup: version, apps, Kodi start", "B", ("Installed", "Third-party", "Kodi started")),
    ("Startup screen", "B", ("Startup",)),
    ("Home rows on the TV", "B", ("All view row", "Down on last row", "Up from", "Row end", "Right at end")),
    ("Every card type clicked", "B", ("Click", "Free Live", "Browse")),
    ("TV Guide", "B", ("Guide",)),
    ("New features on the TV", "B", ("Sports page", "Calendar", "Long-press menu:", "Rediscover:", "Up Next:", "WatchHub settings:",
                                      "About WatchHub", "Guide:", "Info page:", "Episode link", "Xumo:")),
    ("More row tiles", "B", ("More:",)),
    ("Info page buttons", "B", ("Info",)),
    ("Long-press menus", "B", ("Long-press",)),
    ("Header buttons, settings, search", "B", ("Header", "WatchHub settings", "Search")),
    ("Services filter: every service", "B", ("Services row", "Filter", "Back", "Rapid", "Pick", "Kodi restart", "Damaged")),
    ("Settings on the device", "B", ("Device setting",)),
    ("Health: errors, memory, load times", "B", ("Kodi log", "Kodi memory", "Load times")),
    ("Cleanup", "B", ("Cleanup",)),
]
phases = [{"name": n, "state": "todo", "checks": []} for n, _, _ in PHASES]
cur_i = 0
for rowno, l in enumerate(rows):
    m = re.match(r"^\[(\w+)\s*\]\s*([AB]) [^|]*\|\s*([^|]*?)\s*(?:\||$)", l)
    if not m:
        continue
    res, area, case = m.group(1), m.group(2), m.group(3)
    for j in range(cur_i, len(PHASES)):
        if PHASES[j][1] == area and case.startswith(PHASES[j][2]):
            cur_i = j
            break
    phases[cur_i]["checks"].append([res, case[:90]])
    phases[cur_i].setdefault("_first", rowno)
for j, ph in enumerate(phases):
    ph["state"] = "done" if j < cur_i or (final and ph["checks"]) else ("now" if j == cur_i and not final else ("skipped" if final else "todo"))
side_path = log + ".timing.json"
try:
    side = json.load(open(side_path))
except (OSError, ValueError):
    side = {"samples": [], "seen": {}}
t_now = now.timestamp()
side["samples"].append([t_now, done])
for j, ph in enumerate(phases):
    if ph["checks"] and ph["name"] not in side["seen"]:
        side["seen"][ph["name"]] = t_now if j == cur_i else side["seen"].get(ph["name"], t_now)
json.dump(side, open(side_path, "w"))
prev = {}
prev_path = os.environ.get("WH_PREV_TIMING", "")
if prev_path and os.path.exists(prev_path):
    prev = json.load(open(prev_path)).get("minutes", {})
names = [ph["name"] for ph in phases]
starts = [side["seen"].get(n) for n in names]
out_dir = os.environ.get("WH_OUT", "")
if out_dir and os.path.exists(os.path.join(out_dir, "results.json")):
    # each check's time = its screenshot's file time; checks without one take the previous check's time
    rr = json.load(open(os.path.join(out_dir, "results.json")))["rows"]
    t, times = started.timestamp(), []
    for r in rr:
        f = os.path.join(out_dir, r.get("shot") or "")
        if r.get("t"):
            t = r["t"]  # the test runner stamps every check (0.5.2+)
        elif r.get("shot") and os.path.exists(f):
            t = os.stat(f).st_mtime
        times.append(t)
    for j, ph in enumerate(phases):
        k = ph.get("_first")
        if k is not None and k < len(times):
            # a stage starts when the check before its first one finished
            starts[j] = times[k - 1] if k > 0 else started.timestamp()
            if ph["state"] == "now" and k > 0:
                starts[j] = times[k - 1]
for j, ph in enumerate(phases):
    st = starts[j]
    nxt = next((x for x in starts[j + 1:] if x), None)
    if ph["state"] == "done" and st and nxt:
        m = round((nxt - st) / 60, 1)
        if m >= 0.2:
            ph["minutes"] = m
    elif ph["state"] == "now" and st:
        ph["running_min"] = round((t_now - st) / 60, 1)
    if ph["state"] in ("todo", "now") and ph["name"] in prev:
        ph["est_min"] = prev[ph["name"]]
# recent pace: checks per second over the last ~6 minutes of samples
recent = [x for x in side["samples"] if t_now - x[0] <= 360]
if not final and len(recent) >= 2 and recent[-1][1] > recent[0][1]:
    rate = (recent[-1][0] - recent[0][0]) / (recent[-1][1] - recent[0][1]) if len(recent) >= 2 and recent[-1][1] > recent[0][1] else 0
    left = max(doc["total"] - done, 0) * rate
    if prev:  # stage history wins when we have it
        cur_left = max((phases[cur_i].get("est_min") or 0) - (phases[cur_i].get("running_min") or 0), 0)
        left = (cur_left + sum(ph.get("est_min", 0) for ph in phases if ph["state"] == "todo")) * 60 or left
    prev_total = 0
    if prev_path and os.path.exists(prev_path):
        prev_total = json.load(open(prev_path)).get("total_min", 0) * 60
    if prev_total:  # never promise less than the last whole run took
        left = max(left, started.timestamp() + prev_total - t_now)
    doc["eta"] = iso(now + datetime.timedelta(seconds=left))
    doc["minutes_left"] = round(left / 60)
for ph in phases:
    ph.pop("_first", None)
doc["phases"] = phases
doc["phase_now"] = phases[cur_i]["name"] if not final else ""
json.dump(doc, open(os.path.join(os.path.dirname(os.path.abspath(log)), "test_progress.json"), "w"))
print(doc["state"], doc["done"], doc["total"], doc["eta"])
