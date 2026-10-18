"""Sports page row SPORTS STREAMS: Kodi video add-ons the user picks, as app cards.

The list is the user's: sports_addons.json in WatchHub's profile folder ({"ids": [...]}, left to right, plus
"accepted" once they've agreed that add-ons they add are their own responsibility).
Until they change it, the row shows a few sample add-ons from Kodi's official add-on list. OK opens an
installed add-on (or turns it on, or offers to install it); the last card, "Edit this row", and each card's
long-press menu add, move and remove add-ons. Only this row reloads after an edit (sh_addons token)."""
import json
import os
import time

import xbmc
import xbmcgui

from resources.lib import kodi

# The user's own list: private. Tools and AI assistants don't read, copy or change it (only this row does).
FILE = os.path.join(kodi.PROFILE_PATH, "sports_addons.json")
# shown until the user saves a list of their own (all in Kodi's official add-on repository)
SAMPLES = ["plugin.video.youtube", "plugin.video.twitch", "plugin.video.vimeo"]
SAMPLE_NAMES = {"plugin.video.youtube": "YouTube", "plugin.video.twitch": "Twitch", "plugin.video.vimeo": "Vimeo"}


def _read():
    try:
        with open(FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data):
    os.makedirs(kodi.PROFILE_PATH, exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, FILE)


def load():
    ids = _read().get("ids")
    if isinstance(ids, list):
        return [i for i in ids if isinstance(i, str) and i]
    return list(SAMPLES)


def save(ids):
    _write(dict(_read(), ids=ids))
    _reload_row()


NOTICE = ("Add-ons you add to this row are your choice and your responsibility.\n\n"
          "WatchHub only opens them. It doesn't check, install or support them, or what they show.")


def accept():
    """Before the first add-on added by hand: the user agrees they're responsible for it. Asked once per Shield."""
    data = _read()
    if data.get("accepted"):
        return True
    if not xbmcgui.Dialog().yesno("Adding your own add-ons", NOTICE, nolabel="Cancel", yeslabel="I understand"):
        return False
    data["accepted"] = time.strftime("%Y-%m-%d %H:%M")
    data.setdefault("ids", load())
    _write(data)
    return True


def _reload_row():
    kodi.run_builtin("SetProperty(sh_addons,%d,home)" % time.time())


def details(addon_id):
    """{"name", "thumbnail", "enabled"} for an installed add-on, None when it isn't installed."""
    res = kodi.jsonrpc("Addons.GetAddonDetails", {"addonid": addon_id, "properties": ["name", "thumbnail", "enabled"]})
    return (res or {}).get("addon")


def installed_video_addons():
    """Every installed video add-on except WatchHub, as (id, name), by name."""
    res = kodi.jsonrpc("Addons.GetAddons", {"type": "xbmc.addon.video", "properties": ["name"]}) or {}
    found = [(a["addonid"], a.get("name") or a["addonid"]) for a in res.get("addons") or []
             if a.get("addonid") != kodi.ADDON.getAddonInfo("id")]
    return sorted(found, key=lambda a: a[1].lower())


def row():
    """The row's cards: one per add-on, then "Edit this row"."""
    kodi.set_content("videos")
    ids = load()
    for i, addon_id in enumerate(ids):
        d = details(addon_id)
        name = (d or {}).get("name") or SAMPLE_NAMES.get(addon_id) or addon_id
        if not d:
            meta = "Not installed yet - OK installs it from Kodi's add-on list"
        elif not d.get("enabled"):
            meta = "Turned off in Kodi - OK turns it on and opens it"
        else:
            meta = "Open %s" % name
        if addon_id not in SAMPLES:
            meta += " · Added by you"
        ctx = []
        if i > 0:
            ctx.append(("Move left", "RunPlugin(%s)" % kodi.build_url(action="addons_move", id=addon_id, by="-1")))
        if i < len(ids) - 1:
            ctx.append(("Move right", "RunPlugin(%s)" % kodi.build_url(action="addons_move", id=addon_id, by="1")))
        ctx += [("Add an add-on to this row", "RunPlugin(%s)" % kodi.build_url(action="addons_add")),
                ("Remove from this row", "RunPlugin(%s)" % kodi.build_url(action="addons_remove", id=addon_id))]
        kodi.add_item(name, kodi.build_url(action="addon_open", id=addon_id), False,
                      art={"thumb": (d or {}).get("thumbnail") or "DefaultAddonVideo.png", "icon": "DefaultAddonVideo.png"},
                      info={"title": name, "plot": meta},
                      props={"kind": "app", "title": name, "meta": meta, "addon": addon_id}, context=ctx)
    kodi.add_item("Edit this row", kodi.build_url(action="addons_edit"), False,
                  art={"thumb": "DefaultAddSource.png", "icon": "DefaultAddSource.png"},
                  info={"title": "Edit this row", "plot": "Add, move or remove video add-ons"},
                  props={"kind": "app", "title": "Edit this row", "meta": "Add, move or remove video add-ons on this row"})
    kodi.end_directory()


def open_addon(addon_id):
    d = details(addon_id)
    if not d:
        name = SAMPLE_NAMES.get(addon_id, addon_id)
        # Kodi asks "install?" itself and finds it in the add-on repositories it knows
        xbmc.executebuiltin("InstallAddon(%s)" % addon_id, True)
        if details(addon_id):
            _reload_row()
        else:
            kodi.notify("%s isn't installed" % name)
        return
    if not d.get("enabled"):
        kodi.jsonrpc("Addons.SetAddonEnabled", {"addonid": addon_id, "enabled": True})
        _reload_row()
    if addon_id.startswith("plugin.video."):
        xbmc.executebuiltin("ActivateWindow(Videos,plugin://%s/,return)" % addon_id)
    else:
        xbmc.executebuiltin("RunAddon(%s)" % addon_id)


def add():
    """Pick installed video add-ons to put on the row (or type an add-on ID that isn't installed yet)."""
    if not accept():
        return
    ids = load()
    choices = [a for a in installed_video_addons() if a[0] not in ids]
    labels = ["%s  [COLOR 80FFFFFF](%s)[/COLOR]" % (n, i) for i, n in choices] + ["Type an add-on ID..."]
    picks = xbmcgui.Dialog().multiselect("Add to Sports Streams", labels)
    if not picks:
        return
    new = [choices[p][0] for p in picks if p < len(choices)]
    if len(choices) in picks:
        typed = xbmcgui.Dialog().input("Add-on ID (for example plugin.video.youtube)").strip()
        if typed and typed not in ids and typed not in new:
            new.append(typed)
    if new:
        save(ids + new)
        kodi.notify("Added %d to Sports Streams" % len(new))


def remove(addon_id):
    ids = load()
    if addon_id in ids:
        ids.remove(addon_id)
        save(ids)


def move(addon_id, by):
    ids = load()
    if addon_id not in ids:
        return
    i = ids.index(addon_id)
    j = max(0, min(len(ids) - 1, i + by))
    ids.insert(j, ids.pop(i))
    save(ids)


def edit():
    """The "Edit this row" card."""
    ids = load()
    names = [(details(i) or {}).get("name") or SAMPLE_NAMES.get(i) or i for i in ids]
    options = ["Add an add-on", "Remove add-ons", "Change the order", "Put the sample add-ons back"]
    pick = xbmcgui.Dialog().select("Sports Streams", options)
    if pick == 0:
        add()
    elif pick == 1 and ids:
        gone = xbmcgui.Dialog().multiselect("Remove from Sports Streams", names)
        if gone:
            save([i for k, i in enumerate(ids) if k not in gone])
    elif pick == 2 and len(ids) > 1:
        k = xbmcgui.Dialog().select("Move which add-on?", names)
        if k >= 0:
            spots = ["%d. %s" % (n + 1, "here (no change)" if n == k else "before %s" % names[n] if n < k else "after %s" % names[n])
                     for n in range(len(ids))]
            to = xbmcgui.Dialog().select("Move %s to" % names[k], spots, preselect=k)
            if to >= 0 and to != k:
                ids.insert(to, ids.pop(k))
                save(ids)
    elif pick == 3 and xbmcgui.Dialog().yesno("Sports Streams", "Replace this row with the sample add-ons?"):
        save(list(SAMPLES))
