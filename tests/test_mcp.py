"""facty MCP server tests: protocol shape (MCP over stdio), CLI↔serve↔MCP
parity registry, and a live tools/call run against a scratch TerminusDB db.

Run: uv run pytest tests/test_mcp.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from facty import mcp_server, serve
from facty.client import Client
from facty.schema import SCHEMA

pytestmark = pytest.mark.skipif(
    os.environ.get("FACTY_TEST_NO_DB") == "1", reason="needs TerminusDB on :6363")

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "bundles" / "small-business-contract-claim"
FIXTURES = BUNDLE / "fixtures" / "facts-initial.json"


# ── parity: one op set behind CLI / serve / MCP (ADR-0010 §4) ────────────────

def test_mcp_tools_cover_every_serve_op():
    serve_paths = {f"/api/{p}" for p in serve.POST_OPS + serve.GET_OPS}
    tool_paths = {p for p in mcp_server.TOOL_SERVE_PATH.values() if p}
    # every serve op except the streaming/meta endpoints has an MCP tool
    missing = {p for p in serve_paths if p not in tool_paths} - {"/api/watch", "/api/ops"}
    assert not missing, f"serve ops without MCP tool: {missing}"
    # every mapped MCP tool points at a real serve op
    assert tool_paths <= serve_paths
    # and the reverse: every serve op (minus watch/ops) is covered — no orphans
    assert serve_paths - {"/api/watch", "/api/ops"} <= tool_paths


def test_thin_dispatch_structure():
    """The thinnest-wrapper invariant: transports own no logic —
    serve routes are one-line lambdas over ops.py, and every MCP tool name
    IS an ops.py function (called by name with the tool args as kwargs)."""
    from facty import ops
    # every MCP tool dispatches to an ops function of the same name
    for t in mcp_server.TOOLS:
        assert hasattr(ops, t["name"]), f"MCP tool {t['name']} has no ops.{t['name']}"
    # the serve op registry is derived from the route tables (single source)
    assert serve.POST_OPS == sorted(p[len("/api/"):] for p in serve.POST_ROUTES)
    assert set(serve.GET_OPS) == {p[len("/api/"):] for p in serve.GET_ROUTES} | {"watch"}
    # every route maps into /api/<op> form
    assert all(p.startswith("/api/") for p in serve.POST_ROUTES)
    assert all(p.startswith("/api/") for p in serve.GET_ROUTES)


# ── protocol shape ───────────────────────────────────────────────────────────

def test_initialize_ping_tools_list():
    r = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18"}})
    assert r["result"]["protocolVersion"] == "2025-06-18"
    assert r["result"]["capabilities"]["tools"]
    assert r["result"]["serverInfo"]["name"] == "facty"
    # unknown requested version → server picks one it supports
    r = mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize",
                           "params": {"protocolVersion": "1999-01-01"}})
    assert r["result"]["protocolVersion"] in mcp_server.PROTOCOL_VERSIONS
    assert mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "ping"})["result"] == {}
    # notifications are never answered
    assert mcp_server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    r = mcp_server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"run", "turn", "sense", "answer", "assemble", "ingest"} <= names
    assert all(t["inputSchema"]["type"] == "object" for t in r["result"]["tools"])
    r = mcp_server.handle({"jsonrpc": "2.0", "id": 5, "method": "bogus/method"})
    assert r["error"]["code"] == -32601
    # tool errors are results with isError, not protocol errors
    r = mcp_server.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                           "params": {"name": "nope", "arguments": {}}})
    assert r["result"]["isError"] is True


# ── live stdio loop (real subprocess, like a harness spawns it) ──────────────

def test_stdio_subprocess_handshake():
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src") + os.pathsep + env.get("PYTHONPATH", "")
    p = subprocess.Popen([sys.executable, "-m", "facty", "mcp"], cwd=REPO,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, env=env)
    try:
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                  "params": {"protocolVersion": "2025-06-18",
                                             "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}) + "\n")
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
        p.stdin.flush()
        line1 = p.stdout.readline()
        line2 = p.stdout.readline()  # notification must NOT produce a response
        r1, r2 = json.loads(line1), json.loads(line2)
        assert r1["id"] == 1 and r1["result"]["protocolVersion"] == "2025-06-18"
        assert r2["id"] == 2 and any(t["name"] == "turn" for t in r2["result"]["tools"])
    finally:
        p.terminate()
        p.wait(timeout=10)


# ── tools/call end to end on a scratch db ────────────────────────────────────

@pytest.fixture()
def scratch_db(monkeypatch):
    monkeypatch.setenv("TERMINUSDB_DB", "facty-mcptest")
    c = Client(db="facty-mcptest")
    if c.db_exists():
        c.delete_db()
    c.create_db()
    c.install_schema(SCHEMA)
    yield
    c.ref = "main"
    c.delete_db()


def test_query_op_read_only_guard(scratch_db):
    """The tight-read/gated-write boundary: WOQL reads pass through; any write
    operator in the AST is rejected (writes go through the gated ops only)."""
    from facty import ops, woql
    mcp_server.call_tool("case_init", {"case_id": "q1", "bundle_dir": str(BUNDLE)})
    mcp_server.call_tool("load_facts", {"path": str(FIXTURES), "case": "q1"})
    q = woql.select(["F"], woql.fact_pattern("F", predicate="amount"))
    r = mcp_server.call_tool("query", {"case": "q1", "query": q})
    assert r["bindings"], "read query should return bindings"
    for bad in ({"@type": "Insert", "data": q},
                {"@type": "And", "and": [q, {"@type": "Delete", "data": q}]}):
        with pytest.raises(ValueError, match="read-only"):
            ops.query(Client(db="facty-mcptest"), "q1", bad)


def test_tools_call_case_flow(scratch_db, monkeypatch):
    # hermetic: never a live LLM call, even if a free-mode step is reached
    monkeypatch.setattr("facty.sensing.sense_json",
                        lambda prompt, model=None: {"facts": []})
    r = mcp_server.call_tool("case_init", {"case_id": "mcp1", "bundle_dir": str(BUNDLE)})
    assert r["case"] == "mcp1"
    r = mcp_server.call_tool("load_facts", {"path": str(FIXTURES), "case": "mcp1"})
    assert r["loaded"] > 0
    r = mcp_server.call_tool("run", {"case": "mcp1", "phase": "1"})
    assert r["winner"] == "H1"
    # turn dispatcher over MCP: bundle pipeline stops at the ranked answer step
    r = mcp_server.call_tool("turn", {"case": "mcp1", "all": True})
    assert r["awaiting"] == "choice" and r["options"]
    r = mcp_server.call_tool("turn", {"case": "mcp1", "choice": r["options"][0],
                                      "value": "true", "all": True})
    assert r["done"] is True
    r = mcp_server.call_tool("assemble", {"case": "mcp1"})
    assert r["@type"] == "AssembledDocument"
    r = mcp_server.call_tool("state", {"case": "mcp1"})
    types = {d["@type"] for d in r["docs"]}
    assert {"Verdict", "Turn", "Pipeline", "AssembledDocument"} <= types
    r = mcp_server.call_tool("verdict", {"case": "mcp1"})
    assert r["verdicts"]
