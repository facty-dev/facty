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
from textual.screen import Screen
from textual.widgets import (Button, Footer, Header, Input, Label, ListItem,
                             ListView, Static, TabbedContent, TabPane, TextArea)

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
    #pack-left { width: 32; }
    #pack-right { width: 1fr; }
    #pack-list { height: 1fr; }
    #pack-tabs { height: 1fr; }
    .editor { height: 1fr; }
    #test-log { height: 1fr; border: solid green; }
    #validate-result { height: auto; padding: 0 1; }
    #pack-status { height: auto; padding: 0 1; color: $text-muted; }
    """

    def __init__(self, pack_slug=None):
        super().__init__()
        self.pack_slug = pack_slug
        self.pack_dir = None
        self._saving = False

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
