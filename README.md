# drawbridge — Agentic SDLC + multi-tenant agent isolation on Gondolin micro-VMs

Run the SDLC (discovery → PRD → BDD → implementation → review) with two AI
agents — a **decision agent** (plans, reviews) and a **coding agent**
(implements) — each executing inside isolated **gondolin micro-VMs** with
DuckDuckGo web search and a full skill suite baked in. Every run is audited;
secrets never leave the host.

> **Architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) ·
> Key decision: [ADR-0001](docs/adr/0001-session-execution-under-sandboxing.md)
>
> **Lineage:** drawbridge continues the neurosymbolic architecture explored as
> clientsort/Reyearn (2020–2024). Its full git history is imported below and
> the vision document lives at [docs/vision.md](docs/vision.md); the original
> repo remains the canonical record:
> [chartpath/clientsort-docs-archive](https://github.com/chartpath/clientsort-docs-archive).

## Why OST-first

Most AI-SDLC and spec-driven frameworks start at **solution definition**:
PRDs and specs describe *what to build* before anything asks whether it is
the right problem to solve. Drawbridge operates one layer up: the
[OST](docs/discovery/ost.md) is a live strategic asset, and the agents
continuously pick up the direct output of stakeholder-facing discovery work
that happens upstream of PRDs.

The loop spirals: opportunities are evaluated strategically → solutions are
proposed with **testable assumptions** → lean production slices validate the
assumptions, ordered by business value rank (cheapest assumption-killers
first) → evidence flows back into the tree. Discovery is continuous, not a
one-time gate — the same layering Jira Product Discovery added above
delivery workflows, but agentic, auditable, and versioned in the asset
graph.

## Status

**Operational.** The full pipeline is proven end-to-end: the discovery phase
runs decision agents in a VM session (76s, audited, zero secret exposure) and
writes OST/PRD/BDD assets into `docs/` and `specs/`.

## Quick start

Prerequisites (host):

- `gondolin` (`npm install -g @earendil-works/gondolin` + QEMU)
- `pi` (`npm install -g @earendil-works/pi-coding-agent`), Mistral credential
  stored via `pi auth` (or `MISTRAL_API_KEY` exported in your shell)
- The gondolin-pi VM template at `~/code/gondolin-pi` (snapshot built)

```bash
# 1. Boot the SDLC VM session — from YOUR terminal, leave it open
make vm-up                # guest prompt appears; this terminal hosts the session

# 2. (any terminal / agent session) run SDLC phases
make agent-decision PHASE=discovery TASK="Bootstrap the OST for <feature>"
make agent-decision PHASE=prd        TASK="Generate PRD-007 from the OST"
make agent-decision PHASE=bdd        TASK="Write specs from PRD-007"
make agent-coding   TASK=.agentic/messages/decision-to-coding/001-task.md

# or generically
make run-agent AGENT=decision PHASE=prd TASK="..."

# 3. Lifecycle
make vm-status             # session state (safe from sandboxed sessions)
make vm-down              # stop the session (from your terminal)
```

Agents read/write the repo directly: the project is mounted at `/workspace`
inside the VM, so artifacts land on the host. Every run — success or failure —
is appended to `.agentic/audit.jsonl` (role, phase, model, runtime, exit code,
duration).

## The isolation model

```
┌──────────────────────────── YOUR MACHINE ─────────────────────────────┐
│                                                                       │
│  Your terminal                 Sandboxed pi session (host)           │
│  ┌──────────────────┐          ┌──────────────────────────────┐      │
│  │ make vm-up       │          │ drives agents over session   │      │
│  │ (session host)   │          │ IPC — socket PATH only       │      │
│  │ holds the real   │          │ (never sees secret values)  │      │
│  │ API key env-var  │          └──────────────┬───────────────┘      │
│  └────────┬─────────┘                          │ exec                  │
│           │                                    ▼                      │
│           │              ┌──────────────────────────────────────┐     │
│           └─────────────►│  GONDOLIN VM SESSION (from snapshot) │     │
│              host-secret │  pi + ddgr + 88 skills baked in      │     │
│              (real key   │  sees MISTRAL_API_KEY = <placeholder>│     │
│               held host-  │  /workspace = this repo (rw)        │     │
│               side only) │  egress: explicit allow-list only     │     │
│                          └──────────────────────────────────────┘     │
│                                                                       │
│  Host filesystem (NOT mounted into the VM unless explicit):           │
│  ~/.ssh ❌  ~/.aws ❌  other projects ❌  host keychains ❌             │
└───────────────────────────────────────────────────────────────────────┘
```

| Guarantee | Mechanism (gondolin) |
|---|---|
| **Secrets** | `--host-secret`: guest env holds a placeholder; the host proxy substitutes the real value only into outbound requests to allowed hosts. Usable, never readable. |
| **Project** | Only explicitly `--mount-hostfs`-ed directories exist in the guest |
| **Network** | Programmable stack: synthetic DNS + domain allow-list; anything else blocked |
| **Process** | Hypervisor isolation (QEMU/krun micro-VM) |
| **State** | Snapshot-based guest images; sessions are ephemeral-per-boot |
| **Host agent sandboxing** | The orchestrating pi session runs under pi-sandbox; session IPC (unix socket) is the only bridge |

## The two-agent SDLC

- **Decision agent** (`zai-glm-5-3` @ max thinking): discovery (OST), PRD, BDD,
  review. Writes docs/specs assets + coding-agent task queue messages.
- **Coding agent** (`zai-glm-5-3` @ low thinking): implements tasks from
  `.agentic/messages/decision-to-coding/` with TDD, reports back via
  `coding-to-decision/`.

Role prompts: `templates/sdlc/agents/`. Full lifecycle:
[docs/SDLC.md](docs/SDLC.md) · Runtime: [docs/AGENTIC-RUNTIME.md](docs/AGENTIC-RUNTIME.md) ·
Gates: [docs/GITHUB-GATES.md](docs/GITHUB-GATES.md) ·
Assets: [docs/ASSET-MODEL.md](docs/ASSET-MODEL.md)

## Known sharp edges (see ADR-0001)

1. **Never** run `gondolin list` / `exec --sock <session-id>` from a
   sandboxed session — the pid-based session GC misfires under the sandbox
   and deletes live sessions' registry files. The scripts use recorded
   socket paths (`.agentic/vm-session.json`) instead.
2. `gondolin exec` commands don't inherit the boot env — the secret
   placeholder is stashed at `/root/.session-env/` at boot and sourced by
   exec'd agents.
3. The session lives as long as the terminal hosting `make vm-up`. For
   unattended/CI operation, host the session via launchd (future work).

## Roadmap (on the new primitives)

- Multi-tenant client management: per-client gondolin sessions, per-client
  host-secrets and egress policies. Session naming: `pi-<client>-<provider>`;
  credential naming: `<client>-<provider>-<credential>`.
- `launchd`-hosted persistent sessions for unattended operation.
- GitHub Actions wiring: CI runs agents in ephemeral gondolin VMs
  (`--resume` from the cached snapshot).

## Project structure

```
drawbridge/
├── Makefile                  # SDLC + session lifecycle targets
├── scripts/
│   ├── vm-session.sh         # SDLC VM session lifecycle (up/status/exec/down)
│   ├── agent-pi.sh           # decision/coding agent runner (audited)
│   └── sdlc-branch.sh        # git-native phase branches
├── templates/sdlc/           # OST/PRD/BDD/ADR templates + agent role prompts
├── docs/                     # architecture, SDLC, PRDs, ADRs
│   └── adr/                  # decision records (start with ADR-0001)
└── .agentic/                 # audit trail, agent message queues
```
