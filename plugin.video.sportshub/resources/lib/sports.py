"""Classify channels and programmes into sports, and spot things that look like live games."""
import re

# Order matters: first match wins. (sport label, regex over channel name + programme title)
_RULES = [
    ("Football (NFL/College)", r"\bnfl\b|football|\bacc\b|accdn|big 12|big ten|pac-12|\bsec\b|ncaa|college|hbcu|\bcfb\b|cowboy"),
    ("Basketball", r"\bnba\b|basketball|\bwnba\b|overtime|hoops|march madness"),
    ("Baseball", r"\bmlb\b|\bmilb\b|baseball|world series"),
    ("Hockey", r"\bnhl\b|hockey|stanley cup"),
    ("Soccer", r"soccer|f[uú]tbol|uefa|champions league|golazo|bein|fifa|premier league|la ?liga|bundesliga|serie a|\bmls\b|\bcopa\b|liga mx|\bftf\b|world cup|\busl\b"),
    ("Golf", r"\bpga\b|golf|dp world|liv golf|masters|ryder"),
    ("Tennis", r"tennis|wimbledon|us open tennis|\batp\b|\bwta\b|roland"),
    ("MMA / Combat", r"\bufc\b|\bmma\b|bellator|\bpfl\b|one championship|combate|glory|kickbox|\bfight|\bcombat|bkfc"),
    ("Boxing", r"boxing|ringside|top rank|hbo boxing"),
    ("Wrestling", r"wrestl|\btna\b|\bwwe\b|\baew\b|\bnxt\b|swerve"),
    ("Motorsport", r"nascar|formula|\bf1\b|motogp|nhra|racer|racing|motoamerica|speed sport|indycar|supercross|monster jam|flo ?racing|torque|turbo"),
    ("Cricket", r"cricket|willow|\bipl\b"),
    ("Rugby", r"rugby"),
    ("Poker", r"poker|triton"),
    ("Billiards", r"billiard|snooker|\bpool\b"),
    ("Pickleball", r"pickleball"),
    ("Surf / Outdoor", r"\bsurf|outside tv|outdoor|field & stream|meateater|waypoint|pursuit|game & fish|\bski(ing)?\b|fishing|bassmaster|\bhunting\b|rodeo|\bpbr\b"),
    ("Women's Sports", r"women'?s sports|awsn"),
    ("Olympics / Team USA", r"olympic|team usa"),
    ("Multi-sport", r"sport|stadium|fubo|espn|draftkings|fanduel|yahoo|sportsgrid|nesn|msg|unbeaten|scripps|ryz|chgo|phly|\bt2\b|\bslvr\b"),
]
RULES = [(label, re.compile(rx, re.I)) for label, rx in _RULES]

# Programme titles that look like a live event rather than a studio show / replay.
_GAME = re.compile(r"\bvs?\.?\b|\bat\b|@|\blive\b|match|game \d|round \d|final|semifinal|quarterfinal|grand prix|\bopen\b|championship|fight night|raceday|race day", re.I)
_NOT_GAME = re.compile(r"replay|classic|encore|best of|countdown|rewind|archive|highlights?|preview|recap|rerun|from the vault|marathon|top \d+|greatest|all[- ]access|documentary|film|films|movie|timeline|legends|podcast|radio|talk", re.I)

SPORT_LABELS = [label for label, _ in _RULES]


def classify(*texts):
    """Return the sport label for the given strings (channel name, programme title...) or None."""
    blob = " | ".join(t for t in texts if t)
    for label, rx in RULES:
        if rx.search(blob):
            return label
    return None


def is_sports_channel(name, groups=None):
    if groups:
        for g in groups if isinstance(groups, (list, tuple)) else [groups]:
            if g and "sport" in str(g).lower():
                return True
    return classify(name) is not None


def looks_like_game(title):
    if not title:
        return False
    if _NOT_GAME.search(title):
        return False
    return bool(_GAME.search(title))
