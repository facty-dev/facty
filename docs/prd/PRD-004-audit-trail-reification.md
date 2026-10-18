---
# Product Requirements Document (PRD)
---

# PRD-004: Audit Trail & Reification Streams

**Status:** draft
**Author:** agentic-runtime-team
**Date:** 2026-10-06
**Version:** 0.1

---

## 1. Overview

### What
An **append-only event log** (reification stream) that captures every asset materialization, gate decision, agent action, and human review. The stream is the complete audit trail — queryable, exportable, and tamper-evident.

**One-liner:** "Every action leaves a trace — the reification stream is the project's memory."

### Why
- **Compliance:** SOC 2, ISO 27001 require audit trails
- **Debugging:** "Why did the agent do that?" → query the stream
- **Reproducibility:** Replay events to reconstruct any state
- **Accountability:** Know who (human or agent) did what, when
- **Analytics:** Measure agent performance, decision patterns

### Who
- **Auditors** — verify compliance, review decisions
- **Tech Leads** — debug agent behavior
- **Product Owners** — track progress without asking
- **Security team** — detect anomalous agent actions
- **Data scientists** — analyze agent decision patterns

---

## 2. Goals & Non-Goals

### Goals (In Scope)
- [ ] **GOAL-1:** Append-only JSONL event log (`.agentic/audit.jsonl`)
- [ ] **GOAL-2:** Event schema: event_id, timestamp, type, actor, asset, inputs, gates, metadata
- [ ] **GOAL-3:** Event types: asset.materialized, gate.passed, gate.failed, agent.started, agent.completed, human.reviewed, rule.evaluated
- [ ] **GOAL-4:** CLI: `audit.sh query`, `audit.sh replay`, `audit.sh export`
- [ ] **GOAL-5:** Tamper-evidence: hash chain (each event includes previous hash)
- [ ] **GOAL-6:** GitHub Actions: stream committed to repo on each phase
- [ ] **GOAL-7:** Query interface: jq-compatible + simple filters

### Non-Goals (Out of Scope)
- **NON-GOAL-1:** Real-time streaming (batch append is fine)
- **NON-GOAL-2:** External SIEM integration (export format only)
- **NON-GOAL-3:** Cryptographic signatures (hash chain is sufficient for v1)
- **NON-GOAL-4:** Long-term archival (Git history is the archive)

---

## 3. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-001 | Auditor | Query "all assets materialized by coding-agent" | I can review agent output |
| US-002 | Tech Lead | Replay events to reproduce a bug | I can debug agent behavior |
| US-003 | Product Owner | See timeline of PRD approval | I know when I approved |
| US-004 | Security | Detect if agent accessed unauthorized asset | I can investigate incidents |
| US-005 | Analyst | Export events to BigQuery | I can run analytics |
| US-006 | Developer | Run `audit.sh tail -f` locally | I see events as they happen |

---

## 4. Requirements

### Functional Requirements

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| REQ-001 | Event log: `.agentic/audit.jsonl` (one JSON object per line) | P0 | Append-only, valid JSONL |
| REQ-002 | Event schema with required fields | P0 | Schema validation passes |
| REQ-003 | Event types: 7 types (materialized, gate.passed, gate.failed, agent.started, agent.completed, human.reviewed, rule.evaluated) | P0 | All types emit correctly |
| REQ-004 | Hash chain: each event includes `prev_hash` | P0 | Chain verifies with `audit.sh verify` |
| REQ-005 | Actor identification: agent (id, model, run_id) or human (github_user) | P0 | Every event has actor |
| REQ-006 | Asset reference: key, version, hash in materialization events | P0 | Lineage queryable |
| REQ-007 | CLI: `audit.sh append <event.json>` — append event | P0 | Appends + updates hash chain |
| REQ-008 | CLI: `audit.sh query <filter>` — query events | P0 | jq-compatible filters |
| REQ-009 | CLI: `audit.sh replay <asset-key>` — reconstruct asset history | P1 | Rebuilds all versions |
| REQ-010 | CLI: `audit.sh export --format csv/json` — export for analytics | P1 | Valid CSV/JSON output |
| REQ-011 | CLI: `audit.sh verify` — verify hash chain integrity | P0 | Detects tampering |
| REQ-012 | GitHub Actions: commit audit.jsonl after each phase | P0 | Stream in repo |
| REQ-013 | Agents append events automatically | P0 | No manual event creation |

### Non-Functional Requirements

| ID | Category | Requirement | Target |
|----|----------|-------------|--------|
| NFR-001 | Performance | Append event | < 10ms |
| NFR-002 | Performance | Query 10k events | < 1s |
| NFR-003 | Storage | Event size | < 2KB average |
| NFR-004 | Integrity | Hash chain verification | 100% tamper detection |

---

## 5. Assumptions

| ID | Assumption | Source | Validation Method | Status |
|----|-----------|--------|-------------------|--------|
| ASM-001 | JSONL is sufficient (no need for Kafka/etc.) | Architecture | Prototype with 1000 events | pending |
| ASM-002 | Hash chain is sufficient tamper-evidence | Security | Threat model review | pending |
| ASM-003 | Git is sufficient for long-term storage | Product | 1 year retention test | pending |

---

## 6. Open Questions

| ID | Question | Owner | Due Date | Status |
|----|----------|-------|----------|--------|
| Q-001 | Should events include full asset content or just hash? | Security | 2026-10-13 | open |
| Q-002 | Retention policy: how long to keep events? | Legal | 2026-10-20 | open |
| Q-003 | Should we sign events cryptographically? | Security | 2026-10-20 | open |

---

## 7. Acceptance Criteria

Feature is complete when:

- [ ] **AC-1:** `.agentic/audit.jsonl` exists and is valid JSONL
- [ ] **AC-2:** Agent materialization appends event automatically
- [ ] **AC-3:** Gate decisions append events
- [ ] **AC-4:** `audit.sh query` filters events correctly
- [ ] **AC-5:** `audit.sh verify` detects tampering
- [ ] **AC-6:** `audit.sh replay` reconstructs asset history
- [ ] **AC-7:** GitHub Actions commits stream after each phase
- [ ] **AC-8:** Hash chain verifies end-to-end

---

## 8. Dependencies

| Dependency | Type | Owner | Status | Blocker? |
|------------|------|-------|--------|----------|
| Asset graph (PRD-001) | Feature | Engineering | in-progress | YES |
| Agent orchestration (PRD-003) | Feature | Engineering | draft | YES |

---

## 9. Success Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Event coverage | 0% | 100% of actions | Audit log analysis |
| Query performance | N/A | < 1s for 10k events | Benchmark |
| Tamper detection | N/A | 100% | Test suite |
| Storage overhead | N/A | < 10% of repo size | Measurement |

---

## 10. Timeline

| Phase | Dates | Deliverable |
|-------|-------|-------------|
| Design | 2026-10-06 — 2026-10-07 | This PRD + event schema |
| Core log | 2026-10-08 — 2026-10-10 | `audit.sh` + JSONL |
| Hash chain | 2026-10-11 — 2026-10-12 | Tamper-evidence |
| Agent integration | 2026-10-13 — 2026-10-14 | Auto-append |
| GitHub integration | 2026-10-15 — 2026-10-16 | Commit stream |
| Review | 2026-10-17 | Tech Lead approval |

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Log grows too large | Medium | Medium | Rotation + Git history |
| Missing events (agent crash) | Low | High | Checkpoint + recovery |
| Hash chain broken by merge conflict | Low | Medium | Rebuild chain on conflict |

---

## 12. Appendix

### Event Schema

```json
{
  "$schema": "https://facty.dev/schemas/audit-event.schema.json",
  "event_id": "evt-uuid",
  "timestamp": "2026-10-06T10:00:00Z",
  "event_type": "asset.materialized",
  "actor": {
    "type": "agent",
    "id": "decision-agent",
    "model": "mistral/mistral-large-latest",
    "run_id": "github-actions-12345"
  },
  "asset": {
    "key": "discovery/problems",
    "path": "docs/discovery/problems.md",
    "version": 1,
    "hash": "sha256:abc123..."
  },
  "inputs": [
    {"asset_key": "stakeholder-input", "hash": "sha256:..."}
  ],
  "gates": {
    "required": ["product-owner-review"],
    "passed": []
  },
  "prev_hash": "sha256:previous-event...",
  "event_hash": "sha256:this-event...",
  "metadata": {
    "pr": 42,
    "branch": "feature/user-auth",
    "commit": "abc123def"
  }
}
```

### Related Documents
- Asset Model: `docs/ASSET-MODEL.md`
- PRD-001: Asset Graph
- PRD-003: Agent Orchestration

### Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-10-06 | agentic-runtime-team | Initial draft |
