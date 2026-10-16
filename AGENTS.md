# AGENTS.md — redyarn

Instructions for AI coding agents working in this repo. Read the
[README.md](README.md) for the product pitch and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the isolation model — this file covers how to *operate* in the repo
without breaking it.

## What this repo is

Agentic SDLC infrastructure: a two-agent pipeline (**decision** agent plans
and reviews, **coding** agent implements) that runs inside isolated gondolin
micro-VMs. The repo is orchestration code, not an application:

- `Makefile` — the entry point; prefer make targets over calling scripts directly
- `scripts/*.sh` — session lifecycle, agent runner, git-native pipeline, asset sync (bash)
- `templates/sdlc/` — OST/PRD/BDD/ADR templates + agent role prompts (`agents/decision.md`, `agents/coding.md`)
- `docs/` — architecture + SDLC docs, discovery assets, PRDs, ADRs (heavily cross-referenced — follow links)
- `.github/workflows/` — CI gating workflows (agents in ephemeral gondolin VMs on self-hosted runners)
- `assets/graph.json` — the asset DAG (single source of truth)
- `.agentic/` — audit trail (`audit.jsonl`), agent message queues, machine-local session state

No package manager, no build, no test framework of its own. Tooling deps:
`bash`, `jq`, `python3`, `make`, `gondolin` + `pi` (npm globals), QEMU.

## Critical rules — read before running anything

1. **Never run `gondolin list` or id-based `gondolin exec <session-id>` from
   a sandboxed session.** The pid-based session GC misfires under the
   sandbox (cannot signal foreign processes) and **deletes live sessions'
   registry files**. Only ever use socket-path IPC via the scripts
   (`./scripts/vm-session.sh exec -- <cmd>` reads the recorded path from
   `.agentic/vm-session.json`). Full rationale: [ADR-0001](docs/adr/0001-session-execution-under-sandboxing.md).
2. **Session lifecycle commands belong to the user's terminal.** `make
   vm-up` boots the session in the foreground (it holds the real API key
   host-side); `make vm-down` signals the host process — a sandboxed agent
   cannot do either. Agents attach via IPC only.
3. **Secrets are host-side placeholders.** The guest and any sandboxed
   orchestrator only ever see `MISTRAL_API_KEY=<placeholder>`; the gondolin
   host proxy substitutes the real value into outbound requests. Never log,
   echo, or attempt to read API keys.
4. **`.agentic/audit.jsonl` is append-only.** Only `scripts/agent-pi.sh`
   writes entries (via `jq`). Never hand-edit or truncate it. Query with jq:
   `make audit-trail`.
5. **Decision artifacts are inputs, not outputs.** Never modify
   `docs/prd/`, `docs/discovery/`, `docs/adr/`, or `specs/features/` when
   acting as (or on behalf of) the coding agent. Coding agents report to
   `.agentic/messages/coding-to-decision/<NNN>-result.md`.
6. **VM egress is an explicit allow-list** (api.mistral.ai,
   duckduckgo.com + html/lite, registry.npmjs.org). Don't add network
   features that assume open egress.

## Common commands

```bash
# Session lifecycle (user terminal only for up/down)
make vm-up                     # boot SDLC VM session (foreground, keep open)
make vm-status                 # session state — sandbox-safe
make vm-down                   # stop session (user terminal)

# Agents (exec into the VM session via socket-path IPC; every run audited)
make agent-decision PHASE=discovery|prd|bdd|review [TASK="..."]
make agent-coding   TASK=<repo-relative task file> [BDD=<feature file>]
make run-agent AGENT=decision|coding [PHASE=...] [TASK=...]

# Assets
make asset-init / asset-status / asset-lineage KEY=<key>
make audit-trail

# Git-native pipeline (requires git; check `git rev-parse` first — see below)
make sdlc-new FEATURE=<slug>
make sdlc-branch PHASE=<ost|prd|bdd|impl> FEATURE=<slug>
make sdlc-merge PHASE=<phase> FEATURE=<slug>   # merge with skip-ahead detection
make sdlc-status / sdlc-list / sdlc-inject
```

Phase vocabularies differ by surface: the decision agent uses
`discovery|prd|bdd|review`; branch names use `ost|prd|bdd|impl`
(`sdlc/<phase>/<feature-slug>`). Discovery ↔ ost are the same phase.

## Conventions

### Bash scripts (match `scripts/vm-session.sh` / `agent-pi.sh`)

- `set -euo pipefail`
- Header comment block: purpose, usage, env vars
- Colored helpers: `info/ok/warn/err` (`BLUE/GREEN/YELLOW/RED`, `NC` reset)
- Derive paths via `SCRIPT_DIR`/`PROJECT_DIR` — never hardcode relative paths
- Usage errors print usage and `exit 1`

### Artifact naming & paths

| Artifact | Path | Numbering |
|---|---|---|
| Discovery assets | `docs/discovery/{problems,solutions,assumptions,ost}.md` | — |
| PRDs | `docs/prd/PRD-NNN-<slug>.md` | 3-digit (`PRD-001`) |
| BDD specs | `specs/features/<feature>.feature` (Gherkin) | — |
| ADRs | `docs/adr/NNNN-<slug>.md` | **4-digit** (`0001-`) |
| Agent tasks | `.agentic/messages/decision-to-coding/<NNN>-task.md` | 3-digit, next free |
| Agent results | `.agentic/messages/coding-to-decision/<NNN>-result.md` | 3-digit, next free |

- New artifacts are generated from `templates/sdlc/` — fill every
  `{{PLACEHOLDER}}`. Decision-agent output starts as `status: draft`,
  `version: 0.1`, today's date.
- Gherkin tags link upward: `@PRD-NNN`, `@REQ-NNN`, `@assumption-N`.
- `assets/graph.json` is **derived** from merged branches by
  `scripts/asset-sync.sh` — don't hand-maintain node lineage.

### Docs

ASCII diagrams + tables are the house style. Cross-link liberally; ADRs
record any significant tradeoff (template: `templates/sdlc/adr.md`).

### Agent runtime facts

- Models: decision `mistral-large-4` @ max thinking; coding `mistral-large-4` @ low.
  Per-run overrides: `AGENT_MODEL`, `AGENT_THINKING`. VM template path:
  `GONDOLIN_PI` (default `~/code/gondolin-pi/gondolin-pi.sh`).
- Run modes: preferred `gondolin-pi-session` (long-lived VM session,
  key held host-side); fallback ephemeral `gondolin-pi` boot (needs the key
  in the launching shell or the stored `pi auth` credential).
- Audit entry shape (appended per run, success or failure):
  `{timestamp, type:"agent-run", role, phase, task, model, thinking, runtime, exit_code, duration_s}`.

## Environment quirks (sandboxed pi sessions on this host)

- **git fails on global config**: the sandbox blocks `~/.gitconfig`. Use
  `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git ...`, and
  pass `-c user.name=... -c user.email=...` for commits. Also: this repo
  may not be initialized as a git repo yet — the git-native pipeline
  (`sdlc-branch.sh`, `asset-sync.sh`) requires it; check before promising
  pipeline runs.
- **Network egress** from a sandboxed session is restricted per
  `.pi/sandbox.json` (currently only `earendil-works.github.io`). Web
  search/scraping skills will not work from the sandbox; use the VM's ddgr
  instead (it runs inside the session with its own allow-list).
- **Cross-project paths** (`~/code/gondolin-pi`, `~/.cache/gondolin`) may be
  unreadable from the sandbox — expect prompts or failures when scripts
  probe them; run those commands from the user's terminal or a pi `!` escape.
- Machine-local state is gitignored: `.agentic/tmp/`,
  `.agentic/vm-session.json`, `.agentic/vm-session.log`.

## Documentation index

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Isolation model, session lifecycle, why socket-path-only IPC |
| [docs/SDLC.md](docs/SDLC.md) | Phase-by-phase gates, outputs, review roles |
| [docs/AGENTIC-RUNTIME.md](docs/AGENTIC-RUNTIME.md) | Two-agent pattern, message protocol, state machine, CI mapping |
| [docs/ASSET-MODEL.md](docs/ASSET-MODEL.md) | Asset DAG, rules engine, audit/reification stream |
| [docs/GIT-NATIVE-PIPELINE.md](docs/GIT-NATIVE-PIPELINE.md) | Branches = assets, merges = materializations, skip-ahead rules |
| [docs/GITHUB-GATES.md](docs/GITHUB-GATES.md) | Workflow wiring, CODEOWNERS, branch protection |
| [docs/USE-CASES.md](docs/USE-CASES.md) | Multi-tenant client isolation scenarios |
| [docs/adr/](docs/adr/) | Decision records (start at ADR-0001) |
