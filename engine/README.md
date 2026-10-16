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
make dss-live        # interactive walkthrough — step through, streamed LLM sensing
make dss-demo        # phase 1 — the case as first heard (batch)
make dss-demo-2      # phase 2 — the ledger test applied (batch)
make dss-selftest    # acceptance test — the PoC happy path, asserted
```

## Layout

- `schemas/` — the canonical artifact schemas (the common protocol)
- `engine.py` — the symbolic engine (library + CLI: `run`, `selftest`)
- `sensing.py` — the probabilistic half: schema-guided structured
  extraction (schema + messy input → validated object, LLM streamed),
  with a judge layer (schema + compute checks) and a capped correction
  loop — rejections feed back to the LLM, max 3 turns
- `test_retry.py` — the correction loop, tested with a stubbed runner
  (no LLM needed)
- `cli.py` — the interactive CLI: step-through walkthrough with
  module-tagged log lines and live LLM streaming (a stepping stone to
  the Workbench UI)
- `cases/silver-blaze/` — the exemplar case: `evidence/` (raw files),
  `pack/` (rules, constraints, hypotheses), the recorded sensing
  (`evidence-index.json`, `entities.json`, `facts.json`,
  `facts-ledger.json`), `sensing-prompt.md` (the facts task),
  `SENSING.md` (the sensing record), `expected.md` (the outcome the
  selftest asserts)
- `emit.py` → `emit/` — codegen projections (TypeScript types, Datalog)

## The protocol

Every artifact is JSON validated against `schemas/`. Facts are sensed by
the LLM (confidence + source spans); rules, constraints, and hypotheses
are the pack (authored with the pack factory, hypotheses proposed by the
sensing half); the engine's verdict is a deterministic function of those
artifacts alone.

## Debugging

The golden path for the LLM transport is the **pi agent** (`pi -p`) — pi
owns the credential and the engine process never sees it (ADR-0003; the
same isolation posture as the VM host-secret mechanism). To debug the
sensing steps:

```bash
# one sensing op, standalone (fast prompt iteration)
make dss-sense OP=facts          # or: classify | entities | ledger

# loud failures: no fallback, staged prompt path + exact pi command,
# raw LLM response on rejection
REDYARN_DEBUG=1 make dss-live
# or: python3 engine/cli.py --debug ...

# the staged prompts persist for inspection:
ls .agentic/tmp/sensing-*.md

# reproduce a call manually:
pi -p --provider mistral-subscription --model mistral-large-4 "@<staged prompt>"
```

The fallback contract: when the LLM is unreachable (e.g. under an agent
sandbox, where pi cannot read its credential), the CLI logs the failure
and uses the recorded sensing (`SENSING.md`). In debug mode it fails loud
instead (exit 2, no fallback).

## The score (deterministic, documented)

```
score = 0.6 * claims_proven_ratio   (backward chaining)
      + 0.3 * support_ratio         (constraint layer)
      + 0.1 * prior                 (LLM plausibility, static input)
```

Rules take precedence over probabilities: the LLM's prior is the
smallest term, and the verdict never calls the LLM.
