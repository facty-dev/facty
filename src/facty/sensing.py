"""Sensing: the LLM half, programmatic (machine-driven workflows).

Two backends:

  pydantic (default when pydantic-ai is importable): in-process Agent with
    NO tools and a typed `output_type` — a pure function call. PydanticAI's
    retries apply only to the *shape* of the LLM's structured output (induction
    side), never to the verdict path.
  vibe:  headless one-shot `vibe -p` subprocess — fallback when pydantic-ai is
    not installed (e.g. a bare VM), and the same CLI used for human-facing
    sessions (pack-author agent, TerminusDB MCP tools).

The Vibe CLI is deliberately NOT used in the machine-driven loop: subprocess
per call, no typed outputs, session machinery. Human interaction goes through
it; machine calls go through pydantic-ai.

Cache: raw responses cached on disk; FACTY_SENSE=cache replays without any LLM,
so the verdict path stays deterministic.

Env:
  FACTY_SENSE         "live" (default) | "cache"
  FACTY_SENSE_BACKEND "pydantic" (default if importable) | "vibe"
  FACTY_MODEL         default "mistral-large-4"  (pydantic: "mistral:<model>")
  VIBE_BIN            default "vibe"
  MISTRAL_API_KEY     picked up by pydantic-ai's mistral provider / vibe auth
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TypeVar

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / ".cache" / "sensing"
METRICS_PATH = ROOT / ".cache" / "sensing-metrics.jsonl"


def _maybe_logfire():
    """Opt-in tracing: FACTY_LOGFIRE=1 enables logfire + pydantic-ai
    instrumentation. Off by default — the VM egress allow-list has no
    observability endpoint, so nothing leaves by default. Logfire is plain
    OTel: point OTEL_EXPORTER_OTLP_ENDPOINT at a self-hosted collector, or
    FACTY_LOGFIRE=hosted to send to the Logfire platform.
    """
    if os.environ.get("FACTY_LOGFIRE") != "1":
        return
    try:
        import logfire

        logfire.configure(send_to_logfire=os.environ.get("FACTY_LOGFIRE") == "hosted")
        logfire.instrument_pydantic_ai()
        print("[sense] logfire tracing on", file=sys.stderr)
    except ImportError:
        print("[sense] FACTY_LOGFIRE=1 but logfire not installed — metrics only", file=sys.stderr)


def _metric(op: str, model: str, seconds: float, usage, cached: bool):
    """Always-on, zero-egress metrics: stderr line + local JSONL log."""
    req = getattr(usage, "request_tokens", None) if usage else None
    out = getattr(usage, "output_tokens", None) if usage else None
    print(f"[sense] {op} done in {seconds:.1f}s · in={req} out={out} tokens · cached={cached}",
          file=sys.stderr)
    import datetime

    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with METRICS_PATH.open("a") as f:
        f.write(json.dumps({
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "op": op, "model": model, "seconds": round(seconds, 3),
            "input_tokens": req, "output_tokens": out, "cached": cached,
        }) + "\n")

SYSTEM_INSTRUCTION = """You are the SENSES of a detective decision-support system. \
You read messy evidence and output structured data only. \
You never decide, rank, or conclude — the symbolic engine owns the verdict."""

T = TypeVar("T")

# ── typed output models (mirror the TerminusDB schema classes) ───────────────
try:
    from pydantic import BaseModel

    class SensedFact(BaseModel):
        id: str
        type: str = "evidence"          # case | evidence | derived
        subject: str
        predicate: str
        value: str | bool | float
        confidence: float
        source: str
        observedAt: str | None = None

    class SensedFacts(BaseModel):
        facts: list[SensedFact]

except ImportError:  # stdlib-only fallback; the vibe backend parses JSON text
    BaseModel = object
    SensedFact = SensedFacts = None


def _cache_path(key: str) -> Path:
    return CACHE_DIR / (hashlib.sha256(key.encode()).hexdigest()[:16] + ".json")


def _cached(key: str, produce, op: str = "sense") -> str:
    """Disk cache of raw LLM responses. FACTY_SENSE=cache replays, never calls."""
    import time

    cpath = _cache_path(key)
    if os.environ.get("FACTY_SENSE", "live") == "cache":
        if not cpath.exists():
            raise RuntimeError(f"FACTY_SENSE=cache but no cached response at {cpath}")
        _metric(op, "-", 0.0, None, cached=True)
        return json.loads(cpath.read_text())["text"]
    model = f"mistral:{os.environ.get('FACTY_MODEL', 'mistral-large-4')}"
    print(f"[sense] {op} → {model} (prompt {len(key)} chars) …", file=sys.stderr)
    t0 = time.monotonic()
    text, usage = produce()
    _metric(op, model, time.monotonic() - t0, usage, cached=False)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cpath.write_text(json.dumps({"key": key, "text": text}, indent=2))
    return text


def _backend() -> str:
    b = os.environ.get("FACTY_SENSE_BACKEND", "").lower()
    if b:
        return b
    try:
        import pydantic_ai  # noqa: F401

        return "pydantic"
    except ImportError:
        return "vibe"


def _sense_pydantic(prompt: str, output_type):
    """In-process, no tools, typed output. Returns (text, usage)."""
    from pydantic_ai import Agent

    _maybe_logfire()
    model = f"mistral:{os.environ.get('FACTY_MODEL', 'mistral-large-4')}"
    agent = Agent(model, instructions=SYSTEM_INSTRUCTION, output_type=output_type, retries=3)
    result = agent.run_sync(prompt)
    out = result.output
    text = out if isinstance(out, str) else (
        out.model_dump_json() if hasattr(out, "model_dump_json") else json.dumps(out))
    return text, result.usage  # RunUsage property in pydantic-ai v2


def _extract_text(payload) -> str:
    """Tolerantly pull the final assistant text out of a `vibe -p --output json` export."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        msgs = payload.get("messages") or payload.get("transcript") or []
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "assistant":
                c = m.get("content")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    return "\n".join(
                        p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"
                    )
        for key in ("output", "text", "response", "content"):
            if isinstance(payload.get(key), str):
                return payload[key]
    raise RuntimeError(f"could not extract text from vibe --output json payload: {str(payload)[:300]}")


def _sense_vibe(prompt: str) -> str:
    """Fallback backend: one-shot headless Vibe CLI call (no tools, single turn)."""
    vibe = os.environ.get("VIBE_BIN", "vibe")
    env = dict(os.environ)
    env.setdefault("VIBE_ACTIVE_MODEL", "facty-large")  # alias → mistral-large-4 (project config)
    cmd = [
        vibe, "-p", f"{SYSTEM_INSTRUCTION}\n\n{prompt}",
        "--agent", "sensing",
        "--max-turns", "1",
        "--output", "json",
        "--trust",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=720)
    if proc.returncode != 0:
        raise RuntimeError(f"vibe -p failed ({proc.returncode}): {proc.stderr[:800]}")
    if proc.stdout.strip().startswith(("{", "[")):
        return _extract_text(json.loads(proc.stdout))
    return proc.stdout


def sense_text(prompt: str) -> str:
    """One-shot LLM call returning plain text (cached)."""
    key = f"{_backend()}|text|{prompt}"
    return _cached(key, lambda: (_sense_pydantic(prompt, str) if _backend() == "pydantic" else (_sense_vibe(prompt), None)), op="text")


def sense_json(prompt: str, output_model=None):
    """One-shot LLM call returning a validated structured object (cached).

    output_model: a pydantic BaseModel subclass (e.g. SensedFacts). With the
    vibe backend the model is instructed to emit JSON and it is parsed.
    """
    if output_model is not None and _backend() == "pydantic":
        key = f"pydantic|{output_model.__name__}|{prompt}"
        raw = _cached(key, lambda: _sense_pydantic(prompt, output_model), op=output_model.__name__)
        return output_model.model_validate_json(raw)
    # vibe backend (or no pydantic models): ask for JSON text, parse tolerantly
    key = f"{_backend()}|json|{prompt}"
    text = _cached(key, lambda: (_sense_pydantic(prompt, str) if _backend() == "pydantic" else (_sense_vibe(prompt + "\nAnswer with ONLY a single JSON object."), None)), op="json")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError(f"sensing response is not JSON: {text[:300]}")
    return json.loads(text[start:end + 1])
