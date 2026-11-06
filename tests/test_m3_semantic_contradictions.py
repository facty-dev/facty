"""Deterministic-side semantic search (ADR-0009): contradiction candidates from
RECORDED fact embeddings — no LLM call in the verdict path. Plus SmolVM
shutdown hygiene. Run: uv run pytest tests/test_m3_semantic_contradictions.py
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

from facty import engine, sandbox, search
from facty.client import Client
from facty.schema import SCHEMA


def _fake_client_with_facts(tmp_path, monkeypatch, pairs):
    """Facts with hand-set embeddingSha256 pointing at vectors in a tmp store."""
    monkeypatch.setattr(engine, "DATA_DIR", tmp_path) if hasattr(engine, "DATA_DIR") else None
    from facty import ingest
    monkeypatch.setattr(ingest, "DATA_DIR", tmp_path)
    objdir = tmp_path / "objects"
    objdir.mkdir(parents=True, exist_ok=True)
    docs = []
    for fid, val, vec in pairs:
        blob = json.dumps(vec).encode()
        sha = hashlib.sha256(blob).hexdigest()
        (objdir / sha).write_bytes(blob)
        docs.append({"@type": "Fact", "id": fid, "type": "case", "subject": "s",
                     "predicate": "p", "valueString": val, "confidence": 1.0,
                     "source": "t", "embeddingSha256": sha})
    # patch _docs_of via a fake client
    class FC:
        def get_all_docs(self):
            return docs
    return FC()


def test_semantic_contradiction_candidates(tmp_path, monkeypatch):
    fc = _fake_client_with_facts(tmp_path, monkeypatch, [
        ("f1", "yes", [1.0, 0.0]),
        ("f2", "no", [0.99, 0.01]),   # near-duplicate text, conflicting value
        ("f3", "unrelated", [0.0, 1.0]),
    ])
    cands = engine.semantic_contradictions(fc, threshold=0.93)
    assert len(cands) == 1 and cands[0]["a"] == "f1" and cands[0]["b"] == "f2"
    assert cands[0]["score"] > 0.99
    # same value → not a contradiction
    fc2 = _fake_client_with_facts(tmp_path / "b", monkeypatch, [
        ("f1", "yes", [1.0, 0.0]), ("f2", "yes", [0.99, 0.01])])
    assert engine.semantic_contradictions(fc2, threshold=0.93) == []


def test_smolvm_stop_on_shutdown(tmp_path, monkeypatch):
    log = tmp_path / "smolvm.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "smolvm"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'if [ "$2" = "list" ]; then echo "other-vm"; exit 0; fi\n'
        'if [ "$1" = "machine" ] && [ "$2" = "exec" ]; then echo \'{"ok":1}\'; exit 0; fi\n'
        "exit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(sandbox, "_machine_ready", False)
    sandbox.ensure_machine()
    sandbox.run_code("print(1)", backend="smolvm")
    sandbox.shutdown_machine()
    logtxt = log.read_text()
    assert logtxt.count(" create ") == 1          # created once, reused
    assert " stop " in logtxt                     # stopped on shutdown, not left hanging
    assert sandbox._machine_ready is False


def test_mixed_model_vectors_never_compared(tmp_path, monkeypatch):
    """Portability: facts embedded by different models/dims must not be
    compared (cosine across dims is meaningless)."""
    fc = _fake_client_with_facts(tmp_path, monkeypatch, [
        ("f1", "yes", [1.0, 0.0]),        # model A (2-dim)
        ("f2", "no", [1.0, 0.0, 0.0]),    # model B (3-dim) — same direction, diff model/dim
    ])
    # mark different models
    import facty.ingest as ing
    monkeypatch.setattr(ing, "DATA_DIR", tmp_path)
    docs = fc.get_all_docs()
    docs[0]["embeddingModel"] = "model-a"; docs[0]["embeddingDim"] = 2
    docs[1]["embeddingModel"] = "model-b"; docs[1]["embeddingDim"] = 3
    assert engine.semantic_contradictions(fc, threshold=0.5) == []
