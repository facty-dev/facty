"""Semantic search over case evidence (sensing-side RAG).

TerminusDB's native versioned embeddings are a 12.1-RC feature — our pinned
v12.0.9 rejects `store_indices` (verified live, logged in deps-log.md). So on
v12 we embed on the BYO-key path: Mistral's embeddings API (`mistral-embed`),
responses cached on disk (`.cache/embeddings/`), vectors stored content-addressed
in the same object store, `EvidenceChunk` docs in TerminusDB point at them.
Cosine similarity is computed client-side — case scale is a drawer, not a corpus.

CRITICAL: search is induction-only. Retrieved chunks may enrich the SENSING
prompt (`facty sense --case X --rag "..."`); they never enter the verdict path,
which stays pure deterministic WOQL over Facts/Rules/Constraints.

Upgrade path: when the container moves to TerminusDB >= 12.1, switch to native
schema-driven embeddings (`@metadata.embedding` query+template, `store_indices`)
— versioned per commit, deterministic by construction.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.request
from pathlib import Path

from .ingest import DATA_DIR

EMBED_MODEL = os.environ.get("FACTY_EMBED_MODEL", "mistral-embed")
EMBED_URL = "https://api.mistral.ai/v1/embeddings"
CACHE_DIR = Path(os.environ.get("FACTY_CACHE_DIR", ".cache")) / "embeddings"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if len(text) <= size:
        return [text] if text.strip() else []
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


def embed_texts(texts: list[str], model: str = EMBED_MODEL) -> list[list[float]]:
    """Embed via the BYO-key Mistral embeddings API, disk-cached per text.
    Returns [] for all if no key is set (search degrades gracefully)."""
    key = os.environ.get("MISTRAL_API_KEY")
    if not key or os.environ.get("FACTY_SENSE") == "cache-off-embeddings":
        return [[] for _ in texts]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out: list[list[float]] = []
    todo: list[tuple[int, str]] = []
    for i, t in enumerate(texts):
        cp = CACHE_DIR / f"{_sha256(model + ':' + t)}.json"
        if cp.exists():
            out.append(json.loads(cp.read_text())["embedding"])
        else:
            out.append([])
            todo.append((i, t))
    if todo:
        req = urllib.request.Request(
            EMBED_URL,
            data=json.dumps({"model": model, "input": [t for _, t in todo]}).encode(),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
        for (i, t), item in zip(todo, data["data"]):
            emb = item["embedding"]
            out[i] = emb
            (CACHE_DIR / f"{_sha256(model + ':' + t)}.json").write_text(
                json.dumps({"model": model, "embedding": emb}))
    return out


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def store_embedding(vec: list[float], model: str = EMBED_MODEL, data_dir: Path = DATA_DIR) -> str:
    """Store the vector content-addressed in the object store, WITH its model +
    dimensionality in the blob (portability: vectors from different models/dims
    are never compared — see search_case / semantic_contradictions)."""
    blob = json.dumps({"model": model, "dim": len(vec), "embedding": vec}).encode()
    sha = hashlib.sha256(blob).hexdigest()
    obj = data_dir / "objects" / sha
    if not obj.exists():
        tmp = data_dir / "objects" / (sha + ".tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, obj)
    return sha


def index_extracted_texts(client, data_dir: Path = DATA_DIR, model: str = EMBED_MODEL) -> int:
    """Chunk every ExtractedText on the ref and embed the chunks (cached).
    Writes EvidenceChunk docs. Returns the number of chunks indexed."""
    chunks = []
    for e in [d for d in client.get_all_docs() if d.get("@type") == "ExtractedText"]:
        for i, piece in enumerate(chunk_text(e["text"])):
            chunks.append({"@type": "EvidenceChunk",
                           "id": "chunk-" + _sha256(e["id"] + str(i))[:12],
                           "original": e["original"], "extracted": e["id"], "idx": i,
                           "text": piece, "textSha256": _sha256(piece),
                           "embeddingSha256": "", "embeddingModel": model})
    if not chunks:
        return 0
    embs = embed_texts([c["text"] for c in chunks], model=model)
    docs = []
    for c, emb in zip(chunks, embs):
        if emb:
            c["embeddingModel"] = model
            c["embeddingDim"] = len(emb)
            c["embeddingSha256"] = store_embedding(emb, model, data_dir)
        docs.append(c)
    client.insert_docs(docs, message=f"index {len(docs)} evidence chunks ({model})")
    return len(docs)


def search_case(client, query: str, top_k: int = 5, data_dir: Path = DATA_DIR,
                model: str = EMBED_MODEL) -> list[dict]:
    """Rank the case's EvidenceChunks by cosine similarity to the query."""
    chunks = [d for d in client.get_all_docs() if d.get("@type") == "EvidenceChunk" and d.get("embeddingSha256")]
    if not chunks:
        return []
    qemb = embed_texts([query], model=model)[0]
    if not qemb:
        return []
    objdir = data_dir / "objects"
    scored = []
    for c in chunks:
        # portability: only compare vectors from the SAME model and dim
        if c.get("embeddingModel") not in (None, model) or c.get("embeddingDim") not in (None, len(qemb)):
            continue
        blob = objdir / c["embeddingSha256"]
        if not blob.exists():
            continue
        rec = json.loads(blob.read_text())
        vec = rec["embedding"] if isinstance(rec, dict) and "embedding" in rec else rec
        scored.append({**c, "score": round(cosine(qemb, vec), 6)})
    scored.sort(key=lambda s: (-s["score"], s["id"]))
    return scored[:top_k]
