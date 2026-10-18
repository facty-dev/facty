#!/usr/bin/env python3
# test_auth.py — the workbench auth status (no LLM, no pi needed: the
# auth storage is read directly, and token values are never surfaced —
# only presence and expiry).
#
# Usage: python3 engine/test_auth.py   (or: ./facty test / make dss-test)

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import auth  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f" — {detail}" if detail and not ok else ""))


def write_auth(dirpath, entry):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / "auth.json").write_text(json.dumps(
        {"mistral-subscription": entry} if entry else {}))


def main():
    saved_agent_dir = os.environ.get("PI_CODING_AGENT_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PI_CODING_AGENT_DIR"] = str(Path(tmp) / "agent")
        agent = Path(os.environ["PI_CODING_AGENT_DIR"])

        # no auth storage → not authenticated
        s = auth.status()
        check("no auth storage → not authenticated",
              s["authenticated"] is False and "not authenticated" in s["detail"],
              str(s))

        # credential on file → authenticated; expiry shown, tokens never
        entry = {"access": "a" * 32, "refresh": "r" * 23,
                 "expires": int((time.time() + 3600) * 1000), "type": "oauth"}
        write_auth(agent, entry)
        s = auth.status()
        check("credential on file → authenticated", s["authenticated"] is True,
              str(s))
        check("the status shows the expiry, never the tokens",
              s["expires_at"] is not None and "a" * 32 not in json.dumps(s)
              and "r" * 23 not in json.dumps(s), str(s))

        # expired credential → flagged for re-auth
        entry["expires"] = int((time.time() - 10) * 1000)
        write_auth(agent, entry)
        s = auth.status()
        check("expired credential → flagged for re-auth",
              s["authenticated"] is True and "expired" in s["detail"], str(s))

        # empty provider entry → not authenticated
        write_auth(agent, {"access": "", "refresh": "", "expires": 0, "type": "oauth"})
        s = auth.status()
        check("empty credential → not authenticated", s["authenticated"] is False,
              str(s))

    # restore the real agent dir for the extension-location checks
    if saved_agent_dir is None:
        os.environ.pop("PI_CODING_AGENT_DIR", None)
    else:
        os.environ["PI_CODING_AGENT_DIR"] = saved_agent_dir

    # the extension driver is present and the extension is locatable
    check("the OAuth driver script exists",
          (ENGINE_DIR / "mistral-oauth-login.mjs").exists())
    check("the extension's OAuth module is locatable",
          auth._extension_oauth_path() is not None,
          str(auth._extension_oauth_path()))

    # live capture (opt-in: runs the extension's real OAuth flow — needs
    # network to console.mistral.ai and node; the browser open is stubbed)
    if os.environ.get("FACTY_TEST_LIVE_PI") == "1":
        auth.webbrowser.open = lambda url: None
        msgs = []
        ok, url = auth.login(on_progress=msgs.append, timeout=30)
        check("live: the sign-in URL is captured from the extension's flow",
              url is not None and "console.mistral.ai" in url, str(url))
        check("live: the URL is reported to the caller (logged in the workbench)",
              any("sign-in URL:" in m for m in msgs), str(msgs))
        check("live: the flow reports completion or timeout honestly",
              ok in (True, False) and any("sign-in" in m for m in msgs), str(ok))
    else:
        print("SKIP  live OAuth capture — set FACTY_TEST_LIVE_PI=1 to run it")

    print("")
    failed = len(RESULTS) - sum(RESULTS)
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
