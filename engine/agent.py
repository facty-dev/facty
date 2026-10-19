#!/usr/bin/env python3
# agent.py — the embedded agent: a persistent pi RPC session for the
# Pack Studio TUI (the knowledge engineer's pair programmer, PRD-007
# SOL-003-A / REQ-F2).
#
# The transport is the same pi RPC mode as sensing (engine/sensing.py):
# one pi process per Pack Studio session, the assignment travels as a
# JSONL `prompt` command over stdin, the response streams back as
# `text_delta` events. The difference from sensing: the process is
# PERSISTENT (the conversation history is maintained across messages),
# and the system prompt is the pack-factory brief (the agent helps
# author the pack — drafts rules, suggests labels, reviews gaps).
#
# The agent is induction-only — never in the verdict path (ADR-0003 §1).
# Its drafts are proposals; the human accepts; the engine validates.
#
# Tool calls (the ask_questions elicitation dialog — the meta-Facty
# loop, SOL-002-A) are handled by the TUI: when the agent calls a tool,
# the TUI shows the dialog, collects the answer, and sends the tool
# result back over the same RPC pipe.
#
# Library:
#   from agent import AgentSession
#   sess = AgentSession(pack_context="pack: insurance-fraud · 4 rules · ...")
#   for line in sess.send("draft rules for detecting inflated labor rates"):
#       print(line)
#   sess.close()

import json
import subprocess
import sys
import threading
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import procs  # noqa: E402  (subprocess registry — no dangling processes)

PROVIDER = "mistral-subscription"
MODEL = "mistral-large-4"
THINKING = "off"  # chat is interactive — no thinking blocks

# The system prompt: the pack-factory brief. Short for the MVP — the
# full skill lives at gondolin/skills/pack-factory/SKILL.md (the VM's
# pack factory loads it via pi's skill system; the TUI inlines a brief).
SYSTEM_PROMPT = """You are the pack factory — the knowledge engineer's pair programmer
inside Facty's Pack Studio. You help a domain expert author a pack (the
rules, constraints, hypotheses, and sensor config that let Facty reason
with their expertise).

The pack lives at packs/<slug>/. The engine owns the verdict — you are
induction-only: your drafts are proposals, the human accepts, the engine
validates. Never feed the engine's conclusions (verdicts, scores,
rankings, derived facts, prunings) back to the user — that biases their
answers.

The pack's artifacts:
- pack/rules.json — forward-chaining rules (when → then: derive / raise / open)
- pack/constraints.json — eliminate / support hypotheses
- pack/hypotheses.json — the explanation space (statements, priors, claims)
- classify.json — the label sensor config (labels, threshold, template)
- sensor/decisions.json — the Strom decision questions

Schemas: engine/schemas/. The engine validates every artifact.

The pack's current state is given below. Help the user author it:
draft rules from plain language, suggest labels, review for gaps
(dead rules, unraised hypotheses, unanswered questions), explain
engine behavior. Be terse — the user is a domain expert, not a Facty
engineer.
"""


def pi_command(system_prompt=None):
    """The pi invocation for the embedded agent — RPC mode, persistent,
    tools ENABLED (the ask_questions elicitation dialog needs them).
    Lean otherwise: no session files, no context files, no MCP."""
    cmd = ["pi", "--mode", "rpc", "--no-session",
           "--no-context-files", "--no-mcp",
           "--no-prompt-templates", "--no-themes",
           "--provider", PROVIDER, "--model", MODEL,
           "--thinking", THINKING]
    if system_prompt:
        # Stage the system prompt to a file (long prompts break arg handling)
        sp = Path("/tmp/facty-agent-system-prompt.md")
        sp.write_text(system_prompt)
        cmd += ["--system-prompt-file", str(sp)]
    return cmd


class AgentSession:
    """One pi RPC process for the embedded agent's chat (a Pack Studio
    session). The conversation history is maintained across messages
    (the process stays alive). The process registers with procs — a
    quit leaves nothing behind."""

    def __init__(self, pack_context=""):
        self.proc = None
        self.messages = 0
        self._lock = threading.Lock()
        prompt = SYSTEM_PROMPT
        if pack_context:
            prompt += f"\n\nThe pack's current state:\n{pack_context}\n"
        self._system_prompt = prompt

    def _spawn(self):
        self.proc = subprocess.Popen(
            pi_command(self._system_prompt),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
            start_new_session=True)
        procs.register(self.proc)

    def _kill(self):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass
        procs.unregister(proc)

    def close(self):
        """Shut pi down (stdin close → pi exits; kill on timeout)."""
        proc, self.proc = self.proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        procs.unregister(proc)

    def send(self, message, stream=None):
        """Send a user message to the agent; stream the response lines.
        Returns the full response text. Raises RuntimeError on failure.

        The stream callback receives lines (strings) as they arrive.
        Tool calls (ask_questions) are NOT handled here — the TUI must
        pass a tool_handler callback for that (the MVP streams text
        only; tool support is the meta-Facty loop follow-up)."""
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                self._spawn()
            self.messages += 1
            req = f"agent-{self.messages}"
            try:
                self.proc.stdin.write(
                    json.dumps({"id": req, "type": "prompt",
                                "message": message}) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._kill()
                raise RuntimeError(
                    f"pi exited before the prompt was accepted: {exc}")
            chunks, pending, settled = [], "", False
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rtype = rec.get("type")
                if rtype == "message_update":
                    ev = rec.get("assistantMessageEvent") or {}
                    if ev.get("type") == "text_delta":
                        delta = ev.get("delta", "")
                        chunks.append(delta)
                        if stream is not None:
                            pending += delta
                            while "\n" in pending:
                                out, pending = pending.split("\n", 1)
                                stream(out)
                elif rtype == "response" and rec.get("id") == req \
                        and not rec.get("success", True):
                    self._kill()
                    raise RuntimeError(
                        f"pi rejected the prompt: {rec.get('error')}")
                elif rtype == "agent_settled":
                    settled = True
                    break
            if stream is not None and pending:
                stream(pending)
            if not settled:
                err = ""
                try:
                    err = (self.proc.stderr.read() or "").strip()
                except OSError:
                    pass
                self._kill()
                raise RuntimeError(
                    err or "pi RPC ended without agent_settled")
            return "".join(chunks)


def pack_context(pack_dir):
    """Build the pack's current state for the agent's system prompt:
    the artifact counts + the term vocabulary (predicates, subjects)."""
    import pack as pack_lib
    try:
        report = pack_lib.validate_pack(pack_dir)
        c = report["counts"]
        lines = [f"pack: {Path(pack_dir).name}",
                 f"  rules: {c['rules']} · hypotheses: {c['hypotheses']} · "
                 f"constraints: {c['constraints']} · tests: {c['tests']}"]
        if not report["ok"]:
            lines.append(f"  validation: {len(report['violations'])} violation(s)")
            for v in report["violations"][:3]:
                lines.append(f"    ✗ {v['file']}: {v['message']}")
        # The term vocabulary (predicates + subjects from the rules)
        try:
            rules = pack_lib.load_pack(pack_dir)["rules"]
            preds, subs = set(), set()
            for r in rules:
                for cond in r.get("when", []):
                    if "predicate" in cond:
                        preds.add(cond["predicate"])
                    if "subject" in cond:
                        subs.add(cond["subject"])
            if preds:
                lines.append(f"  predicates: {', '.join(sorted(preds))}")
            if subs:
                lines.append(f"  subjects: {', '.join(sorted(subs))}")
        except Exception:
            pass
        return "\n".join(lines)
    except Exception as exc:
        return f"pack: {Path(pack_dir).name} (error reading state: {exc})"
