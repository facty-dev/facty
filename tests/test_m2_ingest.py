"""M2 tests: parsers, content-addressed ingest, idempotency, version-conflict
facts, originals verify by hash, case lifecycle (branch create/delete).

Uses a scratch TerminusDB db (TERMINUSDB_URL must be reachable; the dev
container on :6363). Run: uv run pytest tests/test_m2_ingest.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from facty import cases as cases_mod
from facty import ingest
from facty.client import Client
from facty.schema import SCHEMA

pytestmark = pytest.mark.skipif(
    os.environ.get("FACTY_TEST_NO_DB") == "1", reason="needs TerminusDB on :6363")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTY_DATA_DIR", str(tmp_path / ".facty"))
    monkeypatch.setattr(ingest, "DATA_DIR", tmp_path / ".facty")
    c = Client(db="facty-m2test")
    if c.db_exists():
        c.delete_db()
    c.create_db()
    c.install_schema(SCHEMA)
    c.ref = "main"
    yield c
    c.ref = "main"
    c.delete_db()


@pytest.fixture()
def evdir(tmp_path):
    d = tmp_path / "evidence"
    d.mkdir()
    (d / "note.txt").write_text("the claimant parked at 3am\n")
    (d / "ledger.csv").write_text("id,amount\n1,4200\n2,100\n")
    (d / "meta.json").write_text(json.dumps({"policy": "POL-99"}))
    (d / "weird.xyz").write_bytes(b"\x00\x01\x02unknown")
    return d


def test_parsers_dispatch(tmp_path):
    from facty import parsers
    (tmp_path / "a.csv").write_text("x,y\n1,2\n")
    (tmp_path / "b.json").write_text('{"k": 1}')
    (tmp_path / "c.txt").write_text("hello")
    (tmp_path / "d.eml").write_text("From: a@b.c\nSubject: hi\n\nbody text\n")
    assert "1,2" in parsers.parse(tmp_path / "a.csv")
    assert '"k": 1' in parsers.parse(tmp_path / "b.json")
    assert parsers.parse(tmp_path / "c.txt") == "hello"
    assert "body text" in parsers.parse(tmp_path / "d.eml")
    (tmp_path / "e.png").write_bytes(b"\x89PNG")
    (tmp_path / "f.xyz").write_bytes(b"junk")
    with pytest.raises(parsers.NeedsOCR):
        parsers.parse(tmp_path / "e.png")
    with pytest.raises(parsers.UnknownFormat):
        parsers.parse(tmp_path / "f.xyz")


def test_ingest_idempotent_and_version_conflict(client, evdir):
    s1 = ingest.ingest_dir(client, evdir, "claim-file")
    assert len(s1["added"]) == 4 and not s1["conflicts"]
    assert "weird.xyz" in s1["quarantined"]
    assert "note.txt" in s1["extracted"]
    # second ingest: no-op
    s2 = ingest.ingest_dir(client, evdir, "claim-file")
    assert s2["added"] == [] and len(s2["skipped"]) == 4
    # changed file → version conflict as an adjudication fact, not an error
    (evdir / "note.txt").write_text("the claimant parked at 4am instead\n")
    s3 = ingest.ingest_dir(client, evdir, "claim-file")
    assert s3["conflicts"] == ["note.txt"]
    facts = [d for d in client.get_all_docs() if d.get("@type") == "Fact"
             and d.get("predicate") == "versionConflict"]
    assert len(facts) == 1 and facts[0]["subject"] == "note.txt"
    # custody manifest written
    cust = [d for d in client.get_all_docs() if d.get("@type") == "CustodyEvent"]
    assert cust and all(d["source"] == "claim-file" for d in cust)
    # originals verify unchanged by hash
    v = ingest.verify_originals(client)
    assert v["checked"] >= 4 and v["mismatches"] == []


def test_case_lifecycle(client, tmp_path, monkeypatch):
    monkeypatch.setenv("FACTY_KEYS_DIR", str(tmp_path / "keys"))
    from facty import bundle as bundle_mod, keys
    monkeypatch.setattr(keys, "KEYS_DIR", tmp_path / "keys")
    # a tiny signed bundle
    bdir = tmp_path / "bundles" / "mini"
    bdir.mkdir(parents=True)
    (bdir / "bundle.json").write_text(json.dumps([
        {"@type": "Rule", "id": "r1", "version": "1", "pack": "mini",
         "when": [{"@type": "Condition", "subject": "s", "predicate": "p", "valueBool": True}],
         "then": [{"@type": "Action", "op": "raise", "hypotheses": ["H1"]}]}]))
    keys.init_key("t", keys_dir=tmp_path / "keys")
    b = bundle_mod.Bundle({"id": "mini", "version": "2.0.0", "kind": "domain"},
                          json.loads((bdir / "bundle.json").read_text()), path=bdir)
    b.sign()

    info = cases_mod.case_init(client, "demo-1", str(bdir))
    assert info["branch"] == "case-demo-1"
    # case branch has the bundle docs + a Case doc
    show = cases_mod.case_show(client, "demo-1")
    assert show["docs"].get("Rule") == 1 and show["docs"].get("Case") == 1
    assert show["manifest"]["fingerprint"] == b.fingerprint
    # list shows it
    assert any(d["id"] == "demo-1" for d in cases_mod.case_list(client))
    # delete removes the branch and the registry doc; nothing remains in the DB
    res = cases_mod.case_delete(client, "demo-1")
    assert res["remains_in_db"] == []
    assert cases_mod.case_list(client) == []
    assert "error" in cases_mod.case_show(client, "demo-1")  # branch is gone


def test_unsigned_bundle_refused_in_case_init(client, tmp_path):
    from facty.bundle import BundleError
    bdir = tmp_path / "unsigned"
    bdir.mkdir()
    (bdir / "bundle.json").write_text("[]")
    (bdir / "manifest.json").write_text(json.dumps({"id": "u", "version": "2.0.0"}))
    with pytest.raises(BundleError):
        cases_mod.case_init(client, "x", str(bdir), dev=False)
