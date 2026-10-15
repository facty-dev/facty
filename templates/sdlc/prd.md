---
# Product Requirements Document (PRD)
---

# PRD-{{NNN}}: {{TITLE}}

**Status:** {{STATUS}} <!-- draft | in-review | approved | in-progress | shipped -->
**Author:** {{AUTHOR}}
**Date:** {{DATE}}
**Version:** {{VERSION}}

---

## 1. Overview

### What
{{WHAT_DESCRIPTION}}

**One-liner:** {{ONE_LINER}}

### Why
{{WHY_DESCRIPTION}}

**Problem statement:** {{PROBLEM}}

### Who
**Target users:** {{TARGET_USERS}}

**Personas:**
- {{PERSONA_1}}: {{DESCRIPTION}}
- {{PERSONA_2}}: {{DESCRIPTION}}

---

## 2. Goals & Non-Goals

### Goals (In Scope)
- [ ] **GOAL-1:** {{DESCRIPTION}}
- [ ] **GOAL-2:** {{DESCRIPTION}}
- [ ] **GOAL-3:** {{DESCRIPTION}}

### Non-Goals (Out of Scope)
- **NON-GOAL-1:** {{DESCRIPTION}} — {{REASON}}
- **NON-GOAL-2:** {{DESCRIPTION}} — {{REASON}}

---

## 3. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-001 | {{ROLE}} | {{ACTION}} | {{BENEFIT}} |
| US-002 | {{ROLE}} | {{ACTION}} | {{BENEFIT}} |
| US-003 | {{ROLE}} | {{ACTION}} | {{BENEFIT}} |

---

## 4. Requirements

### Functional Requirements

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| REQ-001 | {{DESCRIPTION}} | {{P0/P1/P2}} | {{CRITERIA}} |
| REQ-002 | {{DESCRIPTION}} | {{P0/P1/P2}} | {{CRITERIA}} |
| REQ-003 | {{DESCRIPTION}} | {{P0/P1/P2}} | {{CRITERIA}} |

### Non-Functional Requirements

| ID | Category | Requirement | Target |
|----|----------|-------------|--------|
| NFR-001 | Performance | {{DESCRIPTION}} | {{METRIC}} |
| NFR-002 | Security | {{DESCRIPTION}} | {{METRIC}} |
| NFR-003 | Scalability | {{DESCRIPTION}} | {{METRIC}} |
| NFR-004 | Accessibility | {{DESCRIPTION}} | {{METRIC}} |
| NFR-005 | Availability | {{DESCRIPTION}} | {{METRIC}} |

---

## 5. Assumptions

*Carried from OST — to be validated during implementation*

| ID | Assumption | Source | Validation Method | Status |
|----|-----------|--------|-------------------|--------|
| ASM-001 | {{ASSUMPTION}} | OST | {{METHOD}} | {{STATUS}} |
| ASM-002 | {{ASSUMPTION}} | OST | {{METHOD}} | {{STATUS}} |
| ASM-003 | {{ASSUMPTION}} | PRD | {{METHOD}} | {{STATUS}} |

---

## 6. Open Questions

| ID | Question | Owner | Due Date | Status |
|----|----------|-------|----------|--------|
| Q-001 | {{QUESTION}} | {{OWNER}} | {{DATE}} | {{STATUS}} |
| Q-002 | {{QUESTION}} | {{OWNER}} | {{DATE}} | {{STATUS}} |

---

## 7. Acceptance Criteria

Feature is complete when:

- [ ] **AC-1:** {{CRITERION}}
- [ ] **AC-2:** {{CRITERION}}
- [ ] **AC-3:** {{CRITERION}}
- [ ] **AC-4:** {{CRITERION}}
- [ ] **AC-5:** {{CRITERION}}

---

## 8. Dependencies

| Dependency | Type | Owner | Status | Blocker? |
|------------|------|-------|--------|----------|
| {{DEP}} | {{API/Team/Service}} | {{OWNER}} | {{STATUS}} | {{YES/NO}} |

---

## 9. Success Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| {{METRIC}} | {{BASELINE}} | {{TARGET}} | {{METHOD}} |

---

## 10. Timeline

| Phase | Dates | Deliverable |
|-------|-------|-------------|
| Discovery | {{DATES}} | OST |
| PRD | {{DATES}} | This document |
| BDD Specs | {{DATES}} | Gherkin features |
| Implementation | {{DATES}} | Working code |
| Review | {{DATES}} | Approved PR |
| Deploy | {{DATES}} | Production release |

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| {{RISK}} | {{H/M/L}} | {{H/M/L}} | {{MITIGATION}} |

---

## 12. Appendix

### Related Documents
- OST: `docs/discovery/ost.md`
- BDD Specs: `specs/features/{{SLUG}}.feature`
- ADRs: `docs/adr/`

### Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | {{DATE}} | {{AUTHOR}} | Initial draft |
