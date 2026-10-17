"""Your order for the home screen's rows (WatchHub settings > Home screen rows).

The skin lays its rows out at fixed heights, so a new order means rewriting the All view's rows in the
WatchHub skin's Home.xml - positions, Up/Down links and the slide animations - and reloading the skin.
Services stays first and More last. A hidden row keeps its place in the file with its content switched
off (content_path_off) and sits below More, out of the Up/Down chain, so it can come back.
A skin update ships the default order: the service re-applies yours at start-up (apply_saved).
Kept per Shield in homerows.json; tools/sync_settings.py copies it.
"""
import json
import os
import re

import xbmcvfs

from resources.lib import kodi

FIRST, LAST = "9050", "9600"
ROWS = {"9960": "Up Next", "9200": "Today's Games", "9950": "New this week", "9450": "Recommended for you",
        "9800": "Trending", "9400": "Rediscover", "9700": "Browse"}
DEFAULT = ["9960", "9200", "9950", "9450", "9800", "9400", "9700"]
ROW_H = 376
FILE = "homerows.json"
_RAIL = re.compile(r'\t\t\t<include content="SH_Rail(?:Static)?">.*?</include>', re.S)


def _path():
    return os.path.join(kodi.ensure_profile_dir(), FILE)


def load():
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = {}
    order = [r for r in data.get("order") or [] if r in ROWS]
    order += [r for r in DEFAULT if r not in order]  # rows added in later versions go to the end
    return {"order": order, "hidden": [r for r in data.get("hidden") or [] if r in ROWS]}


def save(data):
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, _path())


def _home_xml():
    return os.path.join(xbmcvfs.translatePath("special://home/addons/skin.sportshub/xml/"), "Home.xml")


def _block(xml):
    """(start, end, {list_id: rail xml}) of the All view's rows (group 9000)."""
    g = xml.index('<control type="group" id="9000">')
    a = xml.index('\t\t\t<animation effect="slide"', g)
    end = xml.index('</include>', xml.index('<param name="list_id" value="%s"/>' % LAST, g)) + len('</include>')
    # hidden rows sit after More: take everything up to the group's end
    group_end = xml.index('\t\t</control>', end)
    rails = _RAIL.findall(xml[a:group_end])
    by = {re.search(r'list_id" value="(\d+)"', r).group(1): r for r in rails}
    return a, group_end, by


def current(xml=None):
    """The visible order in the skin now (without Services and More)."""
    xml = xml or open(_home_xml(), encoding="utf-8").read()
    _, _, by = _block(xml)
    ids = [i for i, r in sorted(by.items(), key=lambda kv: int(re.search(r'row_top" value="(\d+)"', kv[1]).group(1)))]
    return [i for i in ids if i in ROWS and 'name="content_path_off"' not in by[i]]


def _switch(rail, on):
    if on and 'name="content_path_off"' in rail:
        rail = re.sub(r'\s*<param name="content_path" value=""/>', '', rail)
        return rail.replace('name="content_path_off"', 'name="content_path"')
    if not on and 'name="content_path_off"' not in rail and 'name="content_path"' in rail:
        rail = rail.replace('name="content_path"', 'name="content_path_off"')
        return rail.replace('<param name="content_path_off"', '<param name="content_path" value=""/>\n\t\t\t\t<param name="content_path_off"', 1)
    return rail


def render(xml, order, hidden):
    a, group_end, by = _block(xml)
    shown = [FIRST] + [r for r in order if r not in hidden and r in by] + [LAST]
    rest = [r for r in order if r in hidden and r in by]
    anims = ['\t\t\t<animation effect="slide" end="0,-%d" time="260" tween="cubic" easing="out" condition="%s">Conditional</animation>'
             % (ROW_H, " | ".join("Control.HasFocus(%s)" % c for c in shown[i:])) for i in range(1, len(shown))]
    out = []
    for i, c in enumerate(shown + rest):
        r = _switch(by[c], c not in rest)
        r = re.sub(r'(row_top" value=")\d+', r'\g<1>%d' % (ROW_H * i), r)
        if c in rest:  # out of the chain: Up/Down from it lands on More
            prev, nxt = [LAST] * 3, [LAST] * 3
        else:
            j = shown.index(c)
            prev = [shown[j - k] if j - k >= 0 else "700" for k in (1, 2, 3)]
            nxt = [shown[min(j + k, len(shown) - 1)] for k in (1, 2, 3)]
        r = re.sub(r'<param name="prev1" value="\d+"/><param name="prev2" value="\d+"/><param name="prev3" value="\d+"/>',
                   '<param name="prev1" value="%s"/><param name="prev2" value="%s"/><param name="prev3" value="%s"/>' % tuple(prev), r)
        r = re.sub(r'<param name="next1" value="\d+"/><param name="next2" value="\d+"/><param name="next3" value="\d+"/>',
                   '<param name="next1" value="%s"/><param name="next2" value="%s"/><param name="next3" value="%s"/>' % tuple(nxt), r)
        out.append(r)
    head = re.sub(r'(<control type="group" id="9000">.*?<defaultcontrol>)\d+(</defaultcontrol>)',
                  lambda m: m.group(1) + shown[1] + m.group(2), xml[:a], count=1, flags=re.S)
    return head + "\n".join(anims) + "\n" + "\n".join(out) + "\n" + xml[group_end:]


def apply(data=None, reload=True):
    """Write the order into the skin; True if Home.xml changed."""
    data = data or load()
    path = _home_xml()
    try:
        xml = open(path, encoding="utf-8").read()
        new = render(xml, data["order"], data["hidden"])
    except (OSError, ValueError, AttributeError) as exc:
        kodi.log("home rows: not applied (%s)" % exc)
        return False
    if new == xml:
        return False
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(new)
    os.replace(tmp, path)
    kodi.log("home rows: %s (hidden: %s)" % (", ".join(ROWS[r] for r in data["order"]), ", ".join(ROWS[r] for r in data["hidden"]) or "none"))
    if reload:
        kodi.run_builtin("ReloadSkin()")
    return True


def apply_saved():
    """Start-up: a skin update brings the default order back; put yours back (only if you have one)."""
    if os.path.exists(_path()):
        apply()


def edit():
    """WatchHub settings > Home screen rows: pick a row, move it or hide it; Back applies."""
    import xbmcgui
    data = load()
    before = json.dumps(data)
    pos = 0
    while True:
        labels = ["%d. %s%s" % (i + 1, ROWS[r], "   (hidden)" if r in data["hidden"] else "") for i, r in enumerate(data["order"])]
        labels.append("Reset to WatchHub's order")
        pick = xbmcgui.Dialog().select("Home screen rows (Services stays first, More last)", labels, preselect=pos)
        if pick < 0:
            break
        if pick == len(data["order"]):
            data = {"order": list(DEFAULT), "hidden": []}
            pos = 0
            continue
        r = data["order"][pick]
        acts = ["Move up", "Move down", "Move to the top", "Show this row" if r in data["hidden"] else "Hide this row"]
        a = xbmcgui.Dialog().contextmenu(acts)
        i = pick
        if a == 0 and i > 0:
            data["order"][i - 1], data["order"][i] = data["order"][i], data["order"][i - 1]
            pos = i - 1
        elif a == 1 and i < len(data["order"]) - 1:
            data["order"][i + 1], data["order"][i] = data["order"][i], data["order"][i + 1]
            pos = i + 1
        elif a == 2:
            data["order"] = [r] + [x for x in data["order"] if x != r]
            pos = 0
        elif a == 3:
            data["hidden"] = [x for x in data["hidden"] if x != r] if r in data["hidden"] else data["hidden"] + [r]
            pos = i
    if json.dumps(data) != before:
        save(data)
        apply(data)
