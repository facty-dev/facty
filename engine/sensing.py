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
# The golden path for the LLM transport is the pi agent (`pi -p`): pi owns
# the credential (and its refresh) and the engine process never sees it —
# the same isolation posture as the VM host-secret mechanism. A direct
# Mistral client is deliberately not used. Callers fall back to recorded
# sensing artifacts when the LLM is unreachable or the retries exhaust.
#
# Library:
#   from sensing import extract_structured, CLASSIFY_TASK, ENTITIES_TASK
#   obj = extract_structured("engine/schemas/facts.schema.json", task, stream=print)

import json
import subprocess
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402

PROVIDER = "mistral-subscription"
MODEL = "mistral-large-4"
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


def pi_command(staged_path):
    """The exact pi invocation for a staged sensing prompt — printable,
    copy-pasteable for debugging."""
    return ["pi", "-p", "--provider", PROVIDER, "--model", MODEL,
            f"Read your complete sensing assignment in @{Path(staged_path).resolve()} "
            "and execute it in full. Respond with ONLY the JSON value."]


def _pi_runner(staged_path, stream):
    """Call the LLM via `pi -p`, streaming. Returns the full response text.
    Raises RuntimeError if the call fails (unreachable / no credential)."""
    cmd = pi_command(staged_path)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1)
    chunks = []
    for line in proc.stdout:
        chunks.append(line)
        if stream:
            stream(line.rstrip("\n"))
    stderr = proc.stderr.read()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(stderr.strip() or f"pi exited with code {proc.returncode}")
    return "".join(chunks)


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
                       runner=None, note=None, debug=False):
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
