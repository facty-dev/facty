# Exemplars — interactive data-asset assembly for non-technical workers

**Status:** proposed (ADR-0010) · **Date:** 2026-11-17
**Related:** [docs/vision.md](vision.md) (CRT Solution Explorer inspiration),
[docs/INVESTIGATION-TYPES.md](INVESTIGATION-TYPES.md) (`assembly-` family),
[ADR-0010](adr/0010-triadic-runtime-parity.md) (triadic runtime), [ADR-0007](adr/0007-case-lifecycle-ingest-contract.md) (custody).

**ELI5 / positioning:** Facty is the open-source, cross-industry answer to
commercial document-assembly platforms (Relativity/Gavel in law): interactive,
stochasto-deterministic assembly of a **data asset** — the "document" can be
anything Dagster represents as an asset (a court packet PDF, a story dossier,
a claim-record write-back). The users are non-technical workers — lawyers,
journalists, claims people — who answer questionnaires and file things. Not the
saturated dev-tools market (see verticals.md scan).

Classic principle (Docassemble, BC CRT Solution Explorer): questions as data,
templates with conditions, logical assembly. Facty adds LLM sensing of messy
evidence, chain of custody, and deterministic proof-traced verdicts.

## Intent recognition + slot filling drive the dynamic questionnaire

The human loop is not a fixed form. It runs per turn like this:

```
human utterance ("I want to recover an unpaid invoice from a client")
   │  intent recognition — mode `ranked`:
   │    1. deterministic rules first: known intent phrases → pack + Goal +
   │       hypothesis space (e.g. → small-business-contract-claim /
   │       recover-unpaid-invoice / {H1 breach, H2 setoff, H3 no-breach})
   │    2. unrecognized → LLM proposes candidate intents as a typed enum
   │       (pydantic-ai output_type); engine ranks; the pick is recorded in
   │       the Turn doc — replayable, auditable
   │    (the ethics-guard constraint prunes intents targeting workers)
   ▼
Goal.requiredSlots (from the pack: e.g. deliveryDate, writtenComplaint?,
amount, jurisdictionLimit)
   ▼
Slot spec (in the pack): each `Goal.requiredSlots` entry declares
   `{name, type, fillers: [human | llm | pipeline], confirm: bool}`.
   ▼
slot filling — ANY permitted filler may fill a slot; each filler writes a
   Fact with its own source tag, so the trace shows who filled what:
   │  human    │ free text / options in the UI questionnaire → typed extraction │ `answer:<slot>`
   │  llm      │ pydantic-ai sensing over evidence chunks (if pack allows)      │ `sense:<doc>:<span>`
   │  pipeline │ Dagster asset output (e.g. OCR'd date from a scan, API pull)   │ `pipeline:<asset>@<run>`
   Permission rule: non-human fillers run only if the pack lists them in
   `fillers`; any slot with `confirm: true` (or filled by a non-human filler
   when the user hasn't opted in) opens a ranked confirmation Question to the
   human ("the pipeline read deliveryDate=2026-05-02 from the receipt scan —
   confirm?") and the confirmation is recorded in the Turn doc.
   ▼
engine gap analysis (deterministic): missing slots / unresolved constraints
   → opens ranked Question docs ONLY for the gaps — the questionnaire is
   dynamic: content and order adapt to every answer (Docassemble model:
   questions are data, gap analysis drives the next question)
   ▼
hypothesis space converges → constraints prune → backward proof → assemble
```

So in the demo cases: Marisol says "my client won't pay the cake invoice" —
intent recognition selects the pack and hypothesis space, the required slots
become the questionnaire, her free-text answers fill slots as Facts, and the
engine asks only what's still missing (e.g. only asks "any written complaint?"
if the email thread didn't already answer it — slot already filled by the
machine loop's sensing is skipped). Same for Dana ("the city gave a no-bid
contract to the mayor's guy") and James ("my EPLI insurer denied coverage").

### Switching surfaces mid-chain: chat ↔ wizard

Each turn also carries a `surface` (`chat` | `wizard`), recorded in the `Turn`
doc next to `mode` — so a chain can swap **at any turn boundary**, and the
swap itself is part of the replayable audit:

- **wizard mode** — the engine drives: ranked `Question` docs rendered as the
  questionnaire (options, notes, review tab), gap analysis picks the next one.
- **chat mode** — free conversation with the harness agent; every utterance
  still goes through intent recognition + slot filling, so chat answers fill
  the same slots as wizard answers (same Fact, same `answer:<slot>` tag), and
  the agent can invoke the same ops as the machine loop over MCP (`run`,
  `prove`, `ingest`, …) — parity by construction.
- **switching** — the user toggles at any point (UI toggle / CLI flag); open
  Questions live on the case branch, so the wizard resumes exactly where it
  paused and chat-derived slots count the same. Packs may set a default
  surface per step; the user may always override (recorded).

## Shared happy path

```
1 PACK (signed bundle)   schema + Goal doc + Snippet docs (`when` conditions)
                        + hypotheses + rules + constraints
2 CASE = branch         facty case init <matter> --bundle <pack>
3 INGEST (Dagster)      raw files/APIs → Original (sha256+CustodyEvent commit)
                        → ExtractedText → EvidenceChunk embeddings, committed
4 SENSE (mixed loops)   machine loop: pydantic-ai typed extraction from chunks;
                        human loop: engine-opened Question docs as UI
                        questionnaire (slot filling) → Facts, committed
5 RUN (per-step modes)  free = sensing; deterministic = chain/prune/rank/
                        assemble; ranked = engine-ranked pick (Turn doc)
6 PROVE                 facty prove <subject> <predicate> → proof tree
7 ASSEMBLE              snippets whose `when` is proven → output asset, committed
8 DATA PRODUCT          Dagster materializes downstream; TDB commit authoritative
9 EXPORT                signed evidence package (M7 attestation)
```

Every case below blends the loop: **stochastic induction** (LLM reads the messy
docs into typed Facts with confidence+source), **forward chaining** (rules
derive), **constraint pruning** (anti-joins kill hypotheses), **backward
chaining** (`prove` builds the proof tree), and a **deterministic assembly**
step that renders the output asset. The retroductive loop completes when the
hypothesis space converges; the verdict carries narrative payoff.

---

## Demo case 1 — Lawyers / small business: `assembly-unpaid-invoice`

**Protagonist:** Marisol, owner of a 12-person bakery. A corporate client
refuses to pay an $18,500 custom-order invoice, claiming "quality issues".
The pack assembles her demand letter + small-claims filing and proves the debt.

- **Pack** `small-business-contract-claim`: Goal = "recover unpaid invoice";
  Snippets = demand-letter clauses, small-claims complaint clauses (each with
  `when`); Hypotheses = H1 breach (full amount owed), H2 partial (quality
  setoff valid), H3 no breach (rejection justified); **ethics guard
  constraint**: any assembly path targeting the business's *employees* is
  pruned (never anti-worker) — shows constraints pruning on norms, not just facts.
- **Sensing (stochastic):** LLM reads the contract PDF + email thread + delivery
  receipt scan (OCR) → Facts: `contract.signed=true`, `delivery.accepted=true
  (email: "the cake was perfect")`, `rejection.inWriting=false`,
  `amount=18500`, each with confidence + source span.
- **Questions (human loop):** driven by intent recognition + slot filling —
  her utterance selects pack/goal/hypotheses; the questionnaire opens only for
  unfilled slots (delivery date, written complaint within 5 days per §7,
  small-claims limit); answers slot-fill into Facts.
- **Forward chain (deterministic):** rules derive `amountOwed=18500`,
  `setoffInvalid` (no timely written rejection per §7), `smallClaimsOK`
  ($18,500 < $20k limit) + Derivation edges.
- **Constraints prune:** eliminate H3 (delivery acceptance email exists);
  eliminate H2 (§7 requires written rejection within 5 days — none exists);
  support H1 per corroborating fact. Guard constraint eliminates any
  employee-targeting snippet.
- **Backward:** `facty prove matter-2026-041 invoice owed` → proof tree
  fact←rule←facts down to the email span.
- **Verdict + payoff:** H1 wins; assembly renders demand letter + complaint;
  committed `AssembledDocument`. *Marisol files and takes default judgment —
  the small business gets paid.*

## Demo case 2 — Journalists / corruption: `verification-nobid-contracts`

> **Status:** built 2026-11-17 as the signed bundle `public-corruption-dossier`
> (selftest entry `verification-nobid-contracts`; `demo-ui.sh --check` green).

**Protagonist:** Dana, a local reporter. A FOIA drop shows a **$2.4M no-bid
HVAC contract** to a vendor sharing an address with a city official, against a
$900k budget line, while two cheaper competitive bids were disqualified on
technicalities. The dossier must prove it before publication.

- **Pack** `public-corruption-dossier`: Goal = "verified story dossier";
  Hypotheses = H1 overvalued no-bid award to connected vendor, H2 legitimate
  emergency procurement, H3 record-keeping error; Snippets = brief sections
  (the award, the price gap, the disqualifications, the connection) each with
  `when` claims.
- **Sensing (stochastic):** LLM + OCR read scanned contracts, budget PDFs,
  disqualification letters, registry records → Facts with source spans:
  `contract.noBid=true`, `amount=2.4M`, `budgetLine=900k`,
  `competitorBids=[1.1M, 1.3M] disqualified=technical`,
  `vendor.address == official.address`.
- **Questions (human loop):** intent ("no-bid contract to the official's
  guy") selects pack/goal; questionnaire opens only for gaps (emergency
  declaration on file? who signed? disqualification review?).
- **Forward:** derive `overpayment ≈ 1.5M vs budget, ≈ 1.1–1.3M vs market`,
  `noBidFlag`, `disqualificationThin`.
- **Constraints prune:** eliminate H2 (no emergency declaration exists);
  eliminate H3 (three independent records agree on $2.4M); support H1 with the
  address match + cheaper disqualified bids.
- **Backward:** `prove contract-77 overvaluedBy ≥1M` → proof tree.
- **Verdict + payoff:** H1 supported; dossier asset = per-claim
  supported/refuted with proof + provenance (custody = source protection).
  *The story runs; the council opens an inquiry.* A battle, not the war —
  exactly the right demo note.

## Demo case 3 — Insurance / plaintiff-side EPLI: `adjudication-epli-denial`

**Protagonist:** James, 58, a sales manager terminated after reporting age
discrimination; his employer's **EPLI insurer denied coverage** claiming late
notice and "failure to follow internal complaint procedure". Not personal
injury — employment practices liability. Facty assembles the coverage-demand
package that overturns the denial.

- **Pack** `epli-coverage-demand`: Goal = "coverage demand package";
  Hypotheses = H1 denial wrongful (notice timely, procedure followed/excused),
  H2 denial proper (late notice), H3 no coverage (exclusion applies);
  Snippets = demand-letter clauses + evidence-bundle sections.
- **Sensing (stochastic):** LLM reads the policy PDF (notice clause: 90 days),
  termination letter, complaint emails, insurer denial letter → Facts:
  `terminated=2026-03-02`, `internalComplaint=2026-03-20`,
  `noticeToInsurer=2026-04-12 (day 41 of 90)`, `policy.insuringClause=EPLI`,
  `denial.reason="late notice + procedure"`.
- **Questions (human loop):** intent ("EPLI insurer denied my coverage")
  selects pack/goal; questionnaire opens only for gaps (HR complaint date,
  counsel date, insurer-notice date, cited exclusions).
- **Forward:** derive `noticeTimely=true` (41 ≤ 90), `procedureFollowed=true`
  (complaint email predates termination), `epliCovered=true`.
- **Constraints prune:** eliminate H2 (`noticeTimely`); eliminate H3 (insuring
  clause present, no exclusion matches the cited reason); support H1.
- **Backward:** `prove matter epliClaim covered` → proof tree.
- **Verdict + payoff:** H1 wins; assembly produces the coverage-demand letter +
  evidence bundle; output asset = claim-record write-back (demand logged) +
  signed bundle. *The insurer rescinds the denial — James's EPLI defense is
  funded.* The underlying employment case continues; this demo wins the
  coverage battle.

## Joint demonstration table

| | 1. Unpaid invoice (lawyers/small biz) | 2. No-bid contracts (journalists) | 3. EPLI denial (insurance plaintiff) |
|---|---|---|---|
| Family | assembly / acceptance | verification + assembly | adjudication + assembly |
| Protagonist wins | gets paid | corruption exposed | denial overturned |
| Stochastic induction | contract/emails/OCR → Facts | scans, budgets, registries → Facts | policy/letters → Facts |
| Forward chaining | amountOwed, setoffInvalid, smallClaimsOK | overpayment, noBidFlag, disqualificationThin | noticeTimely, epliCovered |
| Constraint pruning | H2/H3 eliminated; ethics guard on employees | H2/H3 eliminated | H2/H3 eliminated |
| Backward proof | `prove invoice owed` | `prove overvaluedBy ≥1M` | `prove epliClaim covered` |
| Output asset | court packet PDF | embargoed story dossier | claim write-back + evidence bundle |
| Custody story | filing-grade | source protection | litigation-grade |

## Mapping to the classic systems

| Docassemble / CRT concept | Facty artifact |
|---|---|
| interview YAML (questions as data) | pack: Rule/Hypothesis/Question docs in TerminusDB |
| template with conditions | Snippet doc + assembly rules |
| guided pathway / triage tree | ranked hypotheses + engine-opened Questions (UI questionnaire) |
| generated form | output asset (any kind) + committed record |
| session state | case branch commits (git-for-data, time-travelable) |
| (missing in classics) | custody chain, LLM sensing of messy evidence, proof trees, replay |

## Parity (ADR-0010 invariants in action)

Each case runs identically via CLI, Web UI (questionnaire + preview + trace
view), or an agent over MCP (terminusdb MCP + dagster-mcp + facty MCP server).
Machine loop and human loop call the same ops; the human answers the same
Question docs the machine loop would fill from documents.

### Live visualization of the hypothesis space during chain evolution

Everything the engine does is committed docs on the case branch — `Hypothesis`
(status/prior/score), `Derivation` edges (fact←rule←facts), `Turn` docs
(mode/surface per turn), `Verdict` — so the live view is a rendering of the
branch's commit stream, not a parallel state:

- **`facty serve` watch endpoint** (SSE/WebSocket) tails the branch commit log
  (`/api/log`) and pushes per-turn deltas to the UI.
- **Web UI**: a live hypothesis graph — nodes = hypotheses, colored by status
  (open / pruned-greyed with the killing constraint labeled via `prunedBy` /
  winner), sized by score, edges = Derivation/claim links; clicking a node
  opens its proof tree (`facty prove` panel); a bottom timeline shows each
  `Turn` with mode + surface badges (so chat↔wizard switches are visible too).
  In a demo this is the payoff moment: watch H2/H3 get pruned live, each with
  the constraint that killed it.
- **CLI parity**: `facty watch <case>` / `facty run --watch` prints the same
  evolution textually (turn lines + hypothesis table updates) — same committed
  state, two renderings, per the parity invariant. Dagster's own lineage UI
  covers the pipeline side of the same case.

### Live bullseye: Proven / Open / Anomalies

(The classic known-knowns / known-unknowns / unknown-unknowns rings, relabeled
in plain words for the UI.) The Web UI leads with a concentric-circle view
(live counts from the same commit stream; click any zone for its drill-down
list):

| Zone | Meaning | Facty artifacts (the query behind the count) |
|---|---|---|
| **Inner — Proven** (known knowns) | established, proven | Facts backing Derivation edges; proven snippet `when` conditions; winner/confirmed claims; filled+confirmed slots |
| **Middle ring — Open** (known unknowns) | we know what we don't know | open `Question` docs (unfilled slots, incl. pending confirmations); open hypotheses not yet pruned; ranked discriminating tests |
| **Outer ring — Anomalies** (unknown unknowns) | signals with no explanation yet | `Quarantine` docs (unknown formats/images); `versionConflict` Facts; `semanticContradictionWith` candidates from embeddings; open hypotheses with zero supporting facts (anomalies no hypothesis covers) |

The outer ring (Anomalies) is the honest "unknown unknowns": it surfaces anomalies
(quarantined files, conflicting versions, semantic contradictions, unexplained
hypotheses) that no rule has claimed yet — each one clickable into the evidence
that triggered it. The hypothesis graph (previous section) is the second tab.
`facty watch` prints the same three counts textually (CLI parity).

### Surface priority: Web UI first, CLI as headless driver

The **Web UI is the primary human/demo surface** (questionnaire wizard, chat,
bullseye, hypothesis graph, proof trees). The **CLI stays the headless driver**
for Dagster pipelines and CI (`facty ingest/run/export` inside asset ops and
`facty selftest` in CI) — parity of op set is unchanged, but demos to
non-developers go through the UI.
