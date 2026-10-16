# Sensing record — Silver Blaze (the probabilistic half)

**Model:** mistral-large-4 (redyarn dev session, Mistral subscription)
**Date:** 2026-10-16
**Role:** the LLM senses and proposes; the engine (`engine/engine.py`)
verifies, chains, prunes, and decides. No LLM call sits in the verdict
path — the selftest proves the verdict replays from these artifacts alone.

## The sensing motion

Schema-guided structured extraction: a JSON schema + a messy piece of
input from the field → a typesafe, schema-validated structured object
the logic engine consumes (`engine/sensing.py`). Entity extraction and
classification are **sensing operations** — the engine never extracts
or classifies; it verifies what the senses produce.

The loop is sense → **judge** → solve. The judge layer validates the
structured output (schema + compute checks: unique ids, real source
files); a rejection feeds the error back to the LLM for a capped number
of correction turns (max 3) before the corrected object passes for
real. An unreachable LLM fails fast — that error cannot correct itself.

## The operations (phase 1)

1. **Classify** the evidence pile → `evidence-index.json`
   (schema: `evidence-index.schema.json`) — each raw file typed:
   log / report / correspondence / roster / note / financial-record.
2. **Extract entities** → `entities.json` (schema: `entities.schema.json`)
   — every person, animal, place, and object that matters, with roles
   and source spans.
3. **Extract facts** → `facts.json` (schema: `facts.schema.json`) —
   guided by the classification + the entities; includes negative
   evidence (the kennel-log gap).

Phase 2: **extract facts** from the ledger → `facts-ledger.json`.

## What was read (raw evidence)

- `evidence/kennel-log.txt` — the kennel log with the overnight gap
- `evidence/stable-roster.md` — the roster (incl. the dog's known behavior)
- `evidence/moor-report.txt` — the moor find
- `evidence/telegram.txt` — the office telegrams
- `evidence/rival-note.md` — the Mapleton note
- `evidence/ledger.txt` — (phase 2) the second-establishment ledger

## Notable sensing calls

- **f06** — the dog did *not* bark at the night visitor: read from the
  log's **absence** of entries (negative evidence). Confidence 0.9.
- **f07** — "the dog barks at strangers": world knowledge stated by the
  roster, not observed that night. Confidence 0.8.
- **H1–H4** — the hypothesis space was proposed from the case shape;
  priors set by plausibility, not by evidence.

The engine then does the rest deterministically: modus tollens on the
dog's silence (R2), constraint pruning (C1, C2), question discovery
(R6–R8), and the verdict + trace. See `expected.md` for the outcome the
selftest asserts.
