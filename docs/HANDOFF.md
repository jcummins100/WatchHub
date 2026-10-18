# WatchHub handoff (updated 2026-10-16, evening: Ubuntu workstation → MacBook; testing moves to the Pro upstairs)

## Where things stand

**Released: WatchHub 0.7.28** (plugin; skin 0.7.11; the Pro upstairs has it deployed, the Shield TV in the office updates itself) in both repos (jcummins100/coding `Kodi/SportsHub`, public jcummins100/WatchHub). Shields: the Pro upstairs (10.100.1.245) and the Shield TV downstairs (10.100.1.200, 2019 base model, 2 GB). **Testing moves to the Pro upstairs** (Jeremy, Oct 16 evening). The Pro has been asleep all day and is still on 0.6.0: wake it, let it update to 0.7.5, run `tools/sync_settings.py` (favorites FROM the Pro), then a full test. Start steps: `Kodi/START-ON-MACBOOK.md`.

**The three Shields (Jeremy, Oct 16):**
- **Shield TV Pro, upstairs** - 10.100.1.245. Testing happens here.
- **Shield TV Pro #2, downstairs** - not set up yet (no WatchHub, IP unknown).
- **Shield TV (2019 non-Pro, 2 GB), downstairs in Jeremy's office** - 10.100.1.200. Called "the downstairs Shield" in older notes.

**About WatchHub** (0.7.6): WatchHub settings (gear) > About WatchHub shows the versions and "What's new". Add a plain-words entry to `plugin.video.sportshub/resources/changelog.txt` with every release.

Guide tabs now: Favorites · Categories · [picked category] · Sports · News · Movies · Game Shows · Kids · All.

**Trakt:** Netflix (2,055 ep + 428 movies) and Prime (1,095 ep + 278 movies; undo file `~/.watchhub/history/prime-20261015.txt.trakt-undo.json`) imported.

**Testing:**
- Full run on 0.7.5, downstairs Shield, Oct 16 3:54–4:37 PM (`test-results/20261016-1554`, not in git): 329 checks, 261 pass, 31 fail, 3 skipped (Trakt-changing buttons, by design). Every failure was the runner still expecting the old Services row ("Open Netflix" on the picked tile) and Kodi's settings screen behind the gear; the runner is fixed, so rerun on the Pro.
- Full run on 0.6.0, Oct 16 9:04–9:51 AM (`test-results/20261016-0904`): 322 checks, 283 pass, 3 runner mistakes; real finding was the Plex "21 Jump Street" channel error (fixed in 0.6.1).
- To run: `python3 tools/watchhub_test.py --ip 10.100.1.245` (~45–50 min, hands off that TV). Feed the board with `tools/test_progress.py` every few minutes + ArtifactData `status/tests`, and add a `test_runs/r-<ver>` entry at the end. Off-device only: `--only A` (about a minute).

## Done on the Ubuntu workstation today (Oct 16, about 1:30–5 PM)

**Setup.** No system adb and no passwordless sudo on the Ubuntu box, so Android platform-tools went to `~/.local/share/platform-tools` (`~/.local/bin/adb` links to it). Jeremy had testing done on the downstairs Shield during the day.

**Releases 0.6.1 → 0.7.5** (details per release below), each tested on the downstairs Shield and pushed to both repos:
- The WatchHub map's whole build order: Plex link fix and one guide row per channel (0.6.1), your subscriptions with Included / Free / Rent labels and a separate Open-app card, back to the same card after an app (0.6.1–0.6.2), Rediscover (0.6.3), Up Next hero and episode-aware info page (0.6.4), one card per title (0.6.5), Local stations (0.6.6). Only KDKA live is left open.
- Sprint C: "Did you finish S02E04?" and WatchHub settings behind the gear (0.7.0).
- Sprint D: your teams first in Today's Games (0.7.1), app launch counts and grouped Search (0.7.2), ★ channels in Live Now, free-apps checklist, `tools/sync_settings.py` (0.7.3), Free services card and wanted-app counts (0.7.4).
- 0.7.5: 8 fixes from a second-opinion review of the day's code (a review subagent; Codex is broken on Ubuntu), checked on the downstairs Shield.

**Apps.** Jeremy changed the policy: every Shield gets the same streaming apps. Installed downstairs from the Play Store (driven over adb): Tubi, Xumo Play, The CW, FOX One, NBC Sports, truTV, FloSports, Fox Nation, Fox News, Freevee. FOX Sports is "not compatible" with the 2019 Shield TV. Personal extras (Plex Media Server, UniFi Protect, Steam Link, Play Games) stay on the Pros. Downstairs now has 1.3 GB free internal (58 GB SD card adopted if needed). Freevee is part of Prime Video now (Jeremy); its app may be removable everywhere (ask).

**Research.** Subscription costs and ways to pay less (sourced, Oct 2026): `docs/Subscriptions-Research-2026-10.md`. About $108/month today; biggest savings Xfinity StreamSaver, Verizon's Netflix & HBO Max perk, yearly plans. Summary on the board.

**Board** (https://claude.ai/artifact/69TExZCNApxaUJQMza5n9C) updated through 0.7.4 with sprint progress, the research section and new questions. Its test panel showed today's full run.

**Tests.** The runner (`tools/watchhub_test.py`) gained checks for Rediscover, Home duplicates and the new Services row; dev stubs got `Dialog.multiselect`. Off-device group A: 116 pass. Full run on the downstairs Shield at 3:54 PM: see Testing below.

**Also.** Jeremy's plans per the board changelog: Paramount+ Premium and HBO Max Standard through Prime, Peacock Premium. Trakt's watched-movies list is paged (only the first 100 came back before). An earlier mistake: I pressed Home on the downstairs Shield once (Android home, not Kodi) - Kodi was brought back right away.

## Oct 16 evening (MacBook), 0.7.6 → 0.7.14
- 0.7.6 About WatchHub (settings): versions + "What's new" from `resources/changelog.txt` (add a line every release).
- 0.7.7 Fast start: home rows replay a snapshot (`kodi.record_start/save_row`, profile `rows/`, stamp = add-on version + settings/favorites/order files) and rebuild 20 s later; the service saves `guide_rows.json` + `guide_favorites_now.json` so plugin rows never build the guide. Restart → all rows in 1-6 s (was 30-60 s).
- 0.7.8 Up Next-style hero (headline/summary/chips) on New this week, Rediscover, Trending (and later Recommended, Trailers).
- 0.7.9 Sports page = skin window 1120 (`Custom_1120_Sports.xml`): Live sports now (★ sports channels only, no TV Guide card), Today's games, Schedules (0.7.13), Starting soon, By sport; header ball icon 807 (`sportshub/sports_balls.png`). Home lost Live Now and Starting Soon.
- 0.7.10/0.7.11 Up Next order (`upnext.py`, `upnext_order.json`): top / up one / end / usual place / hide for now + "Hidden (N)" card.
- 0.7.11 Recommended for you (Trakt `/recommendations`, row 9450; Trakt's Cloudflare needs a User-Agent). Home screen rows editor (`homerows.py`, `homerows.json`): rewrites the skin's Home.xml order and reloads the skin; re-applied after skin updates.
- 0.7.12 TV Guide: All first and default (All draws 1,131 rows in 2.3 s).
- 0.7.13 Sports calendar (`schedule.py`, `calendarwin.py`, `Calendar.xml`): week by division/conference from ESPN standings, Your teams first; Today's Games is today only.
- 0.7.14 Trailers row (9470): TMDB upcoming (services + theaters) with a YouTube trailer, OK plays it; Rediscover "Show me 20 different movies".
- Home default order: Services, Up Next, Today's Games, New this week, Recommended, Trending, Rediscover, Trailers, Browse, More.
- 0.7.15 Guide Search tab (0.7.21: results show under the Search tab, Back clears). 0.7.16 Trailers only upcoming; instant Rediscover reshuffle (`prepare_next`, row-only reload via `sh_rediscover`). 0.7.17-0.7.18 SEEN right away after Mark watched; focus restore by label. 0.7.19 info page row: TMDB collection ("in the series") + recommendations (`tmdb.related`, list 300); Unmark as watched (`trakt.unmark_watched`). 0.7.20 Trailers from JustWatch Upcoming (`ondemand.upcoming`, names the service). 0.7.21 Pin on Rediscover/Recommended (PINNED badge), Recommended rotates daily (`recommend.py`, `sh_recommended`), restore_spot steps with Control.Move and checks the label.
- **Xumo can't tune a channel** (tested Oct 16 with the app's own query params `deepLinkType` = live_guide / channel_no_ui / network, `channelId`, `genreId`, `playBack`, `hideUI`; and its TV input isn't tunable on the Shield). Told Jeremy: use Xumo's My Favorites, or untick Xumo in WatchHub settings. Saved by the Bell is Xumo-only.
- **Freevee**: not a source in WatchHub; Amazon folded it into Prime Video, whose free-with-ads titles WatchHub already shows. Prime Video's free live channels aren't in the guide (no public lineup; Sprint D item).
- Not yet seen on screen: Trailers row, Recommended pins. Full test planned for Oct 17 on the Pro.

- 0.7.22 guide opens focused on the All tab. 0.7.23 **Xumo tunes directly**: `https://www.xumo.tv/live?deepLinkType=channel_no_ui&channelId={id}` (the app ignores links without a path). 0.7.24 one long-press order everywhere (`uiworker.MENU_ORDER`). 0.7.25 grouped menus (`group_menu`: Watch on…, Move…, Trakt…) and header labels for Favorites/Sports.
- **Sprint E (Jeremy, Oct 16 night):** My Calendar - add shows/movies, see episode air dates, theater openings and streaming arrivals; rent/buy prices per store with sale alerts (JustWatch offers carry prices; check every few days).

## Next up (in order)
0. **Search is slow (8-16 s):** `ui.search` calls `fast.live_now()`, which loads every free service's full channel JSON; the Live Sports Now / Starting Soon rows do the same (12-15 s each). Switch them to the guide's saved list (`guide.channels_quick()` / `guide.search()`) and time with `tools/perf_report.py`. (The Sports page now hides this: 0.7.31 builds its rows in the service after each refresh, so it opens in ~0.6 s.)
1. Done Oct 17 night: the test plan covers every 0.6-0.7 feature (~362 checks). Full run of 0.7.29 on the Pro 10:20-10:59 PM: 297 pass; 12 failures were the script (fixed), 2 real bugs fixed in 0.7.30 (Up Next "Move to the end" dropped the show off the 20-card row; Rediscover/Recommended wrote files in the shared snapshot stamp, so every row rebuilt). Re-checks (`WH_RERUN_GUIDE=1` / `WH_RERUN_HEADER=1 ... --only B`) pass. **The guide test used to delete guide_favorites.json / guide_hidden.json without putting them back** (every full run did, Oct 16 too): now set aside and restored. Jeremy's list was lost; Saved by the Bell (`["saved bell"]`) restored on the Pro, ask him for any others. FOX One uninstalled from the Pro and the office Shield (Jeremy: needs cable/paid, sound was static); 0.7.31 treats FOX/FS1/BTN games as "needs cable or a FOX One subscription" (`apps.PAID_ONLY`). Next: sync settings to the office Shield (`tools/sync_settings.py`, favorites FROM the Pro, dry run first). Never press keys on the Pro while Jeremy is watching.
2. Done Oct 17 evening (0.7.27): series row shows at once (it took ~7 s, so it looked missing); **episode links** from JustWatch episode offers (`ondemand.episode_link`) - MobLand S2E05 plays from Up Next after Prime's profile picker (Prime always asks; that's its app). Also fixed: row snapshot temp names collided between threads.
3. **Multiview idea (Jeremy, Oct 17):** 4 games/screens on one TV, sound follows the highlighted one (YouTube TV, DirecTV, Fubo, Xfinity, ESPN app on some devices). Android TV on the Shield runs one app full screen, so WatchHub can't tile different apps; research which services offer Multiview on the Shield (YouTube TV, ESPN) and link to it, or a separate project.
4. Sprint E: My Calendar (track shows/movies: episode air dates, theater openings, streaming arrivals via JustWatch Upcoming; rent/buy prices per store from JustWatch offers, re-checked every few days, sale alerts).
5. Jeremy's answers on the board (Needs you): subscriptions list (MGM+?), Netflix/Hulu plans + phone carrier + internet provider (savings research), KDKA live inside Prime's Paramount+ channel, PBS app for WQED, remove Freevee? (Trailers placement is answered: it's a movable row.)
6. KDKA live via Paramount+ in Prime Video: needs a Prime Video link to the live channel (if Jeremy says it's there).
7. Sprint C left: Apple TV / Plex / Hulu history into Trakt and the nightly sync (need Jeremy at a signed-in browser / a Plex token).
8. Sprint D left: picture-quality re-check, Shield Pro #2 (downstairs, not set up), Sling Freestream / Prime Video free live channels.

The board has the full sprint list; the user leaves suggestions there. Read answers with ArtifactData `answers/board`.

## Release history

### Oct 16 (Ubuntu), newest first

0.7.5 (Oct 16): 8 fixes from a review of the day's changes (cleared settings stick; Did-you-finish dropped on an early return; back-to-card waits for the reload, yields to key presses after a 5 s grace, runs in a thread, is forgotten once you're back; info page focus; ION/ION Plus favorites; Live row doesn't wait on a guide build; Rediscover state merge). Checked on the downstairs Shield: back to The Traitors after a restart; early return clears the note.

0.7.4 (Oct 16): a "Free services" card ends the Services row (All view) when a free app is missing (opens the free-apps checklist); clicks on games needing an app this Shield lacks are counted as `needed:<pkg>` in launches.json.

0.7.3 (Oct 16): ★ channels first in Home's Live row (renamed "Live Now", `ui._favorite_channels_now`); "Free apps on this Shield" in WatchHub settings; `tools/sync_settings.py`.

0.7.2 (Oct 16): **App launch counts** (`apps.count_launch` from `kodi.start_android_activity`, `launches.json`; skipped while the test runner's `testing` marker is fresh; shown in Your Apps) for picking the lean app set in a few weeks. **Search** grouped: Live now, then shows and movies on your services, then the rest labelled "Rent $3.99 · Prime Video" or "On HBO Max" (16 results).

0.7.1 (Oct 16, Sprint D): **Your teams** (setting `my_teams`, default nfl:pit, nfl:cle, nhl:pit, mlb:pit, mlb:bos; gear > Your teams picks from all NFL/NBA/MLB/NHL teams): each team's live or next game (within 10 days, from ESPN's team schedule when it isn't on today's scoreboard) leads Today's Games, kicker YOUR TEAM. CBS games go to Prime Video ("Paramount+ (Prime Video)") when there's no Paramount+ app but Paramount+ comes through Prime. Schedule events' logos fixed (`espn._logo`).

0.7.0 (Oct 16, Sprint C): **"Did you finish S02E04?"** (`finish.py`): Play from an Up Next info page, or an episode in the episode list, notes the episode (`watching.json`); on the first key press back in Kodi 15 min–12 h later the service asks once; Yes marks that episode on Trakt (`trakt.mark_episode_watched`) and refreshes Up Next. The test runner deletes the note after its Play click. **WatchHub settings** (`settingsmenu.py`, header gear and the menu's Settings tile, run by the ui worker): subscriptions, Prime channels, free live-TV services (marks missing apps), duplicate-channel order, Spanish, local stations, Rediscover unseen-only, Trakt, All settings.

0.6.6 (Oct 16): **Local** (map 5.5): setting `local_market` (default "Pittsburgh, KDKA, WPXI, WTAE, WPGH, WQED"); a channel whose name matches goes in category Local (and News). Local is the first Browse tile, second in the guide's Categories (after Single Show), and leads the News tab with a green LOCAL tag. Found: CBS News Pittsburgh (Pluto), WPXI Pittsburgh (Tubi, Xumo), WTAE Very Pittsburgh 4 (Tubi). The downstairs Shield has no Tubi/Xumo, so only CBS News Pittsburgh there. KDKA live via Paramount+ Premium in Prime Video not done: needs a Prime Video deep link to the live channel (find it by driving the Prime app, or ask Jeremy).

0.6.5 (Oct 16): **One card per title**: every on-demand title carries its JustWatch id (`jw_id`, QV v8); rows dedupe by id, not name. On Home (`home=1` on the row URLs) a title shows once, in its highest row: Up Next > New this week > Trending (`ui._home_taken`); Rediscover skips New this week and Trending by id. Trending on Home: 36 → 24.

0.6.4 (Oct 16): **Up Next hero** (map 5.3): Season · Episode — title line, the episode's summary (JustWatch seasons), details line, "Watched 11 of 16 episodes" with a green bar (props episode/summary/chips/progress_text/progress on Up Next cards; `SH_UpNextHero` in the skin). Clicking an Up Next card opens the info page on that season with the episode focused (`season`/`episode` URL params → `infodialog.show(focus_ep=...)`). Genre names in full everywhere (`ondemand.genre_name`).

0.6.3 (Oct 16): **Rediscover** row (Home row 9400, between New this week and Trending; `rediscover.py`, state in `rediscover.json`): 1985–2015 movies on your services from a ~300 pool (IMDb ≥ 6.5 with ≥ 25k votes), 20 picked once a day (decades in turn, ≤ 5 per first category, one per franchise via TMDB collections, nothing from New this week / Trending, 2-week cooldown). Seen movies (Trakt, now paged) carry a SEEN badge; setting `rediscover_unseen_only`. Long-press: More like this, Hide this movie, Undo hide. Also: one Watch on entry per app.

0.6.2 (Oct 16): HBO Max via Prime added to the default subscriptions (Jeremy's plans: Paramount+ Premium and HBO Max Standard through Prime).

0.6.1 (Oct 16, afternoon):
- Plex channel links use Plex's own slugs (`resources/data/plex_slugs.json`, refresh with `tools/plex_slugs.py`): 145 of 695 channels, 21 Jump Street among them, opened to Plex's error page.
- Guide: one row per channel across services (54 names were 2-4 rows); ION and ION Plus stay apart.
- Your subscriptions (setting `subscriptions`, WatchHub menu > Your subscriptions). Offers labelled Included / Free / Free with ads / Subscription / Rent $x / Buy $x; cards only from Included and free; rentals (Prime Video and Apple TV stores) under Watch on...
- Services row: the picked service stays a tile and a red "Open <service>" card follows it; header "BROWSING: X · Back clears".
- Back to the same Home row and card after an app (`homefilter.remember_spot` in `kodi.start_android_activity`; restored by the service after a kill, and after a row reload if nothing was pressed since).

### Oct 15 (MacBook)
- 0.5.1 Netflix/Peacock/channel links land on the title or channel even when the app is already open (Netflix flags `276856832` + extra `source=30`; Peacock uses JustWatch's `deeplinkURL`).
- 0.5.2 Game Shows tab; Plex/Roku channels get genres; more Spanish channels hidden.
- 0.5.3 Guide and info pages are opened by the background service (`uiworker.py`: skin sets Home property `sh_ui_request`, worker thread polls it every 50 ms). Guide 1.7 s → 0.25 s, info page 0.15 s, buttons fixed from the first frame.
- 0.5.4–0.5.6 ★ Favorites (header icon + screen, `favorites.py`); WatchHub's own long-press menu via keymap `userdata/keymaps/watchhub.xml` (keyboard return longpress → `action=ctx`); Add/Remove label is live.
- 0.5.7 Guide tabs fit one screen; Codex threading review, 4 fixes.
- 0.5.8 Tubi (167 ch, lineup snapshot in `resources/data/tubi_channels.json`, public EPG, tunes directly) and Xumo Play (427 ch, opens its own guide, so ranked last) in the guide.
- 0.5.9 One WatchHub category list (`categories.py`, ~25 categories instead of 88 service labels). Guide "Categories" tab opens tiles (panel 600 in `Guide.xml`), Single Show first. Music tab removed.
- 0.5.10 Tiles skip Sports/News/Movies/Game Shows/Kids (their tabs show exactly the same channels).
- 0.5.11 Other category sorted by hand (89 → 3): `CHANNEL_CATS` in `categories.py`; new International category. `tools/category_report.py <Category>` lists a category with labels and titles for this kind of review.
- 0.6.0 **Browse**: home row 9700 (was Free Live TV) = TV Guide card + a tile per category (`ui.browse_tiles`, counts published by the service in Home property `sh_category_counts`). A tile opens `Browse.xml` (`browse.py`, via the ui worker like the guide): Live now (one card per channel name), Shows and Movies on your services (`ondemand.titles(genres=...)`, JustWatch codes from `categories.JW_FOR`). Channels-only categories show a full-screen grid (panel 110).

## How-tos

**Releasing and deploying**
- **Release:** add the release to `resources/changelog.txt`, bump `version` in plugin (and skin if changed) addon.xml → `python3 tools/make_repo.py --base-url https://raw.githubusercontent.com/jcummins100/WatchHub/main/repo/` → `git checkout` the unchanged rebuilt zips (e.g. `repo/repository.sportshub/...-1.0.0.zip`) → commit + push coding → rsync `plugin.video.sportshub skin.sportshub tools repo` into a clone of jcummins100/WatchHub, commit, push → on the Pro, cmd hook `UpdateAddonRepos(true)` (raw.githubusercontent can lag a few minutes).
- **Skin changes** aren't pushed by `tools/deploy.sh` (plugin only): `adb push --sync skin.sportshub/xml/. <kodi>/addons/skin.sportshub/xml/`.
- **Restart Kodi** after service/guide code changes: Back, write `Quit()` to the cmd hook, wait until `pidof org.xbmc.kodi` is empty (10–25 s), then `monkey -p org.xbmc.kodi -c android.intent.category.LEANBACK_LAUNCHER 1`. Never `am force-stop` Kodi.
- **Plex links:** slugs come from `resources/data/plex_slugs.json`; refresh with `python3 tools/plex_slugs.py` at each release (Plex renames and numbers slugs, e.g. 21-jump-street-2).
- **Tubi:** the anonymous API token needs a signature — not bypassed. The lineup came from a signed-in Chrome session (`tubitv.com/oz/epg`); refresh the snapshot with releases.

**Testing**
- **Before key-press tests:** force-stop apps left open (Plex, Xumo, Tubi come to the front after Quit), `input keyevent 224` to wake the screensaver, confirm Kodi is the resumed activity, and wait for the guide's "tab drawn" log line — right after a start the guide reopens itself and takes ~15 s while the channel list builds; keys sent earlier land on the wrong screen.
- **Off-device guide counts:** `SH_apps=tv.pluto.android,com.plexapp.android,com.roku.web.trc,com.tubitv,com.xumo.xumo.tv python3 tools/guide_report.py` (uses dev_run stubs; without SH_apps the other services count as not installed).

**Keeping the Shields the same**
- **Same settings on every Shield:** `python3 tools/sync_settings.py --from <ip> --to <ip...>` shows what differs (settings, favorites, hidden channels; never the Trakt sign-in); `--apply` quits Kodi on the target, copies, restarts. Pick the source carefully: on Oct 16 the Pro had favorites the downstairs Shield didn't, so copy from the Pro.

**Machines and helpers**
- **Codex:** CLI at `/Users/jcummins/.vscode/extensions/openai.chatgpt-*/bin/macos-aarch64/codex` (logged in with ChatGPT). `codex exec --sandbox read-only -C <dir> --skip-git-repo-check -o out.md "prompt"`. Used for the threading review and the WatchHub map review.
- **Codex on Ubuntu** (`~/.local/bin/codex`, 0.158.0): `codex exec` fails because `~/.local/bin/codex-code-mode-host` is missing (Oct 16). Reinstall (`npm install -g @openai/codex`) before relying on it; a review subagent was used instead.
- **Ubuntu box:** no system adb, no passwordless sudo; platform-tools in `~/.local/share/platform-tools` (`~/.local/bin/adb`).

**Reference**
- **Subscription savings research** (Oct 16): `docs/Subscriptions-Research-2026-10.md`; summary and questions on the board.

## Decisions the user made
- **Oct 16: every Shield is exactly the same** (streaming apps and settings), the 2 GB Shield TV included; "we'll see if it can keep up". Personal extras (Plex Media Server, UniFi Protect, Steam Link, Play Games) stay on the Pros only. Done: 11 streaming apps added downstairs; FOX Sports is "not compatible" with the Shield TV (2019 base model) in the Play Store; FOX One covers FOX games. Freevee is now part of Prime Video (its app may be dead weight on all three).
- Old-movies row is called **Rediscover**, 1985–2015, seen titles included and marked.
- Nothing from the services left out, but no duplicates (a tile/tab that repeats another goes).
- No Music tab (user never plays music); no Shows tab; Kids is a tab; Single Show first in Categories; Spanish channels hidden.
- Wait on Trakt VIP. Resolution issue parked in Sprint D.
- Evenings: test only the change; full test overnight (or when the user hands over the TV).

## Rules that still apply
- Dry run before any Trakt write. Each Shield has its own Trakt sign-in; never copy tokens (only trakt_client_id / tmdb_key).
- Same streaming apps and settings on every Shield (Oct 16). Don't remove an app from any Shield without asking (Freevee is the open question).
- Exports and tokens stay out of git (`~/.watchhub/`). Saved browser sessions: no stored passwords, no captcha/MFA bypass, no faking signed tokens.
- The test runner never touches Trakt data and never picks anything in the Power menu.
- Don't touch the uncommitted AVA file in the coding repo.
