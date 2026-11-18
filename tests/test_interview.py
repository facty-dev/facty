"""Interview loop tests: the questionnaire flow as a pydantic-graph, with every
turn committed to the case branch (Turn docs) — replay parity with the linear
dispatcher, mode discipline (verdict-path nodes deterministic), LLM chooser
gated through the ranked node.

Run: uv run pytest tests/test_interview.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from facty import cases as cases_mod
from facty import engine, ops, sensing
from facty.client import Client
from facty.ops import strip_ids
from facty.schema import SCHEMA

pytestmark = pytest.mark.skipif(
    os.environ.get("FACTY_TEST_NO_DB") == "1", reason="needs TerminusDB on :6363")

REPO = Path(__file__).resolve().parents[1]
BUNDLE = REPO / "bundles" / "small-business-contract-claim"
FIXTURES = BUNDLE / "fixtures" / "facts-initial.json"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTY_DATA_DIR", str(tmp_path / ".facty"))
    c = Client(db="facty-interviewtest")
    if c.db_exists():
        c.delete_db()
    c.create_db()
    c.install_schema(SCHEMA)
    c.ref = "main"
    yield c
    c.ref = "main"
    c.delete_db()


def _init_case(client, case_id):
    cases_mod.case_init(client, case_id, str(BUNDLE))
    client.ref = cases_mod._slug(case_id)
    engine.load_facts(client, FIXTURES, "facts")
    return client


def _turns(client, case):
    return sorted((d for d in client.get_all_docs()
                   if d.get("@type") == "Turn" and d.get("case") == case),
                  key=lambda d: d["id"])


def test_interview_graph_runs_and_commits_turns(client):
    """Scripted-answer interview: the graph loops gap-analysis → ask → answer →
    run until no open questions, then assembles. Turn docs carry the modes."""
    _init_case(client, "iv-a")
    r = ops.interview(client, "iv-a", answers={"*": "true"}, chooser="script",
                      surface="wizard", actor="human")
    assert r.get("done") is True or "awaiting" not in r
    ts = _turns(client, "iv-a")
    assert ts, "interview must commit Turn docs"
    # verdict-path turns are deterministic; only answers are ranked
    assert all(t["mode"] == "deterministic" for t in ts if t["op"] in ("run", "assemble"))
    assert any(t["mode"] == "ranked" and t.get("choice") for t in ts if t["op"] == "answer")
    assert any(d.get("@type") == "Verdict" for d in client.get_all_docs())
    assert any(d.get("@type") == "AssembledDocument" for d in client.get_all_docs())


def test_interview_mermaid_and_replay_parity(client):
    """The graph renders (Mermaid) and two identical runs produce identical
    Turn trails (id/commit-stripped) — replay = branch + cache."""
    from facty import interview as iv
    g = iv.build_graph()
    assert "RunPhase" in g.render()
    outs = []
    for case_id in ("iv-r1", "iv-r2"):
        _init_case(client, case_id)
        ops.interview(client, case_id, answers={"*": "true"})
        ts = strip_ids(_turns(client, case_id))
        for t in ts:
            t["case"] = "X"; t["id"] = "T"
            t.pop("inputCommit", None); t.pop("outputCommit", None)
        outs.append(json.dumps(ts, sort_keys=True))
    assert outs[0] == outs[1], "interview Turn trail not deterministic across identical runs"


def test_interview_llm_chooser_is_ranked_and_gated(client, monkeypatch):
    """chooser=llm: the LLM pick happens only in the AskQuestion node, is
    recorded as a ranked Turn with choice, and the answer is a committed Fact."""
    monkeypatch.setattr(sensing, "sense_json",
                        lambda prompt, model=None: model(value=True, why="scripted")
                        if model is not None else {"value": True})
    _init_case(client, "iv-llm")
    r = ops.interview(client, "iv-llm", chooser="llm", actor="llm")
    ts = _turns(client, "iv-llm")
    answers = [t for t in ts if t["op"] == "answer"]
    assert answers and all(t["mode"] == "ranked" for t in answers)
    assert any(d.get("@type") == "Fact" and str(d.get("source", "")).startswith("answer:")
               for d in client.get_all_docs())
