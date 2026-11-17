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

- **The brain — the symbolic engine** (`src/facty/`): forward + backward
  chaining rules engine with a constraint layer. Plain deterministic
  code. Rules beat vibes; every verdict replays without the LLM.
- **The senses — the LLM** (Mistral Large 4): reads messy evidence into
  facts, proposes hypotheses and discriminating tests. Probabilistic:
  great at reading, not at being right.

Domains are **bundles** (ontology + rules + constraints, signed — ADR-0006) —
fraud, incidents, security findings, contracts. The engine is the same; the
bundle is the costume. (Sherlock was a detective, not a doctor.) One artifact,
three roles: a knowledge pack, a case's starting pack, and a demo example are
the same signed bundle — a case is a branch loaded from it (ADR-0007), a demo
is a bundle plus fixture evidence. A future marketplace/plugin registry is
just a namespace over signed bundle manifests.

The repo is the engine + typed demo cases + the pack factory:

- `src/facty/` — the implementation (ADR-0005, the only stack): TerminusDB-backed engine + CLI
- `bundles/` — the signed bundles (manifest + Ed25519 sig + pack docs + fixtures): packs, case packs and demos are the same artifact (ADR-0006); `./facty selftest` replays them all
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

Schema: `src/facty/schema.py` (the artifact model as a TerminusDB ontology —
schema = ontology, enforced on every write).

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
7. **VM egress is an explicit allow-list** (api.mistral.ai,
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
# ./facty runs the cleanroom stack (TerminusDB-backed, SmolVM + Vibe CLI +
# pydantic-ai, ADR-0005) — the only stack; the PoC engine is retired.
./facty cases                # list the signed bundles (bundles/)
./facty selftest             # acceptance: every signed bundle, asserted + replay
./facty init-db              # create db + install schema (needs TerminusDB on :6363)
./facty keys init            # Ed25519 keypair in ~/.facty/keys (never committed)
./facty bundle sign|verify|load <dir>   # signed bundle gate — the only form; unsigned refused (ADR-0006)
./facty case init <id> --bundle <dir>   # case = TerminusDB branch (ADR-0007); case list|show|branch|delete
./facty ingest <dir> --source <label> --case <id>   # content-addressed originals + custody; conflicts → facts
./facty sense --case <id> --out f.json  # live LLM sensing from the case's extracted texts (or: sense <dir> --out f.json)
./facty extract <file> --out f.json --bundle <dir>  # codemode: LLM writes extractor, sandbox runs it (induction only)
./facty load-facts <file>    # insert fact docs
./facty run <case> --phase 1 --ref <branch>   # deterministic verdict on a branch
./facty verdict|log|metrics  # inspect outputs, audit trail, LLM latency/tokens
./facty sense <dir> --out f.json             # live LLM sensing (pydantic-ai)
# e2e demo: make e2e / make e2e-live   (scripts/e2e.sh [--live], bundles/insurance-claim-fraud)
```

```bash
# Make wrappers:
make selftest               # acceptance test (every signed bundle, asserted + replay)
make demo-ui                # served UI demo (scripts/demo-ui.sh)


# Pack factory (Vibe CLI pack-author profile in the SmolVM; every run audited)

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
  Optional layers (sensing, search, codemode) import lazily and degrade
  gracefully — they are baked into the image at build time, never installed
  at runtime (the SmolVM image has no pypi egress by design).
- Sensing is pydantic-ai only (`src/facty/sensing.py`): typed structured
  output, `tools=[]`, disk-cached — `FACTY_SENSE=cache` replays with no LLM.
  The PoC-era label-sensor ladder (`engine/label.py`, `engine/strom.py`,
  `classify.json`, `requirements-sensors.txt`) is retired with the PoC engine
  (ADR-0005); its case packs survive as signed bundles in `bundles/`.
- **Secrets**: real keys live in `~/.facty/.env` (machine-local, never
  committed); the real environment always wins. `MISTRAL_API_KEY` set in the
  env wins (production); otherwise export the subscription token from
  `~/.pi/agent/auth.json` (`.["mistral-subscription"].access`, read with jq —
  `pi auth` does not recognise extension providers). Same
  `Authorization: Bearer` header, so pydantic-ai's `mistral:` provider picks
  it up unchanged. In the SmolVM the guest only ever sees a placeholder; the
  host substitutes the real value on egress (open item, ADR-0005).
- The primary interface is the `facty` CLI (`./facty` → `src/facty`, ADR-0005).
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
| Bundle (pack = case pack = demo) | `bundles/<bundle>/` (manifest + Ed25519 sig + bundle.json) | — |
| Bundle evidence (raw) | `bundles/<bundle>/evidence/` | — |
| Bundle fact fixtures + expected outcome | `bundles/<bundle>/fixtures/` (`facts*.json`, `expected.md`) | — |
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
  (default model alias `facty-large` → `mistral-large-4`; `thinking = "high"`
  for dev/pack-authoring — the highest level mistral-large-4 supports — and
  `"low"` pinned on the `sensing` profile to keep the machine loop cheap). Machine-driven LLM calls go through pydantic-ai
  (`src/facty/sensing.py`), not the CLI; the `vibe -p` fallback backend does
  read the project `.vibe/config.toml` (`--trust`, cwd=repo root) — the file is
  shared by design, so keep it to runtime-safe settings (models/providers/
  agents; secrets stay in `~/.vibe/.env`). Both `[[models]]` entries sit on
  `mistral-large-4-0` (aliases `facty-large` + the routed `mistral-large-4-0-3`)
  with `max_context_length = 1048576` and `auto_compact_threshold = 800000` —
  overriding the catalogue's stale 400k compaction threshold (the API serves
  1,048,576 — live-verified against `/v1/models`; see deps-log). Pack-factory agent
  runs (decision / coding roles) are being ported from gondolin/pi to
  Vibe-in-SmolVM — T9 in docs/CLEANROOM-METHOD.md.
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
| [bundles/](bundles) | the signed bundles — packs, case packs and demos in one form |
