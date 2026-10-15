# Git-Native Agentic Pipeline

**Branches are assets. Merges are materializations. PRs are gates.**

The agentic SDLC runs as a **convolutional spiral** on Git branches. Each phase produces an asset on its own branch. Merging that branch into `main` materializes the asset and triggers downstream DAG steps. Humans inject at any point — review, comment, or add their own assets.

---

## Core Model

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    BRANCH = ASSET = SDLC PHASE                          │
│                                                                          │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌────────┐ │
│  │   BRANCH    │     │   BRANCH    │     │   BRANCH    │     │ BRANCH │ │
│  │  sdlc/ost/  │────▶│  sdlc/prd/  │────▶│  sdlc/bdd/  │────▶│sdlc/   │ │
│  │  user-auth  │ merge│  user-auth  │ merge│  user-auth  │ merge│impl/   │ │
│  │             │  ──▶ │             │  ──▶ │             │  ──▶ │user-   │ │
│  │  ASSET:     │  main│  ASSET:     │  main│  ASSET:     │  main│auth    │ │
│  │  OST        │      │  PRD        │      │  BDD specs  │      │        │ │
│  │  (discovery)│      │  (define)   │      │  (develop)  │      │ASSET:  │ │
│  └─────────────┘      └─────────────┘      └─────────────┘      │ Code   │ │
│                                                                  │(deliver)│ │
│                                                                  └────────┘ │
│                                                                      │    │
│  ┌───────────────────────────────────────────────────────────────────┘    │
│  ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                         MAIN BRANCH                              │    │
│  │  docs/discovery/ost.md  ← merged asset v1                       │    │
│  │  docs/prd/PRD-001.md    ← merged asset v1                       │    │
│  │  specs/features/*.feature ← merged asset v1                    │    │
│  │  src/auth/              ← merged asset v1                       │    │
│  │  docs/adr/ADR-001.md    ← merged asset v1                       │    │
│  │  assets/graph.json      ← derived from merged branches          │    │
│  │  .agentic/audit.jsonl   ← reification stream                    │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Branch Naming Convention

```
sdlc/<phase>/<feature-slug>
```

| Phase | Branch Prefix | Asset Produced | Directory |
|-------|--------------|----------------|-----------|
| Discovery | `sdlc/ost/` | Opportunity Solution Tree | `docs/discovery/` |
| Define | `sdlc/prd/` | Product Requirements Document | `docs/prd/` |
| Develop | `sdlc/bdd/` | BDD Feature Specs | `specs/features/` |
| Deliver | `sdlc/impl/` | Code + Tests + ADRs | `src/`, `tests/`, `docs/adr/` |

**Examples:**
```
sdlc/ost/user-authentication
sdlc/prd/user-authentication
sdlc/bdd/user-authentication
sdlc/impl/user-authentication
```

---

## Merge = Materialization = Trigger

When a phase branch merges into `main`:

1. **Asset materializes** — files land in `main`, asset graph updates
2. **Audit event logged** — merge event appended to `.agentic/audit.jsonl`
3. **Downstream triggers** — GitHub Actions creates next phase branch
4. **Agents activate** — decision/coding agent runs on new branch

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  sdlc/ost/      │────▶│  MERGE to main  │────▶│  Asset: OST     │
│  user-auth      │ PR  │  (approved)     │     │  materialized   │
│                 │     │                 │     │                 │
│  docs/discovery/│     │  squash merge   │     │  v1, hash: abc  │
│  ost.md         │     │                 │     │                 │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
                                                         │
                              ┌──────────────────────────┘
                              ▼
                    ┌─────────────────┐
                    │  TRIGGER:       │
                    │  Create branch  │
                    │  sdlc/prd/      │
                    │  user-auth      │
                    │                 │
                    │  Run decision   │
                    │  agent to       │
                    │  generate PRD   │
                    └─────────────────┘
```

---

## Human Injection Points

Humans can intervene at **any** point in the pipeline:

### 1. Review + Comment (feedback loop)

```
Human reviews PR: sdlc/ost/user-auth → main
         │
         ▼
    ┌─────────┐
    │  Human  │── comments: "Add assumption about password complexity"
    │ reviews │── requests changes
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ GitHub  │── triggers: agent-update workflow
    │ Actions │── posts comment as task
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ Decision│── reads feedback
    │ agent   │── updates OST on branch
    │         │── commits fix
    └────┬────┘
         │
         ▼
    Human re-reviews → approves → merge → trigger downstream
```

**PR comment commands:**
- `/sdlc-update <instruction>` — tell agent to update the asset
- `/sdlc-approve` — approve (same as GitHub approve)
- `/sdlc-reject <reason>` — reject with reason (agent gets feedback)
- `/sdlc-skip <phase>` — skip a phase (e.g., `/sdlc-skip bdd`)

### 2. Manual Asset Injection (skip-ahead)

A human can add their own asset to a PR, bypassing agent generation:

```
Human has their own PRD (written manually or with different agent)
         │
         ▼
    ┌─────────┐
    │  Human  │── adds docs/prd/PRD-001-user-auth.md
    │         │── to PR: sdlc/ost/user-auth → main
    └────┬────┘
         │
         ▼
    PR now contains: OST (agent) + PRD (human)
         │
         ▼
    ┌─────────┐
    │  MERGE  │── both assets materialize
    │  to main│── OST v1, PRD v1
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │ SKIP-   │── PRD already exists
    │ AHEAD   │── skip sdlc/prd/ branch creation
    │         │── trigger sdlc/bdd/ directly
    └─────────┘
```

### 3. Out-of-Band Generation

Humans can generate assets with any tool (their own agent, manual writing, etc.) and push to a phase branch:

```bash
# Human generates PRD with their own agent
my-agent --output docs/prd/PRD-001-user-auth.md

# Push to the PRD branch (or add to existing PR)
git checkout sdlc/prd/user-auth
git add docs/prd/PRD-001-user-auth.md
git commit -m "docs: add PRD (human-generated)"
git push

# Open PR: sdlc/prd/user-auth → main
# Agent reviews it (optional) or human approves directly
# Merge → triggers BDD generation
```

---

## Skip-Ahead Logic

When a merge contains assets from **multiple phases**, the pipeline skips ahead:

```
Scenario: Human writes both OST and PRD, opens one PR

PR: sdlc/ost/user-auth → main
Files changed:
  docs/discovery/ost.md          ← OST asset
  docs/discovery/problems.md     ← supporting
  docs/prd/PRD-001-user-auth.md  ← PRD asset (human-written!)

Merge analysis:
  ✓ OST asset detected → materialize
  ✓ PRD asset detected → materialize (skip-ahead!)
  ✗ BDD not present → trigger BDD generation

Result:
  • sdlc/prd/ branch NOT created (PRD already exists)
  • sdlc/bdd/user-auth branch created directly
  • Decision agent generates BDD from existing PRD
```

### Skip-Ahead Rules

| Assets in Merge | Downstream Trigger |
|-----------------|-------------------|
| OST only | Create `sdlc/prd/` → decision agent generates PRD |
| OST + PRD | Create `sdlc/bdd/` → decision agent generates BDD (skip PRD) |
| OST + PRD + BDD | Create `sdlc/impl/` → coding agent implements (skip PRD, BDD) |
| PRD only (no OST) | Create `sdlc/bdd/` → warn: OST missing, generate from PRD? |
| BDD only | Create `sdlc/impl/` → coding agent implements |
| Code + ADRs | Final review → merge to release |

---

## PR Review → Agent Feedback Loop

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     PR REVIEW FEEDBACK LOOP                              │
│                                                                          │
│  ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐          │
│  │   PR    │────▶│  Human  │────▶│ Comment │────▶│ GitHub  │          │
│  │  open   │     │ reviews │     │  /sdlc- │     │ Actions │          │
│  │         │     │         │     │  update │     │ trigger │          │
│  └─────────┘     └─────────┘     └────┬────┘     └────┬────┘          │
│                                       │               │                │
│                              ┌────────┴────────┐      │                │
│                              ▼                 ▼      ▼                │
│                         ┌─────────┐       ┌─────────┐                 │
│                         │  Parse  │       │  Direct │                 │
│                         │ command │       │  reply  │                 │
│                         └────┬────┘       └─────────┘                 │
│                              │                                         │
│                              ▼                                         │
│                         ┌─────────┐                                   │
│                         │  Agent  │── reads task from comment        │
│                         │  task   │── updates branch                 │
│                         │ created │── commits fix                    │
│                         └────┬────┘                                   │
│                              │                                         │
│                              ▼                                         │
│                         ┌─────────┐                                   │
│                         │  Agent  │── runs in gondolin VM session           │
│                         │  runs   │── reads PR comments as context    │
│                         │         │── writes updated asset             │
│                         └────┬────┘                                   │
│                              │                                         │
│                              ▼                                         │
│                         ┌─────────┐                                   │
│                         │  Human  │── re-reviews → approve → merge   │
│                         │re-review│                                   │
│                         └─────────┘                                   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Comment Commands

| Command | Effect |
|---------|--------|
| `/sdlc-update <instruction>` | Agent updates asset per instruction |
| `/sdlc-approve` | Approve PR (human still needs to click approve) |
| `/sdlc-reject <reason>` | Reject with feedback to agent |
| `/sdlc-skip <phase>` | Skip a phase (e.g., `/sdlc-skip bdd`) |
| `/sdlc-inject <file-path>` | Human adds file, agent incorporates |
| `/sdlc-regenerate` | Agent regenerates asset from scratch |
| `/sdlc-explain` | Agent explains its decisions |

---

## Full Pipeline Example

### Scenario: Feature "User Authentication"

```bash
# 1. Human opens initial PR with problem statement
gh pr create --title "feat: user authentication" \
  --body "Users need secure login" \
  --label "sdlc"
# → Triggers: sdlc/ost/user-auth branch created
# → Decision agent generates OST

# 2. Agent produces OST, opens PR: sdlc/ost/user-auth → main
# Files: docs/discovery/ost.md, problems.md, solutions.md, assumptions.md

# 3. Product Owner reviews
#    - Comments: "/sdlc-update Add assumption about OAuth providers"
#    - Agent updates OST, commits fix
#    - PO approves

# 4. MERGE: sdlc/ost/user-auth → main
#    → OST materialized
#    → Triggers: sdlc/prd/user-auth branch created
#    → Decision agent generates PRD

# 5. Agent produces PRD, opens PR: sdlc/prd/user-auth → main
#    - PO has their own PRD draft from another tool
#    - PO adds docs/prd/PRD-001-user-auth.md to the PR (manual injection)
#    - PR now has: agent's auto-generated sections + PO's manual sections
#    - PO approves

# 6. MERGE: sdlc/prd/user-auth → main
#    → PRD materialized
#    → Triggers: sdlc/bdd/user-auth branch created
#    → Decision agent generates BDD specs

# 7. Agent produces BDD, opens PR: sdlc/bdd/user-auth → main
#    - QA Lead reviews, approves

# 8. MERGE: sdlc/bdd/user-auth → main
#    → BDD materialized
#    → Triggers: sdllc/impl/user-auth branch created
#    → Coding agent implements

# 9. Agent produces code + ADRs, opens PR: sdlc/impl/user-auth → main
#    - Tech Lead reviews
#    - Comments: "/sdlc-update Add rate limiting to login endpoint"
#    - Coding agent updates code
#    - Tech Lead approves

# 10. MERGE: sdlc/impl/user-auth → main
#     → Code materialized
#     → Triggers: final release PR
#     → Auto-merge to release branch
```

---

## Asset Graph Derivation

The asset graph (`assets/graph.json`) is **derived** from merged branches, not maintained independently:

```json
{
  "derived_from": "git history",
  "generated_at": "2026-10-06T12:00:00Z",
  "nodes": {
    "discovery/ost": {
      "asset_key": "discovery/ost",
      "branch": "sdlc/ost/user-auth",
      "merged_at": "2026-10-06T10:00:00Z",
      "merge_commit": "abc123",
      "files": ["docs/discovery/ost.md"],
      "version": 1,
      "hash": "sha256:...",
      "produced_by": "decision-agent"
    },
    "define/prd": {
      "asset_key": "define/prd",
      "branch": "sdlc/prd/user-auth",
      "merged_at": "2026-10-06T11:00:00Z",
      "merge_commit": "def456",
      "files": ["docs/prd/PRD-001-user-auth.md"],
      "version": 1,
      "hash": "sha256:...",
      "produced_by": "human",  // ← manual injection detected
      "injected_by": "po-alice"
    }
  },
  "edges": [
    {"from": "discovery/ost", "to": "define/prd", "type": "data"},
    {"from": "define/prd", "to": "develop/bdd", "type": "data"}
  ]
}
```

**Sync command:**
```bash
./scripts/asset-sync.sh  # Rebuilds graph.json from git history
```

---

## GitHub Actions Workflows

### Trigger Matrix

| Event | Workflow | Action |
|-------|----------|--------|
| PR labeled `sdlc` | `agentic-sdlc.yml` | Create first phase branch, start agent |
| PR opened (phase branch → main) | `phase-pr.yml` | Run checks, request reviews |
| PR comment `/sdlc-*` | `comment-handler.yml` | Parse command, trigger agent update |
| PR approved + merged | `merge-trigger.yml` | Materialize assets, trigger downstream |
| Push to `sdlc/*` branch | `branch-push.yml` | Update PR, run checks |
| Manual asset added to PR | `merge-trigger.yml` | Detect skip-ahead, adjust triggers |

### Branch Protection

```
main branch:
  - Require PR reviews (CODEOWNERS by path)
  - Require status checks (agent workflows)
  - No direct pushes (agents push to phase branches only)

sdlc/* branches:
  - No protection (agents push freely)
  - Auto-delete after merge
```

---

## Local Simulation

Test the full pipeline locally:

```bash
# Simulate the pipeline
make sdlc-simulate FEATURE=user-auth

# Creates branches, runs agents locally, merges step by step
# Output:
#   ✓ Created sdlc/ost/user-auth
#   ✓ Decision agent generated OST
#   ✓ Simulating PO review... (auto-approve in sim mode)
#   ✓ Merged to main
#   ✓ Triggered sdlc/prd/user-auth
#   ✓ ...

# Manual step-through
make sdlc-step FEATURE=user-auth PHASE=prd

# Human injection simulation
human-agent --output docs/prd/PRD-001.md  # Your own tool
git add docs/prd/PRD-001.md
git commit -m "docs: add human PRD"
make sdlc-merge PHASE=ost  # Merge with skip-ahead detection
```

---

## Summary

| Concept | Git Equivalent | Pipeline Behavior |
|---------|---------------|-------------------|
| Asset | Files on a branch | Materialized on merge |
| Materialization | Merge to main | Triggers downstream branch creation |
| Human review | PR review | Gate before merge |
| Human feedback | PR comments | Agent updates branch |
| Human injection | Manual file add | Skip-ahead if asset exists |
| Skip-ahead | Multi-phase merge | Detect all assets, trigger furthest downstream |
| Audit trail | Git history + audit.jsonl | Full lineage, tamper-evident |
| Agent trigger | GitHub Actions on merge | Create next branch, run agent |
