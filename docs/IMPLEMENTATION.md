# Facty implementation — TerminusDB + SmolVM + Vibe CLI

A cleanroom reimplementation of the detective DSS (ADR-0003) on a three-part
stack, with **no LLM in the verdict path**:

```
┌─ SmolVM image (one OCI image booted as a VM — the portable artifact, ADR-0005) ────────┐
│                                                                                        │
│  SURFACES (thin clients — no op logic; parity by construction, ADR-0010 §4)            │
│  ┌────────────┐  ┌───────────────────┐  ┌───────────────────────────┐                   │
│  │ facty CLI  │  │ Web UI (web/dist) │  │ LLM harness (Vibe CLI /   │                   │
│  │ (headless) │  │ via facty serve   │  │  any MCP client)          │                   │
│  └─────┬──────┘  └────────┬──────────┘  └───────────┬───────────────┘                   │
│        └───────────────────┴─────────── MCP stdio / HTTP ────────┘                       │
│                            ▼                                                            │
│  ┌─ ops.py — the ONE op layer (every op exists exactly once here) ──────────────────┐    │
│  │  case · ingest · load-facts · sense · run · prove · assemble · answer ·         │    │
│  │  turn (dispatcher) · interview (pydantic-graph) · search · query (read-only    │    │
│  │  WOQL) · state · log · verdict · bundles                                        │    │
│  └──┬──────────────────────────────────────┬───────────────────────────────────────┘    │
│     ▼ engine / turn / interview (deterministic)   ▼ sensing (LLM, typed, cached)     │
│  ┌──────────────────────────────┐   ┌─────────────────────────────┐   ┌───────────┐    │
│  │ rule DSL ──compile──▶ WOQL   │   │ pydantic-ai Agent(          │   │ vibe -p   │    │
│  │ chain → prune → rank → verdict│  │   tools=[], output_type=…)  │   │ fallback  │    │
│  │ commits per turn = Turn docs │   │ LLM = sensor/drafter ONLY   │   │           │    │
│  └──────────────┬───────────────┘   └─────────────────────────────┘   └───────────┘    │
│                 ▼                                                                       │
│  ┌─ terminusdb-server ─────────────────────────────────────────────────────────────┐    │
│  │ document graph store · schema = ontology (gate on every write) · WOQL engine  │    │
│  │ case = branch · commits = audit trail · time-travel (commit:<id>) · WOQL       │    │
│  │ read-only passthrough (ops.query); writes only via gated ops above             │    │
│  └─────────────────────────────────────────────────────────────────────────────────┘    │
│  bundles/ (signed v2, Ed25519) ──verify gate──▶ ops.py                                │
└────────────────────────────────────────────────────────────────────────────────────────┘
```
(The same picture as a rendered diagram is in [README.md](../README.md#execution-model-technical-readers);
the turn-mode semantics are in the README's data-flow diagram and ADR-0010 §3.)

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
    `mistral-large-4-0`, optional TerminusDB MCP tools) is what a
    human drives interactively when authoring packs or interrogating the graph.
    The CLI is deliberately *not* in the machine loop: subprocess per call, no
    typed outputs, session machinery — and the audit trail doesn't need its
    session logs (TerminusDB commits + the sensing cache record everything).
    `vibe -p` one-shot remains as the no-dependency fallback backend
    (`FACTY_SENSE_BACKEND=vibe`). No TUI, no tmux in any automated path.

## Why no ReAct / LLM-as-judge (the framework rule)

The rule is **not** "no agentic frameworks" — it is: no framework that imposes
a **ReAct tool loop** (LLM picks the next action) or an **LLM-as-judge** (LLM
scores/decides outcomes) in the verdict path. That is what ADR-0003 forbids
(rules beat vibes; the Air Canada liability precedent). Frameworks and
libraries are welcome as long as they keep the LLM out of the controller/judge
seat — e.g. pydantic-graph's typed state machines (LLM only in designated
nodes) are fine, per the trigger in the table below. Most popular frameworks
(CrewAI, AutoGen, OpenAI Agents SDK, Google ADK, Semantic Kernel's planner)
are ReAct tool loops: the LLM is the controller and the judge. For this domain:

| Approach | Loop style | Verdict path | Machine-driven sensing | Human-in-the-loop authoring |
|---|---|---|---|---|
| **Plain Python orchestrator + PydanticAI programmatic calls** (chosen) | deterministic phases; LLM is a typed function call (`tools=[]`) | correct by construction | ideal — typed output, retries on shape only, disk cache, in-process | n/a |
| **Vibe CLI** (`-p` fallback + interactive `pack-author`) | one-shot or agent session with tools | never used | possible but heavier (subprocess, no typed output) | ideal — MCP over TerminusDB, approvals, session resume |
| **LangGraph / pydantic-graph** (bundled with pydantic-ai 2.63.0; evaluated 2026-11-17, deps-log) | typed in-process state machines (steps/forks/joins, Mermaid render; no persistence module in this version) | acceptable (LLM only in designated nodes) | redundant for the verdict path — TerminusDB commits already give branch/replay/checkpoints; the turn plan is declarative signed Pipeline/Step/Turn docs | **adopted 2026-11-17 for the questionnaire loop** (`src/facty/interview.py`): pydantic-graph is the in-process executor only; every node commits its Turn doc to the case branch (TDB stays the system of record) |
| CrewAI / AutoGen / Agents SDK / ADK / SK planner | ReAct tool-calling, LLM decides next step | wrong fit | wrong fit | acceptable but judge-style |

If a later phase needs an in-code state machine with checkpoints (e.g. the
pack-factory interview), pydantic-graph/LangGraph is the natural add — but the
cleanroom starts with none: `engine.py` is already a deterministic phase
machine, and TerminusDB is the checkpoint store. Standing rule (PO, 2026-11-17):
**any** framework/library may be used as long as it does not impose ReAct or
LLM-as-judge — in the verdict path that means no LLM at all (ADR-0003); in
non-verdict flows (interview FSM, sensing, codemode) the LLM may act only
inside designated nodes whose outputs are gated through the ops layer (typed,
committed, replayable).

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

LLMs write SWI-Prolog text better than WOQL JSON (training-data abundance), and
at the ontology level (schema hierarchies, consistency, diffs) Prolog's
recursion/stratified negation beat hand-building JSON ASTs, so
[ADR-0012](adr/0012-prolog-authoring-dialect.md) adds an optional **Prolog
dialect for ontology-level operations** (users never see it): a restricted
stratified subset, compiled to WOQL JSON by a Prolog module run on the
SWI-Prolog 10.0.2 binary shipped inside the TerminusDB image (same runtime as
the server — verified, deps-log). WOQL JSON-LD remains the only
stored/executed form; all external APIs (`facty serve`, MCP) and the Web UI
stay JSON. Nothing uncompiled ever reaches the verdict path. The dialect also
covers **GraphRAG-style retrieval** (multi-hop patterns over the case graph →
WOQL `Path` queries — deterministic, replayable, provenance-native), alongside
the existing vector RAG (`facty search`, `sense --rag`) which stays
sensing-side only.

## LLM ↔ TerminusDB integration boundary — tight reads, gated writes, ratcheted

The LLM's integration with TerminusDB is as tight as it can be without
violating the ratchet towards pragmatic knowledge:

- **Reads: direct and read-only.** `ops.query` is a WOQL passthrough exposed
  as `facty query`, `POST /api/query`, and the MCP `query` tool — the LLM's
  GraphRAG/dialect patterns compile to WOQL and run straight against the case
  branch (incl. time-travel `commit:<id>` refs). Read-only is enforced
  structurally: any WOQL write operator (`Insert`/`Delete`/`Update`/…) in the
  AST is rejected before it reaches the server (`WOQL_WRITE_OPS` guard,
  tested).
- **Writes: gated, never direct.** The machine-loop LLM holds no DB
  credentials and no shell — it gets MCP tools (TerminusDB's built-in MCP for
  DB-level ops, the facty MCP server for case-level ops). Every write goes
  through an `ops.*` function that commits a schema-validated, typed artifact
  with `confidence`+`source` (sensed/answered facts), a signature gate (bundles,
  pipeline config), or an engine commit (derivations, verdicts). The LLM can
  propose; only the gate makes it knowledge.
- **The ratchet** (why this is safe): *deductive* — engine output carries
  `Derivation` edges and replays byte-identical from commits; *inductive* —
  sensed facts carry confidence+source and are never re-scored by the engine;
  *pragmatic* — only signed bundles and committed verdicts/assembled documents
  are distributable knowledge. LLM output crosses into the graph only at a
  gate, so every node in the case graph is attributable and replayable.

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
   without `--check` it boots `facty serve` for interactive use. The script is
   case-parameterized (`CASE` / `BUNDLE` / `PROVE_SUBJECT` / `PROVE_PREDICATE`).
7. Second exemplar: **done 2026-11-17** — demo case 2
   `verification-nobid-contracts` / bundle `public-corruption-dossier`
   ([USE-CASE-DOC-ASSEMBLY.md](USE-CASE-DOC-ASSEMBLY.md#demo-case-2--journalists--corruption-verification-nobid-contracts)):
   3 hypotheses, 7 rules, 6 constraints (incl. the two-source ethics guard),
   Goal + 4 slots, 6 snippets, a signed Pipeline, 4 FOIA-style evidence files
   and cached fact fixtures. H1 0.950 with 3 supports; H2 pruned by
   `c-no-emergency-eliminates-H2`, H3 by `c-records-agree-eliminates-H3`;
   recommended test `q-emergency-declaration`; `facty assemble` renders the
   six-section dossier; `demo-ui.sh --check` passes for the new case.

**Slice 2 — the evidence plane and MCP glue.** Dagster wrapping of the ingest
assets (framework-agnostic functions, TDB resource, commit per
materialization), pipeline config as signed docs + headless runner, CLI as
headless driver inside Dagster/CI, `dagster-mcp` + TerminusDB built-in MCP +
facty MCP server over stdio in the VM, turn dispatcher + `Turn` docs with
per-step modes and per-turn surface.

- **Interview loop (questionnaire as a graph) — done 2026-11-17.**
  `src/facty/interview.py` + `facty interview` / `/api/interview` / MCP
  `interview` tool (via `ops.interview`). The user-questioning flow is a typed
  pydantic-graph — `RunPhase` (deterministic) → `GapAnalysis` (engine-ranked
  open questions) → `AskQuestion` (scripted or LLM chooser — the only LLM node,
  ranked mode) → `CommitAnswer` (slot fill, pick recorded) → loop → `Assemble`
  → End. The correspondence to the declarative pipeline is explicit:
  `turn.execute_one_turn` is shared by the linear dispatcher and the graph, so
  both commit identical Turn docs and replay = branch + `FACTY_SENSE=cache`
  (tested). `Graph.render()` gives the Mermaid diagram for docs/UI.
- **Turn dispatcher — done 2026-11-17.** `src/facty/turn.py`: schema gained
  `Step`/`Pipeline`/`Turn`; pipeline config is a signed doc (lives in the
  bundle's `bundle.json`, arrives signature-covered on the case branch; the
  demo bundle carries `assembly-unpaid-invoice` + `-live` pipelines). `facty
  turn <case> [--pipeline …] [--choice …] [--value …] [--surface chat|wizard]
  [--actor human|llm|pipeline] [--all]` executes the next un-executed step and
  commits a `Turn` doc `{mode, inputCommit, options?, choice?, outputCommit,
  surface, actor}`. Mode map enforced (`STEP_MODES`): verdict-path ops
  (run/prove/assemble) are **always deterministic** (ADR-0003), `ranked` only
  fills slots (answer — engine's ranked option set, pick recorded), `free`
  only senses/ingests. Default = first pipeline on the branch. Same op behind
  CLI + `/api/turn` + MCP `turn` tool; Web UI header has "next turn" and the
  timeline renders Turn docs with mode/surface/actor badges. Tests:
  `tests/test_turn.py` (modes, choice recording, enforcement, cross-branch
  replay determinism). `scripts/demo-ui.sh --check` drives the pipeline
  headless (stops at the ranked answer, then completes with the recorded pick).
- **In-UI feedback channel — done 2026-11-17.** `Feedback` docs (schema) +
  `ops.feedback_add`/`feedback_list` + `facty feedback add|list` +
  `POST/GET /api/feedback` + MCP `feedback_add`/`feedback_list`. The Web UI
  header has a comment button (badge = count) anchored to the current
  case/surface; comments commit to the case branch and are read with
  `./facty feedback list --case <id>`. Also: a "what am I looking at?" help
  dialog in plain language (rings = Proven / Open / Anomalies, graph, wizard
  vs chat, packet, timeline) and friendlier error/notice banners.
- **facty MCP server — done 2026-11-17.** `src/facty/mcp_server.py` + `facty mcp`:
  MCP over stdio implemented in **stdlib only** (newline-delimited JSON-RPC 2.0;
  spec 2025-06-18 verified + logged in deps-log) so it runs in the SmolVM image
  with no PyPI at runtime. One tool per `facty serve` case op — the parity
  registry (`serve.POST_OPS`/`GET_OPS` ↔ `mcp_server.TOOLS[*].serve`, asserted
  by `tests/test_mcp.py`, incl. a real stdio subprocess handshake). TerminusDB's
  built-in MCP plugin covers DB-level ops; `dagster-mcp` covers the evidence
  plane once Slice 2's Dagster part lands.
- **Remaining in Slice 2:** the Dagster evidence plane itself —
  framework-agnostic asset functions (`Original → ExtractedText → EvidenceChunk
  → Fact`) over a TDB resource with a commit per materialization, per-case
  pipeline config executed by a headless runner without Dagster, `dagster-mcp`
  baked into the OCI image, CLI as headless driver inside Dagster/CI. Plus the
  [ADR-0012](adr/0012-prolog-authoring-dialect.md) Prolog dialect for
  ontology-level operations: a `swipl`-module translator (in-image SWI-Prolog
  10.0.2) from a restricted stratified Prolog subset to WOQL JSON over the
  versioned schema graph, with round-trip tests — internal tooling only, never
  stored, never user-facing, never in the verdict path uncompiled.

**Slice 3 — providers, auth, scale.** Model provider registry (BYO
open-weight, local in-VM serving, non-US via allow-list + host-secret);
multi-user auth/IAM if the served shape is pursued; TrustGraph re-evaluation
per ADR-0010 §6 triggers.

Standing invariants for every slice: `./facty selftest` green (byte-identical
replay from commits); verdict path never touches the LLM, a clock, randomness,
or Dagster; parity checklist — every CLI op has a `facty serve` endpoint and an
MCP tool once MCP lands; secrets host-side only.

- **`src/facty/ops.py` — the canonical op set, the thinnest-possible API
  wrapper.** Every facty operation (case registry, ingest, load-facts, sense,
  run, prove, assemble, answer, turn, search, state, log, verdict, bundles)
  exists exactly once, as a function in `ops.py` (client + plain kwargs →
  JSON-able dict). The three transports are thin marshalling adapters over it
  and own no op logic: CLI commands (`cli.py`), `facty serve` HTTP routes
  (`serve.py` — `POST_ROUTES`/`GET_ROUTES` are one-line lambdas;
  `POST_OPS`/`GET_OPS` are derived from them, single source), and the facty
  MCP server (`mcp_server.py` — `tools/call` dispatches by name:
  `getattr(ops, tool)(Client(), **args)`). TerminusDB's built-in MCP plugin
  (stdio + `POST /api/mcp`) covers DB-level ops, `dagster-mcp` (stdio) the
  evidence plane. Machine loop and human harness call the same interfaces;
  humans answer engine-opened `Question` docs as structured questionnaires in
  the UI (slot filling). `tests/test_mcp.py` locks the structure: parity of
  the op registry across serve/MCP, and every tool name = an `ops` function.
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
- **Model provider registry** — aliases (`facty-local`, …) →
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
│   ├── config.toml            # dev model deepseek-v4-1-flash-1017 (+ mistral-large-4-0 row), 1M/880k
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
