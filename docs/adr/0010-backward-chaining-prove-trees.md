# ADR-0010 — backward chaining with proof trees (`facty prove`); deduction-side status

**Status:** accepted (2026-11-06)
**Related:** [ADR-0003](0003-detective-dss-neurosymbolic-core.md), [ADR-0009](0009-terminusdb-121-upgrade-and-logged-semantic-search-in-verdict-side.md), triage T1/T2 in [docs/CLEANROOM-METHOD.md](../CLEANROOM-METHOD.md)

## Deduction-side status (GOFAI checklist)

| Capability | Status |
|---|---|
| Forward chaining | yes — `engine.forward_chain` to fixpoint (WOQL-compiled rules) |
| Backward chaining | **yes, now** — `engine.prove(goal)` → proof tree (`facty prove <subject> <predicate> [--value v] [--case id]`); recurses through rule premises, mirrors the `Derivation` docs; deterministic (rules sorted by id, depth-capped, seen-set) |
| Constraint layer | yes — eliminate/support constraints + scoring (`apply_constraints`, `rank_hypotheses`); full ASP (clingo-style) remains the optional T2 tier, not in TerminusDB |
| Proof trees | yes — `prove` returns the tree; the forward pass persists per-step `Derivation` docs (rule + premise ids) |
| LLM integration | induction-side only: sensing (pydantic-ai, any model via `FACTY_MODEL`/provider), codemode sandbox execution, BYO-key embeddings; smaller/specialized models slot in via the same env knobs (`FACTY_MODEL`, `FACTY_EMBED_MODEL`, native index model) — never in the verdict path |

## Embeddings model (PO question)

TerminusDB 12.1's default native embedding model is `multilingual-e5-base`
(278M params) served as a **Q8_0-quantized GGUF** (768-dim → 768 bytes/vector);
the official quickstart runs it **CPU-only** with no external network after a
one-time model pull. So yes — CPU-only is the designed path for the native
index. Our BYO-key path uses Mistral's hosted `mistral-embed` instead (no local
model needed); both are swappable via `FACTY_EMBED_MODEL` / schema metadata.

## Consequences

- `facty prove` closes the backward-chaining gap; verified live on the demo case
  and by unit tests (fact leaf, 2-step rule chain, unprovable → exit 1).
- Determinism unchanged: prove is pure WOQL over committed graph data.
