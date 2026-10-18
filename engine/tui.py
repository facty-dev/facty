#!/usr/bin/env python3
# tui.py — the Facty workbench: the Textual primary interface.
#
# Bare `./facty` opens this: a case picker, then an interactive case
# board over the deterministic engine. Running a case is the full e2e
# pipeline: the LLM senses the evidence into facts (induction), then the
# engine derives, prunes, proves, and decides (deduction). The run log
# is the colourful log: every line is tagged with the tool and the
# inference type, content is colour-coded by event, and facts are
# expressed as triples (subject / predicate = value). Lines that carry
# more detail — a streamed LLM response — are EXPANDABLE: click the line
# to reveal the response inline (collapsed by default, so the main
# output stays uncluttered; it live-appends while streaming). Raw
# responses are also cached (demos stay live by default;
# FACTY_SENSE=cache replays them offline). The workbench also
# authenticates the user's Mistral subscription through the
# pi-mistral-subscription extension (browser OAuth), and quitting kills
# every tracked subprocess — no dangling LLM/auth processes.
#
# Textual is the repo's ONE optional dependency (PO, 2026-10-17 — the
# stdlib-only rule is retired; see docs/adr/0004-cli-primary-interface.md
# and requirements.txt). The engine core and the CLI control plane stay
# dependency-free so they run in the gondolin VM snapshot (textual is
# baked into the image); this module is imported lazily by `facty` /
# `facty tui` and degrades to a clear message when Textual is not
# installed (`make deps`).
#
# Tested headless (no TTY): engine/test_tui.py drives the board with
# Textual's pilot (run_test).

import sys
import time
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import cli     # noqa: E402  (control-plane helpers: sense_one, drop_file, …)
import auth    # noqa: E402  (Mistral subscription sign-in via the extension)
import procs   # noqa: E402  (subprocess registry — no dangling processes)

from textual import on, work
from textual.app import App, ComposeResult
from textual.command import DiscoveryHit, Hit, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (Button, Checkbox, DataTable, Footer, Header,
                             Label, ListItem, ListView, Static, TextArea,
                             Tooltip)

HELP_TEXT = """\
Facty — how a case runs

1 · RUN THE CASE
   The LLM (the senses) reads the messy evidence into clean facts
   (induction). The engine then chains rules (deduction), prunes
   impossible explanations (the constraint solver), proves claims
   (the backward chain), and delivers a ranked verdict with a full
   reasoning trace.

2 · RUN THE RECOMMENDED TEST
   The engine names the single check that best discriminates the top
   explanations (the recommended test). Collect that evidence — the
   LLM senses it into new facts — and run again. The verdict updates.

THE RUN LOG — tools and inference types

  llm · induction                the senses: messy evidence → facts;
                                 proposes hypotheses + tests
  fwd chain · deduction          rules fire: derive facts, open
                                 questions, raise the hypothesis space
  constraint solver · deduction  prune impossible explanations,
                                 support the survivors
  bwd chain · deduction          prove claims, rank, deliver the verdict
  llm · commentary               out-of-band LLM explanations (entities,
                                 ranking, verdict) — presentation only;
                                 the verdict itself is deterministic

  click the LIVE line — the last line while the LLM streams (or press
  e) — to EXPAND its streamed response inline; it live-appends while
  streaming (collapsed by default; raw responses are also cached —
  FACTY_SENSE=cache replays them offline)

FACTS ARE TRIPLES

  subject / predicate = value
  e.g.  INV-2261 / bypassedThreeWayMatch = true

KEYS

  r  run the case · d  run the recommended test · s  re-sense facts (LLM)
  a  authenticate with your Mistral subscription (browser sign-in)
  e  expand/collapse the latest streamed response (keyboard — no mouse)
  x  explain the verdict (LLM commentary — out-of-band, cached)
  enter  read an evidence file · ?  this help · esc  back
  ctrl+p  command palette

  ☑ run without the LLM — never calls the LLM: steps with a cached
    response replay it; the rest use the recorded sensing. The cache
    line under the checkbox shows how many steps are cached (N/M).
"""


class HelpScreen(ModalScreen):
    """The help screen: the flow, the run-log vocabulary, the triples."""

    BINDINGS = [("escape", "close", "Close"), ("?", "close", "Close")]

    def compose(self) -> ComposeResult:
        yield VerticalScroll(Static(HELP_TEXT, id="help-text"))
        yield Button("Close", id="close")

    @on(Button.Pressed, "#close")
    def _close(self):
        self.dismiss()

    def action_close(self):
        self.dismiss()


class EvidenceScreen(ModalScreen):
    """Read-only evidence viewer (Enter on a file in the board)."""

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(f"{self.path.name}  ({self.path.stat().st_size} bytes)", classes="title"),
            TextArea(self.path.read_text(), read_only=True),
            Button("Close", id="close"),
        )

    @on(Button.Pressed, "#close")
    def _close(self):
        self.dismiss()

    def action_close(self):
        self.dismiss()


class Response:
    """An LLM response captured for a run-log line: streamed chunks,
    where it came from (live | cache | recorded), and whether the stream
    is complete."""

    def __init__(self, source="live"):
        self.chunks = []
        self.source = source
        self.done = False

    def text(self):
        return "".join(list(self.chunks))


class LogLine(Static):
    """One run-log line — expandable (click) when it carries a detail
    (a streamed LLM response)."""

    def __init__(self, text, response=None):
        super().__init__(text)
        self.base = text
        self.response = response
        self.expanded = False
        self.detail = None


class RunLog(VerticalScroll):
    """The run log (the colourful log): one line per event, tool-tagged,
    content colour-coded by event. Mounting is marshalled to the app
    thread (workers write from threads). The log itself can be maximized
    (the palette's Maximize item)."""

    ALLOW_MAXIMIZE = True

    def __init__(self):
        super().__init__(id="runlog")
        self._last = None

    def write(self, text, response=None):
        line = LogLine(text, response)
        try:
            self.app.call_from_thread(self._mount_line, line)
        except RuntimeError:
            self._mount_line(line)  # already on the app thread
        return line

    def _mount_line(self, line):
        self.mount(line)
        self._last = line
        self.scroll_end(animate=False)


class DetailBlock(VerticalScroll):
    """The expandable detail under a log line — the streamed LLM
    response, revealed inline (collapsed by default; live-appends new
    chunks while the response is still streaming). A proper reading
    pane: fixed height, scrollable."""

    def __init__(self, response, muted_hex="#E0E0E099"):
        super().__init__(classes="detail")
        self._response = response
        self._muted = muted_hex
        self._shown = 0
        self._timer = None

    def on_mount(self):
        self._append_new()
        if not self._response.done:
            self._timer = self.set_interval(0.4, self._append_new)

    def _append_new(self):
        chunks = self._response.chunks
        while self._shown < len(chunks):
            text = chunks[self._shown].rstrip("\n")
            self._shown += 1
            if text:
                self.mount(LogLine(f"[{self._muted}]  │ {text}[/]"))
        if self._response.done and self._timer is not None:
            self._timer.stop()
            self._timer = None


# The log's colour palette. Tool tags render as LABEL BADGES — a
# contrasting background with the tag as its text (black/white chosen
# by the background's luminance, so the badges read in both light and
# dark mode). Content colours resolve the app's theme variables
# (text-primary, text-success, …) so they adapt to the active theme.
TOOL_BADGES = {
    "llm · induction": "#0891B2",               # cyan
    "llm · commentary": "#7C3AED",              # violet (out-of-band explanations)
    "fwd chain · deduction": "#2563EB",         # blue
    "constraint solver · deduction": "#D97706", # amber
    "bwd chain · deduction": "#059669",         # emerald
    "auth": "#DB2777",                          # pink
}
EVENT_TOKENS = {
    "derive": "text-primary",
    "raise": "text-accent",
    "open": "text-secondary",
    "eliminate": "text-warning",
    "support": "text-success",
    "proof": "text-success",
}
CLAIM_PROVEN_TOKEN = "text-success"
CLAIM_REFUTED_TOKEN = "text-error"
FALLBACK_HEX = {
    "text-primary": "#57A5E2", "text-accent": "#FFC473",
    "text-secondary": "#5684A5", "text-success": "#8AD4A1",
    "text-warning": "#FFC473", "text-error": "#D17E92",
    "foreground-muted": "#E0E0E099",
}


def _contrast_fg(bg_hex):
    """Black or white — whichever contrasts with the badge background."""
    h = bg_hex.lstrip("#")
    if len(h) >= 6:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    else:
        r = g = b = 0
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return "#000000" if luminance > 0.5 else "#ffffff"


class PickerScreen(Screen):
    """The case picker — the workbench's front door."""

    BINDINGS = [("q", "quit", "Quit"), ("?", "help", "Help")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("Facty — the detective DSS · pick a case", classes="title")
        yield ListView(*[ListItem(Label(c.name), name=c.name) for c in cli.list_cases()],
                       id="picker")
        yield Footer()
        yield Tooltip()

    @on(ListView.Selected, "#picker")
    def open_case(self, event):
        self.app.push_screen(CaseScreen(cli.CASES_DIR / event.item.name))

    def action_quit(self):
        self.app.exit()

    def action_help(self):
        self.app.push_screen(HelpScreen())


class CaseScreen(Screen):
    """The case board: evidence · the run log · ranking + verdict."""

    BINDINGS = [
        ("r", "run_phase", "Run the case"),
        ("d", "apply_test", "Run the recommended test"),
        ("s", "sense", "Re-sense facts (LLM)"),
        ("a", "auth", "Authenticate (Mistral)"),
        ("e", "expand", "Expand the latest response"),
        ("x", "explain", "Explain the verdict (LLM)"),
        ("?", "help", "Help"),
        ("escape", "back", "Back"),
    ]

    def __init__(self, case, auto=False):
        super().__init__()
        self.case = Path(case)
        self.files = sorted((self.case / "evidence").iterdir())
        self.drop = cli.drop_file(self.case)
        self.auto = auto
        self.result = None
        self.entities = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="left"):
                yield Label("Evidence", classes="title")
                yield ListView(*[ListItem(Label(f"{f.name} ({f.stat().st_size} B)"))
                                 for f in self.files], id="evidence")
                facts = engine.load_array(self.case / "facts.json", "fact.schema.json")
                rules = engine.load_array(self.case / "pack" / "rules.json", "rule.schema.json")
                cons = engine.load_array(self.case / "pack" / "constraints.json",
                                         "constraint.schema.json")
                hyps = engine.load_array(self.case / "pack" / "hypotheses.json",
                                         "hypothesis.schema.json")
                yield Static(f"Sensed facts (recorded): {len(facts)}", id="facts-count")
                yield Static(f"Pack: {len(rules)} rules · {len(cons)} constraints · "
                             f"{len(hyps)} hypotheses")
                yield Checkbox("Run without the LLM (cached responses)",
                               id="offline", value=False,
                               tooltip="Never calls the LLM: steps with a cached "
                                       "response replay it; the rest use the recorded "
                                       "sensing (both logged). The cache line below "
                                       "shows how many steps are cached.")
                yield Static("", id="cache-state")
                yield Static("", id="auth-status")
                yield Button("Re-sense the facts (LLM)", id="sense",
                             tooltip="Run just the fact-sensing step (LLM), without "
                                     "solving — for iterating on the sensing prompt.")
                yield Button("Authenticate (Mistral)", id="auth",
                             tooltip="Sign in with your Mistral subscription — the "
                                     "pi-mistral-subscription extension's browser "
                                     "OAuth, behind the scenes.")
            with Vertical(id="mid"):
                yield Label("The run log — tools, prunes, proofs", classes="title")
                yield Static("1 · Run the case — the LLM senses the evidence, the "
                             "engine decides.\n2 · Run the recommended test — the "
                             "engine opens its questions, the LLM senses that "
                             "evidence with them, re-solve.\n3 · Explain the "
                             "verdict — out-of-band LLM commentary (the verdict "
                             "itself is deterministic).",
                             id="howto")
                yield RunLog()
                with Horizontal():
                    yield Button("Run the case", id="run", variant="primary",
                                 tooltip="Sense the evidence with the LLM, then the "
                                         "engine derives, prunes, ranks — a verdict "
                                         "on the evidence you have.")
                    yield Button("Run the recommended test", id="test",
                                 disabled=self.drop is None,
                                 tooltip="The engine names the one check that best "
                                         "discriminates the top explanations. Collect "
                                         "that evidence (LLM, with the engine's open "
                                         "questions as context) and re-solve — the "
                                         "verdict updates.")
                    yield Button("Explain the verdict (LLM)", id="explain",
                                 disabled=True,
                                 tooltip="Out-of-band LLM commentary: a plain-language "
                                         "explanation of the entities, the ranking, "
                                         "and the verdict. Presentation only — the "
                                         "verdict is deterministic. Cached like the "
                                         "sensing responses.")
            with Vertical(id="right"):
                yield Label("Ranking — backward chain + score", classes="title")
                yield DataTable(id="ranking")
                yield Static("on the initial evidence", id="phase")
                yield Static("", id="verdict")
                yield Static("", id="rec")
        yield Footer()
        yield Tooltip()

    def on_mount(self):
        self.query_one("#ranking", DataTable).add_columns("id", "claims", "support",
                                                         "prior", "score")
        self.query_one("#evidence", ListView).tooltip = \
            "Select a file and press Enter to read it."
        self.runlog = self.query_one("#runlog", RunLog)
        # resolve the theme's colour tokens once (app thread) — the log
        # lines then build their markup from cached hex (thread-safe)
        self._tokens = {name: self._token_hex(name) for name in
                        ("text-primary", "text-accent", "text-secondary",
                         "text-success", "text-warning", "text-error",
                         "foreground-muted")}
        self.refresh_auth_status()
        self.refresh_cache_state()
        if self.auto:
            self.do_run(None, offline=self._offline())

    def _token_hex(self, token):
        """Resolve a theme variable (text-success, foreground-muted, …)
        to a hex colour for the active theme (light/dark)."""
        try:
            value = self.app.theme_variables.get(token)
            if isinstance(value, str) and value.startswith("#"):
                return value
        except Exception:
            pass
        return FALLBACK_HEX.get(token, "#E0E0E0")

    def _badge(self, tag):
        """A tool tag as a label badge: a contrasting background with
        the tag as its text."""
        bg = TOOL_BADGES.get(tag, "#0891B2")
        return f"[{_contrast_fg(bg)} on {bg}] {tag} [/]"

    def _content(self, token, text):
        return f"[{self._tokens[token]}]{text}[/]"

    def _stage_text(self, label, suffix=""):
        return f"{self._badge('llm · induction')} ── {label}{suffix}"

    def _offline(self):
        """The offline checkbox (read on the app thread)."""
        return bool(self.query_one("#offline", Checkbox).value)

    def refresh_cache_state(self):
        ready, total = cli.cache_state(self.case)
        txt = f"response cache: {ready}/{total} steps"
        if ready < total:
            txt += " — run live once to cache them"
        self.query_one("#cache-state", Static).update(txt)

    def write(self, line):
        self.runlog.write(line)

    def refresh_auth_status(self):
        s = auth.status()
        self.query_one("#auth-status", Static).update(f"Mistral: {s['detail']}")

    # ── results ────────────────────────────────────────────────────

    def summarize(self, r):
        self.write(f"{self._badge('fwd chain · deduction')} "
                   + self._content(
                       "text-primary",
                       f"fixpoint: {len(r['derived_facts'])} derived facts · "
                       f"{len(r['opened_questions'])} questions opened · "
                       f"{len(r['raised_hypotheses'])} hypotheses raised"))
        self.write(f"{self._badge('constraint solver · deduction')} "
                   + self._content(
                       "text-warning",
                       f"{len(r['pruned'])} pruned · "
                       f"{len(r['ranking'])} survive"))
        self.write(f"{self._badge('bwd chain · deduction')} "
                   + self._content(
                       "text-success",
                       "claims proven, hypotheses ranked — verdict below"))

    def show_result(self, r):
        self.result = r
        self.query_one("#explain", Button).disabled = False
        table = self.query_one("#ranking", DataTable)
        table.clear()
        for rk in r["ranking"]:
            table.add_row(rk["id"], f"{rk['claims_proven']}/{rk['claims_total']}",
                          str(rk["support"]), f"{rk['prior']:.2f}", f"{rk['score']:.4f}")
        v = r["verdict"]
        if v:
            bg = TOOL_BADGES["bwd chain · deduction"]
            self.query_one("#verdict", Static).update(
                f"[{_contrast_fg(bg)} on {bg}] VERDICT {v['id']} [/] — "
                f"{v['statement']}  (score {v['score']:.4f})")
        if r["recommended_test"]:
            self.query_one("#rec", Static).update(
                f"recommended test: {r['recommended_test']['id']} — "
                f"{r['recommended_test']['text']}")
        self.query_one("#phase", Static).update(r["phase"])
        self.query_one("#test", Button).disabled = False
        # a live run may have populated the cache — show the new state
        self.refresh_cache_state()

    # ── actions ────────────────────────────────────────────────────

    @on(Button.Pressed, "#run")
    def run_phase(self):
        self.do_run(None, offline=self._offline())

    @on(Button.Pressed, "#test")
    def apply_test(self):
        if self.drop is not None:
            self.do_run(self.drop, offline=self._offline())

    @on(Button.Pressed, "#sense")
    def sense(self):
        self.do_sense()

    @on(Button.Pressed, "#auth")
    def auth_button(self):
        self.do_auth()

    @on(ListView.Selected, "#evidence")
    def show_evidence(self, event):
        idx = self.query_one("#evidence", ListView).index
        if idx is not None and 0 <= idx < len(self.files):
            self.app.push_screen(EvidenceScreen(self.files[idx]))

    def run_stage(self, label, op, *args, offline=False, engine_context=None):
        """One sensing stage (called from the run worker). See _live_call."""
        op_label = cli.sensing_ops(self.case)[op][0]

        def call(ui, stream, on_response):
            return cli.sense_one(ui, self.case, op, *args, stream=stream,
                                 on_response=on_response,
                                 mode="cache" if offline else None,
                                 engine_context=engine_context)

        return self._live_call(label, "llm · induction", call,
                               strip=f"{op_label} — ")

    def _live_call(self, label, tag, call, strip=""):
        """One live LLM call as a run-log line (called from a worker).

        The LIVE line — the last line while the call streams — carries
        the streamed response: expandable from the start (click it, or
        press e), live-appending in the detail while the response
        streams, green and expandable when it is ready. The stage's first
        status message folds into the live line (as its suffix); later
        status messages append below it as plain lines. Collapsed by
        default, so the main output stays uncluttered."""
        resp = Response()
        ui = _StageUI(self, strip=strip)
        line = self.runlog.write(f"{self._badge(tag)} ── {label}", resp)
        ui.live_line = line  # expandable from the start — mid-stream included
        count = {"n": 0}
        t0 = time.monotonic()

        def stream(chunk):
            count["n"] += 1
            resp.chunks.append(chunk + "\n")
            if count["n"] % 10 == 0:
                self.app.call_from_thread(
                    self._tick_live, line,
                    f"… streaming ▸ {count['n']} lines · "
                    f"{int(time.monotonic() - t0)}s — click to watch live")

        def on_response(text, source):
            if not resp.chunks:
                resp.chunks.append(text)
            resp.source = source

        try:
            return call(ui, stream, on_response)
        finally:
            self.app.call_from_thread(self._finish_live, line, resp)

    def _tick_live(self, line, suffix):
        if line.is_mounted:
            line.update(f"{line.base}  "
                        + self._content("foreground-muted", suffix))

    def _finish_live(self, line, resp):
        resp.done = True
        if line.is_mounted:
            n = len(resp.text().splitlines())
            src = resp.source or "live"
            line.update(f"{line.base}  "
                        + self._content(
                            "text-success",
                            f"▸ response ready ({src} · {n} lines)"
                            " — click to expand"))

    @work(thread=True)
    def do_run(self, add_facts, offline=False):
        """The e2e pipeline: the LLM senses the evidence (induction),
        then the engine decides (deduction). Falls back to the response
        cache / recorded sensing when the LLM is unreachable (logged).
        offline=True runs without the LLM (cached responses).

        With add_facts (the recommended test's evidence) the flow is:
        sense the initial evidence → the engine solves phase 1 and opens
        its questions → the LLM senses the test's evidence WITH that
        context (the questions + the hypothesis space — never the
        engine's conclusions) → the engine re-solves."""
        if offline:
            self.write(self._stage_text("running without the LLM (cached responses)"))
        index = self.run_stage("classify the evidence pile "
                               "(messy input → typed evidence)", "classify",
                               offline=offline)
        ents = self.run_stage("extract the entities "
                              "(extraction is sensing, not reasoning)", "entities",
                              offline=offline)
        facts = self.run_stage("sense the evidence → facts "
                               "(judge: schema + compute checks)", "facts",
                               index, ents, offline=offline)
        self.entities = ents
        if add_facts is not None:
            # phase 1: the engine decides on the initial evidence — its
            # open questions + hypothesis space are the context for
            # sensing the recommended test's evidence
            r1 = self._engine_run(facts, "on the initial evidence")
            label = Path(add_facts).stem.replace("facts-", "")
            facts = facts + self.run_stage(
                f"sense the {label} evidence (with the engine's open questions)",
                "drop", index, ents, engine_context=r1, offline=offline)
        self._engine_run(facts, "with the recommended test's evidence"
                         if add_facts is not None else "on the initial evidence")

    def _engine_run(self, facts, phase):
        """One deterministic engine solve, logged + shown (called from a
        worker). Returns the result — the phase-1 solve's questions are
        the drop sensing's context."""
        self.write(f"{self._badge('fwd chain · deduction')} ── rules fire: "
                   f"derive, open questions, raise hypotheses ({phase})")

        def engine_emit(e):
            tag = cli.TOOL_TAG[e["op"]]
            token = EVENT_TOKENS.get(e["op"], "text-primary")
            if e["op"] == "claim":
                token = (CLAIM_PROVEN_TOKEN if e.get("proven")
                         else CLAIM_REFUTED_TOKEN)
            for line in cli.fmt_event(e).splitlines():
                self.app.call_from_thread(
                    self.write,
                    f"{self._badge(tag)} {self._content(token, line)}")

        r = engine.run_case(self.case, facts=facts, emit=engine_emit)
        r["phase"] = phase
        self.app.call_from_thread(self.summarize, r)
        self.app.call_from_thread(self.show_result, r)
        return r

    @work(thread=True)
    def do_explain(self, target="verdict"):
        """Out-of-band LLM commentary: a plain-language explanation of the
        engine's result (entities | ranking | verdict). Presentation only
        — the verdict is deterministic and never depends on this call.
        Cached like the sensing responses; offline mode replays the
        cache."""
        if self.result is None:
            self.write(self._content(
                "text-warning", "run the case first — nothing to explain yet"))
            return
        offline = self._offline()
        label = (f"explain the {target} — LLM commentary, out-of-band "
                 "(the verdict itself is deterministic)")

        def call(ui, stream, on_response):
            return cli.explain(ui, self.case, self.result, self.entities,
                               target, stream=stream, on_response=on_response,
                               mode="cache" if offline else None)

        self._live_call(label, "llm · commentary", call)

    def action_explain(self):
        self.do_explain("verdict")

    @work(thread=True)
    def do_sense(self):
        facts = self.run_stage("re-sense the facts (standalone)", "facts",
                               offline=self._offline())
        self.app.call_from_thread(self.query_one("#facts-count", Static).update,
                                  f"Sensed facts (live): {len(facts)}")

    @work(thread=True)
    def do_auth(self):
        """Authenticate with the user's Mistral subscription — pi's
        /login (the pi-mistral-subscription extension's browser OAuth),
        driven behind the scenes; the credential lands in pi's auth
        storage, where the sensing path reads it."""
        self.write(f"{self._badge('auth')} ── authenticate with your Mistral "
                   "subscription")

        def progress(msg):
            self.app.call_from_thread(self.write,
                                      f"{self._badge('auth')} ▸ {msg}")

        ok, _url = auth.login(on_progress=progress)
        self.app.call_from_thread(self.refresh_auth_status)
        self.app.call_from_thread(
            self.write, f"{self._badge('auth')} ▸ "
            + ("authenticated — you're signed in"
               if ok else "sign-in did not complete — try again (a)"))

    def on_click(self, event):
        """Click a log line that carries a detail (a streamed LLM
        response) to expand/collapse it inline."""
        line = event.widget
        if isinstance(line, LogLine) and line.response is not None:
            self._toggle_detail(line)

    def _toggle_latest(self):
        """Keyboard expand (e): toggle the latest response line — works
        without a mouse (e.g. inside a VM console)."""
        lines = [w for w in self.runlog.query(LogLine) if w.response is not None]
        if lines:
            self._toggle_detail(lines[-1])

    def _toggle_detail(self, line):
        if line.expanded:
            line.detail.display = False
            line.expanded = False
            line.update(f"{line.base}  "
                        + self._content("text-success",
                                        "▸ response — click to expand"))
        else:
            if line.detail is None:
                line.detail = DetailBlock(line.response,
                                         self._tokens["foreground-muted"])
                self.runlog.mount(line.detail, after=line)
            line.detail.display = True
            line.expanded = True
            line.update(f"{line.base}  "
                        + self._content("text-success",
                                        "▾ response — click to hide"))
            # make sure the expanded detail is on screen (the stage line
            # is usually the last visible line)
            self.call_after_refresh(
                lambda: line.detail.scroll_visible(animate=False))

    def action_run_phase(self):
        self.do_run(None, offline=self._offline())

    def action_apply_test(self):
        if self.drop is not None:
            self.do_run(self.drop, offline=self._offline())

    def action_expand(self):
        self._toggle_latest()

    def action_sense(self):
        self.do_sense()

    def action_auth(self):
        self.do_auth()

    def action_help(self):
        self.app.push_screen(HelpScreen())

    def action_back(self):
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()
        else:
            self.app.exit()


class _LogUI:
    """Adapts the terminal walkthrough's UI interface (log/step) to the
    board's run log (Rich markup: the tool tag is dimmed, not a tag)."""

    def __init__(self, screen):
        self.screen = screen
        self.log_lines = []

    def log(self, tag, msg):
        for line in str(msg).splitlines() or [""]:
            text = f"[dim]{tag}[/dim] {line}"
            self.log_lines.append(text)
            self.screen.app.call_from_thread(self.screen.write, text)

    def step(self, tag, title):
        self.log(tag, f"── {title} ")


class _StageUI(_LogUI):
    """A stage's UI adapter: the FIRST log line folds into the stage's
    live line (as its status suffix — the live line stays the LAST line
    while the LLM streams, and it carries the streamed response, so it
    is expandable mid-stream); later lines append below it as plain log
    lines. `strip` removes the op-label prefix the status repeats."""

    def __init__(self, screen, strip=""):
        super().__init__(screen)
        self.strip = strip
        self.live_line = None
        self._folded = False

    def log(self, tag, msg):
        lines = str(msg).splitlines() or [""]
        if not self._folded and self.live_line is not None:
            self._folded = True
            first = lines[0]
            if self.strip and first.startswith(self.strip):
                first = first[len(self.strip):]
            self.screen.app.call_from_thread(
                self.screen._tick_live, self.live_line, f"— {first}")
            lines = lines[1:]
        for line in lines:
            super().log(tag, line)


class FactyCommands(Provider):
    """The command palette (ctrl+p): every action, with its help text."""

    def _commands(self):
        s = self.screen
        cmds = []
        if isinstance(s, CaseScreen):
            cmds.append(("Run the case", lambda: s.do_run(None),
                         "Sense the evidence (LLM) → the engine decides"))
            if s.drop is not None:
                cmds.append(("Run the recommended test", lambda: s.do_run(s.drop),
                             "Collect the evidence the engine recommends, then re-solve"))
            cmds.append(("Re-sense the facts (LLM)", lambda: s.do_sense(),
                         "Just the fact-sensing step, without solving"))
            cmds.append(("Authenticate with Mistral (subscription)",
                         lambda: s.do_auth(),
                         "Browser sign-in via the pi-mistral-subscription extension"))
            cmds.append(("Expand/collapse the latest response",
                         lambda: s._toggle_latest(),
                         "Reveal the streamed LLM response inline (keyboard-friendly)"))
            cmds.append(("Explain the verdict (LLM commentary)",
                         lambda: s.do_explain("verdict"),
                         "Plain-language explanation of the result — out-of-band; "
                         "the verdict itself is deterministic"))
            cmds.append(("Summarize the extracted entities (LLM commentary)",
                         lambda: s.do_explain("entities"),
                         "A plain-language summary of the sensed entities"))
            cmds.append(("Explain the ranking (LLM commentary)",
                         lambda: s.do_explain("ranking"),
                         "Why each hypothesis scored where it did"))
        cmds.append(("Show help", lambda: self.app.push_screen(HelpScreen()),
                     "The flow, the run-log vocabulary, the triples"))
        if len(self.app.screen_stack) > 1:
            cmds.append(("Back to the case list", lambda: self.app.pop_screen(),
                         "Return to the case picker"))
        cmds.append(("Quit", lambda: self.app.exit(), "Leave the workbench"))
        return cmds

    async def discover(self):
        for display, callback, help_text in self._commands():
            yield DiscoveryHit(display, callback, help=help_text)

    async def search(self, query):
        q = query.lower()
        for display, callback, help_text in self._commands():
            if q in display.lower() or q in help_text.lower():
                yield Hit(1.0, display, callback, help=help_text)


class FactyApp(App):
    """The Facty workbench. Bare `./facty` opens the case picker."""

    # App-level CSS: always loaded (screen-level CSS is NOT loaded for
    # the default screen — see Textual's _load_screen_css), unscoped.
    CSS = """
    #left { width: 36; }
    #mid { width: 1fr; }
    #right { width: 46; }
    .title { text-style: bold; padding: 0 1; }
    #howto { height: 4; padding: 0 1; color: $text-muted; }
    #runlog { border: solid green; height: 1fr; }
    .detail { height: 14; margin-left: 2; border-left: solid #0891B2;
              padding-left: 1; }
    #ranking { height: 1fr; }
    #verdict { height: auto; padding: 0 1; text-style: bold; }
    #rec { height: auto; padding: 0 1; color: $text-muted; }
    HelpScreen VerticalScroll {
        width: 84%; height: 86%;
        border: solid green; background: $surface;
        padding: 1 2;
    }
    EvidenceScreen Vertical {
        width: 82%; height: 82%;
        border: solid green; background: $surface;
    }
    EvidenceScreen TextArea { height: 1fr; }
    """

    COMMANDS = App.COMMANDS | {FactyCommands}
    BINDINGS = [("ctrl+p", "command_palette", "Command palette")]

    def __init__(self, case=None, auto=False):
        super().__init__()
        self.initial_case = case
        self.auto = auto

    def exit(self, *args, **kwargs):
        # quitting must not leave LLM/auth subprocesses behind
        procs.kill_all()
        return super().exit(*args, **kwargs)

    def get_default_screen(self) -> Screen:
        if self.initial_case is not None:
            return CaseScreen(self.initial_case, auto=self.auto)
        return PickerScreen()


def run(case=None, auto=False):
    """Launch the workbench (imported lazily by cli.py — Textual is the
    repo's one optional dependency)."""
    FactyApp(case, auto=auto).run()
