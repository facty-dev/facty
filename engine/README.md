# engine — the redyarn symbolic engine

The deterministic half of the neurosymbolic split
([ADR-0003](../docs/adr/0003-detective-dss-neurosymbolic-core.md)):
forward + backward chaining over rules, with a constraint layer, over
canonical case artifacts. The LLM (Mistral Large 4) senses and proposes;
this engine verifies, chains, prunes, and decides. stdlib only —
deterministic, replayable, no network, no database, no LLM in the verdict
path.

## Run

```bash
make dss-demo        # phase 1 — the case as first heard
make dss-demo-2      # phase 2 — the ledger test applied
make dss-selftest    # acceptance test — the PoC happy path, asserted
```

## Layout

- `schemas/` — the canonical artifact schemas (the common protocol)
- `engine.py` — the engine (library + CLI: `run`, `selftest`)
- `cases/silver-blaze/` — the exemplar case: `evidence/` (raw files),
  `pack/` (rules, constraints, hypotheses), `facts.json` +
  `facts-ledger.json` (the sensed facts), `SENSING.md` (the sensing
  record), `expected.md` (the outcome the selftest asserts)
- `emit.py` → `emit/` — codegen projections (TypeScript types, Datalog)

## The protocol

Every artifact is JSON validated against `schemas/`. Facts are sensed by
the LLM (confidence + source spans); rules, constraints, and hypotheses
are the pack (authored with the pack factory, hypotheses proposed by the
sensing half); the engine's verdict is a deterministic function of those
artifacts alone.

## The score (deterministic, documented)

```
score = 0.6 * claims_proven_ratio   (backward chaining)
      + 0.3 * support_ratio         (constraint layer)
      + 0.1 * prior                 (LLM plausibility, static input)
```

Rules take precedence over probabilities: the LLM's prior is the
smallest term, and the verdict never calls the LLM.
