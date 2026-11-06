"""Sandbox tests: LLM-written code runs under programmatic control with a hard
timeout; local backend (SmolVM backend activates when the binary + machine exist).

Run: uv run pytest tests/test_sandbox.py
"""

from __future__ import annotations

import json

from facty import sandbox


def test_run_code_ok():
    r = sandbox.run_code("import json;print(json.dumps({'n': 1+1}))", backend="local")
    assert r["ok"] and r["exit_code"] == 0
    assert json.loads(r["stdout"].strip()) == {"n": 2}
    assert r["backend"] == "local"


def test_run_code_with_files():
    r = sandbox.run_code(
        "import sys;print(open(sys.argv[1] if len(sys.argv)>1 else 'data.txt').read().upper())",
        files={"data.txt": b"hello"}, backend="local")
    # main.py is argv[0]; our files are in cwd — read by name
    assert r["ok"] and "HELLO" in r["stdout"]


def test_run_code_error_exit():
    r = sandbox.run_code("raise SystemExit(3)", backend="local")
    assert not r["ok"] and r["exit_code"] == 3


def test_run_code_timeout():
    r = sandbox.run_code("import time;time.sleep(30)", timeout=1.0, backend="local")
    assert not r["ok"] and "TIMEOUT" in r["stderr"]


def test_auto_backend_falls_back_to_local():
    r = sandbox.run_code("print('x')", backend="auto")
    assert r["backend"] in ("local", "smolvm")
