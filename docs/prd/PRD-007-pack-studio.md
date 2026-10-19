---
# Product Requirements Document (PRD)
---

# PRD-007: Pack Studio (the knowledge authoring workbench)

**Status:** draft
**Author:** decision-agent (prd phase)
**Date:** 2026-10-18
**Version:** 0.1

---

## 1. Overview

### What
**Pack Studio** is the knowledge authoring workbench: it lets a domain
expert (fraud analyst, SRE, claims adjuster — not a Facty engineer)
create a complete, tested, deterministic knowledge engine (a **pack**)
on Facty in a single sitting, with the LLM as pair programmer and the
symbolic engine as validator.

The **MVP** (this PRD's scope) is the CLI half — a `./facty pack`
subcommand group that proves the two smallest slices from the OST
build order:

1. **CLI test mode** — `pack validate` + `pack test` with gap analysis
   (SOL-004-B: proves the test harness)
2. **One-shot LLM ops** — `pack draft-rules` / `suggest-labels` /
   `draft-hypotheses` / `draft-questions` / `review` (SOL-003-B: proves
   the LLM authoring path)

The **follow-up phases** (out of scope here, scheduled in §10) are the
full workbench: the TUI surfaces (schema curator, rule editor, label
sensor config, test harness tab — SOL-001-A), the embedded pi agent
pane (SOL-003-A), and the **meta-Facty loop** (SOL-002-A) — the central
innovation, specified in Appendix A.

**One-liner:** "Domains are packs — and now anyone can author one."

### Why
- **The knowledge acquisition bottleneck (OPP-001):** every pack today
  is hand-edited JSON. That is the exact bottleneck that caused the
  1980s AI winter — expert systems needed human knowledge engineers and
  didn't scale. The Facty team is the bottleneck for every new vertical.
- **No structured elicitation (OPP-002):** there is no question-driven
  process for extracting a domain expert's knowledge. Gaps surface only
  when a case fails.
- **The LLM is sensing-only (OPP-003):** the LLM reads evidence into
  facts but never helps author the pack — never drafts a rule, never
  suggests a label set, never reviews constraints for gaps.
- **No test harness (OPP-004):** there is no way to test a pack
  incrementally. You write rules, run a full case, and hope.

### Problem statement
A domain expert cannot create or validate a pack on Facty today. Pack
authoring is hand-coded JSON with no validation, no incremental test,
no LLM assistance, and no elicitation protocol — so "domains are packs"
is unproven at the user level: we have packs, but no way for users to
make their own.

### Who
**Target users:** domain experts who own a judgement-heavy workflow
(fraud, incidents, claims, contracts) and want Facty to reason with
*their* expertise.

**Personas:**
- **Dana, fraud analyst:** 10 years of invoice-fraud experience, zero
  JSON tolerance. Wants her rules in the engine without learning the
  schema syntax.
- **Sam, SRE:** runs incident RCA. Wants a causation pack for his
  stack, tested against last quarter's outages.
- **Kim, claims adjuster:** wants an insurance-fraud pack; will judge
  the tool by whether she can finish it in one sitting.
- **Rita, Facty engineer (secondary):** validates packs, maintains the
  platform, gates pack quality in CI.

---

## 2. Goals & Non-Goals

### Goals (In Scope — the MVP)
- [ ] **GOAL-1:** CLI test mode — `./facty pack validate` + `./facty pack test` with gap analysis (SOL-004-B)
- [ ] **GOAL-2:** One-shot LLM authoring ops — `draft-rules`, `suggest-labels`, `draft-hypotheses`, `draft-questions`, `review` (SOL-003-B)
- [ ] **GOAL-3:** The pack as a first-class, git-versioned artifact directory (`packs/<slug>/`), attachable to cases
- [ ] **GOAL-4:** The platform invariants hold on the authoring path: deterministic test mode, stdlib-only core + CLI, cached + streamed LLM ops, human acceptance gate

### Non-Goals (Out of Scope — follow-up phases, scheduled in §10)
- **NON-GOAL-1:** TUI surfaces (schema curator, rule editor, label sensor config, test harness tab in `engine/tui.py`) — follow-up phase 1
- **NON-GOAL-2:** Embedded pi agent pane (persistent chat, the knowledge engineer's pair programmer) — follow-up phase 2
- **NON-GOAL-3:** The meta-Facty loop (question-driven domain elicitation — Appendix A) — follow-up phase 3
- **NON-GOAL-4:** `pack new` template scaffolding (SOL-002-B — not recommended by the OST)
- **NON-GOAL-5:** Web UI / hosted multi-tenant authoring / pack marketplace
- **NON-GOAL-6:** Any change to the verdict path or engine semantics — `diagnose` is additive; `run_case` is untouched

---

## 3. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-001 | domain expert | validate my pack's JSON before running anything | I catch schema/syntax errors immediately, not at case runtime |
| US-002 | domain expert | run my pack against a fact set and see the verdict + trace | I see what my rules actually do |
| US-003 | domain expert | see gap analysis (dead rules, unraised hypotheses, unanswered questions) | I know what's missing before I ship the pack |
| US-004 | domain expert | assert expected outcomes per scenario (`--tests` + expected) | I can gate my pack in CI |
| US-005 | domain expert | draft rules from a plain-language description of my domain | I don't write JSON from scratch |
| US-006 | domain expert | get a suggested label set + `classify.json` from sample evidence | I don't hand-write sensor config |
| US-007 | domain expert | get draft hypotheses + Strom decision questions | the explanation space and the sensor are complete |
| US-008 | domain expert | get an advisory review of my pack for gaps | I catch what I don't know I don't know |
| US-009 | domain expert | replay every LLM op offline from the response cache | I can demo and test without spending tokens |
| US-010 | Facty engineer | run `./facty pack` in CI with zero extra deps | I gate pack quality the way the selftest gates cases |
| US-011 *(follow-up)* | domain expert | author a pack in the Pack Studio TUI surfaces | authoring is a first-class workbench, not a JSON-editing exercise |
| US-012 *(follow-up)* | domain expert | chat with an embedded agent while authoring | the LLM is my pair programmer |
| US-013 *(follow-up)* | domain expert | answer engine-generated questions until my domain is fully encoded | the pack is complete by construction (the meta-Facty loop) |

---

## 4. Requirements

### Functional Requirements (MVP)

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| REQ-001 | `./facty pack validate <pack>` validates the pack artifacts (rules, constraints, hypotheses against `engine/schemas/`; `classify.json` structural checks when present) and reports every violation with file + rule | P0 | A valid pack exits 0 with a clean report; a pack with a schema violation exits 1 naming the file and the violation |
| REQ-002 | `./facty pack validate` cross-artifact checks: unique rule/hypothesis/constraint IDs; constraints reference existing hypotheses; rules' `raise` targets exist; the `pack` field matches the directory name | P0 | A constraint referencing a missing hypothesis is rejected with a named error |
| REQ-003 | `./facty pack test <pack> --facts <file>` runs the engine on a fact set: verdict + full trace (derived facts, fired rules, open questions, pruned hypotheses) — deterministic, no LLM | P0 | Two runs are byte-identical; the result matches the equivalent `run_case` output |
| REQ-004 | Gap analysis in `pack test`: dead rules (never fire), unraised hypotheses (in the pack, never raised), pruned hypotheses with constraint reasons, open questions left unanswered by the fact set | P0 | A fixture pack with a known dead rule / unraised hypothesis / unanswered question is flagged correctly |
| REQ-005 | `./facty pack test --json` emits the machine-readable result (verdict, trace, gaps) | P0 | Parseable JSON on stdout with `verdict`, `trace`, and `gaps` keys |
| REQ-006 | `./facty pack test <pack> --tests <dir>` runs every `facts-*.json` scenario in a tests directory; a scenario with an expected outcome is asserted and exits non-zero on mismatch | P1 | A failing scenario exits 1 and names the scenario |
| REQ-007 | `./facty pack test <pack> --evidence <dir>` senses sample evidence → facts → verdict (live or from cache), without a full case directory | P1 | Matches the recorded-facts run of the same pack (validates ASM-4a-2) |
| REQ-008 | `./facty pack list` lists the packs under `packs/` with artifact counts | P1 | An empty `packs/` exits 0 with "no packs yet"; a seeded pack is listed |
| REQ-009 | `engine/pack.py` — the library behind the CLI: `load_pack`, `validate_pack`, `diagnose`, `run_pack_test` (stdlib-only, importable without the CLI) | P0 | Unit-tested directly, no CLI involved |
| REQ-010 | `./facty pack draft-rules <pack> --domain "<text>"` — schema-guided LLM extraction: a domain description → draft `rules.json` (validated + judge-checked, streamed) | P0 | The draft validates against `rule.schema.json` and passes the REQ-002 cross-checks; staged per REQ-015 |
| REQ-011 | `./facty pack suggest-labels <pack> --evidence <file>` — drafts `classify.json` (labels, columns, threshold, template) from sample evidence | P0 | The draft is structurally valid (required keys, non-empty labels, threshold in range); staged per REQ-015 |
| REQ-012 | `./facty pack draft-hypotheses <pack> --domain "<text>"` — drafts `hypotheses.json` (statements, priors, claims) | P1 | Validates against `hypothesis.schema.json`; staged per REQ-015 |
| REQ-013 | `./facty pack draft-questions <pack>` — drafts `sensor/decisions.json` (the Strom question set), mirroring `sense --op decide` | P1 | Passes the same judge as `--op decide`; staged per REQ-015 |
| REQ-014 | `./facty pack review <pack>` — advisory LLM review for gaps (dead rules, unproven hypotheses, missing constraints) — prose output, never written to the pack | P1 | Prints a review; the pack directory is byte-identical before and after |
| REQ-015 | Draft write policy: every draft op stages `<artifact>.draft.json` beside the target and prints a summary by default; `--write` overwrites the target explicitly; the human always accepts | P0 | Without `--write` the target is untouched; with `--write` the draft replaces it |
| REQ-016 | LLM op plumbing: streamed output, response cache (`.agentic/cache/sensing/`), `FACTY_SENSE=cache` / `--offline` replay, one pi session per run (`sensing.session_scope()`) | P0 | A cached op replays byte-identically with no LLM call; the run log prints the cache summary like `sense` |

### Functional Requirements (follow-up phases — summary; detailed in their own PRD deltas)

| ID | Requirement | Phase |
|----|-------------|-------|
| REQ-F1 | TUI surfaces in `engine/tui.py`: schema curator, rule editor, label sensor config, test harness tab — JSON-backed, live validation, one shared pack state object (SOL-001-A) | follow-up 1 |
| REQ-F2 | Embedded pi agent pane: persistent chat over the pi RPC transport, one process per Pack Studio session; drafts rules, suggests labels, reviews gaps, drafts Strom questions (SOL-003-A) | follow-up 2 |
| REQ-F3 | The meta-Facty loop: engine-generated elicitation questions → user answers → symbolic representations → validate → iterate until the pack is complete (SOL-002-A, Appendix A) | follow-up 3 |

### Non-Functional Requirements

| ID | Category | Requirement | Target |
|----|----------|-------------|--------|
| NFR-001 | Performance | `pack test` on a demo-scale pack (100 rules, 200 facts) | < 1s (validates ASM-4a-1) |
| NFR-002 | Determinism | `pack test --facts`: no LLM, no clock, no random source in the path | byte-identical replay |
| NFR-003 | Dependency-free | engine core + CLI + `engine/pack.py` import stdlib only | runs in the gondolin VM snapshot + CI |
| NFR-004 | Cache fidelity | LLM draft ops replay from the response cache | byte-identical, no LLM call |
| NFR-005 | Safety | no API keys logged; drafts never overwrite without `--write`; LLM output never enters the verdict path | ADR-0003 §1 |
| NFR-006 | Auditability | packs are git-versioned JSON text artifacts; test runs leave no state beyond the LLM response cache | `git status` clean after `pack test --facts` |

---

## 5. Assumptions

*Carried from the OST (`docs/discovery/assumptions.md`) — to be validated during implementation*

| ID | Assumption | Source | Validation Method | Status |
|----|-----------|--------|-------------------|--------|
| ASM-4a-1 | The engine can run in authoring mode — pack + fact set → trace + gap analysis in < 1s | OST | `pack test` timing on a 100-rule fixture (REQ-003/004) | pending |
| ASM-4a-2 | The sensing pipeline can go sample evidence → facts → verdict without a full case directory | OST | `pack test --evidence` matches the recorded-facts run (REQ-007) | pending |
| ASM-2a-2 | Schema-guided extraction turns a domain description into useful, schema-valid pack artifacts | OST | `draft-rules` output validates + the author accepts it (REQ-010) | pending |
| ASM-P1 | User packs live at `packs/<slug>/` (not inside `engine/cases/`) and authors accept that location | PRD | PO review (Q-001) + dogfood | pending |
| ASM-1a-1 *(follow-up)* | The four TUI surfaces can share one pack state object without conflicting writes | OST | TUI-phase prototype | deferred |
| ASM-1a-2 *(follow-up)* | Textual renders the split-pane layout (editor + agent chat + test output) at 80x24 | OST | TUI-phase prototype | deferred |
| ASM-3a-1 *(follow-up)* | The pi RPC transport runs as a persistent subprocess inside the TUI | OST | agent-phase prototype | deferred |
| ASM-2a-1 *(follow-up)* | The engine's question-generation is repurposable for elicitation questions | OST | meta-Facty-phase spike | deferred |
| ASM-2a-3 *(follow-up)* | The elicitation loop converges (no oscillation, no repeated questions) | OST | meta-Facty phase: rounds-to-complete on a known domain | deferred |
| ASM-1a-3 / 2a-4 / 3a-3 / 4a-3 *(untestable)* | Experts will use the TUI, answer structured questions better than writing rules, use the agent as a pair programmer, and iterate with the harness | OST | Dogfood: 3 domain experts; time-to-first-pack + gap precision | deferred |

---

## 6. Open Questions

| ID | Question | Owner | Due Date | Status |
|----|----------|-------|----------|--------|
| Q-001 | Explicit vocabulary artifact (`pack/vocabulary.json`: entities + predicates) or keep the vocabulary derived from the rules? | PO | 2026-10-20 | open |
| Q-002 | `--evidence` implementation: stage a temp case dir and reuse `sense_one`, or refactor the sensing boundary first? | Engineering | 2026-10-21 | open |
| Q-003 | Draft write policy: `.draft.json` staging + explicit `--write` — confirm? | PO | 2026-10-20 | open |
| Q-004 | Should `pack test --tests` adopt the case `expected.md` format for assertions (the CI gate)? | PO | 2026-10-21 | open |
| Q-005 | Pack → case attachment mechanics: copy, symlink, or a `pack attach <pack> <case>` command? | PO | TUI phase | deferred |
| Q-006 | Meta-Facty loop convergence criterion: max rounds, human gate, or gap-analysis-zero? | PO | meta-Facty phase | deferred |

---

## 7. Acceptance Criteria

The MVP is complete when:

- [ ] **AC-1:** `./facty pack validate` accepts a valid pack (exit 0) and rejects schema violations + cross-artifact errors (exit 1, named)
- [ ] **AC-2:** `./facty pack test --facts` is deterministic (byte-identical replay) and runs in < 1s on a demo-scale pack
- [ ] **AC-3:** gap analysis flags a fixture's known dead rule, unraised hypothesis, and unanswered question
- [ ] **AC-4:** `draft-rules` produces a schema-valid, judge-accepted rules draft staged as `rules.draft.json`; the target is untouched without `--write`
- [ ] **AC-5:** `suggest-labels` produces a structurally valid `classify.json` draft (staged)
- [ ] **AC-6:** every LLM op replays from the response cache (`FACTY_SENSE=cache`) byte-identically with no LLM call; one pi session per run
- [ ] **AC-7:** `python3 engine/test_pack.py` passes with a stubbed runner (no LLM, no network); `./facty selftest` + `./facty test` pass with `test_pack.py` added
- [ ] **AC-8:** the engine core + CLI + `engine/pack.py` import stdlib only (runs in the gondolin VM snapshot + CI)
- [ ] **AC-9 (follow-up gate):** the insurance fraud pack is authored with Pack Studio by 2026-12-31 (the OST desired outcome — dogfood)

---

## 8. Dependencies

| Dependency | Type | Owner | Status | Blocker? |
|------------|------|-------|--------|----------|
| The symbolic engine (`run_case`, `forward_chain`, `apply_constraints`, `combine`) | Feature | Facty team | shipped | YES (MVP) |
| The sensing pipeline (`extract_structured`, `session_scope`, response cache) | Feature | Facty team | shipped | YES (slice 2) |
| The artifact schemas (`engine/schemas/`) | Feature | Facty team | shipped | YES |
| The label sensor + Strom client (`classify.json` / `decisions.json` shapes) | Feature | Facty team | shipped | YES (REQ-011/013) |
| ADR-0003 / ADR-0004 (the invariants the authoring path must respect) | Architecture | Facty team | shipped | YES |
| BDD specs (`specs/features/pack-studio.feature`) | Spec | decision agent | next phase | NO |
| Textual (the workbench) | Optional dep | — | ready | NO (follow-up TUI phase only) |

---

## 9. Success Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Time-to-first-pack (domain expert, one sitting) | N/A (hand-authoring today) | < 1 sitting | dogfood timing |
| Pack test runs per authoring session | 0 (no harness exists) | > 5 | CLI usage count / dogfood |
| LLM draft acceptance rate | N/A | > 60% accepted with minor edits | dogfood review |
| Gap analysis precision | N/A | > 80% of flagged gaps confirmed by the author | dogfood review |
| LLM cache hit rate on draft ops | N/A | measured (session-prefix reuse) | run-log cache summary |
| Dogfood | — | insurance fraud pack authored with Pack Studio by 2026-12-31 | repo state |

---

## 10. Timeline

| Phase | Dates | Deliverable |
|-------|-------|-------------|
| Discovery | 2026-10-18 | OST (`docs/discovery/ost.md`) — done |
| PRD | 2026-10-18 | This document (PRD-007) |
| BDD specs | 2026-10-19 | `specs/features/pack-studio.feature` |
| MVP slice 1 — CLI test mode | 2026-10-19 → 2026-10-23 | `./facty pack validate/test` + gap analysis + `engine/pack.py` + tests |
| MVP slice 2 — one-shot LLM ops | 2026-10-26 → 2026-10-30 | `draft-rules` / `suggest-labels` / `draft-hypotheses` / `draft-questions` / `review` |
| Review | 2026-11-02 | coding-to-decision result + PO approval |
| Follow-up phase 1 — TUI surfaces | 2026-11 | schema curator, rule editor, label config, test tab in `engine/tui.py` |
| Follow-up phase 2 — embedded agent pane | 2026-11 → 2026-12 | persistent pi RPC chat pane |
| Follow-up phase 3 — meta-Facty loop | 2026-12 | question-driven domain elicitation (Appendix A) |
| Dogfood | by 2026-12-31 | insurance fraud pack authored with Pack Studio |

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM draft quality too low for rule authoring (ASM-2a-2) | Medium | High | the judge layer + capped correction loop (already exists); the human acceptance gate; prompt iteration in slice 2 |
| Gap analysis too noisy | Medium | Medium | deterministic flags only (no heuristics) in the MVP; dogfood-tune later |
| Sensing pipeline too coupled to case dirs (ASM-4a-2) | Medium | Medium | stage a temp case dir for `--evidence`; refactor the boundary early; descope to P2 if it bites |
| Scope creep into the TUI | Medium | Medium | the MVP is CLI-only; the TUI is a separate phase with its own review |
| Pack/case split confuses authors | Medium | Low | clear docs + README layout; attach mechanics (Q-005) in the TUI phase |
| Cache/offline divergence on draft ops | Low | Medium | replay assertions in `test_pack.py`; CI runs the offline replay |

---

## 12. Appendix

### A. The meta-Facty loop (the central design — follow-up phase 3)

Pack Studio turns the case loop inside out: instead of investigating a
*case*, it investigates the *user's domain knowledge*. This is
**literally using Facty to compose a domain** — the same
question-generation and sensing machinery that investigates a case is
used to investigate the user's expertise.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  THE META-FACTY LOOP (domain composition)                               │
│                                                                         │
│  User describes their domain (free text, examples, sample evidence)     │
│       │                                                                 │
│       ▼                                                                 │
│  Engine generates QUESTIONS (what entities? what predicates? what       │
│  rules? what hypotheses? what labels?) — driven by the pack schema      │
│       │                                                                 │
│       ▼                                                                 │
│  User answers (the "evidence" is the conversation)                       │
│       │                                                                 │
│       ▼                                                                 │
│  Agent generates SYMBOLIC REPRESENTATIONS (schemas, rules, constraints,  │
│  hypotheses, labels) — schema-guided extraction from the answers        │
│       │                                                                 │
│       ▼                                                                 │
│  Validate (run the engine on sample scenarios, check for gaps)          │
│       │                                                                 │
│       ▼                                                                 │
│  User reviews and refines — iterate until satisfied                     │
│       │                                                                 │
│       ▼                                                                 │
│  Pack is complete (exportable, testable, versioned in git)              │
└─────────────────────────────────────────────────────────────────────────┘
```

| Case loop (Facty today) | Meta-Facty loop (Pack Studio) |
|---|---|
| Evidence (messy files) | User's answers (conversation) |
| Facts (sensed by LLM) | Domain concepts (entities, predicates) |
| Rules (chain facts) | Rules (authored from concepts) |
| Hypotheses (explanations) | Hypotheses (the explanation space) |
| Constraints (prune) | Constraints (prune invalid packs) |
| Open questions (engine asks) | Open questions (engine asks the user) |
| Verdict (deterministic) | Validated pack (deterministic, testable) |

The MVP slices prepare the loop: the gap analysis (REQ-004) becomes the
loop's validation step, the one-shot LLM ops (REQ-010…014) become its
generation step, and the question schema (`question.schema.json`) is
already the loop's question artifact.

### B. Pack directory layout

A Pack Studio pack mirrors the case layout, minus the case:

```
packs/<slug>/
  pack/
    rules.json            # rule.schema.json
    constraints.json      # constraint.schema.json
    hypotheses.json       # hypothesis.schema.json
  classify.json           # optional — the label sensor config
  sensor/
    decisions.json        # optional — the Strom question set
    extract.py            # optional — the generated extract parser
  tests/
    facts-<scenario>.json # test fact sets (--tests)
    evidence/<scenario>/  # optional raw sample evidence (--evidence)
    expected.md           # optional expected outcome (asserted)
```

`engine.run_case(pack_dir, facts=...)` works unchanged on this layout —
the pack attaches to a case by copying `packs/<slug>/pack/` into
`engine/cases/<case>/pack/` (mechanics per Q-005).

### C. CLI surface summary (MVP)

```bash
./facty pack list                                   # list packs under packs/
./facty pack validate <pack>                        # schema + cross-artifact validation
./facty pack test <pack> --facts <file> [--json]    # run the engine on a fact set + gaps
./facty pack test <pack> --tests <dir>              # run every scenario, assert expected
./facty pack test <pack> --evidence <dir>           # sense sample evidence → verdict (P1)
./facty pack draft-rules <pack> --domain "<text>" [--write]
./facty pack suggest-labels <pack> --evidence <file> [--write]
./facty pack draft-hypotheses <pack> --domain "<text>" [--write]
./facty pack draft-questions <pack> [--write]       # the Strom question set
./facty pack review <pack>                          # advisory gap review (prose, never written)
```

### D. Related Documents
- OST: `docs/discovery/ost.md` (+ `problems.md`, `solutions.md`, `assumptions.md`)
- ADRs: `docs/adr/0003-detective-dss-neurosymbolic-core.md`, `docs/adr/0004-cli-primary-interface.md`
- `engine/README.md` — the engine layout + protocol
- `docs/INVESTIGATION-TYPES.md` — the case-prefix convention packs attach to
- PRD-002 (rules engine), PRD-005 (neurosymbolic bridge)

### Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-10-18 | decision-agent (prd phase) | Initial draft — MVP scoped to CLI test mode + one-shot LLM ops; TUI surfaces, embedded agent, meta-Facty loop as follow-up phases |
