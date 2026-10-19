#!/usr/bin/env python3
# pack_tui.py — the Pack Studio TUI: author a pack (rules, constraints,
# hypotheses, labels) and test it (run on a fact set, see verdict + trace
# + gap analysis). The knowledge authoring workbench (PRD-007, follow-up
# phase 1 — the TUI surfaces).
#
# The deterministic half: the editors are TextAreas with JSON content; the
# Save (s) and Validate (v) actions call engine/pack.py (validate_pack,
# run_pack_test) — no LLM in the validation path. The LLM draft ops
# (draft-rules, review) run in a thread via the CLI's plumbing (induction
# only — never in the verdict path).
#
# Layout:
#   ┌──────────────────────────────────────────────────────────────┐
#   │  Header                                                       │
#   ├──────────┬───────────────────────────────────────────────────┤
#   │  Packs   │  [Rules] [Constraints] [Hypotheses] [Labels] [Test]│
#   │  ─────   │  ┌─────────────────────────────────────────────┐  │
#   │  ▸ pack  │  │                                             │  │
#   │  ▸ pack  │  │  TextArea (JSON editor)                     │  │
#   │          │  │                                             │  │
#   │  [+ New] │  └─────────────────────────────────────────────┘  │
#   │  [Validate] [Draft] [Review]                                │
#   ├──────────┴───────────────────────────────────────────────────┤
#   │  Footer (keybindings)                                         │
#   └──────────────────────────────────────────────────────────────┘

import json
import sys
import threading
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen, ModalScreen
from textual.widgets import (Button, Footer, Header, Input, Label, ListItem,
                             ListView, Static, TabbedContent, TabPane, TextArea)

import agent  # noqa: E402  (the embedded agent — pi RPC)
from terminal import TerminalPane  # noqa: E402  (embedded pi TUI — the questionnaire dialog)


class AskDialogScreen(ModalScreen):
    """A modal dialog for the agent's extension_ui_request (the
    ask_questions elicitation over RPC — one question at a time).

    method="select": a ListView of options, Enter to pick.
    method="input": an Input, Enter to submit.
    method="confirm": Yes / No buttons.

    The result is stored in self.result; the event is set when the
    user answers (or cancels with Escape)."""

    CSS = """
    AskDialogScreen {
        align: center middle;
    }
    AskDialogScreen > Vertical {
        width: 70; height: auto; max-height: 80%;
        border: solid $accent; background: $surface; padding: 1 2;
    }
    #ask-title { text-style: bold; padding: 0 0 1 0; }
    #ask-options { height: auto; max-height: 12; }
    #ask-input { margin-top: 1; }
    #ask-buttons { height: auto; align-horizontal: center; }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, request, done, result):
        super().__init__()
        self.request = request
        self.done = done       # threading.Event
        self.result = result   # [value] — set before done.set()

    def compose(self) -> ComposeResult:
        method = self.request.get("method", "input")
        title = self.request.get("title", "")
        with Vertical():
            yield Label(title, id="ask-title")
            if method == "select":
                options = self.request.get("options", [])
                yield ListView(*[ListItem(Label(o)) for o in options],
                               id="ask-options")
            elif method == "confirm":
                with Horizontal(id="ask-buttons"):
                    yield Button("Yes", id="ask-yes", variant="primary")
                    yield Button("No", id="ask-no")
            else:  # input / editor
                yield Input(placeholder=self.request.get("placeholder", ""),
                            id="ask-input")

    def on_mount(self):
        method = self.request.get("method", "input")
        if method == "select":
            self.query_one("#ask-options", ListView).focus()
        elif method == "input":
            self.query_one("#ask-input", Input).focus()

    def _submit(self, value):
        self.result[0] = value
        self.done.set()
        self.app.pop_screen()

    def _cancel(self):
        self.result[0] = None
        self.done.set()
        self.app.pop_screen()

    def on_list_view_selected(self, event):
        if event.list_view.id == "ask-options":
            label = event.item.query_one(Label)
            self._submit(str(label.render()))

    def on_input_submitted(self, event):
        if event.input.id == "ask-input":
            self._submit(event.input.value)

    def on_button_pressed(self, event):
        if event.button.id == "ask-yes":
            self._submit("yes")
        elif event.button.id == "ask-no":
            self._submit("no")

    def action_cancel(self):
        self._cancel()

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import pack    # noqa: E402  (the Pack Studio library)

PACKS_DIR = ENGINE_DIR.parent / "packs"

# The tabs: (tab id, artifact path relative to the pack dir, schema name)
ARTIFACT_TABS = [
    ("rules", "pack/rules.json", "rule.schema.json"),
    ("constraints", "pack/constraints.json", "constraint.schema.json"),
    ("hypotheses", "pack/hypotheses.json", "hypothesis.schema.json"),
    ("labels", "classify.json", None),  # structural checks, not a schema
]


class PackStudioScreen(Screen):
    """The Pack Studio: author a pack and test it."""

    BINDINGS = [
        ("v", "validate", "Validate the pack"),
        ("t", "run_test", "Run the test"),
        ("s", "save", "Save the editor"),
        ("d", "draft_rules", "Draft rules (LLM)"),
        ("r", "review", "Review (LLM)"),
        ("n", "new_pack", "New pack"),
        ("?", "help", "Help"),
        ("escape", "back", "Back"),
    ]

    CSS = """
    #pack-left { width: 28; }
    #pack-right { width: 1fr; }
    #pack-agent { width: 60; border-left: solid $primary; }
    #pack-list { height: 1fr; }
    #pack-tabs { height: 1fr; }
    .editor { height: 1fr; }
    #test-log { height: 1fr; border: solid green; }
    #validate-result { height: auto; padding: 0 1; }
    #pack-status { height: auto; padding: 0 1; color: $text-muted; }
    .agent-terminal { height: 1fr; border: solid $accent; }
    """

    def __init__(self, pack_slug=None):
        super().__init__()
        self.pack_slug = pack_slug
        self.pack_dir = None
        self._saving = False
        self.agent = None  # the AgentSession (lazy-spawned on first message)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="pack-left"):
                yield Label("Packs", classes="title")
                yield ListView(id="pack-list")
                yield Button("New pack", id="new-pack",
                             tooltip="Create a new pack directory under packs/")
                yield Button("Validate", id="validate",
                             tooltip="Schema + cross-artifact checks (deterministic)")
                yield Button("Draft rules (LLM)", id="draft",
                             tooltip="One-shot LLM draft of pack/rules.json "
                                     "(staged as rules.draft.json)")
                yield Button("Review (LLM)", id="review",
                             tooltip="Advisory LLM review for gaps (prose, "
                                     "never written)")
            with Vertical(id="pack-right"):
                with TabbedContent(id="pack-tabs"):
                    for tab_id, rel_path, _schema in ARTIFACT_TABS:
                        with TabPane(tab_id.capitalize(), id=f"tab-{tab_id}"):
                            yield TextArea(id=f"editor-{tab_id}",
                                           language="json",
                                           classes="editor",
                                           read_only=False)
                    with TabPane("Test", id="tab-test"):
                        yield Static("Select a fact set (tests/facts-*.json) "
                                     "and run the test — the engine runs "
                                     "deterministically, no LLM.",
                                     id="test-howto")
                        yield ListView(id="facts-list")
                        yield Button("Run test", id="run-test", variant="primary")
                        yield Static("", id="test-result")
                        yield VerticalScroll(id="test-log")
                yield Static("", id="validate-result")
                yield Static("", id="pack-status")
            with Vertical(id="pack-agent"):
                yield Label("Agent (pi) — your pair programmer", classes="title")
                # The agent pane IS pi's TUI (embedded via a PTY terminal
                # emulator). The ask_questions questionnaire dialog renders
                # natively here — tabs, previews, notes, review tab.
                #
                # Runs pi INSIDE the gondolin VM (the running SDLC session):
                # the VM has the pack-factory skill + ask-questions extension
                # baked in, authenticates via the host-secret proxy (the
                # subscription token), and is hypervisor-isolated.
                # Fallback: run pi on the host if no VM session is up.
                import json as _json
                from pathlib import Path as _Path
                _session_file = _Path(".agentic/vm-session.json")
                if _session_file.exists():
                    try:
                        _sid = _json.loads(_session_file.read_text())["id"]
                        # Source the session env (MISTRAL_API_KEY placeholder —
                        # the host proxy substitutes the real subscription
                        # token into requests to api.mistral.ai) and set
                        # PI_CODING_AGENT_DIR (the mistral-subscription
                        # extension lives at /opt/pi-agent in the VM).
                        _cmd = ["gondolin", "attach", _sid, "--",
                                "bash", "-c",
                                "source /root/.session-env/mistral.sh 2>/dev/null; "
                                "export PI_CODING_AGENT_DIR=/opt/pi-agent; "
                                "exec pi --skill /root/.agents/skills/pack-factory"]
                    except Exception:
                        _cmd = None
                else:
                    _cmd = None
                if _cmd is None:
                    # Fallback: pi on the host
                    _skill = _Path.home() / ".agents" / "skills" / "pack-factory"
                    _cmd = ["pi", "--skill", str(_skill)]
                yield TerminalPane(
                    _cmd,
                    id="agent-terminal",
                    classes="agent-terminal",
                )
        yield Footer()

    def on_mount(self):
        self._refresh_pack_list()
        if self.pack_slug:
            self._select_pack(self.pack_slug)
        else:
            packs = pack.list_packs()
            if packs:
                self._select_pack(packs[0]["slug"])

    # ── Pack list ──────────────────────────────────────────────────

    def _refresh_pack_list(self):
        lv = self.query_one("#pack-list", ListView)
        lv.clear()
        for p in pack.list_packs():
            label = f"{p['slug']}  ({p['counts']['rules']}r/{p['counts']['hypotheses']}h)"
            lv.append(ListItem(Label(label), name=p["slug"]))

    def _select_pack(self, slug):
        self.pack_slug = slug
        self.pack_dir = pack.resolve_pack(slug)
        self._load_artifacts()
        self._refresh_facts_list()
        self.query_one("#pack-status", Static).update(
            f"pack: {slug} · {self.pack_dir}")
        # highlight the selected pack (match by the ListItem's name)
        lv = self.query_one("#pack-list", ListView)
        for i, item in enumerate(lv.children):
            if item.name == slug:
                lv.index = i
                break

    def on_list_view_selected(self, event):
        if event.list_view.id == "pack-list":
            self._select_pack(event.item.name)
        elif event.list_view.id == "facts-list":
            self.action_run_test()

    # ── Artifact editors ───────────────────────────────────────────

    def _load_artifacts(self):
        for tab_id, rel_path, _schema in ARTIFACT_TABS:
            editor = self.query_one(f"#editor-{tab_id}", TextArea)
            path = self.pack_dir / rel_path
            if path.exists():
                editor.text = path.read_text()
            else:
                editor.text = self._empty_artifact(tab_id)

    def _empty_artifact(self, tab_id):
        if tab_id == "rules":
            return json.dumps([], indent=2) + "\n"
        if tab_id == "constraints":
            return json.dumps([], indent=2) + "\n"
        if tab_id == "hypotheses":
            return json.dumps([], indent=2) + "\n"
        if tab_id == "labels":
            return json.dumps({
                "file": "evidence/data.csv",
                "idColumn": "id",
                "textColumn": "text",
                "labels": [],
                "template": "This is {}.",
                "threshold": 0.65,
                "backend": "hybrid"
            }, indent=2) + "\n"
        return ""

    def _save_current_editor(self):
        """Save the active tab's editor to disk."""
        if self.pack_dir is None:
            return
        tabs = self.query_one("#pack-tabs", TabbedContent)
        active = tabs.active
        for tab_id, rel_path, _schema in ARTIFACT_TABS:
            if f"tab-{tab_id}" == active:
                editor = self.query_one(f"#editor-{tab_id}", TextArea)
                path = self.pack_dir / rel_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(editor.text)
                self._set_status(f"saved: {rel_path}")
                return

    def _set_status(self, msg):
        self.query_one("#pack-status", Static).update(f"pack: {self.pack_slug} · {msg}")

    def _set_validate_result(self, msg, ok=True):
        color = "green" if ok else "red"
        self.query_one("#validate-result", Static).update(
            f"[{color}]{msg}[/{color}]")

    # ── Validate ───────────────────────────────────────────────────

    def action_validate(self):
        if self.pack_dir is None:
            self._set_validate_result("no pack selected", ok=False)
            return
        self._save_current_editor()
        try:
            report = pack.validate_pack(self.pack_dir)
        except pack.PackError as exc:
            self._set_validate_result(f"error: {exc}", ok=False)
            return
        if report["ok"]:
            c = report["counts"]
            self._set_validate_result(
                f"valid ✓ — {c['rules']} rules · {c['hypotheses']} hypotheses · "
                f"{c['constraints']} constraints · {c['tests']} tests", ok=True)
        else:
            lines = [f"{len(report['violations'])} violation(s):"]
            for v in report["violations"][:5]:
                lines.append(f"  ✗ {v['file']}: {v['message']}")
            if len(report["violations"]) > 5:
                lines.append(f"  … and {len(report['violations']) - 5} more")
            self._set_validate_result("\n".join(lines), ok=False)

    # ── Test ───────────────────────────────────────────────────────

    def _refresh_facts_list(self):
        lv = self.query_one("#facts-list", ListView)
        lv.clear()
        if self.pack_dir is None:
            return
        tests_dir = self.pack_dir / "tests"
        if not tests_dir.is_dir():
            return
        for f in pack.scenario_files(tests_dir):
            lv.append(ListItem(Label(f.name), name=f.name))

    def _selected_facts_file(self):
        lv = self.query_one("#facts-list", ListView)
        if lv.index is None or lv.index >= len(lv.children):
            return None
        name = lv.children[lv.index].name
        return self.pack_dir / "tests" / name

    def on_button_pressed(self, event):
        if event.button.id == "new-pack":
            self.action_new_pack()
        elif event.button.id == "validate":
            self.action_validate()
        elif event.button.id == "run-test":
            self.action_run_test()
        elif event.button.id == "draft":
            self.action_draft_rules()
        elif event.button.id == "review":
            self.action_review()

    @work(thread=True)
    def action_run_test(self):
        if self.pack_dir is None:
            self.app.call_from_thread(
                self._set_validate_result, "no pack selected", False)
            return
        self._save_current_editor()
        facts_file = self._selected_facts_file()
        if facts_file is None:
            self.app.call_from_thread(
                self._set_validate_result, "no fact set selected", False)
            return
        try:
            facts = pack.load_facts_file(facts_file)
            result = pack.run_pack_test(self.pack_dir, facts)
        except pack.PackError as exc:
            self.app.call_from_thread(
                self._set_validate_result, f"error: {exc}", False)
            return
        # Render the result
        lines = []
        v = result["verdict"]
        lines.append(f"VERDICT: {v['id']} — {v['statement']}" if v else "no verdict")
        lines.append(f"score: {v['score']:.4f}" if v else "")
        gaps = result["gaps"]
        lines.append("")
        lines.append("gap analysis:")
        lines.append(f"  dead rules: {len(gaps['dead_rules'])}")
        for r in gaps["dead_rules"][:3]:
            lines.append(f"    ✗ {r['id']}")
        lines.append(f"  unraised hypotheses: {len(gaps['unraised_hypotheses'])}")
        for h in gaps["unraised_hypotheses"][:3]:
            lines.append(f"    ✗ {h['id']}")
        lines.append(f"  unanswered questions: {len(gaps['unanswered_questions'])}")
        for q in gaps["unanswered_questions"][:3]:
            lines.append(f"    ? {q['id']} [{q['slot']}]")
        text = "\n".join(lines)
        self.app.call_from_thread(self._show_test_result, text)

    def _show_test_result(self, text):
        self.query_one("#test-result", Static).update(text)
        log = self.query_one("#test-log", VerticalScroll)
        log.remove_children()
        log.mount(Static(text))

    # ── New pack ───────────────────────────────────────────────────

    def action_new_pack(self):
        # Simple approach: prompt for a slug via the command line input
        # For the MVP, create a pack with a default slug and let the user
        # rename it in the filesystem.
        import time
        slug = f"pack-{int(time.time())}"
        try:
            pack_dir = PACKS_DIR / slug
            (pack_dir / "pack").mkdir(parents=True, exist_ok=False)
            (pack_dir / "pack" / "rules.json").write_text("[]\n")
            (pack_dir / "pack" / "constraints.json").write_text("[]\n")
            (pack_dir / "pack" / "hypotheses.json").write_text("[]\n")
        except FileExistsError:
            self._set_status(f"pack already exists: {slug}")
            return
        self._refresh_pack_list()
        self._select_pack(slug)
        self._set_status(f"created: {slug}")

    # ── Save ───────────────────────────────────────────────────────

    def action_save(self):
        self._save_current_editor()

    # ── LLM ops (draft rules, review) ──────────────────────────────
    # These run the CLI's LLM plumbing in a thread. Induction only —
    # never in the verdict path.

    @work(thread=True)
    def action_draft_rules(self):
        if self.pack_dir is None:
            return
        # For the MVP: show a message that the LLM op runs via the CLI.
        # The full TUI integration (embedded agent pane) is follow-up phase 2.
        self.app.call_from_thread(
            self._set_status,
            "draft-rules: run `./facty pack draft-rules "
            f"{self.pack_slug} --domain \"...\"` in the terminal "
            "(the embedded agent pane is the next phase)")

    @work(thread=True)
    def action_review(self):
        if self.pack_dir is None:
            return
        self.app.call_from_thread(
            self._set_status,
            f"review: run `./facty pack review {self.pack_slug}` in the terminal")

    # ── Agent chat pane ────────────────────────────────────────────

    def on_input_submitted(self, event):
        """The agent input: send the message to pi, stream the response."""
        if event.input.id != "agent-input":
            return
        message = event.input.value.strip()
        if not message:
            return
        event.input.value = ""
        self.agent_worker = self._agent_send(message)

    def _agent_log(self, text, cls="agent-msg"):
        """Append a line to the agent chat log."""
        log = self.query_one("#agent-log", VerticalScroll)
        log.mount(Static(text, classes=cls))
        # Scroll to the bottom
        log.scroll_end(animate=False)

    @work(thread=True)
    def _agent_send(self, message):
        """Send a message to the embedded agent (pi RPC), stream the
        response into the chat log. Runs in a worker thread."""
        self._agent_send_impl(message)

    def _ui_call(self, fn, *args):
        """Call a UI function — thread-safe: direct in the app thread,
        via call_from_thread in a worker thread."""
        import threading
        if threading.current_thread() is not threading.main_thread():
            self.app.call_from_thread(fn, *args)
        else:
            fn(*args)

    def _mount_agent_widget(self, widget):
        """Mount the agent's response widget on the app thread."""
        log = self.query_one("#agent-log", VerticalScroll)
        log.mount(widget)
        log.scroll_end(animate=False)

    def _scroll_agent_log(self):
        """Scroll the agent chat log to the bottom."""
        log = self.query_one("#agent-log", VerticalScroll)
        log.scroll_end(animate=False)

    def _agent_ui_handler(self, request):
        """Handle an extension_ui_request from the agent (the ask_questions
        elicitation over RPC — one question at a time). Called from the
        worker thread; shows the dialog on the app thread and blocks until
        the user responds (threading.Event). Returns the answer (or None
        if cancelled)."""
        done = threading.Event()
        result = [None]

        def show_dialog():
            self.app.push_screen(AskDialogScreen(request, done, result))

        self.app.call_from_thread(show_dialog)
        done.wait(timeout=600)  # 10 minute timeout
        return result[0]

    def _agent_send_impl(self, message):
        """The agent send logic (synchronous — the @work wrapper calls
        this in a thread; tests call this directly).

        Streaming: a single Static widget per response, updated via
        call_next (non-blocking) as text arrives — no per-line widget
        mounts, and the 'agent: ' label appears once (part of the
        initial text), not on every line.

        UI dialogs: the ask_questions elicitation (extension_ui_request)
        is handled by _agent_ui_handler — it shows the AskDialogScreen
        and blocks until the user answers."""
        # User message (one widget)
        self._ui_call(self._agent_log, f"you: {message}", "agent-user")
        if self.agent is None:
            ctx = ""
            if self.pack_dir is not None:
                try:
                    ctx = agent.pack_context(self.pack_dir)
                except Exception:
                    ctx = f"pack: {self.pack_slug}"
            try:
                self.agent = agent.AgentSession(pack_context=ctx)
            except Exception as exc:
                self._ui_call(self._agent_log,
                              f"agent: failed to start: {exc}", "agent-error")
                return
        # Mount the agent's response widget (blocking — ensures it's
        # mounted before streaming starts)
        response_widget = Static("agent: ", classes="agent-msg")
        self._ui_call(self._mount_agent_widget, response_widget)
        # Stream the response into the widget (non-blocking updates)
        accumulated = ["agent: "]

        def stream(line):
            accumulated[0] += line + "\n"
            self.call_next(response_widget.update, accumulated[0])
            self.call_next(self._scroll_agent_log)

        try:
            self.agent.send(message, stream=stream,
                            ui_handler=self._agent_ui_handler)
        except RuntimeError as exc:
            self.agent = None  # respawn on the next message
            self._ui_call(self._agent_log,
                          f"agent: error: {exc}", "agent-error")
        except Exception as exc:
            self._ui_call(self._agent_log,
                          f"agent: error: {exc}", "agent-error")

    def on_unmount(self):
        """Shut down the agent's pi process when the screen closes."""
        if self.agent is not None:
            try:
                self.agent.close()
            except Exception:
                pass
            self.agent = None

    # ── Navigation ─────────────────────────────────────────────────

    def action_back(self):
        self.app.pop_screen()

    def action_help(self):
        from tui import HelpScreen
        self.app.push_screen(HelpScreen())


def run(pack_slug=None):
    """Launch the Pack Studio TUI (imported lazily by cli.py)."""
    from textual.app import App

    class PackStudioApp(App):
        CSS = PackStudioScreen.CSS

        def on_mount(self):
            self.push_screen(PackStudioScreen(pack_slug))

    PackStudioApp().run()
