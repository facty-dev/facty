---
# Product Requirements Document (PRD)
---

# PRD-002: Rules Engine (Deterministic Decisions)

**Status:** draft
**Author:** agentic-runtime-team
**Date:** 2026-10-06
**Version:** 0.1

---

## 1. Overview

### What
A **rules engine** that evaluates asset graph state and makes deterministic decisions without LLM calls. Rules handle validation, gating, routing, and escalation. When no rule matches, the decision escalates to an LLM (neurosymbolic bridge).

**One-liner:** "Deterministic guardrails for the agentic SDLC — rules decide when they can, LLMs decide when they must."

### Why
- **Cost:** LLM calls are expensive; rules are free
- **Reliability:** Deterministic decisions are reproducible
- **Safety:** Rules enforce invariants (e.g., "no merge without tests")
- **Speed:** Rules evaluate in milliseconds
- **Auditability:** Rule decisions are explainable ("RULE-003 blocked because...")

### Who
- **Rules engine** — evaluates asset state, produces actions
- **Decision agent** — handles escalations (non-deterministic cases)
- **Coding agent** — receives routing decisions
- **Human reviewers** — see which rules gated their review
- **Auditors** — query rule evaluation history

---

## 2. Goals & Non-Goals

### Goals (In Scope)
- [ ] **GOAL-1:** YAML-based rule definitions (`.agentic/rules/*.yaml`)
- [ ] **GOAL-2:** Rule types: validation, gating, selection, routing, escalation, composition
- [ ] **GOAL-3:** Expression language for conditions (JSONPath or CEL)
- [ ] **GOAL-4:** Rule evaluation on asset events (materialized, updated, reviewed)
- [ ] **GOAL-5:** Escalation to LLM when no rule matches
- [ ] **GOAL-6:** Rule evaluation logging (audit trail)
- [ ] **GOAL-7:** CLI: `rules.sh eval`, `rules.sh test`, `rules.sh explain`

### Non-Goals (Out of Scope)
- **NON-GOAL-1:** Complex rule chaining (forward chaining) — v2
- **NON-GOAL-2:** Rule learning (ML-based rule discovery) — v2
- **NON-GOAL-3:** Distributed rule evaluation — single-node only
- **NON-GOAL-4:** Real-time rule updates (reload on git push)

---

## 3. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-001 | Rules engine | Evaluate asset state against rules | I can gate progression deterministically |
| US-002 | Decision agent | Receive escalation when no rule matches | I can make non-deterministic decisions |
| US-003 | Product Owner | See which rule required my review | I understand why I'm being asked |
| US-004 | Auditor | Query rule evaluation history | I can verify gates were enforced |
| US-005 | Developer | Test a rule locally | I know it works before CI |
| US-006 | System | Log every rule evaluation | I have a complete audit trail |

---

## 4. Requirements

### Functional Requirements

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| REQ-001 | Rules defined in YAML (`.agentic/rules/*.yaml`) | P0 | Parseable, schema-valid |
| REQ-002 | Rule schema: id, name, description, when, condition, then | P0 | Validation passes |
| REQ-003 | `when` triggers: asset events (materialized, updated, reviewed, gated) | P0 | Events fire correctly |
| REQ-004 | `condition` types: schema_validation, threshold, test_results, human_review, custom expression | P0 | All types evaluate correctly |
| REQ-005 | `then` actions: block, allow, validate, escalate, materialize, request_review, rematerialize | P0 | Actions execute correctly |
| REQ-006 | Expression language: JSONPath for asset queries | P0 | `$.nodes.prd.status == "materialized"` works |
| REQ-007 | Escalation: when no rule matches, create LLM task | P0 | Task appears in `.agentic/messages/` |
| REQ-008 | Evaluation logging: append to `.agentic/rules-eval.jsonl` | P0 | Every eval logged with result |
| REQ-009 | CLI: `rules.sh eval <asset-key>` — evaluate rules for asset | P0 | Returns matching rules + actions |
| REQ-010 | CLI: `rules.sh test <rule-id> <fixture>` — test rule locally | P1 | Pass/fail with explanation |
| REQ-011 | CLI: `rules.sh explain <eval-id>` — why was this decision made | P1 | Shows rule, condition, result |
| REQ-012 | Integration: GitHub Actions calls rules engine on asset events | P0 | Workflow triggers evaluation |
| REQ-013 | Integration: SDLC agents can query rules | P1 | Agent asks "what should I do?" gets rule answer |

### Non-Functional Requirements

| ID | Category | Requirement | Target |
|----|----------|-------------|--------|
| NFR-001 | Performance | Rule evaluation | < 50ms for < 100 rules |
| NFR-002 | Reliability | No false negatives (missed gates) | 100% gate enforcement |
| NFR-003 | Explainability | Every decision traceable to rule | 100% |
| NFR-004 | Testability | Rules testable without full system | Unit tests per rule |

---

## 5. Assumptions

| ID | Assumption | Source | Validation Method | Status |
|----|-----------|--------|-------------------|--------|
| ASM-001 | JSONPath is sufficient for conditions | Architecture | Evaluate 20+ rule conditions | pending |
| ASM-002 | YAML is human-friendly for rules | Product | User feedback from 3 devs | pending |
| ASM-003 | Most decisions are deterministic (80/20) | Hypothesis | Measure rule vs LLM ratio | pending |
| ASM-004 | Rules can be versioned with code | Architecture | Git-based rule versioning | accepted |

---

## 6. Open Questions

| ID | Question | Owner | Due Date | Status |
|----|----------|-------|----------|--------|
| Q-001 | Should rules be in repo or separate config repo? | Tech Lead | 2026-10-13 | open |
| Q-002 | CEL vs JSONPath for expressions? | Tech Lead | 2026-10-13 | open |
| Q-003 | Can rules call external APIs (e.g., check CI status)? | Security | 2026-10-20 | open |

---

## 7. Acceptance Criteria

Feature is complete when:

- [ ] **AC-1:** Rules load from `.agentic/rules/*.yaml`
- [ ] **AC-2:** `rules.sh eval <asset>` returns matching rules
- [ ] **AC-3:** Validation rules reject invalid assets
- [ ] **AC-4:** Gate rules block progression correctly
- [ ] **AC-5:** Escalation creates LLM task when no rule matches
- [ ] **AC-6:** All evaluations logged to `.agentic/rules-eval.jsonl`
- [ ] **AC-7:** GitHub Actions triggers evaluation on PR events
- [ ] **AC-8:** `rules.sh explain` shows decision rationale

---

## 8. Dependencies

| Dependency | Type | Owner | Status | Blocker? |
|------------|------|-------|--------|----------|
| Asset graph (PRD-001) | Feature | Engineering | in-progress | YES |
| JSONPath library | Tool | — | ready | NO |
| GitHub Actions | Infrastructure | DevOps | ready | NO |

---

## 9. Success Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Rule evaluation time | N/A | < 50ms | Benchmark |
| Rules coverage | 0% | 80% of decisions | Rule vs LLM ratio |
| False negative rate | N/A | 0% | Audit log analysis |
| Developer satisfaction | N/A | > 4/5 | Survey |

---

## 10. Timeline

| Phase | Dates | Deliverable |
|-------|-------|-------------|
| Design | 2026-10-06 — 2026-10-07 | This PRD + rule schema |
| Core engine | 2026-10-08 — 2026-10-12 | `rules.sh` + evaluation |
| Rule types | 2026-10-13 — 2026-10-14 | All 6 condition types |
| GitHub integration | 2026-10-15 — 2026-10-16 | Workflow triggers |
| Review | 2026-10-17 | Tech Lead approval |

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Rule conflicts (two rules, opposite actions) | Medium | High | Priority ordering + conflict detection |
| Expression language too limited | Medium | Medium | Start with JSONPath, add CEL if needed |
| Rules become stale | Medium | Medium | Rule review in SDLC, versioning |

---

## 12. Appendix

### Example Rules

See `docs/ASSET-MODEL.md` § Rules Engine for complete examples.

### Related Documents
- Asset Model: `docs/ASSET-MODEL.md`
- PRD-001: Asset Graph
- PRD-005: Neurosymbolic Bridge (escalation target)

### Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-10-06 | agentic-runtime-team | Initial draft |
