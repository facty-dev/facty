# Sensing record — Silver Blaze (the probabilistic half)

**Model:** mistral-large-4 (redyarn dev session, Mistral subscription)
**Date:** 2026-10-16
**Role:** the LLM senses and proposes; the engine (`engine/engine.py`)
verifies, chains, prunes, and decides. No LLM call sits in the verdict
path — the selftest proves the verdict replays from these artifacts alone.

## What was read (raw evidence)

- `evidence/kennel-log.txt` — the kennel log with the overnight gap
- `evidence/stable-roster.md` — the roster (incl. the dog's known behavior)
- `evidence/moor-report.txt` — the moor find
- `evidence/telegram.txt` — the office telegrams
- `evidence/rival-note.md` — the Mapleton note
- `evidence/ledger.txt` — (phase 2) the second-establishment ledger

## What was produced

- `facts.json` — 14 facts (phase 1), each with confidence + source span
- `facts-ledger.json` — 3 facts (phase 2)
- `pack/hypotheses.json` — the proposed hypothesis space (H1–H4) with priors

## Notable sensing calls

- **f06** — the dog did *not* bark at the night visitor: read from the
  log's **absence** of entries (negative evidence). Confidence 0.9.
- **f07** — "the dog barks at strangers": world knowledge from the
  roster, not from the night in question. Confidence 0.8.
- **H1–H4** — the hypothesis space was proposed from the case shape;
  priors set by plausibility, not by evidence.

The engine then does the rest deterministically: modus tollens on the
dog's silence (R2), constraint pruning (C1, C2), question discovery
(R6–R8), and the verdict + trace. See `expected.md` for the outcome the
selftest asserts.
