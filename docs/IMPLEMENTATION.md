# Facty implementation — TerminusDB + SmolVM + Vibe CLI

A cleanroom reimplementation of the detective DSS (ADR-0003) on a three-part
stack, with **no LLM in the verdict path**:

```
┌──────────────────────── SmolVM (one OCI image booted as a VM) ────────────────────────┐
│                                                                                        │
│   terminusdb-server          facty (Python, deterministic)   vibe CLI        │
│   ├─ document graph store    ├─ rule DSL ──compile──▶ WOQL AST        ├─ sensing      │
│   ├─ schema = ontology       ├─ engine loop (chain→prune→rank→verdict)  │  (one-shot    │
│   ├─ WOQL (Datalog/Prolog)   ├─ commits per phase (branch per run)      │   -p calls,   │
│   └─ git-for-data audit      └─ verdict + trace = one atomic commit    │   mistral-    │
│                                                          ▲             │   large-4)    │
│                                                          └─────────────┘               │
│                                                          LLM = sensor/drafter only   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

- **TerminusDB** (Apache-2.0, Docker image) is the store, the schema-as-ontology,
  the rule/query engine (WOQL — Prolog unification + stratified Datalog under the
  hood), and the audit trail (git-for-data: branch / commit / diff / time-travel,
  with a WOQL-queryable `_commits` graph).
- **SmolVM** (`smol-machines/smolvm`) boots the single OCI image built from
  `Dockerfile` as a portable, branchable micro-VM. For plain-Docker iteration,
  `compose.yaml` runs the same two processes as two services.
- **LLM access has two surfaces, by design:**
  - **Machine-driven workflows → PydanticAI, programmatic.** `sensing.py` uses
    an in-process `Agent("mistral:mistral-large-4", output_type=…, tools=[])`:
    typed structured output (validated + retried on *shape* only), no tool
    loop, trivially cached (`FACTY_SENSE=cache` replays from disk). This is the
    LLM as a *function call* inside the deterministic orchestrator.
  - **Human-in-the-loop → Vibe CLI.** The `pack-author` agent profile (model
    `facty-large` → `mistral-large-4`, optional TerminusDB MCP tools) is what a
    human drives interactively when authoring packs or interrogating the graph.
    The CLI is deliberately *not* in the machine loop: subprocess per call, no
    typed outputs, session machinery — and the audit trail doesn't need its
    session logs (TerminusDB commits + the sensing cache record everything).
    `vibe -p` one-shot remains as the no-dependency fallback backend
    (`FACTY_SENSE_BACKEND=vibe`). No TUI, no tmux in any automated path.

## Why no agentic framework (the LLM-as-judge question)

Most popular frameworks (CrewAI, AutoGen, OpenAI Agents SDK, Google ADK,
Semantic Kernel's planner) are **ReAct tool loops: the LLM is the controller
and the judge**. That is exactly what ADR-0003 forbids in the verdict path
(rules beat vibes; the Air Canada liability precedent). For this domain:

| Approach | Loop style | Verdict path | Machine-driven sensing | Human-in-the-loop authoring |
|---|---|---|---|---|
| **Plain Python orchestrator + PydanticAI programmatic calls** (chosen) | deterministic phases; LLM is a typed function call (`tools=[]`) | correct by construction | ideal — typed output, retries on shape only, disk cache, in-process | n/a |
| **Vibe CLI** (`-p` fallback + interactive `pack-author`) | one-shot or agent session with tools | never used | possible but heavier (subprocess, no typed output) | ideal — MCP over TerminusDB, approvals, session resume |
| **LangGraph / pydantic-graph** | explicit state graph, checkpointers replay | acceptable (LLM only in designated nodes) | redundant — TerminusDB commits already give branch/replay | possible for the interview FSM later |
| CrewAI / AutoGen / Agents SDK / ADK / SK planner | ReAct tool-calling, LLM decides next step | wrong fit | wrong fit | acceptable but judge-style |

If a later phase needs an in-code state machine with checkpoints (e.g. the
pack-factory interview), pydantic-graph/LangGraph is the natural add — but the
cleanroom starts with none: `engine.py` is already a deterministic phase
machine, and TerminusDB is the checkpoint store.

## The Sherlock loop on TerminusDB

Artifact model = TerminusDB schema classes (enforced on every write):
`Fact, Rule, Condition, Action, Hypothesis, Constraint, Question, Derivation, Verdict`.

```
pack factory   interview (vibe) → schema + Rule/Hypothesis docs → commit on branch pack/<name>
case run       branch case/<id> from main
  1 sense      vibe -p (mistral-large-4) → Fact documents {id,subject,predicate,value,confidence,source,observedAt}
  2 chain      for each Rule: compile when→WOQL, run; then-actions insert derived Facts + Derivation edges; fixpoint
  3 prune      Constraint eliminate = WOQL negation (stratified); support = match count
  4 rank       score = 0.6·claims_proven + 0.3·min(support,3)/3 + 0.1·prior  (formula fixed by ADR-0003)
  5 questions  rank open Questions by (alive discriminations, priority, id)
  6 verdict    commit Verdict + full trace in ONE transaction → immutable, time-travelable
replay         query any commit → same documents → same query results → byte-identical verdict
```

Determinism: the verdict path is pure functions over TerminusDB query results.
No LLM (use `FACTY_SENSE=cache` to replay sensed facts from disk), no clock, no
randomness. `observedAt` comes from the sensed facts, not from a clock read in
the engine.

## LLM ↔ WOQL correspondence

TerminusDB's server is Prolog and WOQL variables use Prolog unification, so an
LLM's Prolog training transfers to WOQL *semantics*. It does not transfer to
*syntax* (WOQL is a JSON AST), so the LLM never emits WOQL text: rule DSL (JSON,
schema-validated) → deterministic compiler (`rules.py`) → WOQL AST via the
builder (`woql.py`) → server-side validation at bind time. Dialect errors are
impossible by construction; retry loops exist only for sensing semantics, never
for query syntax.

## Triadic glue roadmap (ADR-0010, proposed 2026-11-17)

Planned components — none exist yet; this section is the spec, not a layout.
**Priority: Web UI/UX first** (it is the demo surface for non-developers —
questionnaire wizard, chat, live bullseye of known knowns / known unknowns /
unknown unknowns, hypothesis graph, proof trees); the CLI remains the headless
driver for Dagster pipelines and CI.

### Order of work (slices)

**Slice 1 — prove one use case end to end, driving the Web UI prototype.**
Vehicle: `assembly-unpaid-invoice` (Marisol's bakery; see
[USE-CASE-DOC-ASSEMBLY.md](USE-CASE-DOC-ASSEMBLY.md)). Ordered steps:

1. Demo content: tiny signed pack `small-business-contract-claim` (3
   hypotheses, 5 rules, 4 constraints incl. the anti-worker guard, 1 Goal with
   4 typed slots, 4 template snippets) + demo case with 4 evidence files
   (contract, delivery receipt, email thread, claimant statement).
   **Done 2026-11-17** (025): pack authored + signed; DSL gained `cmp`
   comparisons (live-verified WOQL `Less/Greater/Gte/Lte`); selftest
   entry added.
2. Engine path as-is: `facty ingest` → `sense` (`FACTY_SENSE=cache` for the
   demo; live LLM optional) → `run` → `prove`. `./facty selftest` stays green.
   **Done 2026-11-17** (025): winner H1 score 0.750, H2/H3 pruned by named
   constraints; `prove` now expands Derivation edges into full proof trees.
3. `facty serve` minimal gateway: stdlib `http.server` + SSE watch endpoint
   tailing the case branch commit log; ops = ingest / load-facts / sense /
   run / prove / assemble / answer + `/api/state`, `/api/log`, `/api/watch`.
   **Done 2026-11-17** (027): `src/facty/serve.py`; CLI↔UI parity by
   construction (UI calls the same endpoints).
4. Web UI prototype (stack per [ADR-0011](adr/0011-web-ui-stack-svelte-static-build.md):
   Svelte 5 + Vite compiled to static `web/dist` at image build, served by
   `facty serve`; pure client of the gateway ops + TDB reads).
   **Done 2026-11-17** (027, reskinned 030): `web/` on the ADR-0011 stack —
   Svelte 5 + Vite 8 + **shadcn-svelte** components (sidebar app shell, button,
   input, select, badge, card, scroll-area, sonner, … copied into
   `web/src/lib/components/ui/` via the CLI — we own the source) on bits-ui +
   **Tailwind v4** (`@tailwindcss/vite`), themed by **Skeleton's `wintry`
   preset** (`data-theme="wintry"`, dark mode via `.dark` + theme toggle in the
   sidebar; Skeleton's `--color-*` scale mapped onto the shadcn vars in
   `src/app.css`). Panels: intent box (deterministic phrase match),
   questionnaire wizard + chat (switchable per turn), live bullseye
   (Proven / Open / Anomalies), hypothesis graph (d3-force SVG, `prunedBy`
   labels), proof-tree panel, assembled-packet preview (marked, print-to-PDF),
   turn timeline. Dockerfile is multi-stage (node builder → static `web/dist`
   only at runtime). Build: 17 kB CSS / 147 kB JS gzip.
5. Deterministic assembly step: **done 2026-11-17** (027) — `facty assemble`
   selects snippets whose `when` is proven, renders Markdown, commits
   `AssembledDocument` (sha256). `facty answer` = human-loop slot filling
   (`answer:<slot>` Fact + closes the OpenQuestion).
6. E2E demo script: **done 2026-11-17** (027) — `scripts/demo-ui.sh [--check]`
   drives the whole flow headless and smoke-tests the served API + SSE + UI;
   without `--check` it boots `facty serve` for interactive use.

**Slice 2 — the evidence plane and MCP glue.** Dagster wrapping of the ingest
assets (framework-agnostic functions, TDB resource, commit per
materialization), pipeline config as signed docs + headless runner, CLI as
headless driver inside Dagster/CI, `dagster-mcp` + TerminusDB built-in MCP +
facty MCP server over stdio in the VM, turn dispatcher + `Turn` docs with
per-step modes and per-turn surface.

**Slice 3 — providers, auth, scale.** Model provider registry (BYO
open-weight, local in-VM serving, non-US via allow-list + host-secret);
multi-user auth/IAM if the served shape is pursued; TrustGraph re-evaluation
per ADR-0010 §6 triggers.

Standing invariants for every slice: `./facty selftest` green (byte-identical
replay from commits); verdict path never touches the LLM, a clock, randomness,
or Dagster; parity checklist — every CLI op has a `facty serve` endpoint and an
MCP tool once MCP lands; secrets host-side only.

- **`facty serve`** — one HTTP/JSON gateway inside the image exposing every CLI
  op; the Web UI and the CLI are both clients of it (parity by construction).
  Every op is also an MCP tool: TerminusDB's built-in MCP plugin (stdio +
  `POST /api/mcp`) for DB-level ops, a small facty MCP server for case-level
  ops, `dagster-mcp` (stdio) for the evidence plane. Machine loop and human
  harness call the same interfaces; humans answer engine-opened `Question`
  docs as structured questionnaires in the UI (slot filling).
- **Turn dispatcher** — reads each step's `mode` (`deterministic` | `ranked` |
  `free`) from the signed step config on the case branch and routes:
  engine-only / engine-ranked + recorded pick / LLM sensing. Verdict-path
  turns are always `deterministic` (ADR-0003). Each turn commits a `Turn` doc
  `{mode, inputCommit, options?, choice?, outputCommit}`; replay =
  branch + `FACTY_SENSE=cache`.
- **Dagster evidence plane** — asset logic stays framework-agnostic
  (`Original → ExtractedText → EvidenceChunk → Fact` via the TDB client
  resource, one commit per materialization); pipeline code in git, per-case
  pipeline config as a signed doc on the branch; headless runner executes the
  same docs without Dagster. Dagster + dagster-mcp baked into the OCI image at
  build time (no PyPI at runtime); SQLite run metadata per VM.
- **Model provider registry** — aliases (`facty-large`, `facty-local`, …) →
  pydantic-ai providers / Vibe `[[providers]]`; BYO open-weight first-class;
  local in-VM serving (ollama/llama.cpp/vLLM) = zero egress; non-US hosted via
  per-deployment egress allow-list + host-secret; US closed models unsupported
  by default (not allow-listed, no code paths for them).
- **TrustGraph deferred** — surveyed 2026-11-17 (deps-log): no reasoning
  engine, no time-travel versioning; revisit on multi-tenant scale, PROV-O
  evidence-mill lineage, or decider-tier substitution.
- **Web UI (first spike)**: questionnaire wizard + chat surface (switchable
  per turn), live bullseye — Proven (facts/clauses with Derivation backing) / Open (open
  Questions, undecided hypotheses) / Anomalies (Quarantine, versionConflicts,
  semantic-contradiction candidates, unexplained hypotheses), hypothesis graph (status colors, `prunedBy` labels, Derivation
  edges, proof-tree panel, turn timeline with mode/surface badges) — all fed
  by a `facty serve` watch endpoint tailing the case branch's commit log.
  CLI parity via `facty watch <case>`. See
  [USE-CASE-DOC-ASSEMBLY.md](USE-CASE-DOC-ASSEMBLY.md).
- **Worked exemplar**: [USE-CASE-DOC-ASSEMBLY.md](USE-CASE-DOC-ASSEMBLY.md) —
  legal document assembly (`assembly-` family,
  [INVESTIGATION-TYPES.md](INVESTIGATION-TYPES.md)): pack = goal + template
  snippets + rules; engine-opened Questions = UI questionnaires (slot
  filling); abductive threads prove which clauses apply; deterministic
  assembly step renders the document as a committed `AssembledDocument` +
  Dagster data-product asset. Anchors: BC CRT Solution Explorer,
  Docassemble/Suffolk Assembly Line, Gavel (acquired by Relativity 2026-06).

## Observability / performance metrics

- Always on, zero egress: every LLM call prints a status line to stderr
  (`[sense] SensedFacts → mistral:mistral-large-4 (prompt N chars) …` then
  `done in 12.3s · in=… out=… tokens · cached=false`) and appends a JSONL row to
  `.cache/sensing-metrics.jsonl`. `python -m facty metrics`
  prints the log; `run` prints per-phase engine latency (`[run] phase 1 done in …`).
- Opt-in tracing: `FACTY_LOGFIRE=1` (needs `logfire` installed) runs
  `logfire.configure()` + `logfire.instrument_pydantic_ai()` — full span traces
  of every model call/tool/retry. Off by default because the VM egress allow-list
  has no observability endpoint. Logfire is plain OTel: point
  `OTEL_EXPORTER_OTLP_ENDPOINT` at a self-hosted collector, or `FACTY_LOGFIRE=hosted`
  to send to the Logfire platform. `PYDANTIC_AI_NO_BANNER=1` silences the banner.

## Pack format — TerminusDB JSON-LD, no runtime munging

Packs are authored/stored **directly as TerminusDB documents** (the schema in
`src/facty/schema.py`): `@type`-tagged JSON-LD with typed fields.
Loading is a plain insert — the DB's schema validation is the only gate.

**Pack ≡ case pack ≡ demo — one form only: the signed bundle.** The signed
bundle (`bundles/<name>/`, ADR-0006) is the only pack representation; there is
no legacy or unsigned form to maintain (`bundle load` verifies the signature
and refuses anything else; `bundle sign` is the authoring bootstrap for a fresh
`bundle.json`). A case starts as a branch loaded from a bundle (ADR-0007); a
demo example is a bundle plus a starter case with fixture evidence (e.g.
`bundles/small-business-contract-claim` + `assembly-unpaid-invoice`; the
retired PoC's case packs live on as `bundles/attribution-silver-blaze` etc.).
A future marketplace/plugin registry is therefore just a namespace + content
store over signed bundle manifests — no new trust or packaging model needed.

- Polymorphic values are typed, not stringly-normalized: exactly one of
  `valueString` / `valueBool` / `valueNum` (or `var` for a bind-any existence
  condition). `confidence`/`prior`/scores are `xsd:decimal` numbers.
- Every bundle in `bundles/` carries its own fixtures (`fixtures/facts*.json`,
  `expected.md`); `./facty selftest` loads each signed bundle (signature
  verified), replays the fixtures on a scratch branch, and asserts the expected
  verdicts plus a byte-identical determinism replay.
- Derive blueprints are `FactTemplate` **subdocuments** (a Fact reference would
  materialize the conclusion as a premise). `Fact` is discriminated in WOQL by
  its unique `source` field (Isa/@type triples don't parse in v12).
- Runtime-opened questions are top-level `OpenQuestion` docs (subdocuments can't
  be inserted standalone); rules/constraints are applied in sorted-id order so
  Set read-back order can't affect the verdict.

## Layout

```

├── README.md                  # this file
├── pyproject.toml
├── Dockerfile                 # the SmolVM image (terminusdb + python + vibe)
├── compose.yaml               # plain-Docker dev alternative
├── .vibe/
│   ├── config.toml            # default model alias facty-large → mistral-large-4
│   └── agents/
│       ├── sensing.toml       # no tools, one-shot structured output
│       └── pack-author.toml   # authoring agent (optional TerminusDB MCP tools)
├── src/facty/
│   ├── client.py              # TerminusDB REST client (stdlib urllib)
│   ├── schema.py              # artifact model as TerminusDB schema
│   ├── woql.py                # WOQL AST builders
│   ├── rules.py               # rule DSL → WOQL compiler (closed template set)
│   ├── engine.py              # deterministic run loop (chain→prune→rank→verdict)
│   ├── sensing.py             # pydantic-ai typed calls + disk cache
│   ├── serve.py               # HTTP/JSON gateway + SSE watch (the Web UI's backend)
│   └── cli.py                 # python -m facty … (headless driver)
├── web/                       # Svelte 5 + Vite static UI (shadcn-svelte + wintry theme)
├── bundles/                   # signed packs (Ed25519 manifest): insurance-claim-fraud, …
├── tests/
│   └── test_*.py              # pytest suite (M1 trust spine, ingest, prove, …)
├── scripts/
│   ├── e2e.sh                 # end-to-end demo: bundles/insurance-claim-fraud, offline or --live
│   └── demo-ui.sh             # headless Web UI e2e demo (case assembly-unpaid-invoice)
└── demos/
    └── fraud-phase2-drop.json # discriminating-test evidence drop for the e2e demo
```

## Running

```bash
# host-side Docker dev (compose): terminusdb on :6363
docker compose -f compose.yaml up -d

# or as one SmolVM machine (smolvm v1.29: local OCI image via stdin, no registry)
docker build -t facty 
docker save facty | smolvm machine run --net --image - -- bash
# persistent machine instead of one-off:
#   docker save facty > /tmp/facty.tar
#   smolvm machine create --net --name facty --image /tmp/facty.tar
#   smolvm machine start --name facty && smolvm machine exec --name facty -- bash

# inside (or against compose from the host):
pip install -e 
python -m facty init-db                 # create db + install schema
python -m facty bundle load bundles/insurance-claim-fraud   # signed gate; --dev for legacy
FACTY_SENSE=cache python -m facty run attribution-silver-blaze   # offline replay
python -m facty run attribution-silver-blaze --add-facts bundles/attribution-silver-blaze/fixtures/facts-ledger.json
python -m facty selftest                # acceptance: every signed bundle in bundles/, asserted + replayed
python -m facty serve                   # Web UI on http://127.0.0.1:8080
```

Env: `TERMINUSDB_URL` (default `http://127.0.0.1:6363`), `TERMINUSDB_USER`
(`admin`), `TERMINUSDB_PASS`, `TERMINUSDB_ORG` (`admin`), `TERMINUSDB_DB`
(`facty`), `TERMINUSDB_REF` (branch to work on), `FACTY_SENSE` (`live`|`cache`),
`FACTY_SENSE_BACKEND` (`pydantic`|`vibe`), `FACTY_MODEL` (`mistral-large-4`),
`VIBE_BIN` (`vibe`). `MISTRAL_API_KEY` rides the environment (host-side secret,
never baked into the image).
