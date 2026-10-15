# GitHub Actions Gating Strategy

How drawbridge's agentic SDLC maps to GitHub Actions workflows with human review gates.

---

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        GITHUB ACTIONS PIPELINE                           │
│                                                                          │
│  PR opened ──▶ ┌─────────┐ ──▶ ┌─────────┐ ──▶ ┌─────────┐ ──▶ ┌─────┐ │
│  (label:       │ trigger │     │ decision│     │  human  │     │ ... │ │
│   sdlc:discov) │         │     │  agent  │     │  gate   │     │     │ │
│                └─────────┘     │ (OST)   │     │  (PO)   │     │     │ │
│                                └────┬────┘     └────┬────┘     │     │ │
│                                     │ approved      │ reject       │     │ │
│                                     ▼               └──────────────┘     │
│                              ┌─────────┐ ──▶ ┌─────────┐ ──▶ ┌─────┐   │
│                              │ decision│     │  human  │     │ ... │   │
│                              │  agent  │     │  gate   │     │     │   │
│                              │ (PRD)   │     │  (PO)   │     │     │   │
│                              └────┬────┘     └────┬────┘     │     │   │
│                                   │ approved      │ reject         │     │
│                                   ▼               └────────────────┘     │
│                            ┌─────────┐ ──▶ ┌─────────┐ ──▶ ┌─────┐     │
│                            │ decision│     │  human  │     │     │     │
│                            │  agent  │     │  gate   │     │ ... │     │
│                            │ (BDD)   │     │  (QA)   │     │     │     │
│                            └────┬────┘     └────┬────┘     │     │     │
│                                 │ approved      │ reject       │     │
│                                 ▼               └──────────────┘     │
│                          ┌─────────┐ ──▶ ┌─────────┐ ──▶ ┌─────┐   │
│                          │ coding  │     │ decision│     │human│   │
│                          │  agent  │     │  agent  │     │gate │   │
│                          │(impl)   │     │(review) │     │(TL) │   │
│                          └────┬────┘     └────┬────┘     │     │   │
│                               │ approved      │ changes    │     │   │
│                               ▼               └────────────┘     │   │
│                          ┌─────────┐ ──▶ ┌─────────┐              │   │
│                          │  merge  │     │  deploy │              │   │
│                          │(auto)   │     │(staging│              │   │
│                          └─────────┘     │→ prod)  │              │   │
│                                          └─────────┘              │   │
│                                                                  │   │
└──────────────────────────────────────────────────────────────────┴───┘
```

---

## Workflow Files

```
.github/workflows/
├── agentic-sdlc.yml          # Main orchestrator — triggers phase workflows
├── phase-discovery.yml       # Discovery phase (decision agent builds OST)
├── phase-prd.yml             # PRD phase (decision agent writes PRD)
├── phase-bdd.yml             # BDD phase (decision agent writes specs)
├── phase-implement.yml       # Implementation (coding agent codes)
├── phase-review.yml          # Code review (decision agent + human)
├── human-gate.yml            # Reusable human review gate
├── agent-decision.yml        # Reusable decision agent runner
├── agent-coding.yml          # Reusable coding agent runner
└── parallel-agents.yml       # Run both agents in parallel
```

---

## Reusable: Human Review Gate

```yaml
# .github/workflows/human-gate.yml
name: Human Review Gate

on:
  workflow_call:
    inputs:
      phase:
        required: true
        type: string
      reviewer_role:
        required: true
        type: string
      artifacts:
        required: true
        type: string
      pr_number:
        required: false
        type: string
    secrets:
      github_token:
        required: true

jobs:
  request-review:
    runs-on: ubuntu-latest
    outputs:
      approved: ${{ steps.gate.outputs.approved }}
      feedback: ${{ steps.gate.outputs.feedback }}
    steps:
      - name: Request review from role
        uses: actions/github-script@v7
        with:
          github-token: ${{ secrets.github_token }}
          script: |
            const phase = '${{ inputs.phase }}';
            const role = '${{ inputs.reviewer_role }}';
            const artifacts = '${{ inputs.artifacts }}';
            const pr = '${{ inputs.pr_number }}' || context.issue.number;

            // Map role to GitHub usernames
            const reviewers = {
              'product-owner': ['po-alice', 'po-bob'],
              'qa-lead': ['qa-lead-carol'],
              'tech-lead': ['tech-lead-dave', 'staff-eng-eve'],
              'architecture': ['architect-frank'],
              'eng-manager': ['eng-manager-grace']
            };

            const team = reviewers[role] || [];

            // Request reviews
            await github.rest.pulls.requestReviewers({
              owner: context.repo.owner,
              repo: context.repo.repo,
              pull_number: pr,
              reviewers: team
            });

            // Post gate comment
            await github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: pr,
              body: `## 🔒 Human Review Gate: ${phase}

**Reviewer role:** ${role}
**Reviewers:** ${team.map(u => '@' + u).join(', ')}
**Artifacts to review:**
${artifacts.split(',').map(a => `- \`${a}\``).join('\n')}

### Review checklist:
- [ ] Artifacts are complete
- [ ] Aligns with previous phase
- [ ] Assumptions are explicit
- [ ] Ready for next phase

**To approve:** comment \`/approve ${phase}\`
**To request changes:** comment \`/changes ${phase}\` with feedback
**To reject and go back:** comment \`/reject ${phase}\``
            `.trim()
            });

      - name: Wait for approval
        id: gate
        uses: actions/github-script@v7
        with:
          github-token: ${{ secrets.github_token }}
          script: |
            // Poll for approval comment or PR review
            // In practice, use a webhook or status check
            // This is a simplified placeholder
            const pr = '${{ inputs.pr_number }}' || context.issue.number;

            const reviews = await github.rest.pulls.listReviews({
              owner: context.repo.owner,
              repo: context.repo.repo,
              pull_number: pr
            });

            const approved = reviews.data.some(r =>
              r.state === 'APPROVED' &&
              ['po-alice', 'po-bob', 'qa-lead-carol', 'tech-lead-dave'].includes(r.user.login)
            );

            core.setOutput('approved', approved ? 'true' : 'false');
            core.setOutput('feedback', '');
```

---

## Reusable: Decision Agent Runner

```yaml
# .github/workflows/agent-decision.yml
name: Decision Agent

on:
  workflow_call:
    inputs:
      phase:
        required: true
        type: string
      task:
        required: true
        type: string
      model:
        required: false
        type: string
        default: 'mistral/mistral-large-latest'
    secrets:
      model_api_key:
        required: true
      github_token:
        required: true

jobs:
  run-decision-agent:
    runs-on: [self-hosted, gondolin]  # runner with gondolin + pi + snapshot
    steps:
      - uses: actions/checkout@v4

      - name: Run decision agent in ephemeral gondolin VM
        env:
          MISTRAL_API_KEY: ${{ secrets.model_api_key }}
        run: |
          ./scripts/agent-pi.sh decision \
            --phase ${{ inputs.phase }} \
            --task '${{ inputs.task }}'

      - name: Upload agent artifacts
        uses: actions/upload-artifact@v4
        with:
          name: decision-agent-${{ inputs.phase }}
          path: |
            .agentic/
            docs/discovery/
            docs/prd/
            specs/
            docs/adr/
```

---

## Reusable: Coding Agent Runner

```yaml
# .github/workflows/agent-coding.yml
name: Coding Agent

on:
  workflow_call:
    inputs:
      task_file:
        required: true
        type: string
      branch:
        required: false
        type: string
        default: ${{ github.head_ref }}
      model:
        required: false
        type: string
        default: 'mistral/codestral-latest'
    secrets:
      model_api_key:
        required: true
      github_token:
        required: true

jobs:
  run-coding-agent:
    runs-on: [self-hosted, gondolin]
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ inputs.branch }}
          token: ${{ secrets.github_token }}

      - name: Run coding agent in ephemeral gondolin VM
        env:
          MISTRAL_API_KEY: ${{ secrets.model_api_key }}
        run: |
          ./scripts/agent-pi.sh coding \
            --task '${{ inputs.task_file }}'

      - name: Push changes
        run: |
          cd ${{ github.workspace }}
          git config user.name "coding-agent"
          git config user.email "coding-agent@agentic.dev"
          git add -A
          git commit -m "feat: agentic implementation

Task: ${{ inputs.task_file }}
Phase: implementation
Agent: coding-agent
Model: ${{ inputs.model }}" || echo "No changes to commit"
          git push origin ${{ inputs.branch }}
```

---

## Phase Workflows

### Discovery Phase

```yaml
# .github/workflows/phase-discovery.yml
name: Phase — Discovery (OST)

on:
  workflow_call:
    secrets:
      model_api_key:
        required: true
      github_token:
        required: true

jobs:
  build-ost:
    uses: ./.github/workflows/agent-decision.yml
    with:
      phase: discovery
      task: |
        Build an Opportunity Solution Tree from:
        - Stakeholder input in this PR description
        - Comments on this PR
        - Linked issues
        Output: docs/discovery/ost.md + supporting files
    secrets:
      model_api_key: ${{ secrets.model_api_key }}
      github_token: ${{ secrets.github_token }}

  human-gate:
    needs: build-ost
    uses: ./.github/workflows/human-gate.yml
    with:
      phase: discovery
      reviewer_role: product-owner
      artifacts: 'docs/discovery/problems.md,docs/discovery/solutions.md,docs/discovery/assumptions.md,docs/discovery/ost.md'
    secrets:
      github_token: ${{ secrets.github_token }}

  trigger-next:
    needs: human-gate
    if: needs.human-gate.outputs.approved == 'true'
    uses: ./.github/workflows/phase-prd.yml
    secrets:
      model_api_key: ${{ secrets.model_api_key }}
      github_token: ${{ secrets.github_token }}
```

### PRD Phase

```yaml
# .github/workflows/phase-prd.yml
name: Phase — PRD

on:
  workflow_call:
    secrets:
      model_api_key:
        required: true
      github_token:
        required: true

jobs:
  write-prd:
    uses: ./.github/workflows/agent-decision.yml
    with:
      phase: prd
      task: |
        Generate a PRD from the approved OST:
        - Read docs/discovery/ost.md
        - Select the highest-priority opportunity + solution
        - Generate docs/prd/PRD-NNN-<slug>.md
        - Include all assumptions from OST
    secrets:
      model_api_key: ${{ secrets.model_api_key }}
      github_token: ${{ secrets.github_token }}

  human-gate:
    needs: write-prd
    uses: ./.github/workflows/human-gate.yml
    with:
      phase: prd
      reviewer_role: product-owner
      artifacts: 'docs/prd/'
    secrets:
      github_token: ${{ secrets.github_token }}

  trigger-next:
    needs: human-gate
    if: needs.human-gate.outputs.approved == 'true'
    uses: ./.github/workflows/phase-bdd.yml
    secrets:
      model_api_key: ${{ secrets.model_api_key }}
      github_token: ${{ secrets.github_token }}
```

### BDD Phase

```yaml
# .github/workflows/phase-bdd.yml
name: Phase — BDD Specs

on:
  workflow_call:
    secrets:
      model_api_key:
        required: true
      github_token:
        required: true

jobs:
  write-specs:
    uses: ./.github/workflows/agent-decision.yml
    with:
      phase: bdd
      task: |
        Generate BDD specs from the approved PRD:
        - Read docs/prd/PRD-*.md
        - Map REQ-NNN to Gherkin scenarios
        - Tag scenarios with @PRD, @REQ, @assumption
        - Output specs/features/*.feature
    secrets:
      model_api_key: ${{ secrets.model_api_key }}
      github_token: ${{ secrets.github_token }}

  human-gate:
    needs: write-specs
    uses: ./.github/workflows/human-gate.yml
    with:
      phase: bdd
      reviewer_role: qa-lead
      artifacts: 'specs/'
    secrets:
      github_token: ${{ secrets.github_token }}

  trigger-next:
    needs: human-gate
    if: needs.human-gate.outputs.approved == 'true'
    uses: ./.github/workflows/phase-implement.yml
    secrets:
      model_api_key: ${{ secrets.model_api_key }}
      github_token: ${{ secrets.github_token }}
```

### Implementation Phase

```yaml
# .github/workflows/phase-implement.yml
name: Phase — Implementation

on:
  workflow_call:
    secrets:
      model_api_key:
        required: true
      github_token:
        required: true

jobs:
  implement:
    uses: ./.github/workflows/agent-coding.yml
    with:
      task_file: '.agentic/messages/decision-to-coding/001-task.md'
    secrets:
      model_api_key: ${{ secrets.model_api_key }}
      github_token: ${{ secrets.github_token }}

  review-code:
    needs: implement
    uses: ./.github/workflows/agent-decision.yml
    with:
      phase: review
      task: |
        Review the coding agent's implementation:
        - Run BDD tests
        - Check code quality
        - Verify ADRs are recorded
        - Approve or request changes
    secrets:
      model_api_key: ${{ secrets.model_api_key }}
      github_token: ${{ secrets.github_token }}

  human-gate:
    needs: review-code
    uses: ./.github/workflows/human-gate.yml
    with:
      phase: review
      reviewer_role: tech-lead
      artifacts: 'src/,tests/,docs/adr/'
      pr_number: ${{ github.event.number }}
    secrets:
      github_token: ${{ secrets.github_token }}

  merge:
    needs: human-gate
    if: needs.human-gate.outputs.approved == 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/github-script@v7
        with:
          github-token: ${{ secrets.github_token }}
          script: |
            await github.rest.pulls.merge({
              owner: context.repo.owner,
              repo: context.repo.repo,
              pull_number: context.issue.number,
              merge_method: 'squash'
            });
```

---

## Main Orchestrator

```yaml
# .github/workflows/agentic-sdlc.yml
name: Agentic SDLC

on:
  pull_request:
    types: [opened, synchronize]
    branches: [main]
  pull_request:
    types: [labeled]

jobs:
  check-labels:
    runs-on: ubuntu-latest
    outputs:
      start-sdlc: ${{ steps.check.outputs.start }}
    steps:
      - id: check
        run: |
          if gh pr view ${{ github.event.number }} --json labels | jq -e '.labels[].name' | grep -q 'sdlc'; then
            echo "start=true" >> $GITHUB_OUTPUT
          fi
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

  start:
    needs: check-labels
    if: needs.check-labels.outputs.start-sdlc == 'true'
    uses: ./.github/workflows/phase-discovery.yml
    secrets:
      model_api_key: ${{ secrets.MISTRAL_API_KEY }}
      github_token: ${{ secrets.GITHUB_TOKEN }}
```

---

## CODEOWNERS

```python
# .github/CODEOWNERS

# Discovery artifacts — Product Owners
/docs/discovery/          @po-alice @po-bob

# PRDs — Product Owners
/docs/prd/                @po-alice @po-bob

# BDD specs — QA Lead
/specs/                   @qa-lead-carol

# Architecture Decision Records — Architecture team
/docs/adr/                @architect-frank

# Source code — Engineering
/src/                     @tech-lead-dave @staff-eng-eve
/tests/                   @tech-lead-dave @staff-eng-eve

# Agentic state — Decision agent manages, Tech Lead reviews
/.agentic/                @tech-lead-dave

# Workflows — DevOps
/.github/workflows/       @devops-team
```

---

## Branch Protection

Configure via GitHub API or UI:

```bash
# Require status checks
 gh api repos/{owner}/{repo}/branches/main/protection \
  --method PUT \
  --field required_status_checks='{"strict":true,"contexts":["agentic-sdlc"]}' \
  --field enforce_admins=true \
  --field required_pull_request_reviews='{"required_approving_review_count":1,"require_code_owner_reviews":true}' \
  --field restrictions=null
```

---

## Triggering the Pipeline

```bash
# Open a PR with the SDLC label
gh pr create --title "feat: user authentication" --body "..." --label "sdlc"

# Or add label to existing PR
gh pr edit 42 --add-label "sdlc"

# Monitor progress
gh run list --workflow=agentic-sdlc.yml
gh run view <run-id> --log
```

---

## Agent Runtime for CI

Agents run in ephemeral gondolin VMs on self-hosted runners
(see `.github/workflows/agent-decision.yml` and `agent-coding.yml`):

```yaml
# Runner prerequisites
#   - gondolin + QEMU, pi (npm globals)
#   - gondolin-pi template + snapshot (~/code/gondolin-pi)
#   - MISTRAL_API_KEY / MODEL_API_KEY repo secrets

- name: Run decision agent in ephemeral gondolin VM
  env:
    MISTRAL_API_KEY: ${{ secrets.model_api_key }}
  run: |
    ./scripts/agent-pi.sh decision --phase prd --task '...'

- name: Run coding agent in ephemeral gondolin VM
  env:
    MISTRAL_API_KEY: ${{ secrets.model_api_key }}
  run: |
    ./scripts/agent-pi.sh coding --task .agentic/messages/decision-to-coding/current-task.md
```

The API key is passed to the VM as a gondolin **host-secret**: the guest
holds only a placeholder and the host proxy substitutes the real value into
outbound requests to allowed hosts. Nothing is stored on the runner between
runs — ephemeral boots from the cached snapshot (see
[ADR-0001](./adr/0001-session-execution-under-sandboxing.md)).
