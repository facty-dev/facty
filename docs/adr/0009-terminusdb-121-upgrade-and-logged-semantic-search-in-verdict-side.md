# ADR-0009 — TerminusDB 12.1.0-rc2 upgrade; semantic search on the deterministic side (logged)

**Status:** accepted (2026-11-06, PO approved an RC)
**Related:** [ADR-0008](0008-sensing-side-rag-and-perf.md), [ADR-0007](0007-case-lifecycle-ingest-codemode.md)

## Decisions

1. **Upgrade to TerminusDB `v12.1.0-rc2`** (latest non-dev tag, 2026-11-03) in
   compose.yaml + the SmolVM Dockerfile. Selftest PASS ×4 and e2e DETERMINISM OK
   on the new version; all v12.0.9 endpoint quirks we logged still hold.
2. **Native VectorLink index: schema-ready, not wired.** 12.1's versioned
   embeddings need `store_indices` in the schema `@context` (root document
   endpoint, `full_replace=true` — branch paths reject contexts) plus an
   embedding provider (separate Ollama service / HF model pull — outside our VM
   egress allow-list). Our schema now carries the metadata on `Fact` and
   `ExtractedText`, so enabling it later is a config change, not a migration.
   Until then, semantic search runs on the BYO-key Mistral embeddings path with
   disk-cached, content-addressed vectors (deterministic replay). Full findings
   in deps-log.md.
3. **Semantic search on the deterministic side — logged, recorded, never
   decisive by itself.** Facts get an embedding at load time (`embeddingSha256`
   on the Fact doc, vector in the object store — part of the case record, so
   replays are byte-identical offline). At each `run`, the engine computes
   pairwise cosine over recorded fact embeddings and appends
   `semantic-contradiction-candidate fA~fB (score)` to the trace, plus a
   queryable `semanticContradictionWith` derived Fact (confidence = score).
   Constraints may reference that predicate; the engine never auto-prunes on
   similarity. No LLM, clock, or live API call is in the verdict path — the
   vectors are recorded artifacts. Rationale (PO): embeddings are a much
   smaller probability surface than LLM calls and can add real effectiveness to
   the constraint layer; the log makes it auditable.
4. **SmolVM lifecycle hygiene.** One fixed machine name (`FACTY_SANDBOX_VM`),
   create-if-absent (checked via `machine list` — never multiplied), created
   once per process from the saved image and reused across calls/tests;
   `shutdown_machine()` stops (not deletes) the VM and is registered with
   `atexit` — nothing hangs open when the engine is done. Persistence is in the
   image, not in rebuilt VMs. `facty vm status|down` exposed. Tested with a fake
   `smolvm` binary: exactly one `create`, one `stop` at shutdown.

## Consequences

- Positive: latest TerminusDB (RC) with a ready native-index upgrade path; the
  demo trace now shows contradiction candidates (e.g. `f05~x01 (0.990)` between
  phase-1 and phase-2 facts) as committed, auditable graph data; no VM thrash.
- Costs accepted: RC software (pinned tag, logged); semantic candidates are
  trace-only unless a constraint uses them — effectiveness claim is empirical
  and auditable via the trace; native VectorLink deferred until an embedding
  provider is in the allow-list.
