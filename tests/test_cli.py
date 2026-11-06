"""CLI smoke tests (Typer CliRunner): command surface, bundle gate exit codes.

Run: uv run pytest tests/test_cli.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from facty.cli import app

REPO = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_help_lists_all_commands():
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for cmd in ("init-db", "keys", "bundle", "load-facts", "sense", "run",
                "compile-rules", "log", "verdict", "metrics", "cases", "selftest"):
        assert cmd in r.output


def test_bundle_verify_signed_demo_bundle():
    r = runner.invoke(app, ["bundle", "verify", str(REPO / "bundles" / "insurance-claim-fraud")])
    assert r.exit_code == 0
    assert "signature valid" in r.output


def test_bundle_verify_unsigned_exits_1(tmp_path):
    d = tmp_path / "b"
    d.mkdir()
    (d / "bundle.json").write_text(json.dumps([{"@type": "Rule", "id": "r1"}]))
    (d / "manifest.json").write_text(json.dumps({"id": "b", "version": "2.0.0"}))
    r = runner.invoke(app, ["bundle", "verify", str(d)])
    assert r.exit_code == 1
    assert "unsigned" in r.output


def test_keys_list_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTY_KEYS_DIR", str(tmp_path / "nope"))
    from facty import keys
    monkeypatch.setattr(keys, "KEYS_DIR", tmp_path / "nope")
    r = runner.invoke(app, ["keys", "list"])
    assert r.exit_code == 0
    assert "no keys" in r.output


def test_cases_lists_signed_bundles():
    r = runner.invoke(app, ["cases"])
    assert r.exit_code == 0
    assert "bundle\tinsurance-claim-fraud" in r.output
    assert "signed" in r.output
