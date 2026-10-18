# How to add a row to the WatchHub home screen

Instructions for a coding assistant (for example a local Ollama model) working in this repository.
Follow the steps in order. Every step names the exact file and shows the code to copy. The worked
example is the real **Trailers** row (list id `9470`, plugin action `trailers`). Copy its pattern.

---

## 1. What WatchHub is (read this first)

- WatchHub is a **Kodi 21 add-on plus a Kodi skin** running on NVIDIA Shield TVs (Android TV).
- It never plays streams itself. Every card **launches an official app** (Netflix, Prime Video, Pluto TV...)
  or opens a WatchHub screen. **Only free, legal sources and the user's own subscriptions.** Never add
  pirate add-ons, scraped streams, or anything that gets around a service's sign-in, region or blackout rules.
- Two parts live in this repo (`Kodi/SportsHub/`):

| Folder | What it is | Language |
|---|---|---|
| `plugin.video.sportshub/` | The add-on: builds every list of cards, runs a background service | Python 3 (Kodi's `xbmc*` modules) |
| `skin.sportshub/` | The look: Home screen, rows, header buttons, the panel above the rows | Kodi skin XML |

How a home row works:

1. The skin's `Home.xml` has one **rail** (a horizontal list) per row. Each rail has a `content_path` like
   `plugin://plugin.video.sportshub/?action=trailers&skin=1&r=...`.
2. Kodi calls the add-on with those parameters. `ui.py` → `dispatch()` runs the Python function for that
   `action`, which adds one card per item with `kodi.add_item(...)` and finishes with `kodi.end_directory(...)`.
3. The skin draws the cards and fills the **hero panel** (the big text above the rows) from properties
   you set on each card (`kicker`, `title`, `episode`, `summary`, `chips`, `meta`).
4. WatchHub saves a **snapshot** of each row so it shows instantly next time, then rebuilds it in the
   background (`ROW_MAX_AGE` in `ui.py` decides how long a snapshot is good for).
5. The user can **reorder and hide** rows (WatchHub settings → Home screen rows). `homerows.py` rewrites
   `Home.xml` for that: row positions, Up/Down links and the slide animations. **You must register the
   new row there**, and you must not hand-edit positions (see step 4).

---

## 2. Pick the ids

- **List id:** an unused 4-digit number for the rail, e.g. `9480`. Rows in use today:
  `9050` Services (always first), `9960` Up Next, `9200` Today's Games, `9950` New this week,
  `9450` Recommended, `9800` Trending, `9400` Rediscover, `9470` Trailers, `9700` Browse, `9600` More (always last).
  Check with: `grep -rn '"9480"' skin.sportshub/xml/` (no results = free).
- **Action name:** a short lowercase name for the plugin, e.g. `mytopic`. Check `ui.py` `dispatch()` doesn't use it yet.

Below, replace `9480`, `mytopic`, `My Topic` and `MY TOPIC` with your names.

---

## 3. The Python side (`plugin.video.sportshub/resources/lib/ui.py`)

### 3a. Write the list function

Put it next to `trailers_list()`. Template:

```python
def mytopic_list():
    """Home row MY TOPIC: one sentence on what it shows and what OK does."""
    kodi.set_content("videos")
    items = []            # fetch your data here (see the rules below)
    for t in items[:25]:  # a home row shows at most 25 cards
        props = {
            "kind": "title",                 # card type the skin understands: title / tile / channel / game
            "title": t["title"],             # hero: big title
            "kicker": "MY TOPIC",            # hero: small line above the title
            "episode": "Coming Fri Oct 23",  # hero: bold line (optional)
            "summary": t.get("plot", ""),    # hero: one-line description (optional)
            "chips": "Movie • 2026",    # hero: grey detail line (optional)
            "meta": "Movie • 2026",     # hero line used when there's no episode line
            "year": str(t["year"]), "type": "Movie", "state": "",
        }
        ctx = [("Watch trailer", "RunPlugin(%s)" % kodi.build_url(action="trailer", title=t["title"], year=t["year"], kind="Movie"))]
        kodi.add_item(t["title"],
                      kodi.build_url(action="info", title=t["title"], year=t["year"], kind="Movie"),  # what OK does
                      False,
                      art={"thumb": t["poster"], "poster": t["poster"], "fanart": t.get("backdrop") or ""},
                      info={"title": t["title"], "plot": t.get("plot") or ""},
                      props=props, context=ctx)
    kodi.end_directory(view="posters")   # "posters" = poster cards; leave out for wide cards
```

Rules for this function:

- **Fetch through the existing sources**, never with your own HTTP calls: `sources/ondemand.py` (JustWatch:
  what's on the user's services), `sources/tmdb.py` (posters, trailers, upcoming movies), `sources/trakt.py`
  (the user's history and lists, **read only**), `sources/espn.py` (games), `sources/fast.py` (free live
  channels). They cache to disk; a direct request on every row load makes the Home screen slow.
- **Be fast.** A row should build in under 3 seconds. If you need many lookups, use a
  `ThreadPoolExecutor(max_workers=6)` like `trailers_list()`, and cap the work (`items[:60]`).
- **Never write to Trakt** from a row (no marking watched, no list changes). Only explicit menu choices do that.
- **Card labels:** when the skin asks (`skin=1`, so `PLAIN` is True) labels are plain text; put details in `props`.
- **Long-press menu:** entries go in `context` as `(label, builtin)`. WatchHub sorts every menu into one
  order (`uiworker.MENU_ORDER`): start labels with the existing words ("Play", "Watch on", "Watch trailer",
  "More like this", "Pin", "Hide"...) so they land in the right place.

### 3b. Hook it into `dispatch()` and the snapshot table

In `dispatch()` (search for `elif action == "trailers":`), add:

```python
    elif action == "mytopic":
        mytopic_list()
```

In `ROW_MAX_AGE` (search for `ROW_MAX_AGE = {`), add how long a saved copy may be shown, in seconds.
This is what makes the row appear instantly:

```python
ROW_MAX_AGE = {..., "trailers": 86400, "mytopic": 86400}
```

Use 600 (10 minutes) for live things (scores, "on now"), 86400 (a day) or 2 * 86400 for catalogue rows.

---

## 4. The skin side

### 4a. Add the rail to `skin.sportshub/xml/Home.xml`

Copy the Trailers block (search for `<param name="list_id" value="9470"/>`) and paste it right after
that block's `</include>`. Change only these lines:

```xml
			<include content="SH_Rail">
				<param name="list_id" value="9480"/>
				<param name="row_top" value="0"/>
				<param name="prev1" value="700"/><param name="prev2" value="700"/><param name="prev3" value="700"/>
				<param name="next1" value="9600"/><param name="next2" value="9600"/><param name="next3" value="9600"/>
				<param name="header" value="MY TOPIC · SHORT EXPLANATION"/>
				<param name="content_path" value="plugin://plugin.video.sportshub/?action=mytopic&amp;skin=1&amp;r=$INFO[Window(Home).Property(sh_refresh)]"/>
				<param name="onclick" value="RunPlugin($INFO[ListItem.FileNameAndPath])"/>
				<param name="layout" value="SH_CardPosterRow"/>
				<param name="item_width" value="232"/>
			</include>
```

- Keep the tabs exactly like the other rails (three tabs before `<include`). `homerows.py` finds rails by that pattern.
- `row_top`, `prev*` and `next*` values don't matter: step 5 rewrites them.
- `&amp;` not `&` inside XML. Always end `content_path` with `&amp;r=$INFO[Window(Home).Property(sh_refresh)]`
  (that's how the service tells rows to reload).
- `layout`: `SH_CardPosterRow` + `item_width` 232 for posters; `SH_CardTitle` / `SH_CardChannelAny` /
  `SH_CardGameAny` + `item_width` 416 for wide cards (look at the rail you're imitating).
- In the `<control type="group" id="9000">` above the rails, raise `<height>` by 376 (one row).

### 4b. Feed the hero panel: `skin.sportshub/xml/Includes_SportsHub.xml`

The panel above the rows reads `<variable>`s. For every variable that has a `Control.HasFocus(9470)` line,
add the same line for `9480` right below it:

```xml
		<value condition="Control.HasFocus(9480)">$INFO[Container(9480).ListItem.Property(kicker)]</value>
```

The variables are `SH_Backdrop` (background art, uses `ListItem.Art(fanart)`), `SH_HeroKicker`,
`SH_HeroEpisode`, `SH_HeroSummary`, `SH_HeroChips`, `SH_HeroTitle` and `SH_HeroMeta`. Also add
`| [Control.HasFocus(9480) + !String.IsEmpty(Container(9480).ListItem.Property(episode))]` to the end of the
`SH_UpNextHero` expression if your cards set `episode` (that switches on the three-line Up Next layout).
Search for `9470` in that file to find every spot.

**Kodi skin limits we have hit:** button and radiobutton textures can't contain `$INFO[...]` (the icon just
disappears; use two fixed pictures and `<selected>` instead). Positions can't come from variables. Keep
conditions simple and test on the TV.

---

## 5. Register the row for ordering: `plugin.video.sportshub/resources/lib/homerows.py`

Add the row to `ROWS` (the name users see in "Home screen rows") and to `DEFAULT` (where it goes for
everyone who hasn't reordered):

```python
ROWS = {..., "9470": "Trailers", "9480": "My Topic", "9700": "Browse"}
DEFAULT = ["9960", "9200", "9950", "9450", "9800", "9400", "9470", "9480", "9700"]
```

Users who saved their own order get new rows at the end automatically (`load()` does that).

Then let `homerows.render` rewrite positions, Up/Down links and animations for the default order.
Run from `Kodi/SportsHub/`:

```bash
SH_skin=skin.sportshub python3 - <<'EOF'
import contextlib, io, runpy, sys
sys.argv = [sys.argv[0], "action=__none__"]
with contextlib.redirect_stdout(io.StringIO()):
    runpy.run_path("tools/dev_run.py", run_name="x")
sys.path.insert(0, "plugin.video.sportshub")
from resources.lib import homerows as h
p = "skin.sportshub/xml/Home.xml"
x = open(p).read()
open(p, "w").write(h.render(x, h.DEFAULT, []))
print(h.current(open(p).read()))
EOF
xmllint --noout skin.sportshub/xml/Home.xml skin.sportshub/xml/Includes_SportsHub.xml
```

The printed list must show your id in the right place.

---

## 6. Check it off the TV first

```bash
SH_skin=skin.sportshub python3 tools/dev_run.py "action=mytopic&skin=1"
```

This runs your row with stand-ins for Kodi and prints every card. No traceback, and cards listed = good.

Then add the row to the tests in `tools/watchhub_test.py`:

- `ALL_ROWS` (near the top): add `(9480, "My Topic")` in its default position.
- Off-device row list (search for `# A1: every home row`): add `("My Topic", "action=mytopic&skin=1")`.

Run the off-device part: `python3 tools/watchhub_test.py --ip 10.100.1.245 --only A`.
It must not show new FAIL lines (in particular "Home rows: default order", which compares the skin with `DEFAULT`).

---

## 7. Release and look at it on the TV

1. Add a line at the top of `plugin.video.sportshub/resources/changelog.txt` (newest first, plain words for
   the user: what they'll see, not how it was coded).
2. Bump `version` in `plugin.video.sportshub/addon.xml` (line 4) **and** `skin.sportshub/addon.xml`
   (line 2), since both changed.
3. `python3 tools/make_repo.py --base-url https://raw.githubusercontent.com/jcummins100/WatchHub/main/repo/`,
   commit and push, then copy `plugin.video.sportshub skin.sportshub tools repo` into the `jcummins100/WatchHub`
   repo and push that (see `docs/HANDOFF.md`, "Release").
4. On the Shield: `UpdateAddonRepos(true)` through the cmd hook, wait for "installed" in `kodi.log`.
   Skin changes show after `ReloadSkin()`, Python service changes after a Kodi restart.
   **Never reload the skin while someone is in the TV Guide or another WatchHub window** (on Oct 17 that froze
   every WatchHub screen until Kodi restarted), and never press keys on the Shield while someone is watching.
5. Look at it: the row appears in place, Up/Down moves through it, the panel above shows your kicker,
   title and lines, OK does what you said, long-press shows your menu in the usual order, and it appears in
   WatchHub settings → Home screen rows where it can be moved and hidden.

---

## Checklist

- [ ] `ui.py`: `mytopic_list()` written, fast, cached sources only, no Trakt writes
- [ ] `ui.py`: `dispatch()` entry and `ROW_MAX_AGE` entry
- [ ] `Home.xml`: rail block (tabs like the others, `&amp;`, `r=` on the path), group height +376
- [ ] `Includes_SportsHub.xml`: every `9470` line copied for the new id
- [ ] `homerows.py`: `ROWS` and `DEFAULT`; `render` run; `xmllint` clean
- [ ] `dev_run.py` shows cards; `watchhub_test.py` `ALL_ROWS` and A1 list updated; `--only A` passes
- [ ] changelog, both versions bumped, released, checked on the TV
