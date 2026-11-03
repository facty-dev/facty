# ADR-0005 — the cleanroom stack replaces the PoC stack

**Status:** accepted (PO-directed, 2026-10-30)
**Supersedes:** the runtime/storage/sensing choices of [ADR-0003](0003-detective-dss-neurosymbolic-core.md) §"Considered Options" (its *invariants* stand — see below)
**Reverses:** ADR-0003's "no graph database" PoC constraint and the gondolin/pi runtime — see [docs/research/stack-survey.md](../research/stack-survey.md) for the full survey. Methodology mapping + triage of not-yet-native reasoning patterns: [docs/CLEANROOM-METHOD.md](../CLEANROOM-METHOD.md)

## What problem are we solving?

The PoC proved the concept on a pile of Python scripts + JSON files + pi RPC +
a Textual TUI. The PO directed (2026-10-30): the cleanroom implementation
completely replaces the original stack, keeping the project vision and goals.

## Decision

The primary implementation is the **cleanroom stack** (``):

| Layer | PoC (retired to oracle) | Cleanroom (primary) |
|---|---|---|
| Store | JSON files in git | **TerminusDB** (Docker/SmolVM image; git-for-data = audit trail, branch/commit/time-travel) |
| Schema/ontology | JSON Schema files | TerminusDB schema (enforced at every write) |
| Rules engine | in-memory Python (forward+backward+constraints) | same semantics compiled to **WOQL** (closed-template compiler, `rules.py`+`woql.py`), deterministic, replayable from commits |
| Pack/case artifacts | `pack/*.json` files | native JSON-LD docs (`<case>/terminusdb/`, one-time `migrate_pack.py`) |
| Sensing (LLM) | pi RPC subprocess | **pydantic-ai** programmatic (`tools=[]`, typed output, cached) — machine loops; **Vibe CLI** for human-in-the-loop authoring |
| Isolation | gondolin VM | **SmolVM** (OCI image booted as a branchable micro-VM) |
| Interface | `./facty` → Textual TUI + tmux | `./facty` → headless `facty` CLI (no TUI/tmux) |

`./facty` now delegates to `` (PYTHONPATH shim in the launcher).
`engine/` stays untouched as the **golden oracle** until migration completes;
`python3 engine/engine.py selftest` remains the cross-check.

## Invariants kept (the vision — unchanged)

1. **The engine owns the verdict.** No LLM call, clock, or randomness in the
   verdict path; same graph state → byte-identical verdict (asserted per case by
   `facty selftest`, which replays each phase and compares). LLM-Modulo.
2. **One canonical artifact model** — Fact/Rule/Hypothesis/Constraint/Question/
   Derivation/Verdict; storage is a projection (now TerminusDB documents).
3. **Auditability as a product feature** — the trace is committed graph data;
   TerminusDB's commit history *is* the git-native pipeline's audit trail.
4. **Packs are the domain costume; the engine is the same.** All 3 demo cases +
   both packs migrated; `facty selftest` golden-matches all of them (PASS
   2026-10-30, live TerminusDB v12.0.9).
5. Rules beat vibes; humans are knowledge engineers and soundness critics.

## Why (drivers, all live-verified 2026-10-29/30 — see docs/research/deps-log.md)

- TerminusDB gives store + schema + Datalog/Prolog reasoning + versioned audit
  in one Apache-2.0 container; the artifact model maps 1:1 (verified against
  v12.0.9, incl. its divergences from the docs: `Set` not `Array`, PUT/POST
  upsert, JSON-LD WOQL variable objects, `local/branch|commit` paths).
- WOQL's evaluation is Prolog unification; the rule DSL → WOQL compiler keeps
  dialect errors impossible by construction (LLM never emits WOQL).
- SmolVM boots the same OCI image as a branchable micro-VM (`docker save |
  smolvm machine run --image -`), replacing gondolin for the cleanroom.
- pydantic-ai gives typed, cached, in-process sensing for machine loops;
  Vibe CLI (mistral-large-4 via project agent profiles) is the human surface.
- No popular one-box alternative exists: RelationalAI is Snowflake-only (data
  egress violation), triplestores are JVM/W3C, CozoDB/TypeDB lack backward
  chaining or are server/copyleft — surveyed in stack-survey.md.

## Migration state (2026-10-30)

Done: all cases/packs migrated to `terminusdb/`; `facty` → cleanroom CLI;
selftest green on all 4 runnable cases (silver-blaze, phantom-invoice,
3am-outage, insurance-claim-fraud) incl. determinism replay; e2e demo
(`scripts/e2e.sh [--live]`) green with live LLM sensing; metrics +
optional Logfire tracing (`FACTY_LOGFIRE=1`); AGENTS.md rule 8 (read dependency
docs in detail; log in docs/research/deps-log.md).

Open (next): boot the SmolVM image with the host-secret key path; port the pack
factory (templates/sdlc agents) onto Vibe CLI + TerminusDB MCP; triage-alert-flood
verdict selftest (583-fact pack migrated, needs expectations); then delete the
PoC runtime (engine/ stays as oracle until the PO signs off, then `docs/` and
`scripts/` referencing it are updated).

## Consequences

- Positive: deterministic verdict now replays from DB commits (not just files);
  schema enforcement at write time; audit trail is queryable; sensing is typed
  and cached; no TUI/tmux dependency in the primary path.
- Costs accepted: TerminusDB is in-memory single-node (fine at case scale);
  no ASP-style optimization (clingo-wasm stays an optional pack tier);
  v12 API quirks are concentrated in `src/facty/client.py`
  and logged in the deps log.
