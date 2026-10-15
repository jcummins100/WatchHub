#!/usr/bin/env bash
# Build the add-on zip and push it to Kodi on an NVIDIA Shield over adb.
#
#   tools/deploy.sh <shield-ip>          # push zip to /sdcard/Download, install via Kodi UI once
#   tools/deploy.sh <shield-ip> --live   # overwrite the installed add-on files directly (needs Kodi
#                                        # add-on already installed once; restarts nothing)
#   tools/deploy.sh <shield-ip> --log    # tail Kodi's log for this add-on
#
# Enable Developer options -> Network debugging on the Shield first.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
ADDON_ID="plugin.video.sportshub"
IP="${1:?usage: deploy.sh <shield-ip> [--live|--log]}"
MODE="${2:-}"
KODI_PKG="${KODI_PKG:-org.xbmc.kodi}"   # use org.xbmc.kodi for nightlies/alpha
KODI_HOME="/sdcard/Android/data/${KODI_PKG}/files/.kodi"

adb connect "${IP}:5555" >/dev/null
adb -s "${IP}:5555" wait-for-device

case "$MODE" in
  --log)
    adb -s "${IP}:5555" shell "tail -f ${KODI_HOME}/temp/kodi.log" | grep --line-buffered "${ADDON_ID}\|EXCEPTION\|Traceback\|Error" ;;
  --live)
    DEST="${KODI_HOME}/addons/${ADDON_ID}"
    echo "Syncing source to ${DEST}"
    adb -s "${IP}:5555" shell "mkdir -p ${DEST}"
    adb -s "${IP}:5555" push --sync "${HERE}/${ADDON_ID}/." "${DEST}/"
    # Kodi caches compiled .py; clearing __pycache__ is enough for the next launch to pick up changes.
    adb -s "${IP}:5555" shell "find ${DEST} -name __pycache__ -type d -exec rm -rf {} +" || true
    echo "Done. Re-open the add-on in Kodi (or run: adb shell am force-stop ${KODI_PKG} to restart)." ;;
  *)
    ZIP="$(python3 "${HERE}/tools/build_zip.py")"
    adb -s "${IP}:5555" push "${ZIP}" /sdcard/Download/
    echo "Pushed $(basename "${ZIP}") to /sdcard/Download on the Shield."
    echo "In Kodi: Settings > Add-ons > Install from zip file > External storage > Download > $(basename "${ZIP}")"
    echo "(First time only: Settings > System > Add-ons > enable 'Unknown sources'.)" ;;
esac
