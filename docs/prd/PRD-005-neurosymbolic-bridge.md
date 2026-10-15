---
# Product Requirements Document (PRD)
---

# PRD-005: Neurosymbolic Bridge (LLM + Structured Data)

**Status:** draft
**Author:** agentic-runtime-team
**Date:** 2026-10-06
**Version:** 0.1

---

## 1. Overview

### What
The **neurosymbolic bridge** — the layer where LLM agents (neural) interact with structured assets and schemas (symbolic). LLMs see the full asset graph, schemas, and data, enabling them to "connect the dots" when non-deterministic decisions are needed.

**One-liner:** "LLMs see the whole graph — structured context for non-deterministic decisions, rules for deterministic ones."

> **Prior art:** this PRD continues the neurosymbolic program described in
> [docs/vision.md](../vision.md) (imported from
> [chartpath/clientsort-docs-archive](https://github.com/chartpath/clientsort-docs-archive),
> 2020–2024): abductive reasoning with rules and classifiers held in balance,
> human soundness critics as the source of framework trust (LLM-Modulo), and
> auditable rationale as a first-class requirement. The audit trail, asset
> graph, and human review gates of this SDLC are that architecture realized.

### Why
- **Grounding:** LLMs hallucinate less with structured context
- **Explainability:** Decisions traceable to assets + rules
- **Composition:** LLMs combine assets in novel ways
- **Efficiency:** Rules handle deterministic, LLMs handle creative
- **Auditability:** Every LLM decision cites its inputs

### The Neurosymbolic Loop

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      NEUROSYMBOLIC LOOP                                  │
│                                                                          │
│   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐             │
│   │ SYMBOLIC│───▶│  RULES  │───▶│ DECIDE  │───▶│ SYMBOLIC│             │
│   │  Asset  │    │ Engine  │    │(determ- │    │  Asset  │             │
│   │  Graph  │    │         │    │  inistic)│   │ Materialized│           │
│   └─────────┘    └─────────┘    └────┬────┘    └─────────┘             │
│        ▲                              │                                  │
│        │                              │ no rule matches                  │
│        │                              ▼                                  │
│   ┌─────────┐                    ┌─────────┐                           │
│   │ SYMBOLIC│◀───────────────────│ NEURAL  │                           │
│   │  Asset  │  structured prompt │  LLM    │                           │
│   │Materialized│                 │ (Agent) │                           │
│   └─────────┘                    └─────────┘                           │
│        ▲                                                            │
│        │                                                            │
│   Full asset graph + schemas + data + history                      │
│   (LLM sees everything, decides what rules can't)                  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Who
- **LLM agents** — see structured context, make non-deterministic decisions
- **Rules engine** — handle deterministic decisions
- **Asset graph** — provides structured context to LLMs
- **Schemas** — constrain and guide LLM output
- **Audit trail** — records which path (rule vs LLM) was taken

---

## 2. Goals & Non-Goals

### Goals (In Scope)
- [ ] **GOAL-1:** Structured prompt builder: assets + schemas + rules → LLM prompt
- [ ] **GOAL-2:** Schema-guided generation: LLM output validated against JSON Schema
- [ ] **GOAL-3:** Lineage-aware prompting: LLM sees full upstream context
- [ ] **GOAL-4:** Decision provenance: record whether decision was rule-based or LLM-based
- [ ] **GOAL-5:** Structured extraction: parse LLM output into schema-valid assets
- [ ] **GOAL-6:** Prompt templates per asset type (OST, PRD, BDD, ADR)
- [ ] **GOAL-7:** Context window management: summarize old assets if too large

### Non-Goals (Out of Scope)
- **NON-GOAL-1:** Fine-tuning models (use APIs only)
- **NON-GOAL-2:** Local model hosting (cloud APIs only)
- **NON-GOAL-3:** Multi-modal (text only for v1)
- **NON-GOAL-4:** Prompt optimization/learning (manual iteration)

---

## 3. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-001 | LLM agent | See the full OST when generating a PRD | My PRD is grounded in discovery |
| US-002 | LLM agent | Know the schema for the asset I'm creating | My output is structurally valid |
| US-003 | Rules engine | Escalate to LLM with full context | The LLM has what it needs |
| US-004 | Auditor | See whether a decision was rule-based or LLM-based | I understand the decision path |
| US-005 | Developer | Reuse prompt templates | Consistent agent behavior |
| US-006 | System | Validate LLM output against schema | No invalid assets materialized |

---

## 4. Requirements

### Functional Requirements

| ID | Requirement | Priority | Acceptance Criteria |
|----|-------------|----------|---------------------|
| REQ-001 | Prompt builder: `prompt.sh build <asset-type>` | P0 | Generates structured prompt |
| REQ-002 | Prompt includes: asset graph state, upstream assets, schemas, rules | P0 | All components present |
| REQ-003 | Schema-guided generation: LLM output validated against JSON Schema | P0 | Invalid output rejected |
| REQ-004 | Structured extraction: LLM output → typed asset | P0 | `extract_asset(llm_output)` works |
| REQ-005 | Lineage-aware: prompt includes `depends_on` chain | P0 | LLM sees full upstream |
| REQ-006 | Decision provenance: record `decision_method: "rule" \| "llm"` | P0 | Audit log shows method |
| REQ-007 | Prompt templates: `templates/prompts/{ost,prd,bdd,adr}.md` | P0 | Templates exist and work |
| REQ-008 | Context management: truncate old assets if prompt > 100k tokens | P1 | Token budget enforced |
| REQ-009 | Few-shot examples: include 1-2 examples per asset type | P1 | Improves output quality |
| REQ-010 | Retry with feedback: if schema validation fails, retry with error | P1 | Self-correction loop |
| REQ-011 | Multi-turn: LLM can ask for clarification (via task queue) | P2 | Async clarification |
| REQ-012 | Cost tracking: log tokens per LLM call | P1 | Budget visibility |

### Non-Functional Requirements

| ID | Category | Requirement | Target |
|----|----------|-------------|--------|
| NFR-001 | Quality | Schema validation pass rate | > 95% first try |
| NFR-002 | Performance | Prompt build time | < 1s |
| NFR-003 | Cost | Tokens per asset | < 50k average |
| NFR-004 | Reliability | LLM call success rate | > 99% |

---

## 5. Assumptions

| ID | Assumption | Source | Validation Method | Status |
|----|-----------|--------|-------------------|--------|
| ASM-001 | Structured context improves LLM output | Research | A/B test with/without | pending |
| ASM-002 | JSON Schema is sufficient for validation | Architecture | Validate all asset types | pending |
| ASM-003 | 80% of decisions can be rule-based | Hypothesis | Measure ratio | pending |
| ASM-004 | Prompt templates are maintainable | Product | Developer feedback | pending |

---

## 6. Open Questions

| ID | Question | Owner | Due Date | Status |
|----|----------|-------|----------|--------|
| Q-001 | Should we use function calling / tool use? | Tech Lead | 2026-10-13 | open |
| Q-002 | Structured output (JSON mode) vs free text + parse? | Tech Lead | 2026-10-13 | open |
| Q-003 | Should LLMs see other LLMs' outputs directly? | Architecture | 2026-10-20 | open |

---

## 7. Acceptance Criteria

Feature is complete when:

- [ ] **AC-1:** `prompt.sh build prd` generates prompt with OST context
- [ ] **AC-2:** LLM output validates against PRD schema
- [ ] **AC-3:** Invalid LLM output is rejected and retried
- [ ] **AC-4:** Decision provenance recorded in audit log
- [ ] **AC-5:** Prompt templates exist for OST, PRD, BDD, ADR
- [ ] **AC-6:** Context truncation works for large graphs
- [ ] **AC-7:** Token usage tracked per call

---

## 8. Dependencies

| Dependency | Type | Owner | Status | Blocker? |
|------------|------|-------|--------|----------|
| Asset graph (PRD-001) | Feature | Engineering | in-progress | YES |
| Rules engine (PRD-002) | Feature | Engineering | draft | YES |
| Agent orchestration (PRD-003) | Feature | Engineering | draft | YES |
| Audit trail (PRD-004) | Feature | Engineering | draft | NO |
| JSON Schema validator | Tool | — | ready | NO |
| LLM APIs (Mistral, etc.) | Service | — | ready | NO |

---

## 9. Success Metrics

| Metric | Baseline | Target | Measurement |
|--------|----------|--------|-------------|
| Schema validation rate | N/A | > 95% | Audit log |
| Rule vs LLM ratio | N/A | 80/20 | Decision provenance |
| Prompt build time | N/A | < 1s | Benchmark |
| Token cost per asset | N/A | < $0.50 | Cost tracking |
| Agent task success rate | N/A | > 95% | Audit log |

---

## 10. Timeline

| Phase | Dates | Deliverable |
|-------|-------|-------------|
| Design | 2026-10-06 — 2026-10-07 | This PRD + prompt schema |
| Prompt builder | 2026-10-08 — 2026-10-10 | `prompt.sh` |
| Schema validation | 2026-10-11 — 2026-10-12 | Structured extraction |
| Templates | 2026-10-13 — 2026-10-14 | 4 prompt templates |
| Provenance | 2026-10-15 — 2026-10-16 | Audit integration |
| Review | 2026-10-17 | Tech Lead approval |

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| LLM ignores structured context | Medium | High | Prompt engineering + eval |
| Schema too rigid for LLM creativity | Medium | Medium | Schema evolution process |
| Context window overflow | Medium | Medium | Truncation + summarization |
| Cost overruns | Medium | Medium | Budget alerts + limits |

---

## 12. Appendix

### Prompt Template Example

```markdown
# System: You are the decision agent in an agentic SDLC.

## Your Role
Generate a Product Requirements Document (PRD) from an approved Opportunity Solution Tree (OST).

## Current Asset Graph
```json
{{ asset_graph_json }}
```

## Upstream Assets (your inputs)
### OST (docs/discovery/ost.json)
```json
{{ ost_content }}
```

### Schema (what your output must conform to)
```json
{{ prd_schema }}
```

## Applicable Rules
```yaml
{{ relevant_rules }}
```

## Your Task
{{ task_description }}

## Output Format
Produce a PRD that:
1. Conforms to the schema above
2. References specific OST elements (OPP-XXX, SOL-XXX, ASM-XXX)
3. Includes all assumptions from the selected solution path
4. Has testable acceptance criteria

## Example (few-shot)
{{ example_prd }}
```

### Related Documents
- Asset Model: `docs/ASSET-MODEL.md`
- PRD-001: Asset Graph
- PRD-002: Rules Engine
- PRD-003: Agent Orchestration
- PRD-004: Audit Trail

### Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-10-06 | agentic-runtime-team | Initial draft |
