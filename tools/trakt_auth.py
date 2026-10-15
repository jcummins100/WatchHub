#!/usr/bin/env python3
"""Sign this computer in to Trakt (device code), and keep the sign-in fresh.

    python3 tools/trakt_auth.py --client-id <Trakt app Client ID>   # one time: shows a code for trakt.tv/activate
    python3 tools/trakt_auth.py --refresh                           # renew (the nightly sync calls this itself)

The token is stored in ~/.config/watchhub/trakt_token.json (readable by this user only, never in git).
This is a separate Trakt sign-in from the Shields': Trakt replaces refresh tokens on every renewal, so
devices must not share one.
"""
import argparse
import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://api.trakt.tv/"
TOKEN_FILE = os.path.expanduser("~/.config/watchhub/trakt_token.json")
HEADERS = {"Content-Type": "application/json", "trakt-api-version": "2", "User-Agent": "WatchHub sync"}


def _post(path, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {}


def save(tok):
    os.makedirs(os.path.dirname(TOKEN_FILE), mode=0o700, exist_ok=True)
    tmp = "%s.%d.tmp" % (TOKEN_FILE, os.getpid())
    if os.path.exists(tmp):
        os.remove(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # fresh file, this user only
    with os.fdopen(fd, "w") as fh:
        json.dump(tok, fh)
    os.replace(tmp, TOKEN_FILE)


def load():
    with open(TOKEN_FILE) as fh:
        return json.load(fh)


def device_login(client_id, client_secret=""):
    status, code = _post("oauth/device/code", {"client_id": client_id})
    if status != 200 or "device_code" not in code:
        sys.exit("Trakt refused the device-code request (HTTP %s) - check the Client ID." % status)
    print("\nOn your phone or computer go to  %s  and enter the code:  %s\n" % (code["verification_url"], code["user_code"]), flush=True)
    deadline = time.time() + int(code.get("expires_in", 600))
    body = {"code": code["device_code"], "client_id": client_id}
    if client_secret:
        body["client_secret"] = client_secret
    while time.time() < deadline:
        time.sleep(int(code.get("interval", 5)))
        status, tok = _post("oauth/device/token", body)
        if status == 200 and tok.get("access_token"):
            tok.update(client_id=client_id, client_secret=client_secret, expires_at=int(time.time()) + int(tok.get("expires_in", 7776000)))
            save(tok)
            print("Signed in. Token saved to %s" % TOKEN_FILE)
            return tok
        if status in (404, 409, 410, 418):  # invalid / already used / expired / denied
            sys.exit("Trakt sign-in failed (HTTP %s)." % status)
    sys.exit("The code expired before it was approved; run this again.")


def refresh(force=False):
    """Renew if expiring within 7 days. Serialised with a lock: Trakt replaces the refresh token on every
    renewal, so two renewals at once would leave one of them holding a dead token."""
    os.makedirs(os.path.dirname(TOKEN_FILE), mode=0o700, exist_ok=True)
    with open(TOKEN_FILE + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _refresh(force)


def _refresh(force=False):
    tok = load()
    if not force and tok.get("expires_at", 0) - time.time() > 7 * 86400:
        return tok
    body = {"refresh_token": tok["refresh_token"], "client_id": tok["client_id"], "grant_type": "refresh_token",
            "redirect_uri": "urn:ietf:wg:oauth:2.0:oob"}
    if tok.get("client_secret"):
        body["client_secret"] = tok["client_secret"]
    status, new = _post("oauth/token", body)
    if status != 200 or not new.get("access_token"):
        sys.exit("Trakt token refresh failed (HTTP %s) - run trakt_auth.py --client-id ... again." % status)
    new.update(client_id=tok["client_id"], client_secret=tok.get("client_secret", ""),
               expires_at=int(time.time()) + int(new.get("expires_in", 7776000)))
    save(new)
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", help="Trakt app Client ID (one-time sign-in)")
    ap.add_argument("--client-secret", default="", help="only for older Trakt apps that have one")
    ap.add_argument("--refresh", action="store_true", help="renew the saved token if it expires within 7 days")
    a = ap.parse_args()
    if a.refresh:
        tok = refresh()
        print("Token valid until %s" % time.strftime("%Y-%m-%d", time.localtime(tok["expires_at"])))
    elif a.client_id:
        device_login(a.client_id, a.client_secret)
    else:
        ap.error("give --client-id for the first sign-in, or --refresh")


if __name__ == "__main__":
    main()
