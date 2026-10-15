"""Data sources. Each exposes functions returning plain dicts ("programmes"):

{
  "source":   "pluto" | "plex" | "roku" | "samsung" | "pvr" | "sportsdb" | "youtube",
  "channel_id": str,
  "channel":  str,           # display name of the channel
  "title":    str,           # programme / event title
  "start":    int,           # epoch seconds (0 if unknown / always-on)
  "end":      int,           # epoch seconds (0 if unknown)
  "sport":    str | None,
  "logo":     str | None,
  "art":      str | None,
  "plot":     str,
  "playable": bool,          # can we tune to it from this device?
  "play":     dict,          # args understood by launcher.play()
}
"""
