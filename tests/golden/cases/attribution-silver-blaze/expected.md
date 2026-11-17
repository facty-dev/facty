# Expected outcome — Silver Blaze PoC

The selftest (`python3 engine/engine.py selftest`) asserts these.

## Phase 1 — the case as first heard

- Forward chain derives **d1–d3**:
  - d1: Silver Blaze's fate = **wandered** (R1)
  - d2: the night visitor's role = **acquaintance** (R2 — modus tollens on the dog's silence)
  - d3: the night visitor **killed** John Straker (R3)
- Opens **q1** (sabotage-payment), **q2** (night-visitor-identity), **q3** (rival-alibi)
- Constraints prune **H4** (stranger — the Pepe Silvia, C1) and **H1** (rival theft, C2)
- Ranking: **H2 (0.740) > H3 (0.235)** — both survive, ranked
- Recommended test: **q1** — collect the second-establishment ledger

## Phase 2 — the ledger test applied

- Forward chain derives **d4** (Straker was sabotaging, R4) and **d5**
  (the night visitor's role = accomplice, R5)
- Constraint **C3** prunes **H2** (Straker was the perpetrator)
- **H3 wins (0.735)**, all 3 claims proven by backward chaining
- Verdict: **H3 — self-sabotage.** Straker was paid by the rival trainer
  to sabotage his own horse and was killed by his accomplice (Ned
  Hunter); Silver Blaze bolted and wandered to Mapleton.

## Determinism

Same artifacts → byte-identical verdict (the selftest replays and
compares). No LLM, clock, or randomness in the verdict path.
