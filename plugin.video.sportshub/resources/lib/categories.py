"""One category list for everything WatchHub shows (docs/WatchHub-Map.md, section 6).

Pluto, Roku, Tubi and Xumo each label channels their own way, Plex not at all, and JustWatch uses its own
genre codes for movies and shows. This maps all of them onto one list of WatchHub categories, so the guide,
Browse and filters speak the same language.

A channel's categories come from, in order: its source labels (SOURCE), words in its name (NAME_RULES), and
for single-show channels without labels (most of Plex: "ALF", "Baywatch") the show's own JustWatch genres,
looked up a few at a time in the background and kept in the profile (show_genres.json). Anything still
unmapped stays uncategorized: it is in "All" and Search, never under a misleading label.
"""
import json
import os
import re
import time

from resources.lib import kodi

# Display order; the first COMMON are shown first in Browse and the guide's Categories
CATEGORIES = [
    "Single Show", "Sports", "News", "Movies", "Comedy", "Drama", "Crime", "Reality", "Kids",
    "Game Shows", "Sci-Fi", "Action", "Documentary",
    "Mystery", "Horror", "Westerns", "Animation", "Nature", "Food & Home",
    "Travel", "Music", "Talk", "Cars", "Romance", "Faith",
]
COMMON = 13

# guide tab -> category
TAB_CATEGORY = {"Sports": "Sports", "News": "News", "Movies": "Movies", "Game Shows": "Game Shows",
                "Kids": "Kids", "Music": "Music"}
SINGLE_SHOW = "Single Show"   # channels that air one show around the clock (Jeremy's idea)


# shows about music people that services file under Music
_NOT_MUSIC = re.compile(r"happy days|growing up hip hop", re.I)


def with_single_show(cats, name, programs):
    """Add Single Show to a channel's categories. Music, news, sports and movie channels often list their own
    name all day (Stingray Hot Country, Bloomberg TV): that's not a show, so they never count. A music label
    on a channel with no music in its name that airs one show (Happy Days, The Masked Singer) is the
    service's mistake: it moves to Single Show."""
    if "Music" in cats and "Music" not in from_name(name) and (is_single_show(name, programs) or _NOT_MUSIC.search(name or "")):
        cats = (cats - {"Music"}) or set()
    if not cats & {"Music", "News", "Sports", "Movies"} and is_single_show(name, programs):
        return cats | {SINGLE_SHOW}
    return cats


def is_single_show(name, programs):
    """One show around the clock: The Price Is Right, ALF, Baywatch. Counts when the show is the channel's own
    name, or when one show fills a whole day of the schedule (a one-night marathon doesn't count)."""
    progs = [(st, _n(t)) for st, t in programs if t]
    if len(progs) < 3:
        return False
    keys = [t for _, t in progs]
    top = max(set(keys), key=keys.count)
    if len(top) < 3:
        return False
    chan = _show_name(_n(name))
    if keys.count(top) >= 0.7 * len(keys) and chan and (_show_name(top) == chan or chan in top or _show_name(top) in chan):
        return True
    span = progs[-1][0] - progs[0][0]
    return span >= 20 * 3600 and keys.count(top) >= 0.95 * len(keys)


def _n(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# source label (any service, normalized) -> WatchHub categories. Combined labels map to both halves.
_SOURCE = {
    # Pluto
    "comedy": ["Comedy"], "drama": ["Drama"], "true crime": ["Crime"], "reality": ["Reality"],
    "competition reality": ["Reality"], "sci fi": ["Sci-Fi"], "halloween hits": ["Horror"],
    "westerns": ["Westerns"], "kids": ["Kids"], "anime": ["Animation"],
    "history science": ["Documentary"], "animals nature": ["Nature"], "home food": ["Food & Home"],
    "movies": ["Movies"], "music videos": ["Music"], "news opinion": ["News"], "local news": ["News"], "sports": ["Sports"],
    # Roku
    "sitcom": ["Comedy"], "standup": ["Comedy"], "romantic comedy": ["Comedy", "Romance"], "comedy drama": ["Comedy", "Drama"],
    "soap": ["Drama"], "crime drama": ["Drama", "Crime"], "docudrama": ["Drama", "Documentary"],
    "action": ["Action"], "adventure": ["Action"], "martial arts": ["Action"],
    "crime": ["Crime"], "law": ["Crime"], "mystery": ["Mystery"],
    "suspense": ["Mystery"], "thriller": ["Mystery"], "paranormal": ["Reality"],
    "game show": ["Game Shows"], "card games": ["Game Shows"], "poker": ["Game Shows"], "talk": ["Talk"],
    "science fiction": ["Sci-Fi"], "fantasy": ["Sci-Fi"], "horror": ["Horror"], "western": ["Westerns"],
    "children music": ["Kids"], "educational": ["Kids"], "animated": ["Animation"],
    "documentary": ["Documentary"], "history": ["Documentary"], "science": ["Documentary"],
    "environment": ["Nature"], "nature": ["Nature"], "animals": ["Nature"], "outdoors": ["Nature"],
    "cooking": ["Food & Home"], "food": ["Food & Home"], "home improvement": ["Food & Home"], "house garden": ["Food & Home"],
    "how to": ["Food & Home"], "travel": ["Travel"], "music": ["Music"], "music talk": ["Music"], "news": ["News"],
    "weather": ["News"], "auto": ["Cars"], "romance": ["Romance"], "faith": ["Faith"], "religious": ["Faith"],
    # Tubi
    "tv dramas": ["Drama"], "pop culture": ["Reality"], "games competition": ["Game Shows"], "sci fi supernatural": ["Sci-Fi"],
    "kids family": ["Kids"], "documentaries": ["Documentary"], "science nature": ["Nature", "Documentary"],
    "good eats": ["Food & Home"], "lifestyle": ["Food & Home"], "movie channels": ["Movies"], "national news": ["News"],
    "business news": ["News"], "global news": ["News"], "sports on now": ["Sports"],
    # Xumo
    "action drama": ["Action", "Drama"], "crime tv": ["Crime"], "reality tv": ["Reality"],
    "daytime tv": ["Talk"], "game shows": ["Game Shows"], "horror sci fi": ["Horror", "Sci-Fi"],
    "season of scares": ["Horror"], "westerns country": ["Westerns"], "faith family": ["Faith", "Kids"],
    "history learning": ["Documentary"], "home design": ["Food & Home"], "travel lifestyle": ["Travel"],
    "music radio": ["Music"], "automotive": ["Cars"], "combat sports": ["Sports"],
}
# Roku's per-sport labels are all Sports
for _s in ("soccer", "baseball", "basketball", "football", "hockey", "rugby", "boxing", "mixed martial arts", "mma", "wrestling",
           "pro wrestling", "action sports", "surfing", "skateboarding", "snowboarding", "skiing", "motorsports", "auto racing",
           "drag racing", "motorcycle racing", "bmx racing", "bicycle", "bicycle racing", "cycling", "mountain biking", "swimming",
           "volleyball", "olympics", "fishing", "billiards", "bowling", "sports talk", "intl soccer", "3x3 basketball"):
    _SOURCE[_n(_s)] = ["Sports"]

# JustWatch genre codes (on-demand titles, and the shows behind single-show channels)
JW = {"cmy": ["Comedy"], "drm": ["Drama"], "act": ["Action"], "war": ["Action", "Documentary"],
      "crm": ["Crime"], "trl": ["Mystery"], "rly": ["Reality"], "scf": ["Sci-Fi"],
      "fnt": ["Sci-Fi"], "hrr": ["Horror"], "wsn": ["Westerns"], "fml": ["Kids"], "ani": ["Animation"],
      "doc": ["Documentary"], "hst": ["Documentary"], "msc": ["Music"], "rma": ["Romance"], "spt": ["Sports"]}
JW_FOR = {}
for _code, _cats in JW.items():
    for _c in _cats:
        JW_FOR.setdefault(_c, []).append(_code)

# words in a channel's name (Plex has no labels). Checked against the full channel list: "FilmRise Comedy" is
# a distributor + genre, "Family Handyman" is not kids, "The Kids in the Hall" is sketch comedy.
NAME_RULES = [
    ("News", r"\bnews|weather|local now|bloomberg|cheddar|france 24|reuters|usa today|livenow|\bcnn\b"),
    ("Movies", r"movie(?! music)|cinema|\bfilms?\b(?!rise)|flix\b|pel[ií]culas|mgm presents|miramax|at the movies"),
    ("Kids", r"\bkid(?!s in the hall)|toon|cartoon|\bbaby|teletubbies|wiggles|little pony|sonic|super mario|power rangers"
                      r"|beyblade|yu-gi-oh|transformers|strawberry shortcake|moonbug|like nastya|pocket\.watch|garfield|sesame"),
    ("Music", r"music|\bhits\b|\bmtv\b(?! pluto)|\bcmt\b|tiktok radio|iheart|stingray|\bxite\b|vevo|karaoke|jazz|classic rock|k-pop|concert|\btrace\b|metal\.rocks"
              r"|easy listening|hip-hop/r&b|country\b|soul storm"),
    ("Comedy", r"comedy|comedies|\blaff|funny|\blol\b|sitcom|stand.?up|snl|\bjokes?\b"),
    ("Drama", r"\bdrama|soaps?\b|novela"),
    ("Crime", r"crime|criminal|killers?\b|\bcops\b|police|forensic|cold case|\bfirst 48\b|court|\bjudge|\bjail|prison|murder|detective|dateline|investigat"),
    ("Mystery", r"myster|thriller|suspense|sherlock|poirot|midsomer"),
    ("Reality", r"reality|real housewives|bachelor|\bwe tv\b|love after|pawn|storage wars|tiny house|survivor|\bfear factor"),
    ("Sci-Fi", r"sci.?fi|science fiction|doctor who|star trek|stargate|outer limits|twilight zone|alien|\bspace\b|paranormal|supernatural"),
    ("Horror", r"horror|scream|scares?\b|fright|haunt|zombie|shudder|crypt|dread|terror"),
    ("Westerns", r"western|cowboy|\bwild west|gunsmoke|bonanza|lone ranger"),
    ("Animation", r"\banime|animation|animated|cartoon"),
    ("Documentary", r"documentar|history|\bhistory\b|biograph|\bpbs\b|smithsonian|curiosity|magellan|science"),
    ("Nature", r"nature|animal|\bpets?\b|\bdogs?\b|\bcats?\b|wild|ocean|earth"),
    ("Food & Home", r"\bfood|cook|kitchen|chef|bak(e|ing)|tastemade|home\b|house|garden|diy|crafts?\b|design|renovat|flip"),
    ("Travel", r"travel|\btrips?\b|explor|getaway|journey|nomad"),
    ("Talk", r"\btalk\b|dr\.? phil|maury|jerry springer|steve wilkos|wendy williams|daytime"),
    ("Cars", r"\bcars?\b|motor|garage|hot rod|\bauto(?!pista)|truck|\bmecum|hagerty|top gear|wheeler"),
    ("Romance", r"romance|romantic|\blove\b|hallmark|wedding"),
    ("Faith", r"faith|gospel|church|bible|christian|\bpray|joel osteen|\bdove\b"),
    ("Game Shows", r"price is right|\btpir\b|family feud|deal or no deal|let'?s make a deal|buzzr|game show|quiz show"
                   r"|supermarket sweep|name game|jeopardy|wheel of fortune|match game|press your luck|card sharks|newlywed"
                   r"|wipeout|hollywood squares|weakest link|minute to win it|to tell the truth"),
]
NAME_RULES = [(c, re.compile(rx, re.I)) for c, rx in NAME_RULES]
_GAME_SHOW_RX = dict(NAME_RULES)["Game Shows"]


def from_labels(labels):
    out = []
    for lab in labels or []:
        for c in _SOURCE.get(_n(lab), []):
            if c not in out:
                out.append(c)
    return out


def from_name(name):
    return [c for c, rx in NAME_RULES if rx.search(name or "")]


def from_jw(codes):
    out = []
    for code in codes or []:
        for c in JW.get(code, []):
            if c not in out:
                out.append(c)
    return out


def for_channel(name, labels, is_sports=False):
    """WatchHub categories for one channel (a set). Game shows go by name only (Pluto's game-show group also
    holds talk and shopping channels); the rest by labels, then name words, then the show behind the channel."""
    cats = set(from_labels(labels))
    if "Game Shows" in cats and not _GAME_SHOW_RX.search(name or ""):
        cats.discard("Game Shows")
        cats.add("Talk")
    if _GAME_SHOW_RX.search(name or ""):
        cats.add("Game Shows")
    if is_sports:
        cats.add("Sports")
    if not cats - {"Sports"}:
        cats.update(from_name(name))
    if not cats:
        cats.update(from_jw(show_genres().get(_n(name)) or []))
    return cats


# ---- shows behind single-show channels (filled in the background by the service)
_SHOW_CACHE = {"at": 0.0, "data": None}


def _show_path():
    return os.path.join(kodi.ensure_profile_dir(), "show_genres.json")


def show_genres():
    """{normalized channel name: [JustWatch genre codes]} ([] = looked up, nothing found)."""
    if _SHOW_CACHE["data"] is None or time.time() - _SHOW_CACHE["at"] > 300:
        try:
            with open(_show_path(), encoding="utf-8") as fh:
                _SHOW_CACHE["data"] = json.load(fh)
        except (OSError, ValueError):
            _SHOW_CACHE["data"] = {}
        _SHOW_CACHE["at"] = time.time()
    return _SHOW_CACHE["data"]


# channel-name decoration that isn't part of the show's title
_DECOR = re.compile(r"\b(by (a&e|a e|mgm|history|lifetime|dust)|channel|network|tv|24/7|classic|the series|show|uk|us)\b|^the\b|\bthe\b$")


def _show_name(key):
    return " ".join(_DECOR.sub(" ", key).split())


def fill_show_genres(names, budget=40):
    """Look up up to `budget` not-yet-known channel names as shows on JustWatch and remember their genres.
    Returns how many were looked up (0 = everything known)."""
    from resources.lib import guide
    from resources.lib.sources import ondemand
    known = dict(show_genres())
    todo = [n for n in dict.fromkeys(_n(x) for x in names) if n and n not in known][:budget]
    for key in todo:
        query = _show_name(key)
        item = ondemand.lookup(query, "", "") or {}
        # only trust a matching name ("Beverly Hillbillies" = "The Beverly Hillbillies"), never a lookalike
        known[key] = (item.get("genre_codes") or [])[:2] if query and _show_name(_n(item.get("title"))) == query else []
    if todo:
        guide._write_json(_show_path(), known)
        _SHOW_CACHE.update(data=known, at=time.time())
    return len(todo)
