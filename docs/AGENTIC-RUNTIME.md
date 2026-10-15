# Agentic Runtime Engine — Architecture

> **See also:** [ASSET-MODEL.md](./ASSET-MODEL.md) for the Dagster-style asset-oriented architecture, rules engine, and neurosymbolic composition that underpins this runtime.


Drawbridge evolves from a multi-tenant agent isolation layer into a full **agentic runtime engine** that drives a structured SDLC (Software Development Life Cycle) inside CI/CD pipelines.

## Vision

> Take a PRD from a PR and start implementing it by following a simple SDLC that includes specific agentic and human review steps.

Two agents run in parallel:
- **Decision agent** (orchestrator) — plans, sequences, reviews, decides
- **Coding agent** (implementer) — writes code, tests, documentation

Both run inside isolated gondolin micro-VM sessions. GitHub Actions gates the flow between phases.

---

## Runtime parity contract

One API drives agents everywhere; only the deployment runtime differs:

| | Local dev (sandboxed session) | CI / teams |
|---|---|---|
| API | `make agent-decision` / `make agent-coding` / `make run-agent` — identical | identical |
| Runtime | `AGENT_RUNTIME=session` (default with a session up) | `AGENT_RUNTIME=ephemeral` |
| Key handling | held host-side by the user-booted session; driving session never sees it | runner env secret, injected per ephemeral boot |
| Extra control | human PO gates, `gondolin attach` for live inspection, snapshot rebuilds, interactive review loops | per-run teardown, cacheable snapshot |

Parity means: a sandboxed local session develops the framework with **the
same or higher control** than the CI pipeline pattern — same targets, same
role prompts, same message queue, same audit schema (the audit records the
effective runtime per run for provenance). It does **not** mean always
dogfooding a particular runtime: `AGENT_RUNTIME` selects per invocation
(`auto|session|ephemeral`), and CI simply pins `ephemeral`.

See [ADR-0001](./adr/0001-session-execution-under-sandboxing.md) and
[ADR-0002](./adr/0002-agent-runtime-override.md).

## The Two-Agent Pattern

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         GITHUB ACTIONS PIPELINE                         │
│                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────┐  │
│  │   TRIGGER   │───▶│  DECISION   │───▶│   HUMAN     │───▶│ CODING  │  │
│  │  (PR opened)│    │   AGENT     │    │   REVIEW    │    │  AGENT  │  │
│  │             │    │ (orchestrate)│   │   (gate)    │    │(implement│  │
│  └─────────────┘    └──────┬──────┘    └─────────────┘    └────┬────┘  │
│                            │                                    │        │
│                    ┌───────┴────────┐                  ┌────────┘        │
│                    │ GONDOLIN VM   │                  │ GONDOLIN VM    │
│                    │  ┌──────────┐  │                  │  ┌──────────┐   │
│                    │  │ Decision │  │◀────state───────▶│  │ Coding   │   │
│                    │  │  Agent   │  │   (shared volume)│  │  Agent   │   │
│                    │  │ (Mistral │  │                  │  │(Mistral  │   │
│                    │  │  Large)  │  │                  │  │  Large)  │   │
│                    │  └──────────┘  │                  │  └──────────┘   │
│                    │  Role: plan,   │                  │  Role: code,    │
│                    │  review, gate  │                  │  test, document │
│                    └────────────────┘                  └─────────────────┘
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    SHARED STATE (GitHub artifacts / repo)        │    │
│  │  • OST (Opportunity Solution Tree)  →  docs/discovery/          │    │
│  │  • PRD                              →  docs/prd/                │    │
│  │  • BDD specs                        →  specs/features/          │    │
│  │  • ADRs                             →  docs/adr/               │    │
│  │  • Code                             →  (target repo)            │    │
│  │  • Agent messages                   →  .agentic/messages/       │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Agent Roles

| Aspect | Decision Agent | Coding Agent |
|--------|---------------|--------------|
| **Model** | Strong reasoning (e.g., `mistral/mistral-large-latest`, `anthropic/claude-opus-4-6`) | Fast + capable (e.g., `mistral/codestral-latest`, `anthropic/claude-sonnet-4-5`) |
| **Role** | Orchestrator, planner, reviewer, gatekeeper | Implementer, coder, tester, documenter |
| **Input** | PRD, BDD specs, ADRs, code diffs | BDD specs, PRD context, existing code |
| **Output** | Plans, review comments, approvals, next-step decisions | Code, tests, documentation, PRs |
| **Tools** | Read-only on repo, write to docs/, comment on PRs | Full repo write, run tests, create branches |
| **Sandbox** | Isolated (read-only project mount) | Isolated (read-write project mount) |
| **Triggered by** | Pipeline phase transitions | Decision agent's instructions |

### Communication Protocol

Agents communicate through **structured state files** in the repository (not direct messaging):

```
.agentic/
├── state.json              # Current SDLC phase, status, metadata
├── messages/
│   ├── decision-to-coding/ # Decision agent → Coding agent
│   │   └── 001-task.md     # Numbered task instructions
│   ├── coding-to-decision/ # Coding agent → Decision agent
│   │   └── 001-result.md   # Numbered results/reports
│   └── human-review/       # Human → Decision agent
│       └── 001-feedback.md # Review feedback
├── decisions/              # Decision agent's logged decisions
│   └── 001-why-this-approach.md
└── reviews/                # Review records
    └── 001-prd-review.md
```

**Message format** (markdown with YAML frontmatter):

```markdown
---
from: decision-agent
to: coding-agent
phase: implementation
task_id: 001
priority: high
---

# Task: Implement user authentication

## Context
[...]

## Requirements
- [ ] REQ-001: Users can sign up with email
- [ ] REQ-002: Users can log in

## BDD Spec
```gherkin
Feature: User Authentication
  Scenario: Successful login
    ...
```

## Acceptance Criteria
- [ ] All tests pass
- [ ] Code coverage > 80%
- [ ] ADR recorded for auth method choice

## Constraints
- Use existing User model
- Follow existing patterns in src/auth/
```

---

## SDLC State Machine

```
                    ┌─────────────┐
    PR opened ─────▶│  DISCOVERY  │◀────────────────────────┐
    (with PRD       │  (OST build)│                         │
     draft)         └──────┬──────┘                         │
                           │                                │
                    ┌──────┴──────┐                         │
                    │  DECISION   │                         │
                    │  AGENT:     │                         │
                    │  validate   │                         │
                    │  OST        │                         │
                    └──────┬──────┘                         │
                           │                                │
                    ┌──────┴──────┐                         │
                    │    HUMAN    │───── reject ────────────┘
                    │   REVIEW    │      (back to discovery)
                    │  (Product    │
                    │   Owner)    │
                    └──────┬──────┘
                           │ approve
                    ┌──────┴──────┐
                    │  DECISION   │
                    │  AGENT:     │
                    │  generate   │
                    │  PRD        │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │    HUMAN    │───── reject ────────────┐
                    │   REVIEW    │                         │
                    │  (Product    │◀────────────────────────┘
                    │   Owner)    │      (back to discovery)
                    └──────┬──────┘
                           │ approve
                    ┌──────┴──────┐
                    │  DECISION   │
                    │  AGENT:     │
                    │  generate   │
                    │  BDD specs  │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │    HUMAN    │───── reject ────────────┐
                    │   REVIEW    │                         │
                    │  (QA Lead)  │◀────────────────────────┘
                    └──────┬──────┘      (back to PRD gen)
                           │ approve
                    ┌──────┴──────┐
                    │  CODING     │◀───────────────────────┐
                    │  AGENT:     │                         │
                    │  implement  │                         │
                    │  features   │                         │
                    └──────┬──────┘                         │
                           │                                │
                    ┌──────┴──────┐                         │
                    │  DECISION   │                         │
                    │  AGENT:     │                         │
                    │  review     │─── changes ─────────────┘
                    │  code       │    requested
                    │             │    (back to coding)
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │    HUMAN    │───── reject ────────────┐
                    │   REVIEW    │                         │
                    │  (Tech Lead)│◀────────────────────────┘
                    └──────┬──────┘      (back to coding)
                           │ approve
                    ┌──────┴──────┐
                    │  DECISION   │
                    │  AGENT:     │
                    │  record ADR │
                    │  merge PR   │
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │   MERGE     │
                    │  (automated)│
                    └─────────────┘
```

### Phase Definitions

| Phase | Agent | Human Gate | Input | Output |
|-------|-------|-----------|-------|--------|
| **Discovery** | Decision | Product Owner | Stakeholder input, problems | OST (Opportunity Solution Tree) |
| **PRD** | Decision | Product Owner | OST, selected solution | PRD document |
| **BDD Specs** | Decision | QA Lead | PRD, assumptions | Gherkin feature files |
| **Implementation** | Coding | Tech Lead | BDD specs, PRD context | Code, tests, docs |
| **Code Review** | Decision | Tech Lead | Code diff, ADR drafts | Approval or change requests |
| **Merge** | — (automated) | — | Approved PR | Merged to main |

---

## GitHub Actions Integration

### Workflow Structure

```
.github/workflows/
├── agentic-sdlc.yml          # Main orchestrator workflow
├── phase-discovery.yml       # Discovery phase (decision agent)
├── phase-prd.yml             # PRD generation (decision agent)
├── phase-bdd.yml             # BDD spec generation (decision agent)
├── phase-implement.yml       # Implementation (coding agent)
├── phase-review.yml          # Code review (decision agent + human)
├── human-review.yml          # Human review gate (reusable)
└── parallel-agents.yml       # Run decision + coding agents in parallel
```

### Gated Reviews

Each phase has a **required reviewer** based on team role:

```yaml
# .github/CODEOWNERS
/docs/discovery/**     @product-team
/docs/prd/**           @product-team
/specs/**              @qa-team
/docs/adr/**           @architecture-team
/src/**                @engineering-team
```

```yaml
# Branch protection rules (via GitHub API)
# - Require PR reviews from CODEOWNERS
# - Specific reviewers per path
# - Status checks must pass (agent workflows)
```

### Parallel Agent Execution

```yaml
# .github/workflows/parallel-agents.yml
jobs:
  decision-agent:
    runs-on: [self-hosted, gondolin]  # runner with gondolin + pi + snapshot
    steps:
      - uses: actions/checkout@v4
      - name: Run decision agent in an ephemeral gondolin VM
        run: |
          ./scripts/agent-pi.sh decision \
            --phase prd \
            --task 'Generate PRD from docs/discovery/ost.md'

  coding-agent:
    runs-on: [self-hosted, gondolin]
    needs: decision-agent  # or run in parallel with message passing
    steps:
      - uses: actions/checkout@v4
      - name: Run coding agent in an ephemeral gondolin VM
        run: |
          ./scripts/agent-pi.sh coding \
            --task .agentic/messages/decision-to-coding/001-task.md
```

---

## Drawbridge Integration

### Local Development (drawbridge)

```bash
# Set up decision and coding agents
make client CLIENT=agentic PROVIDER=mistral NAME="Agentic Runtime"

# Run decision agent locally
make run CLIENT=agentic PROJECT=. ARGS="-- --role decision --phase prd"

# Run coding agent locally  
make run CLIENT=agentic PROJECT=. ARGS="-- --role coding --task .agentic/messages/001.md"
```

### CI/CD (GitHub Actions)

```yaml
# Self-hosted runner with gondolin + pi installed and the
# pi-sandbox snapshot cached (~/code/gondolin-pi/snapshots/)

- name: Run decision agent
  run: |
    ./scripts/agent-pi.sh decision --phase prd \
      --task 'Generate PRD from the approved OST'
```

### Profile Mapping

| Context | Profile | Secrets | Permissions |
|---------|---------|---------|-------------|
| Local dev | decision agent (SDLC VM session) | Personal API keys | Read-write on project |
| Local dev | coding agent (SDLC VM session) | Personal API keys | Read-write on project |
| CI/CD | decision agent (ephemeral VM boot) | `GITHUB_TOKEN`, model API key | Read on repo, write to docs/ |
| CI/CD | coding agent (ephemeral VM boot) | `GITHUB_TOKEN`, model API key | Full repo write |

---

## Triple Diamond → SDLC Mapping

Your SDLC is based on the **Triple Diamond** / **Opportunity Solution Tree (OST)** approach:

```
DISCOVER          DEFINE            DEVELOP           DELIVER
  ◇───◇           ◇───◇             ◇───◇            ◇───◇
  │   │           │   │             │   │            │   │
  ▼   ▼           ▼   ▼             ▼   ▼            ▼   ▼

Problems    →   Solutions     →   PRD          →   BDD Specs
(continuous     (from OST)        (from PRD +         (from PRD +
discovery)                         assumptions)      assumptions)
  │                 │                  │                │
  ▼                 ▼                  ▼                ▼
Assumptions     Assumptions        Implementation   ADRs
(for each       (validated          (coding agent)    (tradeoffs
solution)       in PRD)                              logged)
```

| OST Element | SDLC Artifact | Generated By | Reviewed By |
|-------------|---------------|--------------|-------------|
| Problems list | `docs/discovery/problems.md` | Decision agent | Product Owner |
| Solutions list | `docs/discovery/solutions.md` | Decision agent | Product Owner |
| Assumptions | `docs/discovery/assumptions.md` | Decision agent | Product Owner |
| Selected solution | `docs/discovery/ost.md` | Decision agent | Product Owner |
| PRD | `docs/prd/PRD-001.md` | Decision agent | Product Owner |
| BDD specs | `specs/features/*.feature` | Decision agent | QA Lead |
| Implementation | Code + tests | Coding agent | Tech Lead |
| ADRs | `docs/adr/ADR-001-*.md` | Decision agent | Tech Lead |

---

## Next Steps

1. **Templates** — PRD, BDD, ADR, OST templates (`templates/sdlc/`)
2. **Workflows** — GitHub Actions workflow templates (`.github/workflows/`)
3. **Scripts** — Agent orchestration scripts (`scripts/agentic/`)
4. **Role prompts** — Decision and coding agent prompts (templates/sdlc/agents/)
