# drawbridge — Agentic SDLC + multi-tenant agent isolation on Gondolin micro-VMs

An agent trio — **planner** (reasoning and decomposition), **decider**
(typed routing/gating decisions), **coder** (specs, code, data) — runs your
SDLC (discovery → PRD → BDD → implementation → review) inside isolated
**gondolin micro-VMs**: web search and a full skill suite baked in, every
run audited, secrets never leaving the host.
**Operational** — the pipeline is proven end-to-end (discovery runs in ~76s,
audited, zero secret exposure).

Docs: [Architecture](docs/ARCHITECTURE.md) · [ADR-0001](docs/adr/0001-session-execution-under-sandboxing.md) ·
[SDLC](docs/SDLC.md) · Lineage: [vision](docs/vision.md) ←
[clientsort-docs-archive](https://github.com/chartpath/clientsort-docs-archive) (full history imported)

## Quick start

Prerequisites: `gondolin` + QEMU, `pi` (npm globals), Mistral credential via
`pi auth`, and the gondolin-pi VM template with a built snapshot.

```bash
# 1. Boot the agent VM session — from YOUR terminal, leave it open
make vm-up                # this terminal hosts the session

# 2. Run SDLC phases — from any terminal (or a sandboxed agent session)
make agent-decision PHASE=discovery TASK="Bootstrap the OST for <feature>"
make agent-decision PHASE=prd        TASK="Generate PRD-007 from the OST"
make agent-decision PHASE=bdd        TASK="Write specs from PRD-007"
make agent-coding   TASK=.agentic/messages/decision-to-coding/001-task.md

# 3. Lifecycle
make vm-status             # session state (safe from sandboxed sessions)
make vm-down               # stop the session (from your terminal)
```

Agents work directly on the repo (mounted at `/workspace` in the VM), so
artifacts land on the host. Every run — success or failure — is appended to
`.agentic/audit.jsonl` with role, phase, model, runtime, exit code, duration.

## Why OST-first

Most AI-SDLC frameworks start at **solution definition** — PRDs describe
*what to build* before asking whether it's the right problem. Drawbridge
operates one layer up: the [OST](docs/discovery/ost.md) is a live strategic
asset, continuously fed by stakeholder-facing discovery upstream of PRDs.
The loop spirals — opportunities → solutions with **testable assumptions** →
lean production slices validating them, **ordered by business value rank**
(cheapest assumption-killers first) → evidence back into the tree. Discovery
never closes. It's the layering Jira Product Discovery added above delivery
workflows — but agentic, auditable, and versioned in the asset graph.

## Isolation model

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
│  Never mounted into the VM:  ~/.ssh ❌  ~/.aws ❌  other projects ❌    │
└───────────────────────────────────────────────────────────────────────┘
```

| Guarantee | Mechanism |
|---|---|
| **Secrets** | `--host-secret`: guest sees a placeholder; the host proxy substitutes the real value only into outbound requests to allowed hosts — usable, never readable |
| **Project** | Only explicitly `--mount-hostfs`-ed directories exist in the guest |
| **Network** | Synthetic DNS + explicit domain allow-list; everything else blocked |
| **Process** | Hypervisor isolation (QEMU/krun micro-VM), snapshot-based images |
| **Orchestration** | The driving session runs under pi-sandbox; unix-socket IPC is the only bridge |

## Agents — planner, decider, coder

Three node types; one model for now (`zai-glm-5-3`), tuned per purpose:

| Node | Purpose | Model profile | Today's runtime |
|---|---|---|---|
| **Planner** | OST, PRD, BDD, review, ADRs — logical decomposition over code generation | big model @ **max thinking** (GPQA / tau-bench class) | the `decision` role (`make agent-decision`) |
| **Decider** | routing, gating, classification — typed JSON-schema decisions returning choice + confidence + probabilities; the classifier-replacement layer feeding the self-improvement loop | small decision models (GLiDE / Jev class) | deterministic rules + jq; model layer is roadmap |
| **Coder** | specs, code, data, tests — generation over reasoning | big model @ low thinking (SWE-bench Verified / Terminal-Bench class) | the `coding` role (`make agent-coding`) |

Role prompts: `templates/sdlc/agents/`. Per-run overrides:
`AGENT_MODEL`, `AGENT_THINKING`, `AGENT_RUNTIME=auto|session|ephemeral`.

## Sharp edges (ADR-0001)

1. Never run `gondolin list` / id-based `exec` from a sandboxed session — the
   pid-based session GC misfires under the sandbox and deletes live sessions'
   registry files. The scripts use recorded socket paths instead.
2. `gondolin exec` doesn't inherit the boot env — the secret placeholder is
   stashed at boot (`/root/.session-env/`) and sourced by exec'd agents.
3. The session lives as long as the terminal hosting `make vm-up` — launchd
   hosting for unattended/CI operation is roadmap.

## Roadmap

- **Multi-tenant client sessions**: per-client manifests, host-secrets, and
  egress policies (`pi-<client>-<provider>` naming)
- **Unattended hosting**: launchd-supervised sessions
- **CI wiring**: GitHub Actions phases on ephemeral VM boots (cached snapshot)
- **Decider model layer**: promote routing/gating/classification from
  deterministic rules to typed decision models (JSON schema in → choice +
  confidence + probabilities out)
- **Self-improvement loop**: distill metrics from the audit trail into
  *proposed deterministic inputs* for the decision models — new routing rules,
  gate thresholds, classification schemas — human-critic-gated, versioned in
  the asset graph (PRD-005's neurosymbolic bridge, operationalized)

## Project structure

```
drawbridge/
├── Makefile                  # SDLC + session lifecycle targets
├── scripts/
│   ├── vm-session.sh         # SDLC VM session lifecycle (up/status/exec/down)
│   ├── agent-pi.sh            # decision/coding agent runner (audited)
│   └── sdlc-branch.sh         # git-native phase branches
├── templates/sdlc/           # OST/PRD/BDD/ADR templates + agent role prompts
├── docs/                     # architecture, SDLC, PRDs, ADRs, vision
│   └── adr/                  # decision records (start with ADR-0001)
└── .agentic/                 # audit trail, agent message queues
```
