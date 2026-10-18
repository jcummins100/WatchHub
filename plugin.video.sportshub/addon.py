"""Sports Hub entry point. Kodi calls this with sys.argv = [base_url, handle, '?query']."""
import os
import sys

# Make `resources.lib` importable regardless of how Kodi set up sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from resources.lib import kodi, ui  # noqa: E402


def main():
    try:
        params = kodi.parse_params()
        kodi.CALL = " ".join(str(params[k]) for k in ("action", "row", "cat", "league", "name", "svc") if params.get(k)) or "root"
        ui.dispatch(params)
    except Exception:  # surface errors in the Kodi log instead of a silent empty list
        import traceback

        kodi.log(traceback.format_exc())
        kodi.notify("Error - see kodi.log")
        kodi.end_directory(succeeded=False)
        raise


if __name__ == "__main__":
    main()
