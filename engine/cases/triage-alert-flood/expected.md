# Expected outcome — the alert flood triage (the sensor ladder in the loop)

The selftest (`./facty selftest`) asserts these. The case demonstrates
the **sensor ladder** in the decision loop: the pile of 200 SIEM alerts
is classified by two tiers — a small CPU-only zero-shot classifier
(bulk, free, local) and Strom, a hosted decision model (adjudication,
calibrated, EU-hosted) — the engine routes on the aggregates, and the
LLM never reads `alerts.csv`.

## Phase 1 — the case as first heard

- **Tier 1** — the local classifier (`classify.json`, backend
  `hybrid`) sensed `evidence/alerts.csv` into per-item `classifiedAs`
  facts + aggregates: **131 rows labeled** (77 a targeted attack, 54 a
  probing scan), **69 gated** below the 0.65 margin gate
  (`unclassified` — the handoff set).
- **Tier 2** — Strom (`strom-1.0.7`, questions drafted by the LLM into
  `sensor/decisions.json` and judged, incl. a dry run) adjudicated the
  69 gated rows with calibrated probabilities: **59 more labeled** (45
  a targeted attack, 12 a probing scan, 2 a benign authorized
  activity), **10 still gated**. The drafted decision questions
  (`isExternalSource`, `hasAchievedImpact`, `involvesCredentialAbuse`,
  `targetsSingleAsset`, `urgency`) added 345 per-row decision facts
  over the adjudicated rows.
- Totals (recorded in `facts.json`, 573 label facts + 10 prose):
  **190 rows labeled — 122 a targeted attack** (mean confidence 0.821,
  98 of 122 from 185.220.44.7, 11 sources), **66 a probing scan**
  (0.83), **2 benign**, **10 unclassified** below the 0.65 gate; 28
  aggregate facts.
- Forward chain derives **d1, d2, d2b**:
  - d1: `coordinatedAttackLikely = true` (R1 — 122 attack-classified,
    98 from one source)
  - d2: `mostlyFalsePositives = false` (R2 — 188 of 200 rows are
    attack/scan-classified)
  - d2b: `scanDominates = false` (R2 — 122 attacks > 66 scans)
- Opens **q1** (threat-intel correlation, discriminates H1/H2)
- Constraint **C1** prunes **H3** (false-positive flood — the pile is
  not mostly misfires)
- Ranking: **H1 (0.490) > H2 (0.320)** — both survive, ranked
  (H2's `noAttackClassified` claim is refuted: the sensors counted 122
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
compares). No LLM, model, or API call sits in the verdict path. The
recorded facts replay offline: `FACTY_SENSE=cache` replays the cached
sensor output without any model, and `--offline` / `FACTY_OFFLINE=1`
runs the label sensor's local tier live while the LLM ops replay the
cache.

One honest caveat, measured: **the decider tier is probabilistic** —
re-asking the same row returns slightly different probabilities (32 of
36 rows wobble past the 4th decimal), so a row near the 0.65 gate can
flip on a fresh live run (one row did, across two recordings:
190→191 labeled, 122→123 attacks). The local classifier tier is
deterministic; only the decider tier drifts. The artifact model
absorbs it the same way it absorbs LLM variance: the recorded
`facts.json` + the response cache are the deterministic layer, and a
fresh live re-record means re-checking the pack's exact-count rules
(R1/R2 key on `targetedAttackCount == 122`).
