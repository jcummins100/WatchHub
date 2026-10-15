# WatchHub for Kodi: Design Brief for Review

*As of 2026-10-15. Prepared for outside reviewers (people or AI models) to give feedback on layout, design and configuration.*

## How to use this brief

You are reviewing a TV home-screen app. Please read the whole brief, look at the screenshots if they were attached, then answer the **Questions for reviewers** at the end. For each answer, give a recommendation, the reason, and anything it would cost (complexity, extra clicks, performance). Suggestions outside those questions are welcome. Keep in mind the constraints in "Hard constraints". An idea that a Kodi skin can't do is not useful.

## 1. What WatchHub is

WatchHub is a custom **Kodi add-on plus skin** that turns an NVIDIA Shield into a single home screen for:

- live sports on free channels and the user's streaming services,
- today's games and which network carries them,
- free live TV (Pluto TV, Plex, The Roku Channel),
- on-demand shows and movies on the services the household pays for (Netflix, Hulu, Prime Video...),
- a personal "Up Next" list from Trakt (a watch-history service).

It contains **no streams**. Every play button hands off to the official Android TV app (Netflix, Hulu, Pluto TV, ESPN...) using the user's own accounts. WatchHub only fetches metadata.

## 2. Devices and environment

| Device | Model | Free storage | Notes |
| --- | --- | --- | --- |
| Shield TV Pro #1 | 2019 Pro | 4.7 GB | Reference setup |
| Shield TV Pro #2 | 2019 Pro | not checked | |
| Shield TV | 2019 "tube" | 2.3 GB | Small storage limits how many apps it can hold |

- Android TV 11, Kodi 21.2, WatchHub 0.3.0.
- **Input is a D-pad remote only:** up, down, left, right, select, back, and long-press for a context menu. No pointer, no keyboard.
- Screen: 1920x1080 skin coordinates, watched from a couch (a "10-foot UI").
- Apps installed: Netflix, Prime Video, Apple TV, Hulu, Peacock, YouTube, Pluto TV, Plex, The CW. No ESPN, Max, Paramount+ or Disney+ app yet. (HBO Max and Paramount+ are watched as Prime Video add-on "channels".)
- Updates: a personal Kodi repository on GitHub. Bumping the version makes every Shield update itself.

## 3. Architecture

```
  DATA SOURCES (metadata only)            ON EACH SHIELD
  +---------------------------+
  | Live TV guides            |
  | Pluto TV, Plex, Roku,     |--+
  | Kodi PVR                  |  |
  +---------------------------+  |
  | Sports data               |  |     +--------------------------+
  | ESPN scores, TheSportsDB, |--+---->| WatchHub add-on (Python) |
  | YouTube league channels   |  |     | background refresh timer |
  +---------------------------+  |     | JSON cache (60 min)      |
  | Streaming catalog         |  |     | builds rows + info pages |
  | JustWatch: what is on     |--+     +------------+-------------+
  | which service; TMDB: art, |  |                  |
  | trailers                  |  |                  v
  +---------------------------+  |     +--------------------------+  click   +---------------------+
  | Trakt (per device)        |--+     | WatchHub skin (Kodi XML, |--------->| Official apps       |
  | Up Next, watchlist,       |        | based on Estuary)        |          | Netflix, Hulu,      |
  | history                   |        | hero band + rows         |          | Prime Video, ...    |
  +---------------------------+        +--------------------------+          +---------------------+
```

## 4. Current home screen

The screen has a **hero band** across the top (about the top half) and a stack of **horizontal rows** below it. The focused row always sits directly under the hero. The hero shows the focused card's backdrop art, a small kicker line (service name or LIVE), the title and one line of details. The header has Search, Settings and Power buttons plus the clock.

### "All" view (default): 9 rows

Changed in 0.3.0 after a first round of review: Your Apps was dropped (the Services row covers it), Trending Shows and Trending Movies were merged, By Sport moved into More, and New This Week now comes before Trending.

| # | Row | Card style | Data source | Click does |
| --- | --- | --- | --- | --- |
| 1 | Services | App icon tile | Installed services | Filters the home screen |
| 2 | Up Next | Poster | Trakt + JustWatch | Info page (Play on long-press) |
| 3 | Live Sports Now | Channel logo + "time left" bar | Pluto, Plex, Roku, PVR guides | Opens the app on that channel |
| 4 | Today's Games | Two team logos + time + networks | ESPN / TheSportsDB | Opens the network's app |
| 5 | New This Week on Your Services | Poster | JustWatch | Info page |
| 6 | Trending on Your Services (shows and movies) | Poster | JustWatch | Info page |
| 7 | Free Live TV | Genre tile (Entertainment, Reality, Drama...) | Free guides | Genre channel list |
| 8 | Sports Starting Soon | Channel logo + start time | Free guides | Opens the app |
| 9 | More | Text tile | Static | WatchHub menu, By sport, Your apps, Videos, Add-ons, Settings, Classic Kodi |

Home opens with focus on **Up Next**, so Services sits just above it, one press of Up away.

## 5. New: filter the home screen by provider

The owner wants to keep the home screen showing everything, but also be able to split it by streaming service. This is **built and working on one test Shield**, and still open to change.

- A **Services** row at the top lists "All services" plus each installed service (Netflix, Prime Video, Apple TV, Hulu, Peacock, YouTube, Pluto TV, Plex, HBO Max (Prime), Paramount+ (Prime)...).
- Picking a service swaps the home screen to a shorter **provider view**:
  1. Services (the picked one underlined, followed by an **Open Hulu** card that launches the app)
  2. Up Next on Hulu
  3. New This Week on Hulu
  4. Trending on Hulu
- While a service is picked, the header shows **BROWSING: HULU** next to the WatchHub logo.
- Live sports, games, free TV and Starting Soon are **hidden** in the provider view.
- Picking "All services" returns to the full home screen.
- The filter stays while you open titles or apps and come back, and resets to All when Kodi restarts.

**Why a separate view instead of hiding rows in place:** Kodi skins position rows at fixed vertical slots. Hiding a row in the middle leaves a blank gap, and up/down navigation can only skip a limited number of hidden rows. So the provider view is a second, shorter set of rows that replaces the All view while a service is picked.

**Alternatives considered:**

| Option | Upside | Downside |
| --- | --- | --- |
| Filter row on home (built) | Same screen, one click narrows everything | Adds a row above Up Next |
| "Browse by service" row opening provider pages | Home untouched | Two clicks deep; a second place to look |
| One block of rows per provider on the home screen | Everything visible at once | Very long screen (10+ services x 3 rows) |

## 6. Configuration

Settings are stored **on each Shield separately**; nothing syncs between devices.

| Setting | Default | What it does |
| --- | --- | --- |
| Region | us | Country for catalog data |
| Free sources | Pluto, Plex, Roku on; Samsung TV Plus off | Which free guides feed the live rows |
| Service priority | pluto, plex, roku, samsung | Which app opens when a channel is on several |
| TV / PVR, scores, YouTube | On | Extra live sources |
| TheSportsDB | Off (needs a key) | Alternative games data |
| Trakt Client ID | Empty | Turns on Trakt; each Shield signs in separately |
| Amazon channels | HBO Max, Paramount+ | Prime Video channels the household has |
| TMDB key | Empty | Trailers, Coming Soon, extra details |
| Open on start / delay | On / 3 s | WatchHub opens when Kodi starts |
| Starting-soon window | 120 min | How far ahead "Starting Soon" looks |
| Games only | Off | Hide non-game sports programming |
| Cache | 60 min | How long fetched data is reused |

Decisions already made:

- **Trakt sign-in is per device.** Trakt replaces the login token on every refresh, so two Shields sharing one login would sign each other out.
- **Installed apps decide what shows.** A service whose app is not installed is left out of rows and of the Services filter.
- **No streams, no scraping of paid services.** Metadata only; playback is always the official app.

## 7. Hard constraints

Please keep suggestions within these:

- **Kodi skin engine.** The layout is XML. There's no CSS, no flexbox and no reflow. Rows sit at fixed positions, and every row, focus rule and hero binding is written by hand. Python can set "window properties" that the XML reads, and it can fill lists.
- **D-pad only.** Every feature must work with up/down/left/right/select/back/long-press.
- **Data from third parties.** JustWatch, TMDB, Trakt and public guide feeds. No official APIs from Netflix, Hulu etc.
- **Deep links vary by app.** Pluto TV and The Roku Channel open straight to a channel; most paid apps open a title page or just their home screen.
- **Modest hardware.** The 2019 Shield TV has 2 GB RAM and 2.3 GB free storage.

## 8. Questions for reviewers

1. **Filter placement.** Is a Services row at the top the right pattern? Or should the filter be in the header, behind a button, or a left-side menu?
2. **Provider view contents.** Which rows matter most when one service is picked, and in what order? Should Live Sports and Today's Games stay for services that carry sports (Peacock, Prime Video, YouTube)?
3. **Prime Video channels.** Should HBO Max and Paramount+ (watched through Prime Video) be separate filters, or merged under Prime Video?
4. **Row order in the All view.** It currently goes Up Next, then live sports, then on-demand, then free TV. What order would you use, and why?
5. **Showing the active filter.** On a TV across the room, how should the selected service be shown: underline on the tile, a label in the hero, a tinted background, or something else?
6. **Home length.** Now 9 rows (down from 12). Is that the right length, or would you cut further?
7. **Syncing settings across 3 Shields.** Which settings should be shared, and what's the simplest reliable way to do it (a shared file on the network, a cloud store, Trakt)?
8. **Card design.** Posters for on-demand, logo cards for live channels and team-logo cards for games: is the mix clear, or should it be more uniform?

## Screenshots

If attached, these show the current build on the Shield TV (1280x720):

| File | Shows |
| --- | --- |
| 1-home-all-services-row.jpg | All view, Services row with "All services" selected |
| 2-home-up-next.jpg | All view, focus on Up Next (where home opens) |
| 3-provider-view-hulu-open-card.jpg | Hulu picked: BROWSING: HULU header, Open Hulu card, Up Next on Hulu |
| 4-all-new-this-week.jpg | All view, New This Week row |
| 5-all-trending.jpg | All view, merged Trending row (shows and movies) |
| 6-more-row.jpg | More row with By sport and Your apps |
