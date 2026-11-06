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
  4 rank       score = 0.6·claims_proven + 0.3·min(support,3)/3 + 0.1·prior  (same formula as the PoC engine)
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

- Polymorphic values are typed, not stringly-normalized: exactly one of
  `valueString` / `valueBool` / `valueNum` (or `var` for a bind-any existence
  condition). `confidence`/`prior`/scores are `xsd:decimal` numbers.
- `python -m facty.migrate <case-dir> [facts.json ...]` converts the PoC's
  `pack/*.json` + facts **once** into `<case-dir>/terminusdb/{pack.json, facts-*.json}`.
  PoC files are untouched. Migrated so far: `bundles/insurance-claim-fraud`,
  `engine/cases/attribution-silver-blaze`.
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
│   ├── engine.py              # deterministic run loop
│   ├── sensing.py             # vibe -p one-shot calls + disk cache
│   └── cli.py                 # python -m facty …
├── scripts/
│   └── e2e.sh                 # end-to-end demo: bundles/insurance-claim-fraud, offline or --live
├── demos/
│   └── fraud-phase2-drop.json # discriminating-test evidence drop for the e2e demo
└── spikes/
    ├── spike-01-terminusdb-sherlock.md
    └── e2e-insurance-fraud.md # the e2e demo: what it shows, expected output, acceptance
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
python -m facty run attribution-silver-blaze --add-facts engine/cases/attribution-silver-blaze/facts-ledger.json
python -m facty selftest                # golden-compare vs the PoC expected.md
```

Env: `TERMINUSDB_URL` (default `http://127.0.0.1:6363`), `TERMINUSDB_USER`
(`admin`), `TERMINUSDB_PASS`, `TERMINUSDB_ORG` (`admin`), `TERMINUSDB_DB`
(`facty`), `TERMINUSDB_REF` (branch to work on), `FACTY_SENSE` (`live`|`cache`),
`FACTY_SENSE_BACKEND` (`pydantic`|`vibe`), `FACTY_MODEL` (`mistral-large-4`),
`VIBE_BIN` (`vibe`). `MISTRAL_API_KEY` rides the environment (host-side secret,
never baked into the image).
