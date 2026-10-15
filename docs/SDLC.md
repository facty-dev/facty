# SDLC — Agentic Software Development Life Cycle

> **Asset-oriented:** Each phase produces versioned, auditable **assets** (see [ASSET-MODEL.md](./ASSET-MODEL.md)). The asset graph is the single source of truth.


> **Git-Native Pipeline:** This SDLC runs on Git branches. Each phase is a branch, each merge materializes an asset and triggers downstream. See [GIT-NATIVE-PIPELINE.md](./GIT-NATIVE-PIPELINE.md).


A structured, gated SDLC driven by two AI agents (decision + coding) with human review gates at each phase. Based on the **Triple Diamond** / **Opportunity Solution Tree (OST)** approach from continuous discovery.

---

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           TRIPLE DIAMOND                                 │
│                                                                          │
│   DISCOVER              DEFINE               DEVELOP          DELIVER   │
│   (What?)               (What exactly?)      (How?)           (Ship)    │
│                                                                          │
│   Problems      →       Solutions      →     PRD          →   BDD Specs  │
│   + Assumptions         + Assumptions         + Assumptions    + Impl   │
│   (continuous           (from OST)            (from PRD)         + ADRs  │
│    discovery)                                                                          │
│                                                                          │
│   ◆───────◆             ◆───────◆            ◆───────◆          ◆───────◆ │
│                                                                          │
│   Decision Agent        Decision Agent       Coding Agent      Decision  │
│   (builds OST)          (writes PRD + BDD)   (implements)      Agent     │
│                                               + Decision    (reviews  │
│                                               Agent       + merges)   │
│                                               (reviews)               │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Discovery (Continuous)

**Goal:** Build an Opportunity Solution Tree (OST) from stakeholder input.

**Agent:** Decision agent

**Human gate:** Product Owner

### Inputs
- Stakeholder interviews
- User research
- Support tickets
- Analytics data
- Market/competitive research

### Process

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  COLLECT    │────▶│  SYNTHESIZE │────▶│  STRUCTURE  │────▶│   VALIDATE  │
│  problems   │     │  patterns   │     │  into OST   │     │  with       │
│  from all   │     │  and themes │     │  solutions  │     │  stakeholders│
│  sources    │     │             │     │  + assumpts │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
                                                                     │
                                                          ┌──────────┴──────────┐
                                                          │  HUMAN REVIEW       │
                                                          │  Product Owner      │
                                                          │  approves OST       │
                                                          └─────────────────────┘
```

### Outputs

| Artifact | Path | Description |
|----------|------|-------------|
| Problems list | `docs/discovery/problems.md` | Numbered list of problems to solve |
| Solutions list | `docs/discovery/solutions.md` | Potential solutions per problem |
| Assumptions | `docs/discovery/assumptions.md` | Assumptions per solution |
| OST | `docs/discovery/ost.md` | Opportunity Solution Tree (visual + structured) |

### OST Structure

```
                    ┌─────────────────┐
                    │  DESIRED       │  ← Outcome (business goal)
                    │  OUTCOME       │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
       ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
       │ OPPORTUNITY │ │ OPPORTUNITY │ │ OPPORTUNITY │  ← Opportunities
       │   (P1)      │ │   (P2)      │ │   (P3)      │
       └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
              │              │              │
    ┌─────────┼─────────┐    │    ┌─────────┼─────────┐
    ▼         ▼         ▼    ▼    ▼         ▼         ▼
 ┌─────┐   ┌─────┐   ┌─────┐ ... ┌─────┐   ┌─────┐   ┌─────┐
 │S1   │   │S2   │   │S3   │     │S1   │   │S2   │   │S3   │  ← Solutions
 │+A1 │   │+A1 │   │+A1 │        │+A1 │   │+A1 │   │+A1 │     (+ Assumptions)
 │+A2 │   │+A2 │   │+A2 │        │+A2 │   │+A2 │   │+A2 │
 └─────┘   └─────┘   └─────┘     └─────┘   └─────┘   └─────┘
```

### Gate Criteria (Human Review)
- [ ] Problems are clearly stated and prioritized
- [ ] Solutions cover the problem space adequately
- [ ] Assumptions are explicit and testable
- [ ] OST is reviewed with stakeholders
- [ ] Selected solution path has clear rationale

---

## Phase 2: PRD (Product Requirements Document)

**Goal:** Generate a detailed PRD from the selected OST path.

**Agent:** Decision agent

**Human gate:** Product Owner

### Inputs
- OST (selected opportunity + solution + assumptions)
- Discovery artifacts
- Technical constraints (from engineering)
- Business constraints

### Process

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  EXTRACT    │────▶│  STRUCTURE  │────▶│  DETAIL     │────▶│  VALIDATE   │
│  from OST   │     │  PRD        │     │  requirements│     │  with       │
│  selected   │     │  sections   │     │  + acceptance│     │  PO         │
│  path       │     │             │     │  criteria   │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
                                                                     │
                                                          ┌──────────┴──────────┐
                                                          │  HUMAN REVIEW       │
                                                          │  Product Owner      │
                                                          │  approves PRD       │
                                                          └─────────────────────┘
```

### Output

| Artifact | Path | Description |
|----------|------|-------------|
| PRD | `docs/prd/PRD-NNN-<slug>.md` | Full product requirements document |

### PRD Sections
1. **Overview** — What, why, who
2. **Goals & Non-Goals** — In scope / out of scope
3. **User Stories** — As a [user], I want [goal], so that [benefit]
4. **Requirements** — Functional + non-functional (numbered REQ-NNN)
5. **Assumptions** — Carried from OST, to be validated
6. **Open Questions** — To be resolved during implementation
7. **Acceptance Criteria** — How we know it's done
8. **Dependencies** — External teams, services, blockers
9. **Success Metrics** — How we measure success
10. **Timeline** — Phases, milestones

### Gate Criteria (Human Review)
- [ ] PRD aligns with OST selected path
- [ ] Requirements are complete and unambiguous
- [ ] Acceptance criteria are testable
- [ ] Assumptions are carried and flagged
- [ ] PO approves for BDD generation

---

## Phase 3: BDD Specs (Behavior-Driven Development)

**Goal:** Generate Gherkin feature specs from PRD requirements and assumptions.

**Agent:** Decision agent

**Human gate:** QA Lead

### Inputs
- PRD
- Assumptions from OST/PRD
- Existing codebase context
- Testing strategy

### Process

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  MAP        │────▶│  WRITE      │────▶│  VALIDATE   │────▶│  REVIEW     │
│  REQ-NNN    │     │  Gherkin    │     │  coverage   │     │  with QA    │
│  to         │     │  scenarios  │     │  (all reqs  │     │             │
│  scenarios  │     │             │     │  have specs)│     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
                                                                     │
                                                          ┌──────────┴──────────┐
                                                          │  HUMAN REVIEW       │
                                                          │  QA Lead            │
                                                          │  approves specs     │
                                                          └─────────────────────┘
```

### Output

| Artifact | Path | Description |
|----------|------|-------------|
| Feature files | `specs/features/<feature>.feature` | Gherkin BDD specs |
| Step definitions | `specs/steps/<feature>_steps.py` (or .ts, etc.) | Test step implementations (stubs) |
| Test plan | `specs/test-plan.md` | Overall testing strategy |

### Gherkin Structure

```gherkin
@PRD-001 @REQ-001 @REQ-002
Feature: User Authentication
  As a registered user
  I want to log in securely
  So that I can access my account

  Background:
    Given the authentication service is running
    And the user "alice@example.com" exists with password "SecurePass123!"

  @smoke @happy-path
  Scenario: Successful login with valid credentials
    When the user logs in with email "alice@example.com" and password "SecurePass123!"
    Then the login succeeds
    And the user receives a session token
    And the session token expires in 24 hours

  @security
  Scenario: Failed login with invalid password
    When the user logs in with email "alice@example.com" and password "wrong"
    Then the login fails with "Invalid credentials"
    And no session token is issued
    And the failed attempt is logged

  @edge-case
  Scenario Outline: Login validation
    When the user logs in with email "<email>" and password "<password>"
    Then the login result is "<result>"

    Examples:
      | email                  | password      | result               |
      | not-an-email           | anything      | fails with "Invalid email format" |
      | alice@example.com      |               | fails with "Password required"    |
      | nonexistent@example.com| anything      | fails with "Invalid credentials"  |
```

### Tagging Convention

| Tag | Meaning |
|-----|---------|
| `@PRD-NNN` | Links to PRD document |
| `@REQ-NNN` | Links to specific requirement |
| `@smoke` | Smoke test (run on every build) |
| `@happy-path` | Primary success scenario |
| `@edge-case` | Boundary/edge cases |
| `@security` | Security-related tests |
| `@slow` | Long-running tests |
| `@wip` | Work in progress (skip in CI) |
| `@assumption-N` | Tests assumption from OST/PRD |

### Gate Criteria (Human Review)
- [ ] All PRD requirements have BDD coverage
- [ ] Scenarios are clear and unambiguous
- [ ] Edge cases and error paths covered
- [ ] Assumptions are tagged and testable
- [ ] QA Lead approves for implementation

---

## Phase 4: Implementation

**Goal:** Implement features per BDD specs on the target repo's stack.

**Agent:** Coding agent

**Human gate:** Tech Lead (code review)

### Inputs
- BDD specs
- PRD context
- Existing codebase
- Architecture guidelines
- ADRs (existing)

### Process

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  ANALYZE    │────▶│  IMPLEMENT  │────▶│  TEST       │────▶│  DOCUMENT   │
│  specs +    │     │  features   │     │  (run BDD   │     │  + record   │
│  codebase   │     │  + tests    │     │  tests)     │     │  ADRs       │
└─────────────┘     └─────────────┘     └─────────────┘     └──────┬──────┘
                                                                      │
                                                       ┌──────────────┘
                                                       ▼
                                              ┌─────────────────┐
                                              │  DECISION AGENT │
                                              │  reviews code   │
                                              │  + ADRs         │
                                              └────────┬────────┘
                                                       │
                                              ┌────────┴────────┐
                                              │  changes? ──┐   │
                                              │  requested  │   │
                                              └─────────────┘   │
                                                   │           │
                                              no ──┴──▶ approved
```

### Outputs

| Artifact | Path | Description |
|----------|------|-------------|
| Source code | `src/` (target repo) | Implementation |
| Tests | `tests/` or `specs/` | BDD step implementations + unit tests |
| Documentation | `docs/` | Updated docs |
| ADRs | `docs/adr/ADR-NNN-<slug>.md` | Architecture decisions |
| PR | GitHub PR | For human review |

### ADR Generation

When the coding agent makes a significant decision:

1. **Decision agent** is notified of tradeoffs encountered
2. **Decision agent** writes ADR capturing:
   - Context (what problem)
   - Options considered
   - Decision (what we chose)
   - Consequences (tradeoffs, what worked/didn't)
3. **Human** (Tech Lead) reviews ADR during code review

### Gate Criteria (Human Review — Tech Lead)
- [ ] BDD specs pass
- [ ] Code follows project conventions
- [ ] No security issues
- [ ] ADRs are complete and accurate
- [ ] Documentation is updated
- [ ] Tech Lead approves PR

---

## Phase 5: Merge & Deploy

**Goal:** Merge approved PR and deploy.

**Agent:** Automated (GitHub Actions)

**Human gate:** None (automated after approval)

### Process

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  MERGE      │────▶│  BUILD      │────▶│  DEPLOY     │────▶│  VERIFY     │
│  (squash/   │     │  + TEST     │     │  (staging   │     │  (smoke     │
│   merge)    │     │  (full CI)  │     │   then prod)│     │  tests)     │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

---

## Review Roles & GitHub Mapping

| SDLC Phase | Reviewer Role | GitHub Username(s) | CODEOWNERS Path |
|------------|---------------|-------------------|-----------------|
| Discovery | Product Owner | `@po-alice`, `@po-bob` | `/docs/discovery/` |
| PRD | Product Owner | `@po-alice`, `@po-bob` | `/docs/prd/` |
| BDD Specs | QA Lead | `@qa-lead-carol` | `/specs/` |
| Implementation | Tech Lead | `@tech-lead-dave`, `@staff-eng-eve` | `/src/`, `/tests/` |
| ADRs | Architecture Team | `@architect-frank` | `/docs/adr/` |
| Final Merge | Engineering Manager | `@eng-manager-grace` | `/` (branch protection) |

---

## State Tracking

```json
// .agentic/state.json
{
  "version": "1.0",
  "project": "my-product",
  "current_phase": "implementation",
  "phases": {
    "discovery": {
      "status": "completed",
      "completed_at": "2026-10-01T10:00:00Z",
      "artifacts": ["docs/discovery/ost.md"],
      "reviewer": "po-alice",
      "approved_at": "2026-10-01T14:30:00Z"
    },
    "prd": {
      "status": "completed",
      "completed_at": "2026-10-02T09:00:00Z",
      "artifacts": ["docs/prd/PRD-001-user-auth.md"],
      "reviewer": "po-alice",
      "approved_at": "2026-10-02T11:00:00Z"
    },
    "bdd": {
      "status": "completed",
      "completed_at": "2026-10-03T10:00:00Z",
      "artifacts": ["specs/features/auth.feature"],
      "reviewer": "qa-lead-carol",
      "approved_at": "2026-10-03T15:00:00Z"
    },
    "implementation": {
      "status": "in_progress",
      "started_at": "2026-10-06T09:00:00Z",
      "agent": "coding-agent",
      "branch": "feature/user-auth",
      "pr": "https://github.com/org/repo/pull/42"
    }
  }
}
```
