#!/usr/bin/env python3
# sensing.py — the probabilistic half: schema-guided structured extraction.
#
# The sensing motion, made explicit: a JSON schema + a messy piece of
# input from the field → a typesafe, schema-validated structured object
# that the logic engine can consume. Entity extraction and classification
# are sensing operations — the engine verifies what the senses produce;
# it never extracts or classifies.
#
# The loop: sense (probabilistic) → judge (schema + compute checks) →
# solve (symbolic). When the judge rejects the structured output — a
# parse error, a schema violation, or a compute error from working with
# the objects — the LLM gets a capped number of correction turns
# (max_attempts) with the errors fed back, before the corrected output
# passes the judge layer for real. An unreachable LLM fails fast: that
# error cannot correct itself, so it is never retried.
#
# The golden path for the LLM transport is the pi agent, driven over its
# RPC mode (`pi --mode rpc`): pi owns the credential (and its refresh) and
# the engine process never sees it — the same isolation posture as the VM
# host-secret mechanism. A direct Mistral client is deliberately not used.
# RPC mode streams the response as text_delta events (real live output,
# unlike `pi -p`, which prints the whole response at the end), and the
# runner shuts pi down the moment the agent settles — no lingering
# process, and `--no-session` means no session files pile up per call.
# Callers fall back to recorded sensing artifacts when the LLM is
# unreachable or the retries exhaust.
#
# Library:
#   from sensing import extract_structured, CLASSIFY_TASK, ENTITIES_TASK
#   obj = extract_structured("engine/schemas/facts.schema.json", task, stream=print)

import json
import os
import subprocess
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import procs   # noqa: E402  (subprocess registry — no dangling processes)

# The provider/model the sensing calls use — env-overridable so custom
# providers work today (via pi's own provider config); the future
# providers config (docs/PROVIDERS.md) will drive these same knobs.
PROVIDER = os.environ.get("FACTY_PROVIDER", "mistral-subscription")
MODEL = os.environ.get("FACTY_MODEL", "mistral-large-4")
# Thinking level for the sensing/commentary calls. Default OFF: these are
# one-shot extractions — the model reads the inlined assignment and
# answers, it does not deliberate. Measured on the demo cases: ~4.5x
# faster end-to-end (15s vs 69s per call) with comparable output.
THINKING = os.environ.get("FACTY_THINKING", "off")
MAX_ATTEMPTS = 3               # total turns: 1 initial + up to 2 corrections
PREVIOUS_RESPONSE_CAP = 4000   # chars of the previous response fed back

CLASSIFY_TASK = """Classify the raw evidence files of a detective case. For each file,
produce an evidence item: the file name, an evidence class (one of: log,
report, correspondence, roster, note, financial-record, other), a
one-sentence summary, and an honest confidence (0-1).

Files:
{{FILES}}
"""

ENTITIES_TASK = """Extract the entities of a detective case from raw evidence:
every person, animal, place, and object that matters to the case. For
each entity: a stable id (e.g. "e-straker"), the name, a kind (one of:
person, animal, place, object, organization), a one-line role, the source
spans where it is mentioned, and an honest confidence (0-1).

Evidence:
{{FILES}}
"""


def describe(result, noun="items"):
    """A short human descriptor for a validated extraction result."""
    if isinstance(result, list):
        return f"{len(result)} {noun}"
    if isinstance(result, dict):
        return "object with keys " + ", ".join(list(result)[:5])
    return type(result).__name__


def staged_prompt_path(label):
    """Where a sensing prompt is staged (persisted for inspection)."""
    return ENGINE_DIR.parent / ".agentic" / "tmp" / f"sensing-{label}.md"


def pi_command():
    """The exact pi invocation for a staged assignment — RPC mode (the
    assignment itself travels over stdin as a JSONL `prompt` command,
    inlined). Printable, copy-pasteable for debugging. Lean and one-shot:
    no session files, no skills / context files / MCP / prompt templates
    / themes, and NO TOOLS — the assignment carries everything it needs
    (the evidence is inlined by the task builders), so the model answers
    in a single LLM call instead of agentic-looping through the read
    tool. The extensions stay (the mistral-subscription provider is
    one)."""
    cmd = ["pi", "--mode", "rpc", "--no-session", "--no-tools",
           "--no-context-files", "--no-skills", "--no-mcp",
           "--no-prompt-templates", "--no-themes",
           "--provider", PROVIDER, "--model", MODEL]
    if THINKING:
        cmd += ["--thinking", THINKING]
    return cmd


def _pi_runner(staged_path, stream):
    """Call the LLM via pi's RPC mode, streaming. The staged assignment
    (self-contained — the evidence is inlined) travels as a JSONL
    `prompt` command on stdin; `text_delta` events stream the response
    (reassembled into lines for the stream callback). `agent_settled`
    ends the call — pi is shut down immediately (no lingering after the
    response, no session files). Returns the full response text. Raises
    RuntimeError if the call fails (unreachable / no credential). The
    subprocess registers with procs — a quit mid-call leaves nothing
    behind (kill_all on exit)."""
    proc = subprocess.Popen(pi_command(), stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1, start_new_session=True)
    procs.register(proc)
    try:
        prompt = Path(staged_path).read_text()
        try:
            proc.stdin.write(json.dumps({"id": "sense", "type": "prompt",
                                         "message": prompt}) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError(f"pi exited before the prompt was accepted: {exc}")
        chunks, pending, settled = [], "", False
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue  # not a protocol record
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
            elif rtype == "response" and rec.get("id") == "sense" \
                    and not rec.get("success", True):
                raise RuntimeError(f"pi rejected the prompt: {rec.get('error')}")
            elif rtype == "agent_settled":
                settled = True
                break
        if stream is not None and pending:
            stream(pending)  # the final partial line
        proc.stdin.close()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        stderr = proc.stderr.read()
    except BaseException:
        proc.kill()  # never leave a pi behind on the error path
        raise
    finally:
        procs.unregister(proc)
    if proc.returncode != 0:
        raise RuntimeError(stderr.strip() or f"pi exited with code {proc.returncode}")
    if not settled:
        raise RuntimeError("pi RPC ended without agent_settled")
    return "".join(chunks)


def llm_text(task, stream=None, label="explain", runner=None):
    """One LLM call for prose (no schema, no judge, no correction loop):
    stage the assignment, stream the response, return the full text.
    Used for out-of-band commentary (cli.explain) — the response cache is
    the caller's business."""
    runner = runner or _pi_runner
    staged = staged_prompt_path(label)
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(task)
    return runner(str(staged), stream)


def _correction_prompt(task, schema_text, errors, previous):
    """The retry turn: the original task + the judge's errors + the
    rejected response, asking for a corrected structured value."""
    return (
        f"{task}\n\n"
        "Your previous response was rejected by the judge layer:\n\n"
        + "\n".join(f"- {e}" for e in errors[:5])
        + f"\n\nPrevious response:\n{previous[:PREVIOUS_RESPONSE_CAP]}\n\n"
        "Correct it. Respond with ONLY a pretty-printed JSON value that "
        "validates against this schema — no prose, no commentary, no "
        f"markdown fences:\n\n{schema_text}"
    )


def extract_structured(schema, task, stream=None, label="extract",
                       judge=None, max_attempts=MAX_ATTEMPTS,
                       runner=None, note=None, debug=False, on_response=None):
    """Schema-guided extraction with a capped correction loop.

    Each turn: the LLM responds (streamed) → the judge layer parses and
    validates (schema + optional compute checks) → pass returns the
    object; reject feeds the errors back for a correction turn. Capped at
    max_attempts total turns; exhaustion raises ValueError. An
    unreachable LLM raises RuntimeError immediately (never retried).

    schema:  path to a JSON-schema file, or a schema dict.
    task:    the extraction instruction (may contain @file refs and
             embedded JSON — the messy input lives there).
    stream:  optional callable, fed each streamed output line.
    label:   names the staged prompt file (engine tmp).
    judge:   optional callable(obj) → list of error strings (compute
             checks on the structured objects).
    runner:  optional callable(staged_path, stream) → response text
             (defaults to the pi -p runner; tests stub this).
    note:    optional callable(msg) for progress lines.
    debug:   include the raw response in rejection notes.
    on_response: optional callable(raw_text) — called with the raw
             response of the accepted attempt (the response cache
             stores it).
    """
    if isinstance(schema, dict):
        schema_text = json.dumps(schema)
        schema_dict = schema
    else:
        schema_text = Path(schema).read_text()
        schema_dict = json.loads(schema_text)
    runner = runner or _pi_runner
    staged = staged_prompt_path(label)
    staged.parent.mkdir(parents=True, exist_ok=True)

    prompt = (
        f"{task}\n\n"
        "Respond with ONLY a pretty-printed JSON value that validates "
        "against this schema — no prose, no commentary, no markdown fences:\n\n"
        f"{schema_text}"
    )
    for attempt in range(1, max_attempts + 1):
        staged.write_text(prompt)
        text = runner(str(staged), stream)  # RuntimeError = unreachable, fail fast
        try:
            obj = parse_and_validate(text, schema_dict)
            errs = list(judge(obj)) if judge else []
        except ValueError as exc:
            errs = [str(exc)]
        else:
            if not errs:
                if note:
                    note(f"attempt {attempt}/{max_attempts} accepted by the judge layer")
                if on_response:
                    on_response(text)
                return obj
        if attempt < max_attempts:
            detail = "; ".join(errs[:3])
            if debug:
                detail += f" | response: {text[:300]!r}"
            if note:
                note(f"attempt {attempt}/{max_attempts} rejected — {detail}; correcting")
            prompt = _correction_prompt(task, schema_text, errs, text)
            continue
        raise ValueError(f"judge rejected the output after {max_attempts} "
                         f"attempts: {'; '.join(errs)}")
    raise ValueError("unreachable")  # pragma: no cover


def parse_and_validate(text, schema):
    """Parse the first JSON value from an LLM response and validate it
    against the schema (engine.validate, with $ref support)."""
    cleaned = text
    if "```" in cleaned:
        parts = cleaned.split("```")
        if len(parts) > 1:
            cleaned = parts[1]
    starts = [s for s in (cleaned.find("{"), cleaned.find("[")) if s != -1]
    if not starts:
        raise ValueError("no JSON value found in the response")
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned, min(starts))
    except json.JSONDecodeError as exc:
        raise ValueError(f"unparseable JSON: {exc}") from exc
    errs = engine.validate(obj, schema)
    if errs:
        raise ValueError("schema violations: " + "; ".join(errs))
    return obj
