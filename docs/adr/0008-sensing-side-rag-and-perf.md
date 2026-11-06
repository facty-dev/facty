# ADR-0008 — sensing-side RAG (embeddings) + performance low-hanging fruit

**Status:** accepted (2026-11-06)
**Related:** [ADR-0005](0005-cleanroom-stack-replaces-poc.md), [ADR-0007](0007-case-lifecycle-ingest-codemode.md)

## Decisions

1. **Framework: pydantic-ai stays.** Surveyed the 2026 landscape (LangGraph/
   LangChain/CrewAI/ADK/DSPy/Instructor). The hype leaders optimize for
   LLM-as-controller agent loops — the opposite of our split. pydantic-ai's
   typed `output_type` + `tools=[]` is exactly "LLM as a typed induction
   function"; the deterministic engine owns the verdict. Logged in deps-log.md.
2. **Semantic search over evidence is sensing-side only.** TerminusDB's native
   versioned embeddings are a **12.1-RC feature**; our pinned v12.0.9 rejects
   `store_indices` (verified live). On v12 we embed via the BYO-key Mistral
   embeddings API (`mistral-embed`), cache responses on disk, store vectors
   content-addressed in the object store, and keep `EvidenceChunk` docs in
   TerminusDB. Cosine similarity is computed client-side (case scale is a
   drawer). `facty search "…" --case <id>` ranks chunks; `facty sense --case <id>
   --rag "…"` prepends the top chunks to the sensing prompt. **The verdict path
   never reads embeddings** — determinism is untouched (embeddings are cached
   artifacts; the engine replays byte-identical without them). Upgrade path to
   native 12.1 embeddings is documented in deps-log.md.
3. **Performance low-hanging fruit:**
   - TerminusDB client now uses one persistent keep-alive `HTTPConnection`
     (with a single reconnect-retry) instead of a new connection per request —
     the engine issues many sequential WOQL queries per run.
   - SmolVM sandbox creates the machine **once per process** (`ensure_machine`)
     and reuses it across calls/tests — no VM rebuild thrash (tested with a fake
     `smolvm` binary: exactly one `machine create` across multiple runs).
   - Ingest hashes files in a thread pool.
   - Bodyless DELETE/POST send `Content-Length: 0` (fixes a server-side hang).

## Consequences

- Positive: `facty search` gives fine-grained RAG during sensing (live-verified:
  a repair-cost query ranks the estimate chunk top); verdict determinism
  unchanged (selftest + e2e replay still byte-identical); CLI calls are cheaper.
- Costs accepted: Mistral embeddings API is another BYO-key egress (same trust
  boundary as the LLM — counts/embeddings only, and the cache keeps replays
  offline); client-side cosine is O(chunks) — fine at case scale, revisit if
  cases grow to corpus scale (then native 12.1 vector search).
