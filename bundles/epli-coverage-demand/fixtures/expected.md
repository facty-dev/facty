# Expected outcome — `adjudication-epli-denial`

**Protagonist:** James, 58, a regional sales manager terminated ten days after
filing an internal age-discrimination complaint. His employer's EPLI insurer
denied coverage for "late notice" and "failure to follow the internal
complaint procedure". Facty assembles the coverage-demand package that
overturns the denial.

## Phase 1 (initial evidence drop)

Derived facts: `d1` noticeTimely, `d2` procedureFollowed, `d3` epliCovered,
`d4` denialWrongful.

| Hypothesis | Status | Score |
|---|---|---|
| H1 — denial wrongful (timely notice, procedure followed, coverage applies) | open | 0.950 |
| H2 — denial proper (late notice) | pruned by `c-notice-timely-eliminates-H2` | — |
| H3 — no coverage (exclusion applies) | pruned by `c-exclusion-absent-eliminates-H3` | — |

Recommended discriminating test: `q-insurer-notice-date` (the date that starts
or ends the 90-day claims-made clock).

The arithmetic is the spine of the case: termination 2026-03-02, notice
2026-04-12 = **day 41 of 90** (`notice.daysAfterTermination < policy.noticeWindowDays`,
a numeric `cmp` comparison). `procedureFollowed` rests on the complaint email
of 2026-02-20 and HR's acknowledgement (HR-2026-041) — both before the
termination.

Litigation-grade guard `c-two-source-guard` is present and inert (three
independent records exist); with fewer than two it would refuse the demand.

## Assembly

`facty assemble` renders the coverage demand package from all six snippets
(header, the denial, timely notice, procedure followed, insuring clause, demand
+ reservation), commits `AssembledDocument` with a sha256, and every assertion
carries a proof tree and a provenance span.

**Payoff:** the insurer rescinds the denial and funds the defense under a
reservation of rights. The underlying employment case continues — this demo
wins the coverage battle, not the war.
