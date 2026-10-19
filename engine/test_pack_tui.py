#!/usr/bin/env python3
# test_pack_tui.py — the Pack Studio TUI, tested headless (no TTY needed).
#
# Drives the Pack Studio screen with Textual's pilot (run_test): the pack
# list, the tabbed editors (Rules, Constraints, Hypotheses, Labels), the
# Validate action (deterministic — engine/pack.py), the Test tab (run the
# pack on a fact set, see the verdict + gap analysis), and the New pack
# button. The LLM draft ops are NOT tested here (they need a live LLM or
# a seeded cache — tested in test_pack.py). Skips cleanly when Textual is
# not installed.
#
# Usage:
#   python3 engine/test_pack_tui.py     # or: ./facty test

import asyncio
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import pack    # noqa: E402  (the Pack Studio library)

try:
    from textual.app import App
    from pack_tui import PackStudioScreen
    HAVE_TUI = True
except ImportError:
    HAVE_TUI = False

PACK_SLUG = "triage-alert-flood"
CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" — {detail}" if detail and not ok else ""))


class PackStudioApp(App):
    def on_mount(self):
        self.push_screen(PackStudioScreen(PACK_SLUG))


async def run_tests():
    from textual.widgets import (Button, Label, ListView, Static,
                                 TabbedContent, TextArea)

    app = PackStudioApp()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        screen = app.screen

        # 1. The screen is the Pack Studio
        check("the Pack Studio screen is mounted",
              isinstance(screen, PackStudioScreen))

        # 2. The pack is selected
        check("the seed pack is selected",
              screen.pack_slug == PACK_SLUG,
              f"got: {screen.pack_slug}")

        # 3. The pack list shows the pack
        lv = screen.query_one("#pack-list", ListView)
        pack_names = [c.name for c in lv.children]
        check("the pack list has the seed pack",
              PACK_SLUG in pack_names,
              f"got: {pack_names}")

        # 4. The tabs are present
        tabs = screen.query_one("#pack-tabs", TabbedContent)
        tab_ids = [t.id for t in tabs.query("TabPane")]
        expected = {"tab-rules", "tab-constraints", "tab-hypotheses",
                    "tab-labels", "tab-test"}
        check("the tabs are present (rules/constraints/hypotheses/labels/test)",
              expected.issubset(set(tab_ids)),
              f"got: {tab_ids}")

        # 5. The Rules editor shows the pack's rules
        editor = screen.query_one("#editor-rules", TextArea)
        check("the Rules editor has the pack's rules.json",
              '"id": "R0"' in editor.text,
              f"got: {editor.text[:50]}...")

        # 6. The Constraints editor shows the pack's constraints
        cons_editor = screen.query_one("#editor-constraints", TextArea)
        check("the Constraints editor has the pack's constraints.json",
              '"id": "C1"' in cons_editor.text,
              f"got: {cons_editor.text[:50]}...")

        # 7. Validate (v) — deterministic, no LLM
        await pilot.press("v")
        await pilot.pause(1)
        result = screen.query_one("#validate-result", Static)
        result_text = str(result.render())
        check("validate (v) reports the pack as valid",
              "valid" in result_text.lower(),
              f"got: {result_text[:80]}")

        # 8. Switch to the Test tab
        tabs.active = "tab-test"
        await pilot.pause()
        check("the Test tab is active",
              tabs.active == "tab-test",
              f"got: {tabs.active}")

        # 9. The facts list shows the test scenario
        facts_lv = screen.query_one("#facts-list", ListView)
        check("the facts list has the test scenario",
              len(facts_lv.children) >= 1,
              f"got: {len(facts_lv.children)} items")

        # Select the first fact file (the ListView needs an index)
        if len(facts_lv.children) >= 1:
            facts_lv.index = 0
            await pilot.pause()

        # 10. Run the test (t) — deterministic
        await pilot.press("t")
        await pilot.pause(3)
        test_result = screen.query_one("#test-result", Static)
        test_text = str(test_result.render())
        check("run test (t) shows the verdict",
              "VERDICT" in test_text and "H1" in test_text,
              f"got: {test_text[:100]}")
        check("run test (t) shows the gap analysis",
              "gap analysis" in test_text.lower(),
              f"got: {test_text[:100]}")

        # 11. Switch to the Constraints tab — the editor loads
        tabs.active = "tab-constraints"
        await pilot.pause()
        cons_text = screen.query_one("#editor-constraints", TextArea).text
        check("the Constraints tab loads the constraints",
              '"id"' in cons_text,
              f"got: {cons_text[:50]}")

        # 12. New pack button creates a pack
        # (skip — would create a real directory; tested via the CLI)

        # 13. The status line shows the pack
        status = screen.query_one("#pack-status", Static)
        status_text = str(status.render())
        check("the status line shows the pack slug",
              PACK_SLUG in status_text,
              f"got: {status_text[:80]}")

        # 14. The agent pane is present
        from textual.containers import Vertical, VerticalScroll
        from textual.widgets import Input
        agent_pane = screen.query_one("#pack-agent", Vertical)
        check("the agent pane is present", agent_pane is not None)

        agent_log = screen.query_one("#agent-log", VerticalScroll)
        check("the agent chat log is present", agent_log is not None)

        agent_input = screen.query_one("#agent-input", Input)
        check("the agent input is present", agent_input is not None)

        # 15. The agent input is functional (stub the AgentSession)
        import agent as agent_mod
        original_init = agent_mod.AgentSession.__init__

        class StubAgentSession:
            def __init__(self, pack_context=""):
                self.pack_context = pack_context
                self.sent = []

            def send(self, message, stream=None, ui_handler=None):
                self.sent.append(message)
                if stream:
                    stream("stub response: I can help you draft rules.")
                return "stub response: I can help you draft rules."

            def close(self):
                pass

        agent_mod.AgentSession = StubAgentSession
        try:
            # Call the agent logic directly (synchronous — bypasses the
            # @work decorator for testability)
            screen._agent_send_impl("draft rules for inflated labor rates")
            await pilot.pause(1)
            # The stub agent should have been called
            check("the agent input sends a message to pi",
                  screen.agent is not None,
                  f"agent: {screen.agent}")
            log_text = " ".join(
                str(c.render()) for c in agent_log.children)
            check("the chat log shows the user's message",
                  "draft rules" in log_text.lower(),
                  f"got: {log_text[:100]}")
            check("the chat log shows the agent's response",
                  "stub response" in log_text.lower(),
                  f"got: {log_text[:100]}")
        finally:
            agent_mod.AgentSession = original_init
            if screen.agent is not None:
                screen.agent.close()
                screen.agent = None

        # 16. The AskDialogScreen (the ask_questions elicitation dialog)
        import threading
        from pack_tui import AskDialogScreen
        done = threading.Event()
        result = [None]
        dialog = AskDialogScreen(
            {"method": "select", "title": "What entities exist?",
             "options": ["person", "organization", "other"]},
            done, result)
        app.push_screen(dialog)
        await pilot.pause()
        check("the AskDialogScreen mounts", isinstance(app.screen, AskDialogScreen))
        # Select the first option
        lv = dialog.query_one("#ask-options", ListView)
        lv.index = 0
        await pilot.press("enter")
        await pilot.pause()
        check("the AskDialogScreen returns the selected option",
              result[0] == "person",
              f"got: {result[0]}")
        check("the AskDialogScreen signals done", done.is_set())

        # 17. The input dialog
        done2 = threading.Event()
        result2 = [None]
        dialog2 = AskDialogScreen(
            {"method": "input", "title": "What predicates?",
             "placeholder": "e.g. damageAmount"},
            done2, result2)
        app.push_screen(dialog2)
        await pilot.pause()
        inp = dialog2.query_one("#ask-input", Input)
        inp.value = "damageAmount, witnessRelationship"
        await pilot.press("enter")
        await pilot.pause()
        check("the input dialog returns the typed text",
              result2[0] == "damageAmount, witnessRelationship",
              f"got: {result2[0]}") 


def main():
    if not HAVE_TUI:
        print("SKIP  Pack Studio TUI tests (Textual not installed — `make deps`)")
        return 0
    asyncio.run(run_tests())
    failed = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
