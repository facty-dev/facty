---
# Product Requirements Document (PRD)
---

# PRD-003: Agent Orchestration (Decision + Coding)

**Status:** draft
**Author:** agentic-runtime-team
**Date:** 2026-10-06
**Version:** 0.1

---

## 1. Overview

### What
A **two-agent orchestration system** where a **decision agent** (orchestrator/planner/reviewer) and a **coding agent** (implementer) work in parallel inside isolated gondolin micro-VM sessions. Agents communicate through the asset graph (not direct messaging), enabling neurosymbolic composition.

**One-liner:** "Two specialized agents, one asset graph — decision agent plans, coding agent implements, both leave auditable artifacts."

### Why
- **Separation of concerns:** Planning/reviewing vs. implementing require different skills and models
- **Parallelism:** Both agents can work simultaneously on different assets
- **Isolation:** Each agent runs in its own microVM (security + resource isolation)
- **Auditability:** Every agent action produces an asset (full lineage)
- **Flexibility:** Swap models per agent (e.g., strong reasoner for decision, fast coder for implementation)

### Who
- **Decision agent** — plans, generates PRDs/BDD, reviews code, records ADRs
- **Coding agent** — implements features, writes tests, fixes bugs
- **Rules engine** — routes tasks to the right agent
- **Human reviewers** — gate progression between phases
- **GitHub Actions** — triggers and coordinates agent runs

---

## 2. Goals & Non-Goals

### Goals (In Scope)
- [ ] **GOAL-1:** Two agent roles: `decision` and `coding` (templates/sdlc/agents/)
- [ ] **GOAL-2:** Agent communication via asset graph (not direct messaging)
- [ ] **GOAL-3:** Parallel execution: both agents can run simultaneously
- [ ] **GOAL-4:** Model selection per agent (decision = strong reasoner, coding = fast)
- [ ] **GOAL-5:** Agent task queue (`.agentic/messages/`) for async coordination
- [ ] **GOAL-6:** GitHub Actions integration (trigger on PR label)
- [ ] **GOAL-7:** Local development support (run agents on dev machine)

### Non-Goals (Out of Scope)
- **NON-GOAL-1:** More than 2 agents (specialized agents for testing, docs, etc. — v2)
- **NON-GOAL-2:** Direct agent-to-agent messaging (asset graph only)
- **NON-GOAL-3:** Agent self-modification (agents can't change their own prompts)
- **NON-GOAL-4:** Multi-repo orchestration (single repo for v1)

---

## 3. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-001 | Decision agent | Read the OST asset and produce a PRD asset | The PRD has full lineage to discovery |
| US-002 | Coding agent | Read BDD assets and produce code assets | I implement exactly what was specified |
| US-003 | Rules engine | Route "materialize PRD" to decision agent | The right agent does the right work |
| US-004 | GitHub Actions | Trigger both agents in parallel on PR open | Faster feedback loop |
| US-005 | Developer | Run decision agent locally on my machine | I can iterate without CI |
| US-006 | Auditor | See which agent produced which asset | I know who/what to blame |
| US-007 | Product Owner | See agent activity in asset graph | I know progress without asking |

---

## 4. Requirements

### Functional Requirements

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| REQ-001 | Decision agent role prompt: `templates/sdlc/agents/decision.md` | P0 | Runs in the SDLC VM session; model via session config |
| REQ-002 | Coding agent role prompt: `templates/sdlc/agents/coding.md` | P0 | Runs in the SDLC VM session; model via session config |
| REQ-003 | Agents read assets from mounted repo | P0 | `cat assets/graph.json` works in sandbox |
| REQ-004 | Agents write assets back to mounted repo | P0 | Agent writes file, host sees it |
| REQ-005 | Asset graph updated by agents (not direct file writes) | P0 | `asset.sh materialize` called by agent |
| REQ-006 | Task queue: `.agentic/messages/decision-to-coding/NNN-task.md` | P0 | Decision agent writes task, coding agent reads |
| REQ-007 | Task queue: `.agentic/messages/coding-to-decision/NNN-result.md` | P0 | Coding agent writes result, decision agent reads |
| REQ-008 | Parallel execution: GitHub Actions matrix or separate jobs | P0 | Both agents run simultaneously |
| REQ-009 | Model selection: decision agent uses strong model (e.g., mistral-large) | P0 | Profile specifies model |
| REQ-010 | Model selection: coding agent uses fast model (e.g., codestral) | P0 | Profile specifies model |
| REQ-011 | Agent roles enforced: decision can't write code, coding can't write PRD | P1 | Role prompts + rules engine enforcement |
| REQ-012 | GitHub Actions: trigger on `sdlc` label | P0 | Workflow runs when label added |
| REQ-013 | Local dev: `make run-agent AGENT=decision PHASE=prd` | P0 | Runs in the local SDLC VM session |
| REQ-014 | Agent outputs are schema-valid assets | P0 | Validation passes |
| REQ-015 | Agent failures are logged and retried | P1 | Retry up to 3 times |

### Non-Functional Requirements

| ID | Category | Requirement | Target |
|----|----------|-------------|--------|
| NFR-001 | Isolation | Agents run in separate microVMs | No shared state except repo |
| NFR-002 | Security | Coding agent can't access decision agent's secrets | Per-session host-secrets |
| NFR-003 | Performance | Agent boot time | < 30s |
| NFR-004 | Cost | Token usage per phase | Tracked and budgeted |
| NFR-005 | Reliability | Agent failure rate | < 5% |

---

## 5. Assumptions

| ID | Assumption | Source | Validation Method | Status |
|----|-----------|--------|-------------------|--------|
| ASM-001 | Two agents are sufficient for v1 | Product | User feedback | pending |
| ASM-002 | Asset graph is sufficient for coordination | Architecture | Prototype with 2 agents | pending |
| ASM-003 | Model selection matters (different models per role) | Hypothesis | A/B test | pending |
| ASM-004 | Gondolin VM isolation is sufficient security | Security | Threat model review | pending |

---

## 6. Open Questions

| ID | Question | Owner | Due Date | Status |
|----|----------|-------|----------|--------|
| Q-001 | Should agents have different model providers? | Tech Lead | 2026-10-13 | open |
| Q-002 | How to handle agent disagreement? | Product | 2026-10-13 | open |
| Q-003 | Should coding agent be able to ask decision agent questions? | Architecture | 2026-10-20 | open |

---

## 7. Acceptance Criteria

Feature is complete when:

- [ ] **AC-1:** Decision agent runs in the SDLC VM session (`make agent-decision PHASE=discovery`)
- [ ] **AC-2:** Coding agent runs in the SDLC VM session (`make agent-coding TASK=<file>`)
- [ ] **AC-3:** Decision agent materializes PRD asset from OST
- [ ] **AC-4:** Coding agent materializes code asset from BDD
- [ ] **AC-5:** Both agents run in parallel in GitHub Actions
- [ ] **AC-6:** `make run-agent AGENT=decision PHASE=prd` works locally
- [ ] **AC-7:** Agent writes appear in asset graph with lineage
- [ ] **AC-8:** Task queue enables async coordination

---

## 8. Dependencies

| Dependency | Type | Owner | Status | Blocker? |
|------------|------|-------|--------|----------|
| Asset graph (PRD-001) | Feature | Engineering | in-progress | YES |
| Rules engine (PRD-002) | Feature | Engineering | draft | YES |
| Gondolin VM sessions | Infrastructure | DevOps | ready | YES |
| GitHub Actions runners | Infrastructure | DevOps | ready | NO |

---

## 9. Success Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Parallel speedup | N/A | 1.8x | Compare serial vs parallel time |
| Agent task success rate | N/A | > 95% | Audit log analysis |
| Asset lineage coverage | N/A | 100% | All assets have depends_on |
| Local dev usage | N/A | > 50% of dev time | Survey |

---

## 10. Timeline

| Phase | Dates | Deliverable |
|-------|-------|-------------|
| Design | 2026-10-06 — 2026-10-07 | This PRD + profiles |
| Profiles | 2026-10-08 — 2026-10-09 | Both agent profiles |
| Task queue | 2026-10-10 — 2026-10-11 | Message passing |
| GitHub Actions | 2026-10-12 — 2026-10-14 | Parallel execution |
| Local dev | 2026-10-15 — 2026-10-16 | Makefile targets |
| Review | 2026-10-17 | Tech Lead approval |

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Agent coordination deadlock | Medium | High | Timeout + escalation to human |
| Model mismatch (wrong model for role) | Medium | Medium | Profile validation + A/B test |
| VM session resource contention | Low | Medium | Resource limits per agent |
| GitHub Actions runner limits | Medium | Medium | Self-hosted runners |

---

## 12. Appendix

### Agent Runtime Configuration

Decision and coding agents run from role prompts
(`templates/sdlc/agents/decision.md`, `templates/sdlc/agents/coding.md`)
inside gondolin VM sessions booted from the pi-sandbox snapshot
(pi + ddgr + skill suite baked in). Per-role model selection via
`scripts/agent-pi.sh`:

```bash
# Decision agent: strong reasoner (defaults: zai-glm-5-3 / max thinking)
make agent-decision PHASE=prd TASK="..."

# Coding agent: fast implementation (defaults: zai-glm-5-3 / low thinking)
make agent-coding TASK=.agentic/messages/decision-to-coding/001-task.md

# Per-run overrides
AGENT_MODEL=<model> AGENT_THINKING=<level> make agent-decision PHASE=...
```

Secrets are injected host-side at session boot
(`--host-secret MISTRAL_API_KEY@api.mistral.ai`): the guest and any
orchestrating sandbox see only a placeholder; the host proxy substitutes the
real key into outbound requests to allowed hosts only. See
[ADR-0001](../adr/0001-session-execution-under-sandboxing.md).

### Related Documents
- Asset Model: `docs/ASSET-MODEL.md`
- PRD-001: Asset Graph
- PRD-002: Rules Engine
- PRD-005: Neurosymbolic Bridge

### Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-10-06 | agentic-runtime-team | Initial draft |
