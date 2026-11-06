"""Backward chaining / proof trees (engine.prove). Run: uv run pytest tests/test_prove.py"""

from __future__ import annotations

import pytest

from facty import engine
from facty.client import Client
from facty.schema import SCHEMA

pytestmark = pytest.mark.skipif(
    __import__("os").environ.get("FACTY_TEST_NO_DB") == "1", reason="needs TerminusDB")


@pytest.fixture()
def client():
    c = Client(db="facty-prove-test")
    if c.db_exists():
        c.delete_db()
    c.create_db()
    c.install_schema(SCHEMA)
    c.ref = "main"
    yield c
    c.ref = "main"
    c.delete_db()


def _rule(rid, when, derive):
    return {"@type": "Rule", "id": rid, "version": "1", "pack": "p",
            "when": when, "then": [{"@type": "Action", "op": "derive", "fact": derive}]}


def test_prove_fact_and_rule_chain(client):
    client.insert_docs([
        {"@type": "Fact", "id": "f1", "type": "case", "subject": "a", "predicate": "p",
         "valueBool": True, "confidence": 1.0, "source": "ev"},
        _rule("r1",
              [{"@type": "Condition", "subject": "a", "predicate": "p", "valueBool": True}],
              {"@type": "FactTemplate", "id": "d1", "type": "derived", "subject": "b",
               "predicate": "q", "valueBool": True, "confidence": 1.0}),
        _rule("r2",
              [{"@type": "Condition", "subject": "b", "predicate": "q", "valueBool": True}],
              {"@type": "FactTemplate", "id": "d2", "type": "derived", "subject": "c",
               "predicate": "r", "valueBool": True, "confidence": 1.0}),
    ], message="seed")
    # direct fact
    t = engine.prove(client, {"subject": "a", "predicate": "p", "valueBool": True})
    assert t and t["by"] == "fact" and t["fact"] == "f1"
    # two-step rule chain
    t = engine.prove(client, {"subject": "c", "predicate": "r", "valueBool": True})
    assert t and t["by"] == "rule" and t["rule"] == "r2"
    assert t["premises"][0]["by"] == "rule" and t["premises"][0]["rule"] == "r1"
    assert t["premises"][0]["premises"][0]["by"] == "fact"
    # unprovable
    assert engine.prove(client, {"subject": "zzz", "predicate": "nope", "valueBool": True}) is None
