#!/usr/bin/env python3
"""Import a streaming service's viewing history into Trakt.

    python3 tools/trakt_import.py netflix  NetflixViewingHistory.csv  --token token.json [--since 2023-03-02] [--apply]
    python3 tools/trakt_import.py prime    prime.txt                  --token token.json [--apply]

Without --apply it only matches and prints a report. With --apply it posts to Trakt's history
(episodes with their watched dates), skipping anything already there on the same day, and writes
an undo file (history ids) next to the report.

Matching is by name: show title -> Trakt search; episode title -> the show's episode list (fuzzy);
movies -> Trakt movie search with the year when known. Unmatched rows are listed, never guessed.
"""
import argparse
import csv
import difflib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://api.trakt.tv/"
CLIENT_ID = os.environ.get("TRAKT_CLIENT_ID", "")  # your Trakt app Client ID
CACHE = {}


# ---------------------------------------------------------------- trakt client
class Trakt:
    def __init__(self, token_file):
        global CLIENT_ID
        self.tok = json.load(open(token_file))
        CLIENT_ID = CLIENT_ID or self.tok.get("client_id", "")  # tools/trakt_auth.py stores it with the token
        self.calls = 0

    def _req(self, path, data=None, method=None, retries=4):
        url = API + path
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, method=method or ("POST" if body else "GET"), headers={
            "Content-Type": "application/json", "trakt-api-version": "2", "trakt-api-key": CLIENT_ID,
            "Authorization": "Bearer " + self.tok["access_token"], "User-Agent": "WatchHub import"})
        for attempt in range(retries):
            try:
                self.calls += 1
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(float(e.headers.get("Retry-After", "2")) + 0.5)
                    continue
                if e.code in (500, 502, 503, 504, 520, 521, 522):
                    time.sleep(2 * (attempt + 1))
                    continue
                sys.stderr.write("HTTP %s %s %s\n" % (e.code, path, e.read()[:200]))
                return None
            except Exception as exc:
                time.sleep(2 * (attempt + 1))
                last = exc
        return None

    def get(self, path):
        if path in CACHE:
            return CACHE[path]
        res = self._req(path)
        CACHE[path] = res
        time.sleep(0.25)  # stay well under Trakt's GET limit
        return res

    def post(self, path, data):
        res = self._req(path, data)
        time.sleep(1.1)  # POST limit: 1/sec
        return res


# ---------------------------------------------------------------- normalisation
def norm(s):
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\((pilot|part \d+|\d{4})\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\b(the|a|an)\b", " ", s)
    return " ".join(s.split())


def best_match(name, candidates, cutoff=0.86):
    """candidates: {normalised_title: value}. Returns value or None."""
    n = norm(name)
    if n in candidates:
        return candidates[n]
    hit = difflib.get_close_matches(n, list(candidates), n=1, cutoff=cutoff)
    return candidates[hit[0]] if hit else None


# ---------------------------------------------------------------- parsers
NETFLIX_SEASON = re.compile(r"^(?P<show>.+?): (?P<season>Season \d+|Series \d+|Part \d+|Volume \d+|Book \w+|Chapter \d+|Limited Series|Miniseries|Collection \d+|[^:]*Season[^:]*): (?P<ep>.+)$")
NETFLIX_TWO = re.compile(r"^(?P<show>.+?): (?P<ep>.+)$")


def parse_netflix(path):
    """Netflix CSV: 'Show: Season 2: Episode Title', 'Show: Episode Title', or 'Movie Title' + M/D/YY."""
    rows = []
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            title, date = (r.get("Title") or "").strip(), (r.get("Date") or "").strip()
            try:
                m, d, y = date.split("/")
                watched = "20%02d-%02d-%02dT20:00:00.000Z" % (int(y) % 100, int(m), int(d))
            except ValueError:
                continue
            if not title or title.startswith(":"):
                continue
            mm = NETFLIX_SEASON.match(title)
            if mm:
                sn = re.search(r"\d+", mm.group("season"))
                rows.append({"kind": "episode", "show": mm.group("show"), "season": int(sn.group()) if sn else None,
                             "episode_title": mm.group("ep"), "watched_at": watched, "raw": title})
                continue
            mm = NETFLIX_TWO.match(title)
            if mm and not re.search(r"\b(19|20)\d{2}\b", mm.group("ep")):
                rows.append({"kind": "episode", "show": mm.group("show"), "season": None, "episode_title": mm.group("ep"),
                             "watched_at": watched, "raw": title})
                continue
            rows.append({"kind": "movie", "title": title, "watched_at": watched, "raw": title})
    return rows


MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}
PRIME_DATE = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December) (\d+), (20\d\d)$")


WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12}
SEASON_SUFFIX = re.compile(r"[:\s-]*(?:(?:Season|Series)\s+(\d+|%s)|S(\d+))\s*$" % "|".join(WORD_NUM), re.I)
# Amazon sells several cuts of one film; Trakt knows just the film
EDITION = re.compile(r"\s*[-:(\[]*\s*(4K UHD|UHD|HD|Bonus X-Ray Edition|X-Ray Edition|Unrated Version|Unrated|Extended Edition|"
                     r"Extended Cut|Extended Version|Theatrical Version|Director'?s Cut|Special Edition|Plus Bonus Content)\s*[)\]]*\s*$", re.I)


def split_season(title):
    """'MobLand S2' / 'Lanterns: Season 1' / 'The Bondsman - Season One' -> (show, season or None)."""
    m = SEASON_SUFFIX.search(title)
    if not m:
        return title.strip(), None
    num = m.group(1) or m.group(2)
    return title[:m.start()].strip(), int(num) if num.isdigit() else WORD_NUM.get(num.lower())


def clean_movie(title):
    prev = None
    while prev != title:
        prev, title = title, EDITION.sub("", title).strip()
    return title



def parse_prime(path):
    """Prime watch-history page text: date lines, then titles; 'Episodes watched' blocks list 'Season N, Ep. M Title'."""
    rows, date = [], None
    lines = [ln.strip() for ln in open(path, encoding="utf-8").read().splitlines()]
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = PRIME_DATE.match(ln)
        if m:
            date = "%s-%02d-%02dT20:00:00.000Z" % (m.group(3), MONTHS[m.group(1)], int(m.group(2)))
            i += 1
            continue
        if date and ln and not ln.startswith("Delete") and ln not in ("Episodes watched", "Hide episodes") and not ln.startswith("Watch again"):
            title = ln
            # look ahead for an expanded episode list
            j, eps = i + 1, []
            while j < len(lines) and lines[j] in ("Episodes watched", "Hide episodes"):
                j += 1
            while j < len(lines):
                em = re.match(r"^(?:Season (\d+),? )?(?:Ep(?:isode)?\.? ?(\d+))[:. -]*(.*)$", lines[j])
                if not em:
                    break
                eps.append((int(em.group(1)) if em.group(1) else None, int(em.group(2)), em.group(3).strip()))
                j += 1
            if eps:
                for sn, en, et in eps:
                    show, title_sn = split_season(title)
                    rows.append({"kind": "episode", "show": show, "season": sn if sn is not None else title_sn,
                                 "episode": en, "episode_title": et, "watched_at": date, "raw": "%s / %s" % (title, et)})
                i = j
                continue
            if i + 1 < len(lines) and lines[i + 1].startswith("Delete movie"):
                rows.append({"kind": "movie", "title": clean_movie(title), "watched_at": date, "raw": title})
            elif i + 1 < len(lines) and lines[i + 1] == "Episodes watched":
                # collapsed: we know the show and the day but not which episodes
                show, title_sn = split_season(title)
                rows.append({"kind": "show_day", "show": show, "season": title_sn, "watched_at": date, "raw": title})
        i += 1
    return rows


def netflix_alternatives(raw):
    """Other ways to split 'A: B: C: D' into show / season / episode."""
    parts = raw.split(": ")
    out = []
    for k in range(1, len(parts)):
        show = ": ".join(parts[:k])
        rest = parts[k:]
        season = None
        sm = re.match(r"^(?:.*?\b)?(?:Season|Series|Part|Volume|Book)?\s*(\d+)$", rest[0]) if len(rest) > 1 else None
        if sm and len(rest) > 1:
            season = int(sm.group(1))
            rest = rest[1:]
        ep = rest[-1]
        out.append({"kind": "episode", "show": show, "season": season, "episode_title": ep, "raw": raw})
        cm = re.match(r"^Chapter (\w+)$", rest[0]) if len(rest) > 1 else None
        if cm:
            out.append({"kind": "episode", "show": show, "season": season, "episode_title": rest[-1], "raw": raw})
    return out


# ---------------------------------------------------------------- matching
class Matcher:
    def __init__(self, trakt):
        self.t = trakt
        self.shows = {}       # norm(show) -> (show obj, {norm(ep title): (season, number, ids)}, {(season,number): ids})
        self.movies = {}      # norm(title) -> ids
        self.hints = {}       # norm(show) -> episode titles we watched (picks between same-named shows)

    def _episodes(self, show):
        seasons = self.t.get("shows/%s/seasons?extended=episodes" % show["ids"]["trakt"]) or []
        by_title, by_num = {}, {}
        for s in seasons:
            for e in s.get("episodes", []):
                by_num[(s["number"], e["number"])] = e["ids"]
                if e.get("title"):
                    by_title.setdefault(norm(e["title"]), []).append((s["number"], e["number"], e["ids"]))
        return by_title, by_num

    def show(self, name, hints=()):
        """Best Trakt show for a name. Several shows can share one title (US / Japanese / Korean
        "Suits"): then each is tried and the one whose episode list contains the most of the
        titles we watched (`hints`) wins - not whichever the search happened to list last."""
        key = norm(name)
        if key in self.shows:
            return self.shows[key]
        res = self.t.get("search/show?query=%s&limit=10" % urllib.parse.quote(name)) or []
        shows = [r["show"] for r in res if r.get("show")]
        titles = {norm(sh["title"]) for sh in shows}
        best_title = best_match(name, {t: t for t in titles}, cutoff=0.8) if titles else None
        same = [sh for sh in shows if norm(sh["title"]) == best_title] if best_title else []
        if not same:
            self.shows[key] = None
            return None
        hint_titles = [norm(h) for h in hints if h]
        picked = None
        for sh in same[:4]:
            by_title, by_num = self._episodes(sh)
            score = sum(1 for h in hint_titles if best_match(h, by_title, cutoff=0.82)) if hint_titles else 0
            if picked is None or score > picked[0]:
                picked = (score, sh, by_title, by_num)
            if not hint_titles:
                break  # nothing to compare: keep the search's first (most relevant) result
        _, show, by_title, by_num = picked
        self.shows[key] = (show, by_title, by_num)
        return self.shows[key]

    def episode(self, row):
        hit = self.show(row["show"], self.hints.get(norm(row["show"]), ()))
        if not hit:
            return None, "show not found"
        show, by_title, by_num = hit
        if row.get("episode") and (row.get("season"), row["episode"]) in by_num:
            return {"ids": by_num[(row["season"], row["episode"])], "show": show["title"]}, None
        et = row.get("episode_title") or ""
        # Netflix sometimes prefixes 'Episode 3' or 'Chapter Three'
        enum = re.match(r"^(?:episode|chapter|part)\s+(\d+)\b", et, re.I)
        if enum and row.get("season") is not None and (row["season"], int(enum.group(1))) in by_num:
            return {"ids": by_num[(row["season"], int(enum.group(1)))], "show": show["title"]}, None
        cands = best_match(et, by_title, cutoff=0.82)
        if cands:
            if row.get("season") is not None:
                same = [c for c in cands if c[0] == row["season"]]
                cands = same or cands
            s, n, ids = cands[0]
            return {"ids": ids, "show": show["title"], "sn": (s, n)}, None
        return None, "episode '%s' not in %s" % (et, show["title"])

    def movie(self, row):
        key = norm(row["title"])
        if key in self.movies:
            return self.movies[key], None if self.movies[key] else "movie not found"
        res = self.t.get("search/movie?query=%s&limit=5" % urllib.parse.quote(row["title"])) or []
        cands = {norm(r["movie"]["title"]): r["movie"] for r in res if r.get("movie")}
        m = best_match(row["title"], cands, cutoff=0.85) if cands else None
        if not m:
            # same words, different order or case: "BALLERINA: FROM THE WORLD OF JOHN WICK"
            words = sorted(norm(row["title"]).split())
            m = next((c for k, c in cands.items() if sorted(k.split()) == words), None)
        self.movies[key] = m["ids"] if m else None
        return self.movies[key], None if m else "movie not found"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("service", choices=["netflix", "prime"])
    ap.add_argument("path")
    ap.add_argument("--token", required=True)
    ap.add_argument("--since", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="")
    a = ap.parse_args()

    t = Trakt(a.token)
    rows = parse_netflix(a.path) if a.service == "netflix" else parse_prime(a.path)
    if a.since:
        rows = [r for r in rows if r["watched_at"][:10] >= a.since]
    print("parsed %d rows (%d episodes, %d movies, %d show-days)" % (
        len(rows), sum(r["kind"] == "episode" for r in rows), sum(r["kind"] == "movie" for r in rows), sum(r["kind"] == "show_day" for r in rows)))

    # existing history -> (trakt id, day) so re-runs and old scrobbles don't duplicate
    print("loading existing Trakt history...")
    have = set()
    for kind in ("episodes", "movies"):
        page = 1
        while True:
            h = t.get("users/me/history/%s?limit=250&page=%d" % (kind, page)) or []
            for x in h:
                obj = x.get("episode") or x.get("movie") or {}
                have.add((kind, obj.get("ids", {}).get("trakt")))
            if len(h) < 250:
                break
            page += 1
    print("  %d existing entries" % len(have))

    m = Matcher(t)
    for r in rows:  # episode titles per show: lets the matcher choose between same-named shows
        if r["kind"] == "episode" and r.get("episode_title"):
            m.hints.setdefault(norm(r["show"]), []).append(r["episode_title"])
    episodes, movies, unmatched, skipped = [], [], [], 0
    matched = []  # (raw, what it matched) - written to the report so matches can be checked, not just misses
    queued = set()
    for i, r in enumerate(rows):
        if r["kind"] == "show_day":
            unmatched.append((r["raw"], "episodes not expanded on the page"))
            continue
        if r["kind"] == "episode":
            hit, why = m.episode(r)
            if not hit and a.service == "netflix":
                for alt in netflix_alternatives(r["raw"]):
                    hit, _ = m.episode(alt)
                    if hit:
                        break
                if not hit:
                    # stand-up specials and one-offs are movies on Trakt ("Comedian: Special Name")
                    ids, _ = m.movie({"title": r["raw"].split(": ", 1)[-1]})
                    if not ids:
                        ids, _ = m.movie({"title": r["raw"]})
                    if ids:
                        if ("movies", ids["trakt"]) in have or ("movies", ids["trakt"]) in queued:
                            skipped += 1
                        else:
                            movies.append({"ids": {"trakt": ids["trakt"]}, "watched_at": r["watched_at"]}); matched.append((r["raw"], "MOVIE [trakt %s %s]" % (ids["trakt"], ids.get("slug", ""))))
                            queued.add(("movies", ids["trakt"]))
                        continue
            if not hit:
                unmatched.append((r["raw"], why))
                continue
            if ("episodes", hit["ids"]["trakt"]) in have or ("episodes", hit["ids"]["trakt"]) in queued:
                skipped += 1
                continue
            episodes.append({"ids": {"trakt": hit["ids"]["trakt"]}, "watched_at": r["watched_at"]})
            matched.append((r["raw"], "%s%s  [trakt ep %s]" % (hit.get("show", "?"), " S%02dE%02d" % hit["sn"] if hit.get("sn") else "", hit["ids"]["trakt"])))
            queued.add(("episodes", hit["ids"]["trakt"]))
        else:
            ids, why = m.movie(r)
            if not ids:
                unmatched.append((r["raw"], why))
                continue
            if ("movies", ids["trakt"]) in have or ("movies", ids["trakt"]) in queued:
                skipped += 1
                continue
            movies.append({"ids": {"trakt": ids["trakt"]}, "watched_at": r["watched_at"]}); matched.append((r["raw"], "MOVIE [trakt %s %s]" % (ids["trakt"], ids.get("slug", ""))))
            queued.add(("movies", ids["trakt"]))
        if i % 200 == 0:
            print("  ... %d/%d (api calls %d)" % (i, len(rows), t.calls))

    print("\nREADY: %d episodes + %d movies to add; %d already in Trakt; %d unmatched" % (len(episodes), len(movies), skipped, len(unmatched)))
    report = a.report or (a.path + ".trakt-report.txt")
    with open(report, "w", encoding="utf-8") as fh:
        fh.write("to add: %d episodes, %d movies; skipped %d; unmatched %d\n\n" % (len(episodes), len(movies), skipped, len(unmatched)))
        for raw, why in unmatched:
            fh.write("UNMATCHED  %-70s  %s\n" % (raw[:70], why))
        fh.write("\n")
        for raw, what in matched:
            fh.write("MATCHED    %-70s  -> %s\n" % (raw[:70], what))
    print("report:", report)

    if not a.apply:
        print("dry run only (add --apply to write)")
        return
    added = {"episodes": 0, "movies": 0, "not_found": []}
    for kind, items in (("episodes", episodes), ("movies", movies)):
        for k in range(0, len(items), 500):
            chunk = items[k:k + 500]
            res = t.post("sync/history", {kind: chunk}) or {}
            added[kind] += (res.get("added") or {}).get(kind, 0)
            nf = (res.get("not_found") or {}).get(kind, [])
            added["not_found"] += nf
            print("  posted %s %d-%d -> added %s" % (kind, k, k + len(chunk), (res.get("added") or {})))
    with open(a.path + ".trakt-undo.json", "w") as fh:
        json.dump({"episodes": episodes, "movies": movies}, fh)
    print("DONE: added %d episodes, %d movies (%d not found by Trakt). Undo file: %s" % (added["episodes"], added["movies"], len(added["not_found"]), a.path + ".trakt-undo.json"))


if __name__ == "__main__":
    main()
