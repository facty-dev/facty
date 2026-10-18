# Expected outcome — the alert flood triage (label sensor in the loop)

The selftest (`./facty selftest`) asserts these. The case demonstrates the
label sensor (a small CPU-only zero-shot classifier, `classify.json`) in
the decision loop: the pile of 200 SIEM alerts is classified locally, the
engine routes on the aggregates — the LLM never reads `alerts.csv`.

## Phase 1 — the case as first heard

- The classifier sensed `evidence/alerts.csv` into 200 per-item
  `classifiedAs` facts + 22 aggregate facts (recorded in `facts.json`):
  **77 targeted attacks** (mean confidence 0.81, 60 of 77 from
  185.220.44.7), **54 probing scans** (0.83), **69 below the 0.65
  confidence gate** (`unclassified` — the LLM fallback set).
- Forward chain derives **d1, d2, d2b**:
  - d1: `coordinatedAttackLikely = true` (R1 — 77 attack-classified,
    60 from one source)
  - d2: `mostlyFalsePositives = false` (R2 — 131 of 200 rows are
    attack/scan-classified)
  - d2b: `scanDominates = false` (R2 — 77 attacks > 54 scans)
- Opens **q1** (threat-intel correlation, discriminates H1/H2)
- Constraint **C1** prunes **H3** (false-positive flood — the pile is
  not mostly misfires)
- Ranking: **H1 (0.490) > H2 (0.320)** — both survive, ranked
  (H2's `noAttackClassified` claim is refuted: the classifier counted 77
  attack-classified alerts — the claim is robust to any prose the LLM
  senses from the narrative)
- Recommended test: **q1** — pull the threat intel on the top source

## Phase 2 — the threat-intel test applied

- Forward chain derives **d3**: `attackConfirmed = true` (R3 —
  `topSourceIsKnownBad`, from `evidence/threat-intel.txt`)
- Constraint **C2** prunes **H2** (background noise — the top source
  is a known bulletproof-hosting range); **C3** supports **H1**
- **H1 wins (0.740)**, all 4 claims proven by backward chaining
- Verdict: **H1 — targeted attack.** Route **P1 to incident response**;
  hand off to **attribution** to identify the operator.

## Determinism

Same artifacts → byte-identical verdict (the selftest replays and
compares). No LLM, clock, or randomness in the verdict path. The
recorded classifier facts replay offline (`FACTY_SENSE=cache` replays
the cached sensor output without the model).
