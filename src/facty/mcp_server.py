"""facty MCP server — stdlib-only JSON-RPC 2.0 over stdio (MCP protocol).

Exposes the case-level op set — the SAME ops `facty serve` exposes — as MCP
tools, so the machine loop (any MCP-capable harness) and the human loop (Vibe
CLI) call the same interfaces (ADR-0010 §4.2 parity by construction).

The engine core + control plane stay dependency-free (ADR-0005 invariant):
this module uses only the stdlib, so it runs in the SmolVM image snapshot with
no PyPI at runtime. Run it with `facty mcp` (stdio) — a harness spawns it as a
subprocess.

Protocol shape verified against modelcontextprotocol.io/specification/
2025-06-18 (basic/transports, basic/lifecycle, server/tools; live-read
2026-11-17, logged in docs/research/deps-log.md):
  stdio transport = newline-delimited JSON-RPC 2.0, no embedded newlines
  initialize            → {protocolVersion, capabilities:{tools:{}}, serverInfo}
  notifications/initialized → no response;   ping → {}
  tools/list            → {tools: [{name, description, inputSchema}]}
  tools/call {name, arguments}
                        → {content: [{type:"text", text}], structuredContent, isError}
Tool execution failures are returned as results with isError=true (not
protocol errors), per spec.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROTOCOL_VERSIONS = ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"]
LATEST = "2025-06-18"
SERVER_INFO = {"name": "facty", "version": "0.2.0"}

# One MCP tool per `facty serve` op (parity registry — the test asserts this).
# `serve` maps the tool onto its gateway path; None = MCP/CLI-only read.
TOOLS: list[dict] = [
    {"name": "case_init", "serve": "/api/case/init",
     "description": "Create a case branch from a signed bundle (signature verified).",
     "inputSchema": {"type": "object", "required": ["case_id", "bundle_dir"],
                     "properties": {"case_id": {"type": "string"}, "bundle_dir": {"type": "string"},
                                    "model": {"type": "string"}}}},
    {"name": "case_list", "serve": "/api/cases",
     "description": "List registered cases (Case docs on main).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "case_show", "serve": "/api/case/show",
     "description": "Case manifest + doc counts on its branch.",
     "inputSchema": {"type": "object", "required": ["case_id"],
                     "properties": {"case_id": {"type": "string"}}}},
    {"name": "case_branch", "serve": "/api/case/branch",
     "description": "Branch off a case.",
     "inputSchema": {"type": "object", "required": ["case_id", "name"],
                     "properties": {"case_id": {"type": "string"}, "name": {"type": "string"}}}},
    {"name": "case_delete", "serve": "/api/case/delete",
     "description": "Delete the case branch + registry doc (real deletion).",
     "inputSchema": {"type": "object", "required": ["case_id"],
                     "properties": {"case_id": {"type": "string"}}}},
    {"name": "ingest", "serve": "/api/ingest",
     "description": "Content-addressed ingest of an evidence dir onto a case branch.",
     "inputSchema": {"type": "object", "required": ["dir", "source", "case"],
                     "properties": {"dir": {"type": "string"}, "source": {"type": "string"},
                                    "case": {"type": "string"}, "ocr": {"type": "boolean"},
                                    "no_embed": {"type": "boolean"}}}},
    {"name": "load_facts", "serve": "/api/load-facts",
     "description": "Insert fact docs (JSON) onto a case branch.",
     "inputSchema": {"type": "object", "required": ["path", "case"],
                     "properties": {"path": {"type": "string"}, "case": {"type": "string"},
                                    "message": {"type": "string"}}}},
    {"name": "sense", "serve": "/api/sense",
     "description": "LLM sensing (pydantic-ai typed output, disk-cached; FACTY_SENSE=cache replays). Induction only — never in the verdict path.",
     "inputSchema": {"type": "object", "required": ["case"],
                     "properties": {"case": {"type": "string"}}}},
    {"name": "run", "serve": "/api/run",
     "description": "Deterministic engine phase on a case branch (chain → prune → rank → verdict).",
     "inputSchema": {"type": "object", "required": ["case"],
                     "properties": {"case": {"type": "string"}, "phase": {"type": "string"}}}},
    {"name": "prove", "serve": "/api/prove",
     "description": "Backward chaining: prove a goal → proof tree. Deterministic.",
     "inputSchema": {"type": "object", "required": ["case", "subject", "predicate"],
                     "properties": {"case": {"type": "string"}, "subject": {"type": "string"},
                                    "predicate": {"type": "string"}, "value": {"type": "string"}}}},
    {"name": "assemble", "serve": "/api/assemble",
     "description": "Deterministic assembly: proven snippets → AssembledDocument.",
     "inputSchema": {"type": "object", "required": ["case"],
                     "properties": {"case": {"type": "string"}, "goal": {"type": "string"}}}},
    {"name": "answer", "serve": "/api/answer",
     "description": "Human-loop slot filling: answer an open question → typed Fact.",
     "inputSchema": {"type": "object", "required": ["case", "question", "value"],
                     "properties": {"case": {"type": "string"}, "question": {"type": "string"},
                                    "value": {"type": "string"}}}},
    {"name": "turn", "serve": "/api/turn",
     "description": "Turn dispatcher (ADR-0010 §3): run the next step of the case's signed pipeline under its determinism mode; commits a Turn doc.",
     "inputSchema": {"type": "object", "required": ["case"],
                     "properties": {"case": {"type": "string"}, "pipeline": {"type": "string"},
                                    "choice": {"type": "string"}, "value": {"type": "string"},
                                    "surface": {"type": "string", "enum": ["chat", "wizard"]},
                                    "actor": {"type": "string"}, "all": {"type": "boolean"}}}},
    {"name": "search", "serve": "/api/search",
     "description": "Semantic search over a case's embedded evidence chunks (sensing-side RAG only).",
     "inputSchema": {"type": "object", "required": ["case", "query"],
                     "properties": {"case": {"type": "string"}, "query": {"type": "string"},
                                    "top_k": {"type": "integer"}}}},
    {"name": "state", "serve": "/api/state",
     "description": "Full case state (all artifact docs on the case branch).",
     "inputSchema": {"type": "object", "required": ["case"],
                     "properties": {"case": {"type": "string"}}}},
    {"name": "log", "serve": "/api/log",
     "description": "Commit log of a case branch (the git-for-data audit trail).",
     "inputSchema": {"type": "object", "required": ["case"],
                     "properties": {"case": {"type": "string"}}}},
    {"name": "verdict", "serve": "/api/verdict",
     "description": "Verdict docs on a case branch, @id-stripped, sorted (stable hashing).",
     "inputSchema": {"type": "object", "required": ["case"],
                     "properties": {"case": {"type": "string"}}}},
    {"name": "query", "serve": "/api/query",
     "description": "Read-only WOQL query against a case branch (the LLM's tight read surface — GraphRAG/dialect patterns compile to this). Write operators in the AST are rejected; writes go through the gated ops.",
     "inputSchema": {"type": "object", "required": ["query"],
                     "properties": {"case": {"type": "string"},
                                    "query": {"type": "object"}}}},
    {"name": "interview", "serve": "/api/interview",
     "description": "Run the questionnaire loop as a pydantic-graph (gap analysis → ask → slot-fill → engine run → assemble). Every turn commits a Turn doc. chooser=llm uses the LLM only in the designated answer-pick node (ranked mode, gated+committed).",
     "inputSchema": {"type": "object", "required": ["case"],
                     "properties": {"case": {"type": "string"},
                                    "answers": {"type": "object"},
                                    "chooser": {"type": "string", "enum": ["script", "llm"]},
                                    "surface": {"type": "string", "enum": ["chat", "wizard"]},
                                    "actor": {"type": "string"}, "max_turns": {"type": "integer"},
                                    "pipeline": {"type": "string"}}}},
    {"name": "bundles", "serve": None,
     "description": "List the signed bundles in bundles/ (the only pack/case/demo form).",
     "inputSchema": {"type": "object", "properties": {}}},
]

TOOL_SERVE_PATH = {t["name"]: t["serve"] for t in TOOLS}


def call_tool(name: str, args: dict) -> dict:
    """THIN dispatch: one MCP tool per op in ops.py, called by name with the
    tool's arguments as kwargs (inputSchema property names == op kwargs).
    No op logic lives here. Raises on bad input — the protocol layer converts
    that to isError=true."""
    from . import ops
    from .client import Client
    fn = getattr(ops, name, None)
    if fn is None or name.startswith("_"):
        raise ValueError(f"unknown tool {name!r}")
    return fn(Client(), **args)


def _result(id, payload: dict, is_error: bool = False) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, default=str, indent=2)
    r = {"jsonrpc": "2.0", "id": id,
         "result": {"content": [{"type": "text", "text": text}]}}
    if not isinstance(payload, str):
        r["result"]["structuredContent"] = payload
    if is_error:
        r["result"]["isError"] = True
    return r


def handle(msg: dict) -> dict | None:
    """One JSON-RPC message → response dict, or None for notifications."""
    mid = msg.get("id")
    method = msg.get("method", "")
    if mid is None:  # notification — never answered (notifications/initialized)
        return None
    if method == "initialize":
        requested = (msg.get("params") or {}).get("protocolVersion")
        pv = requested if requested in PROTOCOL_VERSIONS else LATEST
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": pv,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [
            {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"]}
            for t in TOOLS]}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name, args = params.get("name"), params.get("arguments") or {}
        try:
            payload = call_tool(name, args)
            return _result(mid, payload)
        except Exception as e:  # tool errors are results, not protocol errors
            return _result(mid, {"error": str(e)}, is_error=True)
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def serve_stdio() -> None:
    """MCP stdio loop: newline-delimited JSON-RPC on stdin/stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue  # not JSON-RPC — ignore (a stray log line must not kill the loop)
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
