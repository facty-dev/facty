# ADR-0012 — Prolog authoring dialect for bundle authoring / chat; WOQL JSON-LD remains the only stored and executed form

**Date:** 2026-11-17
**Status:** proposed
**Related:** [ADR-0003](0003-detective-dss-neurosymbolic-core.md) (verdict-path
invariants — unchanged), [ADR-0005](0005-cleanroom-stack-replaces-poc.md)
(cleanroom stack), [ADR-0006](0006-bundle-trust-spine.md) (signed bundles),
[ADR-0010](0010-triadic-runtime-parity.md) (§4 machine/human loop parity).
Research log: [docs/research/deps-log.md](../research/deps-log.md) (TerminusDB
v12 entry; SWI-Prolog-in-image verification, 2026-11-17).

## Problem

LLMs write SWI-Prolog text far better than WOQL JSON: Prolog is abundant in
training data, the WOQL JSON AST is nearly absent. Bundle authoring (the pack
factory) and chat mode could benefit from a Prolog surface. But three facts
constrain the design:

1. **WOQL is not Prolog.** It is a JSON AST interpreted by the TerminusDB
   server (itself a SWI-Prolog saved state); Prolog unification shows up only in
   variable binding (deps-log: "Server is Prolog; WOQL variables use Prolog
   unification; stratified negation"). v12 exposes no Prolog-*source* query
   endpoint — queries enter as WOQL JSON or GraphQL — so a Prolog dialect can
   never be executed directly by the server; it must be compiled.
2. **Unrestricted Prolog is unsafe in the verdict path.** Cut, `assertz`,
   negation-as-failure across strata, and unbounded recursion are valid Prolog
   but outside WOQL's stratified semantics and outside what our engine can
   audit — "rules beat vibes" (ADR-0003) applies regardless of syntax.
3. **The machine loop already has a reliable emission format:** the typed JSON
   rule DSL + pydantic structured output (`rules.py` → WOQL AST via `woql.py`),
   shape-validated, disk-cached, with server-side bind-time validation. Dialect
   errors are impossible by construction there.

## Decision

- **Stored/executed form: WOQL JSON-LD only** (unchanged). External-facing APIs
  (`facty serve`, the facty MCP server, TerminusDB MCP) stay JSON — client
  callers never need to know about the dialect.
- **Machine loop:** unchanged — typed JSON DSL, pydantic structured output,
  deterministic compiler.
- **Optional authoring dialect (new, for bundle authoring and chat mode):** a
  restricted, stratified Prolog subset — `head :- body.` with conjunctions and
  comparisons; no cut, no assert/retract, no `\+/is` on unbound variables, no
  negation across strata. Accepted as *text input* only; translated by a small
  Prolog module run on the **SWI-Prolog 10.0.2 binary shipped inside the
  TerminusDB image** (`/usr/bin/swipl`, live-verified 2026-11-17 — the same
  runtime the server is a saved state of): `read_term` → WOQL JSON → the normal
  insert path → server bind-time validation → bundle signature gate. The
  translated WOQL/rule docs are what get stored, signed, and executed; the
  Prolog text itself is never persisted as an executable artifact.
- **Verdict-path invariant unchanged:** nothing uncompiled from an LLM ever
  reaches the engine. The dialect is an authoring convenience, compiled by
  deterministic code, same as the JSON DSL.

## Considered options

- **LLM emits WOQL JSON directly** — rejected: rare in training data, dialect
  errors likely; this is the problem the JSON DSL already solves.
- **Full SWI-Prolog as the rule language, executed by Terminus** — rejected:
  not possible (no Prolog-source query interface in v12) and unsafe (semantics
  beyond stratified Datalog; non-termination; un-auditable constructs).
- **Prolog dialect compiled by the in-image swipl** — chosen: same runtime as
  the server itself, zero new dependencies, deterministic translation, output
  gated by the existing signature + schema checks.
- **Prolog dialect only for humans, JSON DSL for LLMs** — viable fallback if
  the dialect's LLM reliability doesn't beat the JSON DSL in practice; the
  compiler is shared either way.

## Consequences

- One more deterministic compiler to build and test (round-trip: dialect →
  WOQL → identical verdict on a bundle fixture). Kept entirely out of the
  verdict path by construction.
- Chat mode and the pack factory can accept Prolog text; every persisted
  artifact remains JSON-LD/WOQL inside a signed bundle. External clients see
  only JSON.
- Neutral: if the dialect underperforms, drop it — no stored format depends on
  it.

## Validation (when implemented)

- Round-trip test: the same rule written in the JSON DSL and in the Prolog
  dialect compiles to identical WOQL and produces identical verdicts on a
  bundle fixture.
- Negative tests: cut / assert / cross-stratum `\+` are rejected by the
  translator with a deterministic error.
- `./facty selftest` stays green (byte-identical replay).
