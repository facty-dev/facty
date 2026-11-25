# Expected outcome — `verification-nobid-contracts`

**Protagonist:** Dana, a local reporter. A FOIA drop shows a $2.4M no-bid HVAC
contract to a vendor sharing an address with a city official, against a $900k
budget line, while two cheaper competitive bids were disqualified on
technicalities. The dossier must prove it before publication.

## Phase 1 (initial evidence drop)

Derived facts: `d1` noBidFlag, `d2` overBudgetFlag, `d3` pricePremiumFlag,
`d4` thinCompetitionFlag, `d5` conflictMarker, `d6` dossierReady.

| Hypothesis | Status | Score |
|---|---|---|
| H1 — overvalued no-bid award to a connected vendor | open | 0.950 |
| H2 — legitimate emergency procurement | pruned by `c-no-emergency-eliminates-H2` | — |
| H3 — record-keeping error | pruned by `c-records-agree-eliminates-H3` | — |

Recommended discriminating test: `q-emergency-declaration` (the question that
separates favouritism from a lawful emergency award).

Ethics guard `c-two-source-guard` is present and inert (three independent
records exist); with fewer than two independent sources it would prune H1 —
Facty never publishes a connection claim on one source.

## Assembly

`facty assemble` renders the verified story dossier from all six snippets
(header, award + price gap, thin competition, the connection, custody, method
and limits), commits `AssembledDocument` with a sha256, and every claim in it
carries a proof (rule + premises) and a provenance span.

**Payoff:** H1 supported, the story is publishable with proofs attached, and
the record-keeping-error explanation is excluded — a battle, not the war.
