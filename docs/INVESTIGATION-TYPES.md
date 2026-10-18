# Investigation types — the judgements Facty supports

**Status:** decided (demo coverage) · **Date:** 2026-10-17
**Inputs:** [docs/discovery/verticals.md](discovery/verticals.md), [ADR-0003](adr/0003-detective-dss-neurosymbolic-core.md), [ADR-0004](adr/0004-cli-primary-interface.md), session taxonomy brainstorm

**ELI5:** an investigation is a question plus a pile of messy evidence,
and it ends in a *judgement*. Facty speaks every kind of
judgement-driven investigation with one skeleton — abduction — and the
kind of judgement decides what the verdict **is**.

## The common skeleton

Every investigation, whatever the domain, runs the same loop
([ADR-0003](adr/0003-detective-dss-neurosymbolic-core.md)):

```
anomaly → hypothesis space → discriminating tests → ranked verdict + trace
```

The two halves ratchet knowledge into existence:

```
induction (the LLM senses):   messy evidence → facts; proposes hypotheses + tests
deduction (the engine):       facts → derived facts + open questions;
                              constraints prune; backward chain proves; verdict
induction (the LLM collects): answers the open questions → new evidence → new facts
… until the hypothesis space converges.
```

What changes between investigation types is not the skeleton but the
**verdict type** — what the judgement is — and the shape of the errors.

## The seven families

| Family | Case prefix | Core question | Verdict type | Canonical examples | Error-cost shape |
|---|---|---|---|---|---|
| Attribution | `attribution-` | Who did it? | perpetrator + confidence | detective work, insider threat, HR misconduct, breach attribution | wrong accusation is the costly error |
| Causation | `causation-` | Why did it happen? | root cause + contributing factors | incident RCA, accident investigation, defect CAPA, debugging | missed systemic cause = recurrence |
| Adjudication | `adjudication-` | Is it X, or not-X? | disposition + confidence | fraud, insurance claims (SIU), AML/SAR, audit (error vs fraud), complaint validity | asymmetric: false positive ≠ false negative |
| Triage | `triage-` | How bad, who owns it, how fast? | route + priority | incident severity, security alert, support routing | delay is the costly error |
| Verification | `verification-` | Is the claim true? | supported / refuted / unproven + trace | fact-checking, OSINT, financial-statement audit | unsupported claim published = the costly error |
| Acceptance | `acceptance-` | Is it OK to proceed? | risk rating + conditions | contract DD, vendor onboarding, M&A tech DD, hiring, regulatory-change impact | missed red flag = downstream liability |
| Diagnosis | `diagnosis-` | What's wrong with it? | condition + confidence | medical, mechanical | wrong treatment — **declined as a vertical** (ADR-0003, option 5) |

Triage is not a peer of the others — it is the shallow, confidence-gated
judgement that routes a signal into one of the families above. A future
`triage-` pack is the front door, not a destination.

## What each family exercises in the engine

- **Attribution** — negative evidence (the dog that didn't bark),
  alibi-style constraints, timeline pruning. The suspect space is
  *people*.
- **Causation** — timeline reconstruction as the constraint surface;
  each hypothesis is a *causal chain* that predicts a signature, and
  evidence checkpoints prune chains that contradict the timeline.
- **Adjudication** — base-rate priors; cheap, decisive discriminating
  tests (a PO match, a domain lookalike, an account's age); the verdict
  is a *disposition* (pay / block / escalate), and the engine owns the
  disposition rules while the LLM only reads documents.
- **Triage** — fast, shallow packs; a confidence-gated handoff to a
  human or to a deeper pack.
- **Verification** — source triangulation; absence of corroboration
  refutes; the trace *is* the verdict.
- **Acceptance** — obligation extraction + rule checklists; the verdict
  is a gate, not an explanation.
- **Diagnosis** — the canonical abduction, declined for liability
  reasons; the method transfers if a domain ever clears the bar.

## The demo cases (prefix convention)

Case directories are prefixed with the family, so the type is visible as
examples accumulate: `engine/cases/<type>-<slug>/`.

| Case | Family | The story | The verdict |
|---|---|---|---|
| `attribution-silver-blaze` | attribution | a champion horse vanishes; its trainer is found dead; the kennel dog did not bark | self-sabotage — the trainer was paid to sabotage his own horse |
| `adjudication-phantom-invoice` | adjudication | a €38,400 invoice to a vendor that doesn't exist; the real vendor denies it | external invoice fraud — recall, escalate, notify the bank |
| `causation-three-am-outage` | causation | checkout degrades 02:47–03:12 — our deploy, our cert, an attack, or the provider? | upstream provider outage — plus the detection gap to fix |

`./facty selftest` asserts the abductive skeleton for every case
(forward chain + open questions, constraint pruning, ranked hypotheses,
the discriminating test, backward-chained verdict, deterministic replay)
plus each case's narrative outcome. See each case's `expected.md`.

## Where this maps to the verticals

- **Tier 1** ([verticals.md](discovery/verticals.md)): adjudication
  (AML/fraud investigation), causation (abductive incident RCA),
  triage + attribution (security assessment).
- **Tier 2**: acceptance (contract due diligence), verification
  (audit-adjacent).
- **Tier 3**: acceptance (M&A tech DD), verification (scientific /
  RFP work).
- **Declined**: diagnosis (ADR-0003, option 5).

## See also

- [docs/discovery/verticals.md](discovery/verticals.md) — market tiers
- [ADR-0003](adr/0003-detective-dss-neurosymbolic-core.md) — the neurosymbolic core
- [ADR-0004](adr/0004-cli-primary-interface.md) — the `facty` CLI + the retired stdlib-only rule
- [engine/README.md](../engine/README.md) — the engine + case layout
- [docs/discovery/detective-dss-poc.md](discovery/detective-dss-poc.md) — the PoC plan
