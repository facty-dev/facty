# Sensing record — the alert-flood triage (the label sensor in the loop)

**Recorded:** facty dev session · **Date:** 2026-10-18
**Role:** the LLM senses and proposes; the classifier senses the pile;
the engine (`engine/engine.py`) verifies, chains, prunes, and decides.
No LLM or model call sits in the verdict path — the selftest proves the
verdict replays from these artifacts alone. Re-derive live from a host
with the sensor deps (`make deps-sensors`):
`./facty sense alert-flood --op label` (streams the sensor log; caches
the facts; `FACTY_SENSE=cache` replays them without the model).

## The sensing motion

Schema-guided structured extraction for the prose (a JSON schema + a
messy piece of input → a validated object, `engine/sensing.py`), and the
label sensor for the pile (`engine/label.py`): a small zero-shot NLI
classifier scores every row against the pack's labels — premise = the
alert message, hypothesis = `"This alert is {label}."`, scored by
entailment − contradiction (margin) softmaxed across the labels.

## The operations

1. **Classify** the prose evidence → `evidence-index.json` (the pile,
   `alerts.csv`, is sensor-sourced: typed by `classify.json`, excluded
   from the LLM's phase-1 files — the LLM never reads it).
2. **Extract entities** → `entities.json` (the on-call, the SIEM, INC-552,
   the top source, the routing teams).
3. **Extract facts** (prose) → the `fNN` facts in `facts.json`
   (the flood window, the page, the deadline, the routing policy).
4. **Label the pile** (the classifier, `classify.json`) → the `cl-*`
   per-item facts + the `ag-*` aggregates in `facts.json`:
   - 200 rows scored; **77 a targeted attack** (mean confidence 0.808,
     60 from 185.220.44.7, 11 sources), **54 a probing scan** (0.826,
     38 sources), **69 unclassified** below the 0.65 gate
     (mean best-probability 0.525 — the LLM fallback set).
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

## The classifier (measured during development)

- Model: `onnx-community/ModernBERT-base-nli-ONNX` (the ONNX of
  `tasksource/ModernBERT-base-nli`, 149M params, Apache-2.0), fp32,
  onnxruntime, CPU-only — ~6–7s for the 600-pair call on a 2–4 vCPU
  budget (the M5 Pro dev host measured 6.4s at 4 emulated vCPUs).
- Label phrasing is pack design: `"a probing scan"` beat
  `"a background scan"` on this evidence (the "background" qualifier
  made single-alert entailment fail). Margin scoring (entailment −
  contradiction) calibrated the confidences far better than raw
  entailment (mean 0.72 vs 0.53) — the threshold gate depends on it.
- Accuracy on this synthetic pile: ~75% of the 131 rows that cleared
  the 0.65 gate; the false-positive rows are meta-texts ("matched a
  signature") and mostly fall below the gate — the honest outcome, and
  exactly what the gate is for: they become `unclassified` facts and
  route to the LLM.
- Threshold is a per-pack calibration knob, tuned on the pack's
  evidence sample.

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

- **The aggregates are the signal** — `ag-targetedattackcount` (77),
  `ag-targetedattacktopsourcecount` (60 of 77 from one source) drive
  R1 → `coordinatedAttackLikely`; `ag-probingscancount` (54) and the
  gated 69 drive R2 → `mostlyFalsePositives = false`.
- **Negative evidence**: the 69 gated rows are recorded as
  `unclassified` (not silently dropped), and the LLM fallback set is
  visible in the trace.
- **f101** — (phase 2) the window/source match: the top source is in a
  known bulletproof-hosting range. Confidence 0.95.

The engine then does the rest deterministically: the forward chain
(R0–R3), the open question (q1), constraint pruning (C1, C2), the
support (C3), and the verdict + trace. See `expected.md` for the
outcome the selftest asserts.
