---
# Product Requirements Document (PRD)
---

# PRD-001: Asset Graph & State Management

**Status:** draft
**Author:** agentic-runtime-team
**Date:** 2026-10-06
**Version:** 0.1

---

## 1. Overview

### What
A **versioned, content-addressed asset graph** that serves as the single source of truth for the agentic SDLC. Each node is a materialized asset with schema, lineage, and hash. The graph tracks dependencies, enables deterministic orchestration, and provides full audit history.

**One-liner:** "Git for SDLC artifacts — every intermediate state is a versioned, auditable asset."

### Why
Current agentic workflows produce ephemeral outputs (PR comments, chat logs) with no structured state. We need:
- **Reproducibility:** Re-run any phase from any asset version
- **Auditability:** Who produced what, when, and why
- **Composition:** Downstream agents see full upstream context
- **Determinism:** Rules engine can gate based on asset state

### Who
- **Decision agents** — read upstream assets, produce new ones
- **Coding agents** — read BDD assets, produce code assets
- **Human reviewers** — inspect asset graph to understand progress
- **Rules engine** — evaluates asset state for deterministic decisions
- **Auditors** — query full lineage and history

---

## 2. Goals & Non-Goals

### Goals (In Scope)
- [ ] **GOAL-1:** Asset graph as JSON (`assets/graph.json`) with nodes, edges, and metadata
- [ ] **GOAL-2:** Content-addressed storage (SHA-256 hashes) for all assets
- [ ] **GOAL-3:** JSON Schema validation for each asset type
- [ ] **GOAL-4:** Lineage tracking (upstream/downstream dependencies)
- [ ] **GOAL-5:** Version history per asset (v1, v2, v3...)
- [ ] **GOAL-6:** CLI to query graph (`./scripts/asset.sh`)
- [ ] **GOAL-7:** Integration with SDLC agents (read/write assets via /workspace mount)

### Non-Goals (Out of Scope)
- **NON-GOAL-1:** Distributed asset storage (single-repo only for now)
- **NON-GOAL-2:** Real-time collaboration (Git-based versioning)
- **NON-GOAL-3:** Asset caching/lazy materialization (materialize on demand)
- **NON-GOAL-4:** Database backend (JSON files + Git for now)

---

## 3. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-001 | Decision agent | Materialize an OST asset with lineage | Downstream PRD agent knows what I produced |
| US-002 | Coding agent | Read the BDD asset graph to find my task | I know exactly what to implement |
| US-003 | Product Owner | Query the asset graph to see PRD status | I know what needs my review |
| US-004 | Rules engine | Evaluate asset state deterministically | I can gate progression without LLM calls |
| US-005 | Auditor | Replay the full asset history | I can verify compliance and decisions |
| US-006 | Developer | Run `asset.sh status` locally | I see the same state as CI |

---

## 4. Requirements

### Functional Requirements

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| REQ-001 | Asset graph stored as `assets/graph.json` | P0 | File exists, valid JSON, parseable |
| REQ-002 | Each asset has: key, path, schema, hash, version, status, produced_by, depends_on, materialized_at | P0 | Schema validation passes |
| REQ-003 | Content-addressed: asset hash = SHA-256 of file contents | P0 | Same content → same hash; different content → different hash |
| REQ-004 | Versioned storage: `assets/materialized/<key>/v<N>.<ext>` + `.meta.json` | P0 | v1, v2, v3 coexist; metadata per version |
| REQ-005 | Graph tracks edges: data dependencies + gate dependencies | P0 | `depends_on` arrays correct; gates marked |
| REQ-006 | CLI: `asset.sh init` — initialize graph | P0 | Creates `assets/graph.json` with empty nodes |
| REQ-007 | CLI: `asset.sh materialize <key> <file>` — add/update asset | P0 | Updates graph, computes hash, stores version |
| REQ-008 | CLI: `asset.sh status [key]` — show graph or asset status | P0 | Human-readable output; `--json` for machine |
| REQ-009 | CLI: `asset.sh lineage <key>` — show upstream/downstream | P1 | Traces full dependency chain |
| REQ-010 | CLI: `asset.sh diff <key> v1 v2` — compare versions | P1 | Shows content diff |
| REQ-011 | Schema validation on materialize | P0 | Rejects invalid assets with clear error |
| REQ-012 | VM session integration: agents read/write via the /workspace mount | P0 | Agent writes asset, host sees update |

### Non-Functional Requirements

| ID | Category | Requirement | Target |
|----|----------|-------------|--------|
| NFR-001 | Performance | Graph operations (add node, query) | < 100ms for < 1000 nodes |
| NFR-002 | Storage | Asset storage overhead | < 2x source file size |
| NFR-003 | Portability | Works on macOS + Linux | No platform-specific code |
| NFR-004 | Git-friendly | Graph + assets commit cleanly | No merge conflicts on graph.json |

---

## 5. Assumptions

| ID | Assumption | Source | Validation Method | Status |
|----|-----------|--------|-------------------|--------|
| ASM-001 | Git is sufficient for versioning (no DB needed) | Architecture | Prototype with 10+ assets | pending |
| ASM-002 | JSON Schema is sufficient for validation | Architecture | Validate all 8 asset types | pending |
| ASM-003 | SHA-256 is sufficient for content addressing | Security | Collision resistance analysis | accepted |
| ASM-004 | Single-repo scope is sufficient for v1 | Product | User feedback | pending |

---

## 6. Open Questions

| ID | Question | Owner | Due Date | Status |
|----|----------|-------|----------|--------|
| Q-001 | Should graph.json be hand-edited or agent-only? | Tech Lead | 2026-10-13 | open |
| Q-002 | Conflict resolution when two agents update same asset? | Tech Lead | 2026-10-13 | open |
| Q-003 | Should we use Git LFS for large assets? | DevOps | 2026-10-20 | open |

---

## 7. Acceptance Criteria

Feature is complete when:

- [ ] **AC-1:** `assets/graph.json` exists with valid schema
- [ ] **AC-2:** `./scripts/asset.sh init` creates empty graph
- [ ] **AC-3:** `./scripts/asset.sh materialize` adds asset with hash + version
- [ ] **AC-4:** `./scripts/asset.sh status` shows graph state
- [ ] **AC-5:** `./scripts/asset.sh lineage <key>` traces dependencies
- [ ] **AC-6:** Schema validation rejects invalid assets
- [ ] **AC-7:** Agent can materialize asset inside the VM session
- [ ] **AC-8:** Git commit includes graph + assets cleanly

---

## 8. Dependencies

| Dependency | Type | Owner | Status | Blocker? |
|------------|------|-------|--------|----------|
| VM session isolation | Infrastructure | DevOps | ready | YES |
| JSON Schema validator (ajv/python) | Tool | Engineering | ready | NO |
| Git | Tool | — | ready | NO |

---

## 9. Success Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Asset materialization time | N/A | < 5s | CLI timing |
| Graph query time | N/A | < 100ms | CLI timing |
| Schema validation coverage | 0% | 100% | All 8 asset types |
| Agent integration | 0 | 2 agents | Decision + Coding |

---

## 10. Timeline

| Phase | Dates | Deliverable |
|-------|-------|-------------|
| Design | 2026-10-06 — 2026-10-07 | This PRD + schemas |
| Implementation | 2026-10-08 — 2026-10-12 | `asset.sh` + graph.json |
| VM session integration | 2026-10-13 — 2026-10-14 | Agent read/write |
| Review | 2026-10-15 | Tech Lead approval |

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Graph.json merge conflicts | Medium | Medium | Git merge driver or agent-only writes |
| Schema drift (schemas change, assets don't) | Medium | High | Schema versioning + migration tool |
| Performance with large graphs | Low | Medium | Indexing + lazy loading |

---

## 12. Appendix

### Related Documents
- Architecture: `docs/ASSET-MODEL.md`
- SDLC: `docs/SDLC.md`
- Schemas: `assets/schemas/*.schema.json`

### Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-10-06 | agentic-runtime-team | Initial draft |
