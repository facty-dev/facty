# AGENTS.md — Facty

Instructions for AI agents working in this repo. Read the
[README.md](README.md) for the ELI5 pitch and
[ADR-0003](docs/adr/0003-detective-dss-neurosymbolic-core.md) for the
architecture — this file covers how to *operate* in the repo without
breaking it.

## What this repo is

**Facty** (`facty.dev`) — a domain-agnostic abductive decision-support
system (the "detective DSS"). *Evidence in, verdict out.* Evidence in →
ranked hypotheses with confidence → discriminating tests → verdict with a
full reasoning trace. Two halves, never swapping jobs:

- **The brain — the symbolic engine** (`engine/`): forward + backward
  chaining rules engine with a constraint layer. Plain deterministic
  code. Rules beat vibes; every verdict replays without the LLM.
- **The senses — the LLM** (Mistral Large 4): reads messy evidence into
  facts, proposes hypotheses and discriminating tests. Probabilistic:
  great at reading, not at being right.

Domains are **packs** (ontology + rules + constraints) — fraud, incidents,
security findings, contracts. The engine is the same; the pack is the
costume. (Sherlock was a detective, not a doctor.)

The repo is the engine + typed demo cases + the pack factory:

- `engine/` — schemas, the engine + `facty` CLI, typed demo cases
  (attribution / adjudication / causation), codegen
- `scripts/*.sh` — session lifecycle, agent runner, git-native pipeline, asset sync (bash)
- `templates/sdlc/` — pack-factory templates + agent role prompts (`agents/decision.md`, `agents/coding.md`)
- `docs/` — architecture, discovery, PRDs, ADRs (heavily cross-referenced — follow links)
- `.github/workflows/` — CI gating workflows (agents in ephemeral gondolin VMs on self-hosted runners)
- `assets/graph.json` — the asset DAG (single source of truth)
- `.agentic/` — audit trail (`audit.jsonl`), agent message queues, machine-local session state

The SDLC machinery is the **pack factory** — and SDLC management is a
future vertical application of the DSS, not its foundation.

## The artifact model (the common protocol)

Every tool and agent speaks these types. Canonical JSON shapes; one schema,
three projections (git JSON files now, JSONB rows later, codegen TS/Datalog):

| Artifact | Canonical shape | Lives in |
|---|---|---|
| Fact | `{id, type, subject, predicate, value, confidence, source, observedAt}` | `cases/<case>/facts.json` (sensed by the LLM) |
| Rule | `{id, version, pack, when:[conds], then:[actions], salience}` | `cases/<case>/pack/rules.json` |
| Hypothesis | `{id, statement, status, prior, claims:[conds], killer, horse_fate, …}` | `cases/<case>/pack/hypotheses.json` |
| Constraint | `{id, type: eliminate\|support, hypothesis, when:[conds], reason}` | `cases/<case>/pack/constraints.json` |
| Question | `{id, text, slot, mandatory, status, raisedBy, discriminates}` | opened by the engine, filled by the senses |
| Derivation | lineage edge `fact ← rule ← facts` | the trace (engine output) |

Schemas: `engine/schemas/*.schema.json`. Codegen: `engine/emit.py` →
`engine/emit/` (TypeScript types, Datalog).

## Critical rules — read before running anything

1. **The engine owns the verdict.** The LLM senses and proposes; the
   symbolic engine verifies, chains, prunes, and decides. Never put an
   LLM call in the verdict path (LLM-Modulo; ADR-0003 §1). Rules take
   precedence over probabilities.
2. **Never run `gondolin list` or id-based `gondolin exec <session-id>` from
   a sandboxed session.** The pid-based session GC misfires under the
   sandbox (cannot signal foreign processes) and **deletes live sessions'
   registry files**. Only ever use socket-path IPC via the scripts
   (`./scripts/vm-session.sh exec -- <cmd>` reads the recorded path from
   `.agentic/vm-session.json`). Full rationale: [ADR-0001](docs/adr/0001-session-execution-under-sandboxing.md).
3. **Session lifecycle commands belong to the user's terminal.** `make
   vm-up` boots the session in the foreground (it holds the real API key
   host-side); `make vm-down` signals the host process — a sandboxed agent
   cannot do either. Agents attach via IPC only.
4. **Secrets are host-side placeholders.** The guest and any sandboxed
   orchestrator only ever see `MISTRAL_API_KEY=<placeholder>`; the gondolin
   host proxy substitutes the real value into outbound requests. Never log,
   echo, or attempt to read API keys.
5. **`.agentic/audit.jsonl` is append-only.** Only `scripts/agent-pi.sh`
   writes entries (via `jq`). Never hand-edit or truncate it. Query with jq:
   `make audit-trail`.
6. **Decision artifacts are inputs, not outputs.** Never modify
   `docs/prd/`, `docs/discovery/`, `docs/adr/` when acting as the coding
   agent — unless the PO directs a rename or reframe. Coding agents
   report to `.agentic/messages/coding-to-decision/<NNN>-result.md`.
7. **VM egress is an explicit allow-list** (api.mistral.ai,
   registry.npmjs.org). Don't add network features that assume open
   egress — and don't add web-search tooling (ddgr or similar): cases
   handle sensitive data, so nothing leaves the VM except LLM calls.

## Common commands

```bash
# The engine (the product) — primary interface: ./facty (see `./facty --help`)
./facty cases                # list the demo cases (type · pack · drop)
./facty run <case>           # run a case (phase 1) · --add-facts <drop> = phase 2
./facty run <case> --json    # machine-readable verdict + trace
./facty selftest             # acceptance test — every case, asserted
./facty test                 # all tests: selftest + retry loop + the TUI (headless)
./facty sense <case> --op facts   # one sensing op, standalone (LLM, streamed)
./facty walkthrough <case>   # terminal step-through (VMs, no-TTY)
./facty tui <case>           # the Textual workbench (needs `make deps`)
./facty emit                 # codegen projections (TS types + Datalog per case)
./facty completion bash      # shell completion
make deps                    # install the optional deps (Textual — the workbench)

# Make wrappers (kept for muscle memory)
make dss-demo               # run the attribution case (phase 1)
make dss-demo-2             # apply the ledger test (phase 2)
make dss-demo-fraud[-2]     # the fraud case (phases 1/2)
make dss-demo-rca[-2]       # the RCA case (phases 1/2)
make dss-selftest           # acceptance test (every case, asserted)
make dss-test               # all tests
make dss-live               # walkthrough
make dss-sense OP=facts     # one sensing op

# Session lifecycle (user terminal only for up/down)
make vm-image                  # build the gondolin VM image (gondolin/, one-time)
make vm-up                     # boot the pack-factory VM session (foreground, keep open)
make vm-status                 # session state — sandbox-safe
make vm-down                   # stop session (user terminal)

# Pack factory (exec into the VM session via socket-path IPC; every run audited)
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

### Python (the engine)

- Dependencies are allowed — the stdlib-only rule was retired (PO,
  2026-10-17; see ADR-0004). #1 focus: knowledge-developer experience.
- The invariants that remain: (1) the verdict path is deterministic —
  same artifacts → byte-identical verdict, never an LLM call, a clock,
  or a random source in it; (2) case records are auditable text-file
  artifacts (JSON files now, a DB later) — the artifact model is the
  audit trail; (3) the engine core + CLI control plane stay
  dependency-free so they run in the gondolin VM snapshot (no pip
  guarantees there) — optional DX layers (the Textual workbench,
  `./facty`) import lazily and degrade gracefully. Root
  `requirements.txt` holds the optional deps (`make deps`, uv-managed).
- `engine/engine.py` is library + CLI (`run`, `selftest`); the selftest
  asserts the acceptance criteria and the deterministic replay. The
  primary interface is the `facty` CLI (`./facty`, `engine/cli.py`).
- LLM response cache: live sensing calls are cached as raw responses
  (`.agentic/cache/sensing/`, gitignored); `FACTY_SENSE=cache` replays
  them without the LLM (offline demos / deterministic-side testing).
  The workbench authenticates the Mistral subscription through the
  pi-mistral-subscription extension (the `a` key in `./facty`).
- Sensing transport: the LLM half runs through the **pi agent's RPC
  mode** (`pi --mode rpc`, `engine/sensing.py`) — the staged assignment
  is sent inline (evidence inlined, no tools, thinking off, no session
  files) and the response streams back live; pi is shut down the moment
  the agent settles. Env knobs: `FACTY_PROVIDER`, `FACTY_MODEL`,
  `FACTY_THINKING`. No VM is involved per call — pi is a subprocess;
  the gondolin VM is the long-lived SDLC-agent session.
- The senses are guided by the pack's **term vocabulary** (the
  predicates + subjects the rules reference, embedded in the facts
  task), and the recommended test's evidence is sensed with the
  engine's **open questions** + hypothesis statements — never the
  engine's conclusions (scores, rankings, derived facts, prunings);
  feeding those back would bias the reading toward the current verdict.
- Out-of-band **commentary**: `./facty explain <case> [--target
  entities|ranking|verdict]` and the workbench's `x` key ask the LLM to
  explain the result in plain language. Presentation only — the verdict
  is deterministic and never depends on it; the commentary is cached
  like the sensing responses and replayed offline.
- In the gondolin VM the CLI + workbench run from the baked image
  (textual + git); `MISTRAL_API_KEY` arrives via gondolin's host-secret
  injection (guest sees a placeholder, the host proxy substitutes it).

### Bash scripts (match `scripts/vm-session.sh` / `agent-pi.sh`)

- `set -euo pipefail`
- Header comment block: purpose, usage, env vars
- Colored helpers: `info/ok/warn/err` (`BLUE/GREEN/YELLOW/RED`, `NC` reset)
- Derive paths via `SCRIPT_DIR`/`PROJECT_DIR` — never hardcode relative paths
- Usage errors print usage and `exit 1`

### Case & pack artifacts

| Artifact | Path | Numbering |
|---|---|---|
| Case evidence (raw) | `engine/cases/<case>/evidence/` | — |
| Pack (rules/constraints/hypotheses) | `engine/cases/<case>/pack/` | — |
| Sensed facts | `engine/cases/<case>/facts.json` (+ `facts-<drop>.json`) | — |
| Sensing record | `engine/cases/<case>/SENSING.md` | — |
| Expected outcome | `engine/cases/<case>/expected.md` | — |
| Discovery assets | `docs/discovery/{problems,solutions,assumptions,ost,verticals}.md` | — |
| PRDs | `docs/prd/PRD-NNN-<slug>.md` | 3-digit (`PRD-001`) |
| ADRs | `docs/adr/NNNN-<slug>.md` | **4-digit** (`0001-`) |
| Agent tasks | `.agentic/messages/decision-to-coding/<NNN>-task.md` | 3-digit, next free |
| Agent results | `.agentic/messages/coding-to-decision/<NNN>-result.md` | 3-digit, next free |

Case directories carry the investigation type as a prefix
(`attribution-`, `adjudication-`, `causation-`, …) —
[docs/INVESTIGATION-TYPES.md](docs/INVESTIGATION-TYPES.md).

- Sensed facts carry `confidence` + `source` spans; the engine never
  re-scores them. The pack (rules, constraints, hypotheses) is authored
  with the pack factory; hypotheses are proposed by the LLM sensing half
  (recorded in `SENSING.md`).
- `assets/graph.json` is **derived** from merged branches by
  `scripts/asset-sync.sh` — don't hand-maintain node lineage.

### Docs

ELI5 front and centre; the data flow is expressible in ≤3 mermaid
diagrams, ≤6 boxes each. ASCII diagrams + tables are the house style.
Cross-link liberally; ADRs record any significant tradeoff (template:
`templates/sdlc/adr.md`).

### Agent runtime facts

- Models: decision `mistral-large-4` @ max thinking; coding `mistral-large-4` @ low.
  Per-run overrides: `AGENT_MODEL`, `AGENT_THINKING`. VM template path:
  `GONDOLIN_PI` (default `<repo>/gondolin/gondolin-pi.sh` — the gondolin
  image config is vendored in-repo at `gondolin/`; build the snapshot
  with `make vm-image`).
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
  `.pi/sandbox.json` (currently only `earendil-works.github.io` +
  `docassemble.org`). Web search/scraping skills will not work from the
  sandbox — and the VM has no web-search tooling by design (cases handle
  sensitive data; its egress is api.mistral.ai + registry.npmjs.org
  only). Do web research on the host, or skip it for sensitive cases.
- **Cross-project paths** (`~/.cache/gondolin`) may be unreadable from
  the sandbox — expect prompts or failures when scripts probe them; run
  those commands from the user's terminal or a pi `!` escape. (The gondolin
  image config itself is vendored in-repo at `gondolin/`, so it is always
  readable — the sandbox sees the repo.)
- Machine-local state is gitignored: `.agentic/tmp/`,
  `.agentic/vm-session.json`, `.agentic/vm-session.log`.

## Documentation index

| Doc | Contents |
|---|---|
| [README.md](README.md) | ELI5 pitch + tagline |
| [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md) | Determinism as baseline, LLM liability, human role (Air Canada case, reverse centaurs) |
| [docs/discovery/verticals.md](docs/discovery/verticals.md) | Product direction + market reasoning |
| [docs/adr/0003-detective-dss-neurosymbolic-core.md](docs/adr/0003-detective-dss-neurosymbolic-core.md) | The neurosymbolic core (the architecture) |
| [docs/discovery/detective-dss-poc.md](docs/discovery/detective-dss-poc.md) | The PoC plan (case vocabulary) |
| [docs/vision.md](docs/vision.md) | The method's philosophical foundations |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Isolation model, session lifecycle, why socket-path-only IPC |
| [docs/SDLC.md](docs/SDLC.md) | Phase-by-phase gates, outputs, review roles (pack factory) |
| [docs/AGENTIC-RUNTIME.md](docs/AGENTIC-RUNTIME.md) | Two-agent pattern, message protocol, state machine, CI mapping |
| [docs/ASSET-MODEL.md](docs/ASSET-MODEL.md) | Asset DAG, rules engine, audit/reification stream |
| [docs/GIT-NATIVE-PIPELINE.md](docs/GIT-NATIVE-PIPELINE.md) | Branches = assets, merges = materializations, skip-ahead rules |
| [docs/GITHUB-GATES.md](docs/GITHUB-GATES.md) | Workflow wiring, CODEOWNERS, branch protection |
| [docs/USE-CASES.md](docs/USE-CASES.md) | Multi-tenant client isolation scenarios |
| [docs/INVESTIGATION-TYPES.md](docs/INVESTIGATION-TYPES.md) | The seven judgement-driven investigation families + the case-prefix convention |
| [docs/PROVIDERS.md](docs/PROVIDERS.md) | Custom LLM providers — contemplated design (config, auth flow, workbench UI) |
| [docs/adr/](docs/adr/) | Decision records (start at ADR-0001) |
| [engine/README.md](engine/README.md) | The engine: layout, protocol, run commands |
