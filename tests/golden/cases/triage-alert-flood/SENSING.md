# Sensing record — the alert-flood triage (the sensor ladder in the loop)

**Recorded:** facty dev session · **Date:** 2026-10-18 (re-recorded
2026-10-18 with the Strom decider tier)
**Role:** the LLM senses and proposes; the sensor ladder senses the
pile; the engine (`engine/engine.py`) verifies, chains, prunes, and
decides. No LLM or model call sits in the verdict path — the selftest
proves the verdict replays from these artifacts alone. Re-derive live
from a host with the sensor deps (`make deps-sensors`) and a Strom key
(`UPRELIC_API_KEY`): `./facty sense alert-flood --op label` (streams the
sensor log; caches the facts; `FACTY_SENSE=cache` replays them without
any model). Offline (`--offline` / `FACTY_OFFLINE=1`): the label sensor
runs its local tier live, the LLM ops replay the cache.

## The sensing motion

Schema-guided structured extraction for the prose (a JSON schema + a
messy piece of input → a validated object, `engine/sensing.py`), and the
**sensor ladder** for the pile (`engine/label.py`, backend `hybrid`):

- **Tier 1 — the local classifier** (`engine/label.py`): a small
  zero-shot NLI classifier scores every row against the pack's labels —
  premise = the alert message, hypothesis = `"This alert is {label}."`,
  scored by entailment − contradiction (margin) softmaxed across the
  labels. Free, local, unlimited — the bulk tier.
- **Tier 2 — the Strom decider** (`engine/strom.py`): a hosted decision
  model (Uprelic, Berlin; EU/Paris GPUs) adjudicates the rows tier 1
  gated, with calibrated probabilities. The question set is drafted by
  the LLM once per pack (`./facty sense <case> --op decide` →
  `sensor/decisions.json`, judged — schema + label coverage + a dry run
  against the API — in a capped 1+2 revision loop) and committed like
  any artifact.

## The operations

1. **Classify** the prose evidence → `evidence-index.json` (the pile,
   `alerts.csv`, is sensor-sourced: typed by `classify.json`, excluded
   from the LLM's phase-1 files — the LLM never reads it).
2. **Extract entities** → `entities.json` (the on-call, the SIEM, INC-552,
   the top source, the routing teams).
3. **Extract facts** (prose) → the `fNN` facts in `facts.json`
   (the flood window, the page, the deadline, the routing policy).
4. **Draft the decision questions** (`--op decide`, the LLM + the judge's
   dry run) → `sensor/decisions.json` (the classification choice with
   concrete criteria + 4 noul questions + an urgency score).
5. **Label the pile** (`--op label`, backend `hybrid`) → the `cl-*`
   per-item facts + the `ag-*` aggregates + the `dq-*` decision facts
   in `facts.json`:
   - Tier 1: 200 rows scored; **131 labeled** (77 a targeted attack,
     54 a probing scan), **69 gated** below the 0.65 margin gate.
   - Tier 2: Strom adjudicated the 69 gated rows — **59 more labeled**
     (45 a targeted attack, 12 a probing scan, 2 a benign authorized
     activity), **10 still gated**; the 5 drafted decision questions
     added 345 `dq-*` facts over the adjudicated rows.
   - Totals: **190 labeled — 122 a targeted attack** (mean confidence
     0.821, 98 of 122 from 185.220.44.7, 11 sources), **66 a probing
     scan** (0.83), **2 benign**, **10 unclassified** below the 0.65
     gate; 28 aggregate facts.
   - Phase 2: **extract facts** from the threat intel →
     `facts-threat-intel.json`.

## What was read (raw evidence)

- `evidence/alerts.csv` — the 200-row SIEM export (the classifier's
  input; ~5.9K tokens the LLM never spends)
- `evidence/narrative.txt` — the SOC narrative (the flood, the page,
  the routing call)
- `evidence/routing-policy.txt` — the P1/P2/P3 routing policy (the
  pack's rules encode it)
- `evidence/threat-intel.txt` — (phase 2) the known-bad range

## The tiers (measured during development)

**Tier 1 — the local classifier.**

- Model: `onnx-community/ModernBERT-base-nli-ONNX` (the ONNX of
  `tasksource/ModernBERT-base-nli`, 149M params, Apache-2.0), fp32,
  onnxruntime, CPU-only — ~2.5s for the 600-pair call on the dev host.
- Label phrasing is pack design: `"a probing scan"` beat
  `"a background scan"` on this evidence (the "background" qualifier
  made single-alert entailment fail). Margin scoring (entailment −
  contradiction) calibrated the confidences far better than raw
  entailment (mean 0.72 vs 0.53) — the threshold gate depends on it.
- Accuracy on this synthetic pile: ~75% of the 131 rows that cleared
  the 0.65 gate; the false-positive rows are meta-texts ("matched a
  signature") and mostly fall below the gate — the honest outcome, and
  exactly what the gate is for: they become the tier-2 handoff set.
- Threshold is a per-pack calibration knob, tuned on the pack's
  evidence sample.

**Tier 2 — the Strom decider** (`strom-1.0.7`, measured on the same
pile, gold labels known from the generator):

- **96.0%** accuracy on the rows it classifies at the 0.65 gate (vs
  the classifier's 75.6%) — the +20-point win is concentrated exactly
  in the gated set the classifier could not decide. On everyday
  language (a 126-row tickets eval) it ties the classifier (90.0% vs
  90.5%).
- **Calibrated**: answers at 0.9+ were right 100% of the time on this
  pile (63/63 and 54/54 in the top bins) — the threshold gate is
  principled here, not a heuristic.
- Cost: the whole 200-row pile ≈ **$0.0016** ($0.042 per 1M input
  tokens, output free); the 69-row adjudication ≈ $0.0006.
- Latency: ~0.5s per request from the dev host; the 69-row adjudication
  ≈ 9s at the documented 500 req/min account limit (which is why the
  decider tier is the adjudication tier, not the bulk tier).
- Posture: EU/Paris GPUs, no third-party AI provider, request contents
  deleted after 90 days and never used for training (zero data
  retention on request). The key rides `UPRELIC_API_KEY` (env /
  gondolin host-secret injection) — never logged, never committed.
- Fallback: with no key, a 402, or an outage, the gated rows stay
  `unclassified` (the LLM fallback set) and the run is logged — the
  local tier is the bulk and the fallback; offline mode
  (`--offline`) skips the decider tier by design.

## Live sensing (a real session, 2026-10-18)

The LLM senses ran live (Mistral Large 4 via the pi subscription) and
are cached under `.agentic/cache/sensing/triage-alert-flood/`. Two
things worth keeping from that session:

- **The pile never reached the LLM.** Its own facts response says:
  *"The referenced `evidence/alerts.csv` is not available to me"* —
  `phase1_evidence` excludes the sensor-sourced file, and the LLM
  emitted its counts as `null` rather than guessing. The classifier's
  aggregates are the only counts in the case.
- **The live reading can diverge from the recorded one — by design.**
  The LLM sensed `scanDominates = true` from the narrative's "most
  alerts look like background radiation" (a prose vibe); the pack's
  R2 derives `scanDominates = false` from the classifier's counts.
  Rules beat vibes: H2's claims avoid anything the prose can prove
  (`noAttackClassified` is refuted by the aggregates), so the live run
  ranks identically to the recorded one — H1 0.49 > H2 0.32 in phase
  1, H1 0.74 after the threat intel.

## Notable sensing calls

- **The aggregates are the signal** — `ag-targetedattackcount` (122),
  `ag-targetedattacktopsourcecount` (98 of 122 from one source) drive
  R1 → `coordinatedAttackLikely`; `ag-probingscancount` (66) and the
  still-gated 10 drive R2 → `mostlyFalsePositives = false`.
- **Negative evidence**: the 10 still-gated rows are recorded as
  `unclassified` (not silently dropped), and the LLM fallback set is
  visible in the trace.
- **The decision facts** — the drafted questions emit per-row
  `dq-isexternalsource`, `dq-hasachievedimpact`,
  `dq-involvescredentialabuse`, `dq-targetssingleasset`, and
  `dq-urgency` facts over the adjudicated rows (the question name is the
  predicate; packs reference them).
- **f101** — (phase 2) the window/source match: the top source is in a
  known bulletproof-hosting range. Confidence 0.95.

The engine then does the rest deterministically: the forward chain
(R0–R3), the open question (q1), constraint pruning (C1, C2), the
support (C3), and the verdict + trace. See `expected.md` for the
outcome the selftest asserts.

## Prompt caching (measured)

Strom caches prompt prefixes across requests (Uprelic's "Prompt
caching" post): byte-identical replays come back with
`usage.cached_input_tokens` > 0 (measured: 768 cached tokens on a
replay of a 6-question request vs 0 cold), different rows share
nothing, and **billed tokens are the payload size either way —
caching buys latency, not cost**. The sensor's request pattern
follows the vendor's tips (many questions per request; deterministic,
byte-identical states), and the op's log line reports the tier's API
usage — e.g. the demo's adjudication: `69 calls, 45,157 input tokens,
3% cached, $0.0019`.
