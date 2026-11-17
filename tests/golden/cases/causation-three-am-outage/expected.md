# Expected outcome — the 3 a.m. outage (causation / incident RCA)

The selftest (`./facty selftest`) asserts these.

## Phase 1 — the symptom and the initial telemetry

- R0 raises the causal space **H1–H4** (deploy regression · expired
  certificate · upstream outage · attack).
- Forward chain derives **d1–d3**:
  - d1: the failing calls target **Payline** (R1 — 502s from
    payline-gateway + checkout depends on Payline)
  - d2: d-2214 is the **only deploy candidate** (R2 — touched checkout;
    nothing deployed in the window)
  - d3: the symptom **matches an upstream outage** (R3 — 502s from an
    upstream gateway)
- Opens **q1** (deploy-diff), **q2** (provider-status), **q3**
  (cert-check)
- Constraints prune **H2** (expired certificate — C1: valid through the
  window, zero TLS errors) and **H4** (attack — C2: traffic flat, WAF
  silent)
- Ranking: **H1 (0.535) > H3 (0.43)** — our own change first, the
  upstream outage second; both survive, ranked
- Recommended test: **q1** — rule out our own deploy first

## Phase 2 — the postmortem evidence applied

- Forward chain derives **d4–d6**:
  - d4: d-2214 **cannot explain the incident** (R7 — one backoff
    constant, no error path, 8h clean soak)
  - d5: the **upstream failure is confirmed** (R8 — Payline's incident
    window matches ours to the minute; our app tier stayed healthy)
  - d6: the **detection gap** (R9 — no synthetic health check on
    Payline; the pager fired on customer impact)
- Constraint **C5** prunes **H1** (the deploy regression)
- **H3 wins (0.83)**, all 4 claims proven by backward chaining
- Verdict: **H3 — upstream provider outage.** Proximate cause:
  Payline's database failover automation error (their postmortem).
  Contributing factor: no upstream health check in our monitoring
  (d6) — the fix: add a synthetic check on Payline and automate the
  status page.

## Determinism

Same artifacts → byte-identical verdict (the selftest replays and
compares). No LLM, clock, or randomness in the verdict path.
