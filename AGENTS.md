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

- `engine/` — the PoC engine, golden oracle post-ADR-0005 (`make poc-oracle`) + demo case data
- `src/facty/` — the implementation (ADR-0005): TerminusDB-backed engine + CLI
- `scripts/*.sh` — git-native pipeline, asset sync, e2e demo (bash)
- `templates/sdlc/` — pack-factory templates + agent role prompts (`agents/decision.md`, `agents/coding.md`)
- `docs/` — architecture, discovery, PRDs, ADRs (heavily cross-referenced — follow links)
- `.github/workflows/` — CI gating workflows (merge triggers, SDLC)
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
2. **SmolVM, not gondolin.** The retired gondolin/pi runtime is gone (ADR-0005);
   isolation is one SmolVM machine booted from the root `Dockerfile`
   (`docker build -t facty . && docker save facty | smolvm machine run --net --image - -- bash`,
   persistent: `smolvm machine create --net --name facty` + `start` + `exec --name facty -- <cmd>`).
   Don't run docker-in-docker inside the VM; the VM egress allow-list stands
   (api.mistral.ai, registry.npmjs.org, api.uprelic.com).
3. **Secrets stay host-side.** The guest only ever sees `MISTRAL_API_KEY=<placeholder>`;
   the host substitutes the real value on egress (SmolVM host-secret path is the
   open item in ADR-0005). Never log, echo, or read API keys. Local dev:
   `export MISTRAL_API_KEY="$(jq -r '.["mistral-subscription"].access' ~/.pi/agent/auth.json)"`
   (read `auth.json` directly) or `eval "$(./facty env --exports)"`-style hoisting.
4. **Secrets are host-side placeholders.** The guest and any sandboxed
   orchestrator only ever see `MISTRAL_API_KEY=<placeholder>`; the host
   substitutes the real value into outbound requests (SmolVM host-secret path — open item, ADR-0005). Never log,
   echo, or attempt to read API keys.
   **Credential resolution** (local dev): if `MISTRAL_API_KEY` is set
   (production — explicit pay-per-use API key), it wins. Otherwise the
   scripts prefer the **Mistral subscription token** — the long-lived API
   key the pi-mistral-subscription extension obtains via browser sign-in,
   stored in `~/.pi/agent/auth.json` under `"mistral-subscription"` (`...
   .access`), read directly with jq — so local dev runs on the subscription.
   Both auth styles use the same `Authorization: Bearer <token>` header, so
   pydantic-ai's `mistral:` provider picks it up unchanged.
5. **`.agentic/audit.jsonl` is append-only.** Never hand-edit or truncate it;
   query with `make audit-trail`. (The pi agent-run writer is retired with the
   gondolin runtime; the pack-factory port writes it — see ADR-0005/T9.)
6. **Decision artifacts are inputs, not outputs.** Never modify
   `docs/prd/`, `docs/discovery/`, `docs/adr/` when acting as the coding
   agent — unless the PO directs a rename or reframe. Coding agents
   report to `.agentic/messages/coding-to-decision/<NNN>-result.md`.
7. **VM egress is an explicit allow-list** (api.mistral.ai, api.uprelic.com
   for the Strom decider tier,
   registry.npmjs.org). Don't add network features that assume open
   egress — and don't add web-search tooling (ddgr or similar): cases
   handle sensitive data, so nothing leaves the VM except LLM calls.
8. **Read each stack dependency's docs in detail before building on it.**
   Search-result snippets are not documentation. For every dependency a
   component integrates — the cleanroom stack today: TerminusDB v12, SmolVM,
   pydantic-ai, the Vibe CLI — read the official docs end to end for the
   features we use (`llms.txt` / `llms-full.txt` / per-page `page.md`, the
   OpenAPI reference, and the official client source all count), note the
   version, and log what was read plus every fact that touches our code in
   `docs/research/deps-log.md`. Verify API shapes against the client
   source or OpenAPI, not blog posts. When the docs and the running server
   disagree, trust the server's bind-time errors and record the divergence
   in the log.

## Common commands

```bash
# The engine (the product) — primary interface: ./facty (see `./facty --help`).
# Since ADR-0005, ./facty runs the CLEANROOM stack (, TerminusDB-backed,
# SmolVM + Vibe CLI + pydantic-ai); engine/ is the retired PoC, kept as the
# golden oracle: python3 engine/engine.py selftest.
./facty cases                # list migrated cases/packs (terminusdb/ dirs)
./facty selftest             # golden acceptance: every migrated case, asserted + replay
./facty init-db              # create db + install schema (needs TerminusDB on :6363)
./facty load-pack <dir>      # insert <dir>/terminusdb/pack.json
./facty load-facts <file>    # insert fact docs
./facty run <case> --phase 1 --ref <branch>   # deterministic verdict on a branch
./facty verdict|log|metrics  # inspect outputs, audit trail, LLM latency/tokens
./facty sense <dir> --out f.json             # live LLM sensing (pydantic-ai)
# e2e demo: make e2e / make e2e-live   (scripts/e2e.sh [--live], packs/insurance-claim-fraud)
```

```bash
# PoC oracle (engine/, JSON artifacts) — kept for cross-checking until the PoC
# is retired (ADR-0005):
python3 engine/engine.py run --case <case>           # run a case (phase 1)
python3 engine/engine.py run --case <case> --add-facts <drop>   # phase 2
python3 engine/engine.py selftest                    # PoC acceptance test

# Make wrappers:
make selftest               # acceptance test (every case, asserted)


# Pack factory (exec into the VM session via socket-path IPC; every run audited)

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
  dependency-free so they run in the SmolVM image snapshot (no pip
  guarantees there) — optional layers import lazily and degrade gracefully. The root
  `pyproject.toml` holds the deps (`make deps` = `uv sync`, uv-managed, Python 3.14).
  The optional sensors (`engine/label.py`) import lazily and degrade
  gracefully; their deps live in
  `requirements-sensors.txt` (`make deps-sensors`) — heavy-ish and
  host/CI-only, never the SmolVM image. Sensor-sourced evidence
  (the `classify.json` file) is excluded from the LLM's phase-1 files.
- The label sensor is a **ladder** (`classify.json` `backend`):
  `strom` (default — the Strom decider tier scores every row, the local
  classifier is the automatic fallback), `hybrid` (the classifier
  scores the bulk, the decider adjudicates the gated rows — the demo
  case pins this to show the ladder), `local` (the local NLI classifier
  only — the offline mode). The Strom decider (`engine/strom.py`,
  stdlib-only) is Uprelic's hosted decision model (`strom-1.0.7`,
  EU/Paris GPUs, calibrated probabilities, ~$0.04 per 1M input tokens,
  500 req/min); its key rides `UPRELIC_API_KEY` (env / host-side secret injection — never logged, never committed), its question
  set is drafted per pack by the LLM (`--op decide` →
  `sensor/decisions.json`, judged, committed), and its responses cache
  like any sensing response. All tiers are induction-only — never in
  the verdict path. The decider tier is probabilistic (re-asked rows
  wobble past the 4th decimal; rows near the gate can flip) — the
  recorded facts + cache are the deterministic layer. `--offline` /
  `FACTY_OFFLINE=1` runs the local tier live and replays the LLM ops
  from cache.
- **Secrets**: real keys live in `~/.facty/.env` (machine-local, never
  committed); the real environment always wins. `MISTRAL_API_KEY` set in the
  env wins (production); otherwise export the subscription token from
  `~/.pi/agent/auth.json` (`.["mistral-subscription"].access`, read with jq —
  `pi auth` does not recognise extension providers). Same
  `Authorization: Bearer` header, so pydantic-ai's `mistral:` provider picks
  it up unchanged. In the SmolVM the guest only ever sees a placeholder; the
  host substitutes the real value on egress (open item, ADR-0005). The Strom
  decider key rides `UPRELIC_API_KEY` the same way (never logged, never
  committed); its question sets live in `sensor/decisions.json`.
- `engine/engine.py` is the PoC oracle: library + CLI (`run`, `selftest`),
  `make poc-oracle`. The primary interface is the `facty` CLI (`./facty` →
  `src/facty`, ADR-0005).
- The engine core (`src/facty/`: client/engine/rules/woql) is stdlib-only and
  runs anywhere; sensing is pydantic-ai (programmatic, `src/facty/sensing.py`,
  `tools=[]`, typed output, disk cache — `FACTY_SENSE=cache` replays with no
  LLM) with the Vibe CLI (`vibe -p`, project profiles in `.vibe/agents/`) as
  the human-facing surface and no-dependency fallback. Metrics:
  `./facty metrics`; opt-in tracing `FACTY_LOGFIRE=1`. In the SmolVM image the
  CLI runs from the baked rootfs; `MISTRAL_API_KEY` arrives host-side.

### Bash scripts (match `scripts/e2e.sh`)

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
| Sensor config + drafted artifacts | `engine/cases/<case>/classify.json` + `sensor/` (`extract.py` + tests, `decisions.json`) | — |
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

### Agent runtime facts (post-ADR-0005)

- The LLM surface is the **Vibe CLI** with project profiles in `.vibe/agents/`
  (default model alias `facty-large` → `mistral-large-4`; `thinking` per
  profile). Machine-driven LLM calls go through pydantic-ai
  (`src/facty/sensing.py`), not the CLI. Pack-factory agent runs (decision /
  coding roles) are being ported from gondolin/pi to Vibe-in-SmolVM — T9 in
  docs/CLEANROOM-METHOD.md.
- Audit entry shape (appended per run, success or failure):
  `{timestamp, type:"agent-run", role, phase, task, model, thinking, runtime, exit_code, duration_s}`.

## Environment quirks (sandboxed pi sessions on this host)

- **git fails on global config**: the sandbox blocks `~/.gitconfig`. Use
  `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null git ...`, and
  pass `-c user.name=... -c user.email=...` for commits. Also: this repo
  may not be initialized as a git repo yet — the git-native pipeline
  (`sdlc-branch.sh`, `asset-sync.sh`) requires it; check before promising
  pipeline runs.
- **Network egress** from a sandboxed session is restricted by the
  host's pi sandbox allow-list (the project ships no sandbox config).
  Web search/scraping skills will not work from the sandbox — and the
  VM has no web-search tooling by design (cases handle sensitive data;
  its egress is api.mistral.ai + registry.npmjs.org + api.uprelic.com
  only). Do web research on the host, or skip it for sensitive cases.
- Machine-local state is gitignored: `.agentic/tmp/`, `.cache/`, `.venv/`.

## Documentation index

| Doc | Contents |
|---|---|
| [README.md](README.md) | ELI5 pitch + tagline |
| [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md) | Determinism as baseline, LLM liability, human role (Air Canada case, reverse centaurs) |
| [docs/discovery/verticals.md](docs/discovery/verticals.md) | Product direction + market reasoning |
| [docs/adr/0003-detective-dss-neurosymbolic-core.md](docs/adr/0003-detective-dss-neurosymbolic-core.md) | The neurosymbolic core (the architecture) |
| [docs/discovery/detective-dss-poc.md](docs/discovery/detective-dss-poc.md) | The PoC plan (case vocabulary) |
| [docs/vision.md](docs/vision.md) | The method's philosophical foundations |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Isolation model (SmolVM; ADR-0005) — gondolin model retired |
| [docs/SDLC.md](docs/SDLC.md) | Phase-by-phase gates, outputs, review roles (pack factory) |
| [docs/AGENTIC-RUNTIME.md](docs/AGENTIC-RUNTIME.md) | Two-agent pattern, message protocol, state machine, CI mapping |
| [docs/ASSET-MODEL.md](docs/ASSET-MODEL.md) | Asset DAG, rules engine, audit/reification stream |
| [docs/GIT-NATIVE-PIPELINE.md](docs/GIT-NATIVE-PIPELINE.md) | Branches = assets, merges = materializations, skip-ahead rules |
| [docs/GITHUB-GATES.md](docs/GITHUB-GATES.md) | Workflow wiring, CODEOWNERS, branch protection |
| [docs/USE-CASES.md](docs/USE-CASES.md) | Multi-tenant client isolation scenarios |
| [docs/INVESTIGATION-TYPES.md](docs/INVESTIGATION-TYPES.md) | The seven judgement-driven investigation families + the case-prefix convention |
| [docs/PROVIDERS.md](docs/PROVIDERS.md) | Custom LLM providers — contemplated design (config, auth flow, workbench UI) |
| [docs/adr/](docs/adr/) | Decision records (start at ADR-0001; ADR-0001's gondolin session rules retired by ADR-0005) |
| [docs/adr/0005-cleanroom-stack-replaces-poc.md](docs/adr/0005-cleanroom-stack-replaces-poc.md) | ADR-0005: cleanroom stack (TerminusDB + SmolVM + Vibe CLI + pydantic-ai) is primary |
| [docs/CLEANROOM-METHOD.md](docs/CLEANROOM-METHOD.md) | methodology → cleanroom mapping + triage of not-yet-native reasoning patterns (T1–T10) |
| [docs/research/stack-survey.md](docs/research/stack-survey.md) | backend survey + cleanroom proposal |
| [docs/research/deps-log.md](docs/research/deps-log.md) | dependency docs log (rule 8): versions, what was read, live-verified divergences |
| [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md) | the cleanroom implementation: layout, run, e2e demo, observability |
| [engine/README.md](engine/README.md) | the PoC engine — golden oracle post-ADR-0005 |
