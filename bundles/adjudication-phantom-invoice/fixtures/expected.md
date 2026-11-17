# Expected outcome — the phantom invoice (adjudication / fraud)

The selftest (`./facty selftest`) asserts these.

## Phase 1 — the flag and the initial documents

- R0 raises the disposition space **H1–H4** (the real vendor denies
  the invoice; the payment is paid).
- Forward chain derives **d1–d4**:
  - d1: INV-2261 **bypassed the three-way match** (R1 — no PO, policy requires one)
  - d2: the vendor record **failed callback verification** (R2 — blank field, policy requires it)
  - d3: the payment **violated segregation of duties** (R3 — same user entered and approved)
  - d4: the invoice **impersonates the real vendor** (R4 — lookalike domain)
- Opens **q1** (vendor-provenance), **q2** (email-authentication),
  **q3** (payment-trail), **q4** (po-trace)
- Constraints prune **H3** (payment diversion — C1: no genuine
  invoice, no change request — nothing to divert) and **H4** (honest
  error — C2: a clerical error passes the mandatory controls; this
  bypassed both)
- Ranking: **H2 (0.725) > H1 (0.535)** — the evidence points at the
  clerk first (created-by + SoD violation); external fraud survives,
  ranked second
- Recommended test: **q1** — pull the vendor-master audit + session
  records

## Phase 2 — the audit trail applied

- Forward chain derives **d5–d8**:
  - d5: the invoice email and the vendor-record creation came from the
    **same IP** (R9 — the killer link)
  - d6: the invoice email **failed SPF and DKIM** (R10)
  - d7: the receiving account **predates the vendor record** (R11 — a
    mule account opened before the vendor existed)
  - d8: the clerk **did not create the vendor record** (R12 — foreign
    service-account session, no clerk session in the window)
- Constraint **C6** prunes **H2** (the inside job — the created-by
  field was spoofed)
- **H1 wins (0.935)**, all 4 claims proven by backward chaining
- Verdict: **H1 — external invoice fraud.** Disposition: recall the
  payment, escalate to the fraud unit, notify the bank. The clerk is
  exonerated by the same evidence that convicts the impersonator.

## Determinism

Same artifacts → byte-identical verdict (the selftest replays and
compares). No LLM, clock, or randomness in the verdict path.
