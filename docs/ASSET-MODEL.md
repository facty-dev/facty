# Asset-Oriented Architecture


> **Git-Native:** Branches are assets. Merges are materializations. PRs are gates. See [GIT-NATIVE-PIPELINE.md](./GIT-NATIVE-PIPELINE.md).


Inspired by **Dagster's** asset-oriented programming model. Each node in the orchestration DAG corresponds to an **asset** — a materialized, versioned, auditable intermediate state of the project. Assets double as audit trails and enable **neurosymbolic composition**: LLMs see the full data and schemas, connecting dots when non-deterministic decisions are needed.

---

## Core Concepts

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         ASSET-ORIENTED DAG                              │
│                                                                          │
│   ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐          │
│   │ ASSET:  │────▶│ ASSET:  │────▶│ ASSET:  │────▶│ ASSET:  │          │
│   │ Problems│     │Solutions│     │   PRD   │     │  BDD    │          │
│   │  List   │     │  List   │     │         │     │ Specs   │          │
│   └────┬────┘     └────┬────┘     └────┬────┘     └────┬────┘          │
│        │               │               │               │                │
│        ▼               ▼               ▼               ▼                │
│   ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐          │
│   │ Schema: │     │ Schema: │     │ Schema: │     │ Schema: │          │
│   │ problems│     │solutions│     │   prd   │     │  bdd    │          │
│   │  .v1    │     │  .v1    │     │  .v1    │     │  .v1    │          │
│   └─────────┘     └─────────┘     └─────────┘     └─────────┘          │
│        │               │               │               │                │
│        ▼               ▼               ▼               ▼                │
│   ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐          │
│   │ Metadata│     │ Metadata│     │ Metadata│     │ Metadata│          │
│   │ (hash,  │     │ (hash,  │     │ (hash,  │     │ (hash,  │          │
│   │  lineage)│    │  lineage)│    │  lineage)│    │  lineage)│          │
│   └─────────┘     └─────────┘     └─────────┘     └─────────┘          │
│                                                                          │
│   Each asset is: MATERIALIZED + VERSIONED + AUDITABLE + COMPOSABLE     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## What is an Asset?

An **asset** is a materialized, versioned artifact that represents an intermediate state of the project. Unlike a task (which is about *doing*), an asset is about *being* — it's the **what**, not the **how**.

| Property | Description |
|----------|-------------|
| **Materialized** | Exists as a concrete file/artifact (markdown, JSON, code) |
| **Versioned** | Content-addressed by hash; history preserved |
| **Typed** | Has a schema (JSON Schema, Gherkin, PRD template) |
| **Lineage-tracked** | Knows its upstream dependencies |
| **Auditable** | Full history of changes with who/what/when/why |
| **Composable** | Can be consumed by downstream assets or agents |

---

## Asset Types in the SDLC

```
┌─────────────────────────────────────────────────────────────────────────┐
│  DISCOVERY          DEFINE             DEVELOP            DELIVER        │
│                                                                          │
│  ┌─────────┐       ┌─────────┐       ┌─────────┐       ┌─────────┐     │
│  │ problems│       │   prd   │       │   bdd   │       │  code   │     │
│  │  .md    │──────▶│  .md    │──────▶│ .feature│──────▶│  .py    │     │
│  │         │       │         │       │         │       │  .ts    │     │
│  └─────────┘       └─────────┘       └─────────┘       │  .rs    │     │
│                                                        └─────────┘     │
│  ┌─────────┐       ┌─────────┐       ┌─────────┐       ┌─────────┐     │
│  │solutions│       │assumptions│     │  tests  │       │  adr    │     │
│  │  .md    │──────▶│  .md    │──────▶│  .py    │──────▶│  .md    │     │
│  │         │       │         │       │  .ts    │       │         │     │
│  └─────────┘       └─────────┘       └─────────┘       └─────────┘     │
│                                                                          │
│  ┌─────────┐                                                            │
│  │   ost   │  ← The root asset: Opportunity Solution Tree               │
│  │  .md    │                                                            │
│  │  .json  │  ← Machine-readable graph for composition                 │
│  └─────────┘                                                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Asset Catalog

| Asset | Path | Schema | Produced By | Consumed By |
|-------|------|--------|-------------|-------------|
| `problems` | `docs/discovery/problems.md` | `schemas/problems.schema.json` | Decision agent | Decision agent |
| `solutions` | `docs/discovery/solutions.md` | `schemas/solutions.schema.json` | Decision agent | Decision agent |
| `assumptions` | `docs/discovery/assumptions.md` | `schemas/assumptions.schema.json` | Decision agent | Decision + Coding agents |
| `ost` | `docs/discovery/ost.md` + `.json` | `schemas/ost.schema.json` | Decision agent | Product Owner, Decision agent |
| `prd` | `docs/prd/PRD-NNN-slug.md` | `schemas/prd.schema.json` | Decision agent | Product Owner, Coding agent |
| `bdd_specs` | `specs/features/*.feature` | Gherkin | Decision agent | QA Lead, Coding agent |
| `test_results` | `.agentic/test-results.json` | `schemas/test-results.schema.json` | Coding agent | Decision agent |
| `code` | `src/**/*` | (language-specific) | Coding agent | Decision agent, Tech Lead |
| `adr` | `docs/adr/ADR-NNN-slug.md` | `schemas/adr.schema.json` | Decision agent | Tech Lead |
| `review` | `.agentic/reviews/NNN.md` | `schemas/review.schema.json` | Decision agent | Human reviewers |
| `merge_record` | `.agentic/merge-record.json` | `schemas/merge.schema.json` | CI/CD | Audit |

---

## Asset Graph (DAG)

The **asset graph** is the DAG that defines how assets depend on each other. It's the single source of truth for the project's state.

```json
{
  "graph": {
    "nodes": {
      "problems": {
        "asset_key": "discovery/problems",
        "path": "docs/discovery/problems.md",
        "schema": "schemas/problems.schema.json",
        "depends_on": [],
        "produced_by": "decision-agent",
        "status": "materialized",
        "hash": "sha256:abc123...",
        "version": 1,
        "materialized_at": "2026-10-06T10:00:00Z"
      },
      "solutions": {
        "asset_key": "discovery/solutions",
        "path": "docs/discovery/solutions.md",
        "schema": "schemas/solutions.schema.json",
        "depends_on": ["problems"],
        "produced_by": "decision-agent",
        "status": "materialized",
        "hash": "sha256:def456...",
        "version": 1,
        "materialized_at": "2026-10-06T10:30:00Z"
      },
      "ost": {
        "asset_key": "discovery/ost",
        "path": "docs/discovery/ost.json",
        "schema": "schemas/ost.schema.json",
        "depends_on": ["problems", "solutions", "assumptions"],
        "produced_by": "decision-agent",
        "status": "materialized",
        "hash": "sha256:ghi789...",
        "version": 1,
        "materialized_at": "2026-10-06T11:00:00Z"
      },
      "prd": {
        "asset_key": "define/prd",
        "path": "docs/prd/PRD-001-user-auth.md",
        "schema": "schemas/prd.schema.json",
        "depends_on": ["ost"],
        "produced_by": "decision-agent",
        "status": "pending",
        "hash": null,
        "version": 0
      },
      "bdd": {
        "asset_key": "develop/bdd",
        "path": "specs/features/",
        "schema": "gherkin",
        "depends_on": ["prd"],
        "produced_by": "decision-agent",
        "status": "pending"
      },
      "code": {
        "asset_key": "develop/code",
        "path": "src/",
        "schema": null,
        "depends_on": ["bdd"],
        "produced_by": "coding-agent",
        "status": "pending"
      }
    },
    "edges": [
      {"from": "problems", "to": "solutions", "type": "data"},
      {"from": "problems", "to": "ost", "type": "data"},
      {"from": "solutions", "to": "ost", "type": "data"},
      {"from": "assumptions", "to": "ost", "type": "data"},
      {"from": "ost", "to": "prd", "type": "data"},
      {"from": "prd", "to": "bdd", "type": "data"},
      {"from": "bdd", "to": "code", "type": "data"},
      {"from": "code", "to": "test_results", "type": "validation"},
      {"from": "code", "to": "adr", "type": "documentation"},
      {"from": "ost", "to": "prd", "type": "gate", "gate": "product-owner-review"},
      {"from": "prd", "to": "bdd", "type": "gate", "gate": "product-owner-review"},
      {"from": "bdd", "to": "code", "type": "gate", "gate": "qa-lead-review"}
    ]
  }
}
```

---

## Rules Engine (Deterministic Decisions)

Not every decision needs an LLM. The **rules engine** handles deterministic, repeatable decisions based on asset state and schemas.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        RULES ENGINE                                      │
│                                                                          │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐             │
│  │  INPUT  │───▶│  RULES  │───▶│ DECIDE  │───▶│  OUTPUT │             │
│  │  (asset │    │ (YAML/ │    │(determ-│    │ (action │             │
│  │   state)│    │  JSON)  │    │  inistic)│    │  or LLM │             │
│  └─────────┘    └─────────┘    └────┬────┘    │  request)│             │
│                                     │          └─────────┘             │
│                              ┌──────┴──────┐                          │
│                              │ If no rule  │                          │
│                              │ matches →   │                          │
│                              │ escalate to │                          │
│                              │ LLM (neural)│                          │
│                              └─────────────┘                          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Rule Types

| Rule Type | Purpose | Example |
|-----------|---------|---------|
| **Validation** | Check asset conforms to schema | PRD must have REQ-001 through REQ-005 |
| **Gating** | Block progression until condition met | All BDD tests must pass before merge |
| **Selection** | Choose next asset to materialize | If OST approved → materialize PRD |
| **Routing** | Decide which agent handles task | If asset is code → coding agent |
| **Escalation** | When to involve human | If assumption confidence < 0.5 → PO review |
| **Composition** | Combine multiple assets | Merge problems + solutions → OST |

### Rule Example (YAML)

```yaml
# .agentic/rules/sdlc-rules.yaml
rules:
  - id: RULE-001
    name: "OST approval gate"
    description: "OST must be approved by Product Owner before PRD generation"
    when:
      asset: "discovery/ost"
      event: "materialized"
    condition:
      type: "human_review"
      reviewer_role: "product-owner"
      required: true
    then:
      action: "block"
      until: "review.approved == true"
      on_approved:
        action: "materialize"
        target: "define/prd"
        agent: "decision-agent"

  - id: RULE-002
    name: "BDD coverage check"
    description: "All PRD requirements must have BDD scenarios"
    when:
      asset: "define/prd"
      event: "materialized"
    condition:
      type: "schema_validation"
      check: |
        prd.requirements.all(req =>
          bdd.scenarios.any(s => s.tags.includes(`@REQ-${req.id}`))
        )
    then:
      action: "validate"
      on_fail:
        action: "escalate"
        to: "decision-agent"
        message: "PRD requirements missing BDD coverage"

  - id: RULE-003
    name: "Test pass gate"
    description: "All BDD tests must pass before code review"
    when:
      asset: "develop/code"
      event: "materialized"
    condition:
      type: "test_results"
      check: "test_results.passed == test_results.total"
      threshold: 1.0
    then:
      action: "gate"
      on_pass:
        action: "request_review"
        reviewer_role: "tech-lead"
      on_fail:
        action: "rematerialize"
        target: "develop/code"
        agent: "coding-agent"
        feedback: "test_results.failures"

  - id: RULE-004
    name: "Assumption confidence escalation"
    description: "Low-confidence assumptions trigger stakeholder review"
    when:
      asset: "discovery/assumptions"
      event: "materialized"
    condition:
      type: "threshold"
      field: "confidence"
      operator: "lt"
      value: 0.5
    then:
      action: "escalate"
      to: "human"
      reviewer_role: "product-owner"
      message: "Assumption {{id}} has low confidence ({{confidence}})"
```

---

## Neurosymbolic Composition

The key insight: **LLMs (neural) + structured assets (symbolic) = neurosymbolic system**.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    NEUROSYMBOLIC COMPOSITION LAYER                       │
│                                                                          │
│  ┌─────────────┐         ┌─────────────┐         ┌─────────────┐       │
│  │   NEURAL    │◀───────▶│   SYMBOLIC  │◀───────▶│   NEURAL    │       │
│  │  (LLM)      │  prompt │  (Assets +  │  query  │  (LLM)      │       │
│  │  Decision   │         │  Rules +    │         │  Coding     │       │
│  │  Agent      │         │  Schemas)   │         │  Agent      │       │
│  └─────────────┘         └──────┬──────┘         └─────────────┘       │
│                                 │                                       │
│                    ┌────────────┴────────────┐                         │
│                    │   ASSET GRAPH (source    │                         │
│                    │   of truth for both)     │                         │
│                    │                          │                         │
│                    │  • problems.json         │                         │
│                    │  • solutions.json        │                         │
│                    │  • ost.json (graph)      │                         │
│                    │  • prd.json              │                         │
│                    │  • bdd.json (parsed)     │                         │
│                    │  • code_manifest.json    │                         │
│                    │  • test_results.json     │                         │
│                    │  • adr.json              │                         │
│                    └─────────────────────────┘                         │
│                                                                          │
│  LLM sees: Full asset graph + schemas + data + history                 │
│  LLM decides: Non-deterministic choices (which solution, how to code)   │
│  Rules decide: Deterministic gates, validations, routing               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### How LLMs Use Structured Assets

```python
# Example: Decision agent prompt with full asset visibility
prompt = f"""
You are the decision agent in an agentic SDLC.

## Current Asset Graph State
{json.dumps(asset_graph.get_current_state(), indent=2)}

## Available Assets (with schemas)
{format_assets_with_schemas(available_assets)}

## Upstream Asset Contents
{format_asset_contents(upstream_assets)}

## Rules (deterministic constraints)
{format_rules(active_rules)}

## Your Task
{task_description}

## Instructions
1. Read the upstream assets to understand context
2. Check which rules apply to your decision
3. If a rule fully determines the outcome, follow it
4. If the decision is non-deterministic, use your judgment
5. Materialize the output asset with full lineage metadata
6. Record any ADRs for significant decisions
"""
```

### Composition Example: OST → PRD

```
SYMBOLIC (structured):                    NEURAL (LLM):
┌─────────────────┐                      ┌─────────────────┐
│  ost.json       │                      │  Decision Agent │
│  ├── outcome    │─────────────────────▶│                 │
│  ├── opportunities│  "Generate PRD     │  • Reads OST    │
│  │   ├── OPP-001 │   from this OST"    │  • Sees schemas │
│  │   ├── OPP-002 │                      │  • Applies rules│
│  │   └── OPP-003 │                      │  • Writes PRD   │
│  ├── solutions  │                      │  • Records ADR  │
│  │   ├── SOL-001-A│◀────────────────────│                 │
│  │   └── SOL-001-B│  prd.md (output)    └─────────────────┘
│  └── selected:  │         │
│      SOL-001-A  │─────────┘
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  prd.md +       │  ← New asset with lineage
│  prd.json       │    pointing back to ost.json
│  (schema-valid) │
└─────────────────┘
```

---

## Audit Trail via Reification Streams

Every asset materialization is an **event** in a reification stream. The stream is the audit trail.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    REIFICATION STREAM (Audit Trail)                     │
│                                                                          │
│  Event 1          Event 2          Event 3          Event 4             │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐          │
│  │ Asset:  │────▶│ Asset:  │────▶│ Asset:  │────▶│ Asset:  │          │
│  │ problems│     │solutions│     │   ost   │     │  prd    │          │
│  │ v1      │     │ v1      │     │ v1      │     │ v1      │          │
│  │         │     │         │     │         │     │         │          │
│  │ agent:  │     │ agent:  │     │ agent:  │     │ agent:  │          │
│  │ decision│     │ decision│     │ decision│     │ decision│          │
│  │         │     │         │     │         │     │         │          │
│  │ hash:   │     │ hash:   │     │ hash:   │     │ hash:   │          │
│  │ abc123  │     │ def456  │     │ ghi789  │     │ jkl012  │          │
│  │         │     │         │     │         │     │         │          │
│  │ gate:   │     │ gate:   │     │ gate:   │     │ gate:   │          │
│  │ none    │     │ none    │     │ PO ✅   │     │ PO ✅   │          │
│  │         │     │         │     │         │     │         │          │
│  │ time:   │     │ time:   │     │ time:   │     │ time:   │          │
│  │ 10:00   │     │ 10:30   │     │ 11:00   │     │ 14:00   │          │
│  └─────────┘     └─────────┘     └─────────┘     └─────────┘          │
│       │               │               │               │                 │
│       └───────────────┴───────────────┴───────────────┘                 │
│                               │                                        │
│                    ┌──────────┴──────────┐                            │
│                    │  audit.jsonl        │  ← Append-only log         │
│                    │  (every event)      │                            │
│                    └─────────────────────┘                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Event Schema

```json
{
  "event_id": "evt-001",
  "timestamp": "2026-10-06T10:00:00Z",
  "event_type": "asset.materialized",
  "asset": {
    "key": "discovery/problems",
    "path": "docs/discovery/problems.md",
    "version": 1,
    "hash": "sha256:abc123...",
    "size_bytes": 2048
  },
  "producer": {
    "type": "agent",
    "id": "decision-agent",
    "model": "mistral/mistral-large-latest",
    "run_id": "github-actions-12345"
  },
  "inputs": [
    {"asset_key": "stakeholder-input", "hash": "sha256:..."}
  ],
  "gates": {
    "required": [],
    "passed": []
  },
  "metadata": {
    "pr": 42,
    "branch": "feature/user-auth",
    "commit": "abc123def"
  }
}
```

### Audit Queries

```bash
# What assets exist and their lineage?
jq '.nodes | to_entries | map({key: .key, version: .value.version, depends_on: .value.depends_on})' assets/graph.json

# Full history of an asset
jq 'select(.asset.key == "define/prd")' .agentic/audit.jsonl

# Who approved what and when?
jq 'select(.event_type == "gate.passed") | {asset: .asset.key, reviewer: .reviewer, time: .timestamp}' .agentic/audit.jsonl

# What changed between versions?
diff <(jq -r '.content' <(get_asset prd v1)) <(jq -r '.content' <(get_asset prd v2))
```

---

## Asset Materialization Protocol

When an agent materializes an asset:

```
1. READ upstream assets (from graph)
2. VALIDATE inputs against schemas
3. CHECK applicable rules
4. COMPUTE output (LLM or deterministic)
5. VALIDATE output against schema
6. WRITE asset file
7. COMPUTE content hash
8. UPDATE asset graph (node + edges)
9. APPEND event to audit stream
10. TRIGGER downstream (rules engine)
```

---

## File Layout

```
redyarn/
├── assets/                     # Asset-oriented project state
│   ├── graph.json              # The asset DAG (source of truth)
│   ├── schemas/                # JSON Schemas for each asset type
│   │   ├── problems.schema.json
│   │   ├── solutions.schema.json
│   │   ├── assumptions.schema.json
│   │   ├── ost.schema.json
│   │   ├── prd.schema.json
│   │   ├── bdd.schema.json
│   │   ├── test-results.schema.json
│   │   ├── adr.schema.json
│   │   └── review.schema.json
│   └── materialized/           # Versioned asset storage
│       ├── discovery/
│       │   ├── problems/
│       │   │   ├── v1.md
│       │   │   └── v1.meta.json
│       │   └── solutions/
│       └── define/
│           └── prd/
│               └── v1.md
├── .agentic/
│   ├── state.json              # Current SDLC state
│   ├── audit.jsonl             # Append-only event log
│   ├── rules/                  # Rules engine config
│   │   └── sdlc-rules.yaml
│   └── messages/               # Agent communication
├── docs/                       # Human-readable assets
│   ├── discovery/
│   ├── prd/
│   ├── adr/
│   └── *.md                    # Architecture docs
└── templates/sdlc/             # Asset templates
    ├── ost.md
    ├── prd.md
    ├── feature.feature
    └── adr.md
```

---

## Summary

| Concept | Dagster Equivalent | Redyarn Implementation |
|---------|-------------------|---------------------------|
| Asset | `@asset` decorated function | Materialized file + metadata + hash |
| Asset graph | Dagster's asset graph | `assets/graph.json` |
| Materialization | Running an asset | Agent or rule produces asset |
| Schema/Type | Dagster type system | JSON Schema per asset type |
| Lineage | Dagster's built-in lineage | `depends_on` in graph + audit log |
| Observations | Dagster metadata | `.agentic/audit.jsonl` events |
| Rules | N/A (new) | `rules/sdlc-rules.yaml` |
| Neurosymbolic | N/A (new) | LLM agents + structured assets |
| Audit trail | Dagster run history | Reification stream (append-only) |
