"""Tests for sensing-side semantic search, SmolVM create-once reuse, and the
keep-alive TerminusDB client. Run: uv run pytest tests/test_search_sandbox_perf.py
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from facty import sandbox, search
from facty.client import Client


# ── semantic search (embeddings injected — no API needed) ───────────────────

class FakeClient:
    def __init__(self, docs):
        self._docs = docs

    def get_all_docs(self):
        return self._docs


def _vec(*xs):
    return list(xs)


def test_chunking_and_cosine():
    assert search.chunk_text("short") == ["short"]
    long = "x" * 2500
    chunks = search.chunk_text(long, size=1000, overlap=150)
    assert len(chunks) == 3 and all(len(c) <= 1000 for c in chunks)
    assert search.cosine([1, 0], [1, 0]) == 1.0
    assert search.cosine([1, 0], [0, 1]) == 0.0


def test_search_case_ranks_by_cosine(tmp_path, monkeypatch):
    monkeypatch.setattr(search, "DATA_DIR", tmp_path)
    objdir = tmp_path / "objects"
    objdir.mkdir(parents=True)
    # two chunks with known embeddings: chunk A ~ query, chunk B orthogonal
    import hashlib
    emb_a = json.dumps(_vec(1.0, 0.0)).encode()
    emb_b = json.dumps(_vec(0.0, 1.0)).encode()
    sha_a, sha_b = hashlib.sha256(emb_a).hexdigest(), hashlib.sha256(emb_b).hexdigest()
    (objdir / sha_a).write_bytes(emb_a)
    (objdir / sha_b).write_bytes(emb_b)
    docs = [
        {"@type": "EvidenceChunk", "id": "chunk-a", "original": "o1", "extracted": "e1",
         "idx": 0, "text": "alpha text", "textSha256": "x", "embeddingSha256": sha_a,
         "embeddingModel": "test"},
        {"@type": "EvidenceChunk", "id": "chunk-b", "original": "o1", "extracted": "e1",
         "idx": 1, "text": "beta text", "textSha256": "y", "embeddingSha256": sha_b,
         "embeddingModel": "test"},
    ]
    monkeypatch.setattr(search, "embed_texts", lambda texts, model="test": [_vec(0.9, 0.1)] * len(texts))
    hits = search.search_case(FakeClient(docs), "alpha query", top_k=2, data_dir=tmp_path, model="test")
    assert [h["id"] for h in hits] == ["chunk-a", "chunk-b"]
    assert hits[0]["score"] > hits[1]["score"]


# ── SmolVM create-once reuse (fake smolvm binary on PATH) ────────────────────

def test_smolvm_machine_created_once_and_reused(tmp_path, monkeypatch):
    log = tmp_path / "smolvm.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "smolvm"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        'if [ "$1" = "machine" ] && [ "$2" = "exec" ]; then echo \'{"out":42}\'; exit 0; fi\n'
        "exit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(sandbox, "_machine_ready", False)
    r1 = sandbox.run_code("print('a')", backend="smolvm")
    r2 = sandbox.run_code("print('b')", backend="smolvm")
    assert r1["ok"] and r2["ok"] and r1["backend"] == "smolvm"
    creates = [l for l in log.read_text().splitlines() if " create " in l]
    assert len(creates) == 1, f"VM must be created once and reused, got {creates}"
    execs = [l for l in log.read_text().splitlines() if " exec " in l]
    assert len(execs) == 2


# ── keep-alive client ────────────────────────────────────────────────────────

def test_client_reuses_connection():
    c = Client(db="facty-e2e")
    c._req("ok", "GET", "/api/ok")
    conn1 = c._conn
    assert conn1 is not None
    c._req("ok", "GET", "/api/ok")
    assert c._conn is conn1  # same persistent connection, no reconnect
