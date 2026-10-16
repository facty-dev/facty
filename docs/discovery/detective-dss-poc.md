# PoC plan — the detective DSS, one exemplar happy path

**Status:** proposed · **Date:** 2026-10-15
**Product:** redyarn · **Vocabulary:** case decision support (opportunity / assumptions / hypotheses / acceptance)
**Architecture:** [ADR-0003](../adr/0003-detective-dss-neurosymbolic-core.md)

## Opportunity

A domain-agnostic abductive DSS: evidence → ranked hypotheses →
discriminating tests → verdict with a full reasoning trace. Domains are
packs. ([verticals.md](verticals.md))

## Exemplar (proposed): "The Curious Incident of the Dog in the Night-Time"

Inspired by *The Adventure of Silver Blaze* (Arthur Conan Doyle, 1892 —
public domain). Not healthcare; a classic mystery, instantly recognizable,
and structurally perfect for abduction:

- A champion racehorse (Silver Blaze) vanishes from its stable the night its
  trainer (John Straker) is found dead on the moor.
- The famous clue: **the kennel dog did not bark** — absence of evidence as
  evidence (the visitor was someone the dog knew).
- Competing explanations:
  - **H1** — the rival trainer stole the horse and killed Straker (sabotage).
  - **H2** — a mystery visitor killed Straker (secret, blackmail); the horse
    wandered to the rival's stables.
  - **H3** — Straker was sabotaging his own horse (double life, debts) and
    was killed by an accomplice; the horse bolted.
  - **H4** — a stranger stole the horse (pruned by the dog constraint).
- Why it demos well: negative evidence, ranked hypotheses, discriminating
  tests (hoofprints, the dog's visitors, Straker's second establishment),
  timeline/geography constraints — and it's fun.

Evidence files for the case: kennel log (with the barking gap), stable
roster, the moor report, a telegram, a note from the rival stables.

## Assumptions (= spikes)

Spikes, OST assumptions, acceptance/API contract tests, and case-based
hypotheses are **one structure with four names**. Each assumption below is a
spike with acceptance criteria:

- **A1 (spike: engine)** — the symbolic engine (forward chain + constraints)
  ranks the correct explanation from JSON facts alone, deterministically,
  replayable without the LLM.
- **A2 (spike: sensing)** — Mistral Large 4 turns the raw evidence files
  into schema-valid facts with confidence + source spans.
- **A3 (spike: composition)** — the two halves compose into one verdict +
  one derivation trace.

## Hypotheses (case-based)

The exemplar's own suspect list (H1–H4) doubles as the demo of case-based
hypotheses: the engine ranks them, prunes, and names the discriminating test
that would settle the top two.

## Acceptance criteria (the happy path)

1. Evidence files → `sense` → schema-valid `fact[]` (A2)
2. `derive` (forward chain) produces derived facts **and opens ≥1 question** —
   e.g. the kennel-log gap ("did the dog bark?") — the awareness loop,
   demonstrated (A1)
3. `solve` (constraints) prunes to a ranked hypothesis set; H4 (stranger)
   eliminated by the dog constraint (A1)
4. `test` (backward chain) validates the surviving hypothesis; `propose-test`
   names the discriminating test; the test "runs" (a new evidence file
   appears → new facts → loop)
5. `combine` produces the verdict + full `derivation` trace; **deterministic
   replay**: same inputs → same verdict, no LLM in the verdict path (A1, A3)
6. All artifacts are JSON files validated against JSON schemas; no database,
   no graph DB, no VM

## Scope

- **In:** JSON schemas (`engine/schemas/`), the engine spike
  (`engine/engine.py`: forward chain, backward chain, constraint layer), the
  exemplar (`engine/cases/silver-blaze/`), codegen projections
  (`engine/emit.py`: TS + Datalog), the trace.
- **Out (later):** Postgres persistence (JSONB), VM isolation testing
  (security requirement for sensitive deployments), workbench UI, pack
  factory, decider layer, self-improvement loop wiring.

## Build mode

Built and tested **in the current dev agent session** (host, sandboxed). VM
testing comes after, when real deployments need isolation from secrets.
