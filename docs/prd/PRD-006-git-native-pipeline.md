---
# Product Requirements Document (PRD)
---

# PRD-006: Git-Native Pipeline (Branch Automation)

**Status:** draft
**Author:** agentic-runtime-team
**Date:** 2026-10-06
**Version:** 0.1

---

## 1. Overview

### What
A **Git-native agentic pipeline** where branches are assets, merges are materializations, and PRs are gates. The pipeline runs as a convolutional spiral on Git branches, with automatic downstream triggering, human injection points, and skip-ahead logic.

**One-liner:** "Branches are assets. Merges are materializations. PRs are gates. Humans inject anywhere."

### Why
- **Familiar workflow:** Developers already use branches + PRs
- **Full audit trail:** Git history IS the audit trail
- **Human control:** Inject at any point (review, comment, manual asset)
- **Skip-ahead:** Human adds PRD to OST PR → pipeline jumps to BDD
- **Convolutional spiral:** Each merge triggers the next, assets accumulate

### Who
- **Developers** — use familiar Git workflow, no new tools
- **Agents** — run on phase branches, produce assets
- **Reviewers** — review PRs as usual, add `/sdlc-*` commands
- **Product Owners** — inject their own PRDs, skip agent generation
- **Tech Leads** — approve implementation PRs

---

## 2. Goals & Non-Goals

### Goals (In Scope)
- [ ] **GOAL-1:** Branch naming: `sdlc/<phase>/<feature-slug>`
- [ ] **GOAL-2:** Merge = materialization = downstream trigger
- [ ] **GOAL-3:** Skip-ahead: multi-phase merges trigger furthest downstream
- [ ] **GOAL-4:** Human injection: manual asset addition detected on merge
- [ ] **GOAL-5:** PR comment commands: `/sdlc-update`, `/sdlc-approve`, `/sdlc-reject`, `/sdlc-skip`, `/sdlc-inject`, `/sdlc-regenerate`, `/sdlc-explain`
- [ ] **GOAL-6:** Asset graph derived from git history (not maintained independently)
- [ ] **GOAL-7:** Local simulation: `./scripts/sdlc-branch.sh`
- [ ] **GOAL-8:** GitHub Actions automation: merge-trigger, comment-handler

### Non-Goals (Out of Scope)
- **NON-GOAL-1:** GitLab/Bitbucket support (GitHub only for v1)
- **NON-GOAL-2:** Real-time collaboration (Git-based async)
- **NON-GOAL-3:** Branch conflict auto-resolution (human resolves)
- **NON-GOAL-4:** Multi-repo SDLC (single repo for v1)

---

## 3. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-001 | Developer | Label a PR `sdlc` to start the pipeline | Agents start working automatically |
| US-002 | Product Owner | Review OST and comment `/sdlc-update Add OAuth assumption` | Agent fixes it without me editing |
| US-003 | Product Owner | Add my own PRD to the OST PR | Pipeline skips PRD generation, goes to BDD |
| US-004 | QA Lead | Add BDD specs I wrote to the PRD PR | Pipeline skips BDD generation, goes to implementation |
| US-005 | Tech Lead | Approve implementation PR | Code merges to main, release triggered |
| US-006 | Auditor | Run `git log` to see full SDLC history | I have complete audit trail |
| US-007 | Developer | Run `./scripts/sdlc-branch.sh status` locally | I see pipeline state without GitHub |

---

## 4. Requirements

### Functional Requirements

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| REQ-001 | Branch naming: `sdlc/<phase>/<slug>` | P0 | Convention enforced by workflow |
| REQ-002 | Merge to main triggers `merge-trigger.yml` | P0 | Workflow runs on PR merge |
| REQ-003 | Merge analysis: detect which phases have assets | P0 | Correct phase detection |
| REQ-004 | Skip-ahead: OST+PRD merged → trigger BDD (not PRD) | P0 | Correct downstream branch created |
| REQ-005 | Human injection: detect manually-added assets | P0 | Commit author analysis |
| REQ-006 | `/sdlc-update <instruction>` comment → agent updates | P0 | Agent runs, commits fix |
| REQ-007 | `/sdlc-reject <reason>` comment → agent gets feedback | P0 | Feedback in task file |
| REQ-008 | `/sdlc-skip <phase>` comment → skip on merge | P1 | Stored in PR metadata |
| REQ-009 | `/sdlc-inject <file>` comment → acknowledge injection | P1 | Bot acknowledges |
| REQ-010 | `/sdlc-regenerate` comment → agent regenerates | P1 | Fresh asset generated |
| REQ-011 | `/sdlc-explain` comment → agent explains decisions | P2 | Explanation posted |
| REQ-012 | Asset graph derived from git history | P0 | `asset-sync.sh` works |
| REQ-013 | Local simulation: `sdlc-branch.sh` | P0 | Full pipeline locally |
| REQ-014 | Audit trail: merge events logged | P0 | `.agentic/audit.jsonl` |
| REQ-015 | Downstream branch auto-created on merge | P0 | `sdlc/<next-phase>/<slug>` exists |
| REQ-016 | Agent auto-triggered on new branch | P0 | Workflow dispatched |

### Non-Functional Requirements

| ID | Category | Requirement | Target |
|----|----------|-------------|--------|
| NFR-001 | Reliability | No lost triggers (merge always triggers) | 100% |
| NFR-002 | Performance | Merge analysis | < 5s |
| NFR-003 | Usability | Familiar Git workflow | No new tools |
| NFR-004 | Auditability | Full history in git log | 100% |

---

## 5. Assumptions

| ID | Assumption | Source | Validation Method | Status |
|----|-----------|--------|-------------------|--------|
| ASM-001 | Git workflow is sufficient (no external state) | Architecture | Prototype | pending |
| ASM-002 | Humans will use injection (not just review) | Product | User testing | pending |
| ASM-003 | Skip-ahead is valuable (saves time) | Product | Measure time saved | pending |
| ASM-004 | Branch naming convention is maintainable | Engineering | Enforce via workflow | pending |

---

## 6. Open Questions

| ID | Question | Owner | Due Date | Status |
|----|----------|-------|----------|--------|
| Q-001 | Should phase branches be protected? | Tech Lead | 2026-10-13 | open |
| Q-002 | How to handle branch name collisions? | Engineering | 2026-10-13 | open |
| Q-003 | Should we support `sdlc/<phase>/<slug>@<version>`? | Product | 2026-10-20 | open |

---

## 7. Acceptance Criteria

Feature is complete when:

- [ ] **AC-1:** PR labeled `sdlc` starts pipeline
- [ ] **AC-2:** Merge of `sdlc/ost/*` creates `sdlc/prd/*` branch
- [ ] **AC-3:** Merge of PR with OST+PRD creates `sdlc/bdd/*` (skip-ahead)
- [ ] **AC-4:** `/sdlc-update` comment triggers agent update
- [ ] **AC-5:** Human-added PRD detected on merge
- [ ] **AC-6:** `asset-sync.sh` rebuilds graph from git
- [ ] **AC-7:** `sdlc-branch.sh` simulates full pipeline locally
- [ ] **AC-8:** Audit trail captures all merge events

---

## 8. Dependencies

| Dependency | Type | Owner | Status | Blocker? |
|------------|------|-------|--------|----------|
| Asset graph (PRD-001) | Feature | Engineering | draft | YES |
| Agent orchestration (PRD-003) | Feature | Engineering | draft | YES |
| GitHub Actions | Infrastructure | DevOps | ready | YES |
| Git | Tool | — | ready | NO |

---

## 9. Success Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Pipeline completion time | N/A | < 2 hours | Git log timestamps |
| Human injection usage | N/A | > 20% of PRs | Audit log analysis |
| Skip-ahead time saved | N/A | > 30 min per use | Survey |
| Developer satisfaction | N/A | > 4/5 | Survey |

---

## 10. Timeline

| Phase | Dates | Deliverable |
|-------|-------|-------------|
| Design | 2026-10-06 — 2026-10-07 | This PRD + docs |
| Branch tooling | 2026-10-08 — 2026-10-10 | `sdlc-branch.sh` |
| Merge trigger | 2026-10-11 — 2026-10-13 | `merge-trigger.yml` |
| Comment handler | 2026-10-14 — 2026-10-15 | `comment-handler.yml` |
| Asset sync | 2026-10-16 — 2026-10-17 | `asset-sync.sh` |
| Review | 2026-10-18 | Tech Lead approval |

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Git history rewrite breaks graph | Low | High | Derive from current state, not history |
| Branch explosion (too many branches) | Medium | Medium | Auto-delete merged branches |
| Merge conflicts in spiral | Medium | Medium | Human resolution + retry |
| Agent fails on branch | Medium | Medium | Retry + human escalation |

---

## 12. Appendix

### Branch Lifecycle

```
Created → Agent works → PR opened → Review → Merge → Deleted → Downstream created
   │                                           │
   └───────────────────────────────────────────┘
                    (auto-delete)
```

### Skip-Ahead Examples

| PR Contains | Merge Triggers |
|-------------|---------------|
| OST only | `sdlc/prd/` |
| OST + PRD | `sdlc/bdd/` (skip prd) |
| OST + PRD + BDD | `sdlc/impl/` (skip prd, bdd) |
| PRD only | `sdlc/bdd/` + warn (no OST) |
| BDD only | `sdlc/impl/` |
| Code + ADRs | Release PR |

### Related Documents
- Git-Native Pipeline: `docs/GIT-NATIVE-PIPELINE.md`
- Asset Model: `docs/ASSET-MODEL.md`
- PRD-001: Asset Graph
- PRD-003: Agent Orchestration

### Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-10-06 | agentic-runtime-team | Initial draft |
