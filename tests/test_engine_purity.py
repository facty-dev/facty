"""Guard tests for the verdict-path purity invariant (ADR-0003 §1,
PHILOSOPHY.md §3/§7): the engine core never touches the LLM, a clock, or a
random source, and the sensing layer is a tool-less typed function call.

Source-level (AST) so the invariant is checked structurally, not by
behaviour alone.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "facty"

FORBIDDEN_IMPORTS = {"sensing", "datetime", "random", "time", "uuid"}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def test_engine_core_has_no_llm_clock_or_random_imports():
    for name in ("engine.py", "rules.py", "woql.py", "client.py"):
        mods = _imported_modules(SRC / name)
        bad = mods & FORBIDDEN_IMPORTS
        assert not bad, f"{name} imports forbidden modules: {bad}"


def test_engine_code_has_no_clock_random_or_sensing_references():
    # AST-level: comments/docstrings may *mention* sensing.py, code may not use it.
    tree = ast.parse((SRC / "engine.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_IMPORTS:
            raise AssertionError(f"engine.py uses forbidden name {node.id!r} at line {node.lineno}")
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in FORBIDDEN_IMPORTS):
            raise AssertionError(f"engine.py uses {node.value.id}.{node.attr} at line {node.lineno}")


def test_sensing_agent_is_toolless_typed_call():
    tree = ast.parse((SRC / "sensing.py").read_text())
    agent_calls = [n for n in ast.walk(tree)
                   if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Name) and n.func.id == "Agent"]
    assert agent_calls, "sensing.py must construct a pydantic-ai Agent"
    for call in agent_calls:
        kw = {k.arg: k.value for k in call.keywords}
        assert "output_type" in kw, "sensing Agent must use typed structured output"
        tools = kw.get("tools")
        assert tools is None or (isinstance(tools, ast.List) and not tools.elts), \
            "sensing Agent must be tool-less (tools=[] or omitted)"


def test_ops_query_guard_rejects_write_ops():
    from facty import ops

    for bad in ({"@type": "Insert", "data": {}},
                {"@type": "Delete", "data": {}},
                {"@type": "Update", "data": {}}):
        try:
            ops._assert_read_only(bad)
        except ValueError:
            continue
        raise AssertionError(f"write op not rejected: {bad['@type']}")
