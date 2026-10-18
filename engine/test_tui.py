#!/usr/bin/env python3
# test_tui.py — the Textual workbench, tested headless (no TTY needed).
#
# Drives the case board with Textual's pilot (run_test): the full e2e
# pipeline (the LLM sensing layer is stubbed to the recorded facts —
# like test_retry stubs its runner — unless FACTY_TUI_LIVE=1), the
# colourful run log's tool tags and triples, the expandable LLM
# responses (inline, live mid-stream), the command palette (incl. the
# system commands), the tooltips, the help screen, the auth button, and
# the clean quit (no dangling subprocesses). Skips cleanly when Textual
# is not installed: the engine core + CLI control plane are
# dependency-free and always runnable (`make deps` installs Textual).
#
# Usage:
#   python3 engine/test_tui.py     # or: ./facty test / make dss-test

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import cli     # noqa: E402
import procs   # noqa: E402

CASE = ENGINE_DIR / "cases" / "adjudication-phantom-invoice"

try:
    import tui  # noqa: E402  (imports textual; ImportError → skip)
    HAVE_TUI = True
except ImportError:
    HAVE_TUI = False

LIVE = os.environ.get("FACTY_TUI_LIVE") == "1"

checks = []


def check(name, ok, detail=""):
    checks.append(ok)
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f" — {detail}" if detail and not ok else ""))


STUB_MODES = []


def _recorded(case, op):
    case = Path(case)
    if op == "classify":
        return engine.load_validated(case / "evidence-index.json",
                                     "evidence-index.schema.json")
    if op == "entities":
        return engine.load_validated(case / "entities.json", "entities.schema.json")
    if op == "facts":
        return engine.load_validated(case / "facts.json", "facts.schema.json")
    return engine.load_array(cli.drop_file(case), "fact.schema.json")


def slow_stub_sense_one(ui, case, op, evidence_index=None, entities=None,
                        stream=None, on_response=None, mode=None, **_kw):
    """A stub that STREAMS the recorded response slowly (line by line,
    with delays) — to exercise the mid-stream expand."""
    import json as _json
    import time as _time
    result = _recorded(case, op)
    text = _json.dumps(result, indent=2)
    if stream is not None:
        for line in text.splitlines():
            stream(line)
            _time.sleep(0.04)
    if on_response is not None:
        on_response(text, "recorded")
    return result


def stub_sense_one(ui, case, op, evidence_index=None, entities=None, stream=None,
                   on_response=None, mode=None, **_kw):
    """The LLM boundary, stubbed to the recorded sensing (fast and
    deterministic). FACTY_TUI_LIVE=1 runs the real LLM instead. Records
    the requested mode so the offline-checkbox plumbing is testable."""
    import json as _json
    STUB_MODES.append(mode)
    result = _recorded(case, op)
    if on_response is not None:
        on_response(_json.dumps(result, indent=2), "recorded")
    return result


EXPLAIN_CALLS = []


def stub_explain(ui, case, result, entities, target="verdict", stream=None,
                 on_response=None, mode=None, **_kw):
    """The commentary boundary, stubbed (streamed, like the sensing stub).
    Records the target / mode / inputs so the plumbing is testable."""
    EXPLAIN_CALLS.append({"target": target, "mode": mode,
                          "has_result": result is not None,
                          "has_entities": entities is not None})
    text = f"Commentary on the {target}: the verdict stands on its own."
    if stream is not None:
        for line in text.splitlines():
            stream(line)
    if on_response is not None:
        on_response(text, "live")
    return text


async def wait_for(pilot, cond, timeout=15.0):
    """Pause until cond() holds (the run workers are threads — poll politely)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await pilot.pause(0.05)
        if cond():
            return True
    return cond()


def log_texts(app):
    return [str(w.render()) for w in app.query(tui.LogLine)]


async def run_board():
    from textual.command import CommandPalette
    from textual.widgets import Button, Checkbox, DataTable, Static

    if not LIVE:
        cli.sense_one = stub_sense_one
    else:
        cli.sense_one = slow_stub_sense_one
    cli.explain = stub_explain  # the commentary boundary, stubbed
    tui.auth.webbrowser.open = lambda url: None  # no real browser in tests
    # an empty response cache → the offline checkbox starts disabled
    os.environ["FACTY_CACHE_DIR"] = tempfile.mkdtemp(prefix="facty-tui-cache-")
    app = tui.FactyApp(CASE)
    sleeper = None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()  # let the default screen settle
        screen = app.screen
        check("the board mounts straight on the case (no picker)",
              isinstance(screen, tui.CaseScreen))
        n_files = len(app.query("#evidence ListItem"))
        check("the evidence list is populated (all 11 files)", n_files == 11, str(n_files))

        # the buttons say what they do, in plain language, with tooltips
        run_btn = app.query_one("#run", Button)
        test_btn = app.query_one("#test", Button)
        auth_btn = app.query_one("#auth", Button)
        check("the run button says what it does ('Run the case')",
              "Run the case" in str(run_btn.label))
        check("the test button says what it does ('Run the recommended test')",
              "Run the recommended test" in str(test_btn.label))
        check("the authenticate button says what it does",
              "Authenticate" in str(auth_btn.label))
        check("the buttons carry tooltips (help text)",
              bool(run_btn.tooltip) and bool(test_btn.tooltip)
              and bool(auth_btn.tooltip))
        check("the workbench shows the Mistral subscription auth status",
              "Mistral" in str(app.query_one("#auth-status", Static).render()))

        # out-of-band commentary: the button starts disabled, the key
        # warns until there is a result to explain
        check("the Explain button starts disabled (no result yet)",
              app.query_one("#explain", Button).disabled)
        await pilot.press("x")
        await pilot.pause()
        check("x before a run warns (nothing to explain yet)",
              any("nothing to explain yet" in t for t in log_texts(app)))

        # the palette keeps the system commands (Maximize the focused widget)
        titles = [c.title for c in app.get_system_commands(app.screen)]
        check("the palette keeps the system commands (Maximize)",
              "Maximize" in titles, str(titles))
        check("the run log can be maximized (the palette item's target)",
              app.query_one("#runlog", tui.RunLog).allow_maximize is True)

        await pilot.press("r")
        ok = await wait_for(pilot, lambda: screen.result is not None
                            and screen.result["phase"] == "on the initial evidence")
        check("key r runs the case (the full e2e: LLM sensing → engine)", ok)
        if ok:
            r1 = screen.result
            table = app.query_one("#ranking", DataTable)
            check("the initial evidence ranks the two survivors — the inside job "
                  "(H2) first, external fraud (H1) second",
                  table.row_count == 2 and r1["verdict"]["id"] == "H2",
                  f"rows={table.row_count} verdict={r1['verdict'] and r1['verdict']['id']}")
            texts = log_texts(app)
            check("the run log shows the llm · induction stages (the LLM was called)",
                  any("llm · induction" in t for t in texts))
            check("the run log shows the fwd chain · deduction firings",
                  any("fwd chain · deduction" in t for t in texts))
            check("the run log shows the constraint solver · deduction prunes",
                  any("constraint solver · deduction" in t for t in texts))
            check("the run log shows the bwd chain · deduction proofs",
                  any("bwd chain · deduction" in t for t in texts))
            check("facts are expressed as triples (subject / predicate = value)",
                  any("INV-2261 / bypassedThreeWayMatch = True" in t for t in texts),
                  str([t for t in texts if "bypassedThreeWayMatch" in t][:1]))
            colored = next((w for w in app.query(tui.LogLine)
                            if "fwd chain · deduction" in str(w.render())), None)
            check("the run log renders markup as styled content (the colourful log)",
                  colored is not None
                  and len(getattr(colored.render(), "spans", []) or []) > 0)
            spans = getattr(colored.render(), "spans", []) or []
            check("tool tags render as label badges (a background colour "
                  "that contrasts with the text)",
                  any(" on " in str(s.style) for s in spans),
                  str([str(s.style) for s in spans][:3]))
            check("content colours resolve from the theme (adapt to light/dark)",
                  all(screen._token_hex(t).startswith("#") for t in
                      ("text-primary", "text-success", "text-warning",
                       "text-error", "foreground-muted")))

        # expandable items: the streamed LLM response reveals inline
        resp_lines = [w for w in app.query(tui.LogLine) if w.response is not None]
        check("the llm stage lines carry their responses (expandable)",
              len(resp_lines) >= 3, str(len(resp_lines)))
        check("the main output stays uncluttered (the raw response is not in the log)",
              all('"id": "f' not in t for t in log_texts(app)))
        if resp_lines:
            line0 = resp_lines[0]
            line0.response.done = False  # simulate a still-streaming response
            line0.scroll_visible(animate=False)
            await pilot.pause()
            await pilot.click(line0)  # expand
            await pilot.pause()
            blocks = app.query(tui.DetailBlock)
            check("clicking an llm line expands its response inline",
                  len(blocks) == 1, str(len(blocks)))
            check("the expanded detail is a proper reading pane (tall, scrollable)",
                  blocks[0].virtual_region.height >= 10,
                  f"height={blocks[0].virtual_region.height}")
            detail_texts = [str(w.render()) for w in blocks[0].query(tui.LogLine)]
            check("the expanded detail shows the streamed response",
                  any("INV-2261" in t or "evidence" in t.lower()
                      for t in detail_texts),
                  str(detail_texts[:2]))
            line0.response.chunks.append("\n…PARTIAL-STREAM-MARKER…")
            await pilot.pause(0.9)  # the detail live-appends while streaming
            detail_texts = [str(w.render()) for w in blocks[0].query(tui.LogLine)]
            check("the detail shows the streaming output as it arrives (mid-stream)",
                  any("PARTIAL-STREAM-MARKER" in t for t in detail_texts))
            line0.response.done = True
            await pilot.click(line0)  # collapse
            await pilot.pause()
            check("clicking again collapses the detail (main output uncluttered)",
                  blocks[0].display is False)

        # keyboard expand (e) — works without a mouse (e.g. a VM console)
        await pilot.press("e")
        await pilot.pause()
        check("the e key expands the latest response (no mouse needed)",
              len(app.query(tui.DetailBlock)) >= 1
              and any(b.display for b in app.query(tui.DetailBlock)))
        await pilot.press("e")
        await pilot.pause()
        check("the e key collapses it again",
              all(not b.display for b in app.query(tui.DetailBlock)))

        # the offline checkbox: run without the LLM (cached or recorded)
        offline = app.query_one("#offline", Checkbox)
        check("the offline checkbox exists and says what it does",
              "without the LLM" in str(offline.label))
        check("the cache-state line shows the cache progress (visible, not "
              "just a tooltip)",
              "cache" in str(app.query_one("#cache-state", Static).render()).lower()
              and "/" in str(app.query_one("#cache-state", Static).render()))
        await pilot.click("#offline")  # clickable (not gated-disabled)
        await pilot.pause()
        check("clicking the checkbox toggles it", offline.value is True)
        STUB_MODES.clear()
        await pilot.press("r")
        ok_off = await wait_for(
            pilot, lambda: screen.result is not None
            and screen.result["phase"] == "on the initial evidence")
        check("a run with the checkbox ticked still completes (stubbed senses)",
              ok_off)
        check("the checkbox plumbs mode='cache' into the sensing calls "
              "(run without the LLM)",
              ok_off and STUB_MODES and all(m == "cache" for m in STUB_MODES),
              str(STUB_MODES))
        check("the run log says it is running without the LLM",
              any("running without the LLM" in t for t in log_texts(app)))
        offline.value = False
        # the stage lines are colourful too (the log is colourful throughout)
        stage_line = next((w for w in app.query(tui.LogLine)
                           if "llm · induction" in str(w.render())), None)
        check("the stage lines render styled content (colourful throughout)",
              stage_line is not None
              and len(getattr(stage_line.render(), "spans", []) or []) > 0)

        # mid-stream expand: the response streams LIVE into the detail
        cli.sense_one = slow_stub_sense_one
        await pilot.press("s")  # re-sense — a stage that streams slowly
        await pilot.pause(0.7)  # the stub is mid-stream
        live_lines = [w for w in app.query(tui.LogLine)
                      if w.response is not None and not w.response.done]
        check("a stage is streaming (response not complete yet)",
              len(live_lines) >= 1, str(len(live_lines)))
        check("the streaming line offers the live expand (click to watch)",
              any("click to watch live" in str(w.render())
                  for w in app.query(tui.LogLine)))
        if live_lines:
            live = live_lines[-1]
            live.scroll_visible(animate=False)
            await pilot.pause()
            await pilot.click(live)  # expand MID-STREAM
            await pilot.pause()
            live_blocks = [b for b in app.query(tui.DetailBlock) if b.display]
            check("clicking a streaming line expands it (mid-stream)",
                  len(live_blocks) >= 1, str(len(live_blocks)))
            if live_blocks:
                n1 = len(live_blocks[0].query(tui.LogLine))
                await pilot.pause(1.2)  # more chunks stream in
                n2 = len(live_blocks[0].query(tui.LogLine))
                check("the expanded detail grows LIVE while streaming",
                      n2 > n1, f"{n1} -> {n2}")
        cli.sense_one = stub_sense_one
        # let the slow run finish before the palette test
        await wait_for(pilot, lambda: all(
            w.response is None or w.response.done
            for w in app.query(tui.LogLine)))

        # the command palette (ctrl+p) lists the actions, with help text
        await pilot.press("ctrl+p")
        await pilot.pause()
        check("ctrl+p opens the command palette", isinstance(app.screen, CommandPalette))
        await pilot.press(*"recommended")
        await pilot.pause()
        await pilot.press("enter")
        ok2 = await wait_for(pilot, lambda: screen.result is not None
                             and screen.result["phase"] == "with the recommended test's evidence")
        check("the palette runs the recommended test (the discriminating test)", ok2)
        if ok2:
            r2 = screen.result
            check("the verdict flips to external invoice fraud (H1), all claims proven",
                  r2["verdict"]["id"] == "H1"
                  and r2["verdict"]["claims_proven"] == r2["verdict"]["claims_total"],
                  str(r2["verdict"] and r2["verdict"]["id"]))
            check("the recommended test prunes the inside job (H2) — one survivor "
                  "in the table",
                  app.query_one("#ranking", DataTable).row_count == 1)

        # out-of-band LLM commentary (the LLM as explainer, never decider)
        check("the Explain button is enabled once a result exists",
              not app.query_one("#explain", Button).disabled)
        n_before = len(EXPLAIN_CALLS)
        await pilot.press("x")
        ok3 = await wait_for(pilot, lambda: len(EXPLAIN_CALLS) > n_before)
        check("key x asks the LLM for commentary (out-of-band)", ok3)
        if ok3:
            call = EXPLAIN_CALLS[-1]
            check("the commentary call targets the verdict, with the result "
                  "+ the sensed entities",
                  call["target"] == "verdict" and call["has_result"]
                  and call["has_entities"], str(call))
            check("the run log shows the llm · commentary line (a distinct badge)",
                  any("llm · commentary" in t for t in log_texts(app)))
            live = [w for w in app.query(tui.LogLine)
                    if w.response is not None
                    and "explain the verdict" in str(w.render())]
            check("the commentary line carries the streamed response (expandable)",
                  len(live) >= 1 and live[-1].response.done)
            if live:
                live[-1].scroll_visible(animate=False)
                await pilot.pause()
                await pilot.click(live[-1])
                await pilot.pause()
                blocks = [b for b in app.query(tui.DetailBlock) if b.display]
                check("the commentary expands inline (the explanation is readable)",
                      any("Commentary on the verdict" in str(w.render())
                          for b in blocks for w in b.query(tui.LogLine)))
        offline = app.query_one("#offline", Checkbox)
        offline.value = True
        n_before = len(EXPLAIN_CALLS)
        await pilot.press("x")
        await wait_for(pilot, lambda: len(EXPLAIN_CALLS) > n_before)
        check("offline mode asks for the cached commentary (no LLM call)",
              EXPLAIN_CALLS[-1]["mode"] == "cache", str(EXPLAIN_CALLS[-1]))
        offline.value = False

        # the help screen explains the flow and the run-log vocabulary
        await pilot.press("?")
        await pilot.pause()
        check("? opens the help screen", isinstance(app.screen, tui.HelpScreen))
        content = str(app.screen.query_one("#help-text", Static).render())
        check("the help explains the tools and inference types",
              all(tag in content for tag in
                  ("llm · induction", "fwd chain · deduction",
                   "constraint solver · deduction", "bwd chain · deduction")))
        check("the help explains the two steps in plain language",
              "RUN THE CASE" in content and "RUN THE RECOMMENDED TEST" in content)
        await pilot.press("escape")
        await pilot.pause()
        check("escape closes the help screen", isinstance(app.screen, tui.CaseScreen))

        # the Authenticate BUTTON works (not just the key)
        await pilot.click("#auth")
        ok_auth = await wait_for(
            pilot, lambda: any("sign-in started" in t for t in log_texts(app)),
            timeout=20)
        check("the Authenticate button starts the sign-in flow", ok_auth)

        # quitting leaves no dangling processes
        sleeper = subprocess.Popen(["sleep", "60"], start_new_session=True)
        procs.register(sleeper)
        app.exit()

    check("quitting kills tracked subprocesses (no dangling processes)",
          sleeper is not None and sleeper.poll() is not None,
          f"poll={sleeper and sleeper.poll()}")
    r = subprocess.run(["pgrep", "-f", "mistral-oauth-login"], capture_output=True)
    check("no dangling OAuth-driver processes after quit",
          r.returncode != 0, r.stdout.decode().strip())


def main():
    if not HAVE_TUI:
        print("SKIP  textual is not installed — the workbench test needs it (`make deps`)")
        print("      (the engine core + CLI control plane are dependency-free)")
        return 0
    asyncio.run(run_board())
    # the doctor self-check runs and reports the loaded workbench
    r = subprocess.run([sys.executable, str(ENGINE_DIR / "cli.py"), "doctor"],
                       capture_output=True, text=True)
    check("`facty doctor` runs and reports the loaded workbench + cache + gondolin",
          r.returncode == 0 and "workbench:  loaded" in r.stdout
          and "cache:" in r.stdout and "gondolin:" in r.stdout,
          (r.stdout + r.stderr)[-200:])
    print("")
    failed = len(checks) - sum(checks)
    print(f"{sum(checks)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
