#!/usr/bin/env python3
# auth.py — Mistral subscription authentication for the workbench.
#
# The workbench authenticates with the user's own Mistral subscription
# THROUGH the pi-mistral-subscription extension: a small node driver
# (engine/mistral-oauth-login.mjs) imports the extension's own
# mistral-oauth module and runs its login flow — PKCE, the sign-in
# process, polling, the token exchange. The sign-in URL comes out on the
# driver's stdout (logged for the user and opened in the default
# browser); the browser sign-in completes outside the terminal; the
# resulting credential is stored in pi's normal auth storage
# (~/.pi/agent/auth.json) — the same place the sensing path
# (`pi -p --provider mistral-subscription`) reads it, so the extension
# stays behind the scenes. (pi's own /login can't be driven from a pipe:
# its TUI renders the URL to /dev/tty, not stdout.) Token values are
# never surfaced — only presence and expiry.

import hashlib
import json
import os
import selectors
import subprocess
import time
import webbrowser
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(ENGINE_DIR))
import procs  # noqa: E402  (subprocess registry — no dangling processes)

PROVIDER = "mistral-subscription"


def agent_dir():
    """pi's agent dir (PI_CODING_AGENT_DIR overrides — the gondolin VM
    bakes extensions at /opt/pi-agent)."""
    return Path(os.environ.get("PI_CODING_AGENT_DIR")
                or Path.home() / ".pi" / "agent")


def auth_path():
    return agent_dir() / "auth.json"


def _entry(provider=PROVIDER):
    try:
        data = json.loads(auth_path().read_text())
    except (OSError, ValueError):
        return None
    return data.get(provider)


def _fingerprint(entry):
    """A fingerprint of the stored credential — compared before/after a
    sign-in to detect completion. Never returns token values."""
    if not entry or not entry.get("access"):
        return None
    return hashlib.sha256(
        f"{entry.get('access')}|{entry.get('expires')}".encode()).hexdigest()


def status(provider=PROVIDER):
    """Auth status for a provider (default: the Mistral subscription),
    without token values: {authenticated, expires_at, detail}. Per-
    provider status is the seam for the future providers config
    (docs/PROVIDERS.md)."""
    entry = _entry(provider)
    if not entry or not entry.get("access"):
        return {"authenticated": False, "expires_at": None,
                "detail": "not authenticated — sign in to configure it"}
    expires_at = None
    remaining = None
    try:
        exp = float(entry.get("expires"))
        if exp > 1e12:  # epoch milliseconds
            exp /= 1000.0
        expires_at = time.strftime("%Y-%m-%d %H:%M", time.localtime(exp))
        remaining = exp - time.time()
    except (TypeError, ValueError):
        pass
    if remaining is not None and remaining <= 0:
        return {"authenticated": True, "expires_at": expires_at,
                "detail": f"credential expired ({expires_at}) — sign in again to refresh"}
    return {"authenticated": True, "expires_at": expires_at,
            "detail": f"authenticated · credential on file (expires {expires_at})"}


def _extension_oauth_path():
    """The pi-mistral-subscription extension's OAuth module (pi installs
    git extensions under <agent-dir>/git/github.com/<owner>/<repo>)."""
    for cand in sorted(agent_dir().glob(
            "git/github.com/*/pi-mistral-subscription/src/mistral-oauth.ts")):
        return cand
    return None


def _store_credential(creds):
    """Write the credential into pi's auth storage — the same place the
    extension stores it, where the sensing path reads it."""
    path = auth_path()
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except ValueError:
            data = {}
    data[PROVIDER] = {"access": creds.get("access"),
                      "refresh": creds.get("refresh"),
                      "expires": creds.get("expires"),
                      "type": "oauth"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def login(on_progress=None, timeout=300):
    """Run the extension's own OAuth login behind the scenes (a small
    node driver imports the extension's mistral-oauth module and runs
    its login flow). The sign-in URL is captured from the driver's
    stdout, logged for the user, and opened in the default browser.

    Returns (ok, url): ok=True when the credential landed in pi's auth
    storage; url is the sign-in URL."""
    oauth_ts = _extension_oauth_path()
    if oauth_ts is None:
        if on_progress:
            on_progress("the pi-mistral-subscription extension is not installed — "
                        "pi install https://github.com/5omeOtherGuy/pi-mistral-subscription")
        return False, None
    driver = ENGINE_DIR / "mistral-oauth-login.mjs"
    try:
        proc = subprocess.Popen(
            ["node", "--experimental-strip-types", str(driver), str(oauth_ts)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True)
        procs.register(proc)
    except FileNotFoundError:
        if on_progress:
            on_progress("node is not installed — the sign-in driver needs node ≥ 22.19")
        return False, None
    url = [None]
    try:
        if on_progress:
            on_progress("sign-in started — complete the browser sign-in "
                        "(the pi-mistral-subscription extension's OAuth)")
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)
        buf = ""
        deadline = time.time() + timeout

        def handle(line):
            line = line.strip()
            if line.startswith("URL:"):
                url[0] = line[4:]
                if on_progress:
                    on_progress(f"sign-in URL: {url[0]} — complete the sign-in "
                                "in your browser")
                try:
                    webbrowser.open(url[0])
                    if on_progress:
                        on_progress("browser opened automatically")
                except Exception:
                    pass
            elif line.startswith("PROGRESS:"):
                if on_progress:
                    on_progress(line[len("PROGRESS:"):])
            elif line.startswith("CRED:"):
                _store_credential(json.loads(line[len("CRED:"):]))
                if on_progress:
                    on_progress("credential stored in pi's auth storage — authenticated")
                return True
            elif line.startswith("ERROR:"):
                if on_progress:
                    on_progress(f"sign-in failed — {line[len('ERROR:'):]}")
                return "error"
            return False

        while time.time() < deadline:
            if sel.select(0.5):
                chunk = os.read(proc.stdout.fileno(), 4096)
                if not chunk:
                    break
                buf += chunk.decode("utf-8", "replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    outcome = handle(line)
                    if outcome is True:
                        proc.wait(timeout=10)
                        return True, url[0]
                    if outcome == "error":
                        proc.wait(timeout=5)
                        return False, url[0]
            elif proc.poll() is not None:
                break
        if on_progress:
            on_progress("sign-in did not complete in time — try again (a)")
        return False, url[0]
    finally:
        procs.unregister(proc)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
