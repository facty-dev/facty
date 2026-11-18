"""Turn dispatcher tests (ADR-0010 §3): per-turn determinism modes, Turn docs,
ranked choice recording, verdict-path enforcement, replay determinism.

Uses a scratch TerminusDB db (TERMINUSDB_URL must be reachable, :6363).
Run: uv run pytest tests/test_turn.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from facty import cases as cases_mod
from facty import engine, sensing, turn
from facty.client import Client
from facty.schema import SCHEMA

pytestmark = pytest.mark.skipif(
    os.environ.get("FACTY_TEST_NO_DB") == "1", reason="needs TerminusDB on :6363")

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "bundles" / "small-business-contract-claim"
FIXTURES = BUNDLE / "fixtures" / "facts-initial.json"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTY_DATA_DIR", str(tmp_path / ".facty"))
    c = Client(db="facty-turntest")
    if c.db_exists():
        c.delete_db()
    c.create_db()
    c.install_schema(SCHEMA)
    c.ref = "main"
    yield c
    c.ref = "main"
    c.delete_db()


def _mk_pipeline(case: str, steps: list[dict], pid: str = "p1") -> dict:
    return {"@type": "Pipeline", "id": pid, "pack": "test", "version": "1.0.0",
            "case": case, "steps": steps}


def _step(i, op, mode, order, params=None, surface="wizard"):
    return {"@type": "Step", "id": i, "op": op, "mode": mode, "surface": surface,
            "order": order, "params": json.dumps(params or {})}


def _init_case(client, case_id: str):
    cases_mod.case_init(client, case_id, str(BUNDLE))
    client.ref = cases_mod._slug(case_id)
    return client


def _turns(client, case):
    return sorted((d for d in client.get_all_docs()
                   if d.get("@type") == "Turn" and d.get("case") == case),
                  key=lambda d: d["id"])


def test_turn_modes_and_turn_docs(client):
    """A mixed-mode pipeline: deterministic steps execute and commit Turn docs;
    the ranked step returns the engine's option set and records the pick."""
    _init_case(client, "t-modes")
    client.insert_docs([_mk_pipeline("t-modes", [
        _step("s1", "load-facts", "deterministic", 1, {"path": str(FIXTURES)}),
        _step("s2", "run", "deterministic", 2, {"phase": "1"}),
        _step("s3", "answer", "ranked", 3, {}),
        _step("s4", "assemble", "deterministic", 4, {}),
    ])], message="test pipeline")
    r1 = turn.run_turn(client, "t-modes", pipeline_id="p1", run_all=True)
    assert r1["done"] is False and r1["awaiting"] == "choice"
    assert r1["options"], "ranked step must offer the engine's ranked questions"
    ts = _turns(client, "t-modes")
    assert [t["step"] for t in ts] == ["s1", "s2"]          # ranked step not yet executed
    assert all(t["mode"] == "deterministic" for t in ts)
    assert all(t.get("inputCommit") and t.get("outputCommit") for t in ts)
    assert all(t.get("surface") == "wizard" for t in ts)
    choice = r1["options"][0]
    r2 = turn.run_turn(client, "t-modes", pipeline_id="p1", choice=choice, value="true", run_all=True)
    assert r2["done"] is True
    ts = _turns(client, "t-modes")
    assert [t["step"] for t in ts] == ["s1", "s2", "s3", "s4"]
    ranked = next(t for t in ts if t["step"] == "s3")
    assert ranked["mode"] == "ranked"
    assert ranked["choice"] == choice and choice in ranked["options"]
    assert any(d.get("@type") == "AssembledDocument" for d in client.get_all_docs())
    assert any(d.get("@type") == "Verdict" for d in client.get_all_docs())


def test_verdict_path_always_deterministic(client):
    """ADR-0003 invariant: a verdict-path op (run/prove/assemble) with a
    non-deterministic mode in the signed config is rejected by the dispatcher."""
    _init_case(client, "t-enforce")
    client.insert_docs([_mk_pipeline("t-enforce", [
        _step("s1", "run", "free", 1, {"phase": "1"}),       # must be rejected
    ])], message="bad pipeline")
    with pytest.raises(ValueError, match="deterministic"):
        turn.run_turn(client, "t-enforce", pipeline_id="p1")
    assert _turns(client, "t-enforce") == []
    client.insert_docs([_mk_pipeline("t-enforce", [
        _step("s1", "sense", "deterministic", 1, {}),        # free-only op, wrong mode
    ], pid="p2")], message="bad pipeline 2")
    with pytest.raises(ValueError, match="not allowed"):
        turn.run_turn(client, "t-enforce", pipeline_id="p2")


def test_ranked_choice_must_be_in_options(client):
    _init_case(client, "t-choice")
    engine.load_facts(client, FIXTURES, "facts")
    engine.run_phase(client, "t-choice", "1")
    client.insert_docs([_mk_pipeline("t-choice", [
        _step("s1", "answer", "ranked", 1, {}),
    ])], message="p")
    with pytest.raises(ValueError, match="not in ranked options"):
        turn.run_turn(client, "t-choice", pipeline_id="p1", choice="q-nope", value="true")
    assert _turns(client, "t-choice") == []


def test_free_mode_sense_is_llm_only_and_replays(client, monkeypatch):
    """`free` mode runs LLM sensing (monkeypatched here) and commits the facts;
    the Turn doc records mode=free so the audit trail shows the stochastic turn."""
    facts = json.loads(FIXTURES.read_text())
    monkeypatch.setattr(sensing, "sense_json",
                        lambda prompt, model=None: {"facts": [
                            {"id": f["id"], "type": f.get("type", "evidence"),
                             "subject": f["subject"], "predicate": f["predicate"],
                             "value": f.get("valueString", f.get("valueBool", f.get("valueNum"))),
                             "confidence": f.get("confidence", 1.0),
                             "source": f.get("source", "test")} for f in facts]})
    _init_case(client, "t-free")
    client.insert_docs([_mk_pipeline("t-free", [
        _step("s1", "sense", "free", 1, {}, surface="chat"),
        _step("s2", "run", "deterministic", 2, {"phase": "1"}),
    ])], message="p")
    r = turn.run_turn(client, "t-free", pipeline_id="p1", run_all=True)
    assert r["done"] is True
    ts = _turns(client, "t-free")
    assert [t["mode"] for t in ts] == ["free", "deterministic"]
    assert ts[0]["surface"] == "chat"
    fact_ids = {d["id"] for d in client.get_all_docs() if d.get("@type") == "Fact"}
    assert {f["id"] for f in facts} <= fact_ids  # sensed facts committed (derived d* may add more)


def test_turn_replay_is_deterministic(client):
    """Same bundle + same facts + same choices on two case branches → identical
    Turn docs (id-stripped) and identical verdict content."""
    from facty.ops import strip_ids as _strip_ids
    outs = []
    for case_id in ("t-rep-a", "t-rep-b"):
        _init_case(client, case_id)
        client.insert_docs([_mk_pipeline(case_id, [
            _step("s1", "load-facts", "deterministic", 1, {"path": str(FIXTURES)}),
            _step("s2", "run", "deterministic", 2, {"phase": "1"}),
            _step("s3", "answer", "ranked", 3, {}),
            _step("s4", "run", "deterministic", 4, {"phase": "2"}),
            _step("s5", "assemble", "deterministic", 5, {}),
        ])], message="p")
        r1 = turn.run_turn(client, case_id, pipeline_id="p1", run_all=True)
        choice = r1["options"][0]
        r2 = turn.run_turn(client, case_id, pipeline_id="p1", choice=choice, value="true", run_all=True)
        assert r2["done"] is True
        turns = _strip_ids(_turns(client, case_id))
        for t in turns:  # case label + commit pointers differ per branch — normalize
            t["case"] = "X"; t["id"] = "T"
            t.pop("inputCommit", None); t.pop("outputCommit", None)
        verdicts = _strip_ids([d for d in client.get_all_docs() if d.get("@type") == "Verdict"])
        for v in verdicts:
            v["case"] = "X"; v["id"] = "V"
            if isinstance(v.get("ranking"), list):
                v["ranking"] = sorted(v["ranking"], key=lambda r: str(r.get("hypothesis")))
        outs.append((json.dumps(turns, sort_keys=True),
                     json.dumps(verdicts, sort_keys=True)))
    assert outs[0] == outs[1], "turn trail / verdict not deterministic across identical runs"
