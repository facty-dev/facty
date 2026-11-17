# ADR-0010 — the triadic runtime: harness + Dagster + TerminusDB glued through MCP, with surface and loop parity

**Date:** 2026-11-17
**Status:** proposed (PO-directed)
**Related:** [ADR-0003](0003-detective-dss-neurosymbolic-core.md) (invariants — unchanged),
[ADR-0005](0005-cleanroom-stack-replaces-poc.md) (cleanroom stack),
[ADR-0006](0006-bundle-trust-spine.md) (signed bundles/config as docs),
[ADR-0007](0007-case-lifecycle-ingest-contract.md) (case = branch, custody).
Research log: [docs/research/deps-log.md](../research/deps-log.md) (TrustGraph, Dagster, TerminusDB MCP entries, 2026-11-17).

## What problem are we solving?

Four requirements landed at once:

1. **Ingestion at enterprise grade without reinventing ETL.** Evidence arrives as
   messy documents, scans, tracker exports, APIs. We do not want to hand-roll
   a DAG engine, retries, or lineage UI.
2. **A web UI beside the CLI** for non-technical operators (lawyers,
   journalists, accountants, forensic staff) managing case files.
3. **Provider freedom:** open-weight and non-US hosted models must be
   user-configurable; US closed models are not a support target.
4. **Configurable determinism per turn.** Codemode-style LLM loops are great
   for probabilistic "what next" (sensing, drafting), but some decisions must
   be fully deterministic (the verdict). The harness itself is just a
   program, so the *routing* of each turn can always be deterministic code;
   only the content of some turns is probabilistic.

## Decision

### 1. Triadic architecture

```
┌─ harness plane (human/agent surface) ─────────────────────────────┐
│  Vibe CLI today; any MCP-capable agent harness later               │
│     │ MCP stdio                    │ MCP stdio                     │
│     ▼                              ▼                               │
│  terminusdb MCP (built-in plugin)  dagster-mcp (OSS)               │
│     │                              │                               │
│     └──────────► facty serve ◄─────┘   one op set, one dispatcher  │
└───────────────────────┬───────────────────────────────────────────┘
                        │ HTTP/JSON gateway inside the SmolVM image
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
       CLI            Web UI       machine loop (pydantic-ai, typed)
        └───────────────┴───────────────┘
                        │ turn dispatcher: reads Step.mode from the case branch
                        ▼
        ┌─ system of record: TerminusDB case branch (commits) ─┐
        │ schema/ontology, Facts, Rules, Questions, Derivation, │
        │ Verdict, CustodyEvent, signed Pipeline/Step config    │
        │ Dagster assets write here via a TDB resource (commit   │
        │ per materialization) — Dagster run history = telemetry │
        └────────────────────────────────────────────────────────┘
```

- **TerminusDB is the system of record** for everything verdict-replayable and
  all config: store, schema-as-ontology, WOQL reasoning, git-for-data audit,
  case branches, signed bundle/pipeline/step documents. Its v12 server ships
  a **built-in MCP plugin** (`builtin_plugins/mcp.pl`: stdio + HTTP
  `POST /api/mcp`; tools cover db/branch/rebase/squash/log, document CRUD,
  WOQL query, versioned search).
- **Dagster is the evidence plane** — a thin, portable shell. Asset logic is
  framework-agnostic plain Python functions over the TDB client
  (`Original → ExtractedText → EvidenceChunk → Fact`); Dagster contributes
  orchestration, retries, asset checks, scheduling, lineage UI, CI. Pipeline
  *code* lives in git; per-case pipeline *config* is a signed doc on the case
  branch (ADR-0006 gate), passed as run config. A headless runner can execute
  the same config docs without Dagster at all — portability escape hatch.
  `dagster-mcp` (PyPI, OSS) runs stdio in the VM so agents drive pipelines over
  MCP. Dagster deps are baked into the OCI image at build time (no PyPI at
  runtime); SQLite metadata per VM, Postgres when shared.
- **The harness is a plane, not a product dependency.** Vibe CLI is the human
  surface (custom `[[providers]]` make any OpenAI-compatible endpoint work);
  the machine surface is pydantic-ai in-process. Neither the engine nor the
  CLI depends on the harness.

### 2. Sensing from anything, at either determinism level

Sensing sources: **humans** (the engine opens `Question` docs; the operator
answers them through the UI as structured questionnaires — slot filling),
**documents** (Dagster decode/OCR/chunk/embed → typed `Fact`s), **APIs**
(ingest adapters), and **LLMs** (pydantic-ai typed structured output, validated
on shape only, disk-cached; in machine loops the LLM is a typed function call
down to the type level). Each step carries a mode (below), so a step can be
deterministic (decoder, commit, engine turn) or stochastic (LLM extraction,
classification) — recorded per turn.

### 3. Per-turn determinism modes (the bridge)

Every turn/step has a `mode` in the signed config on the case branch:

| Mode | Next action chosen by | Replay |
|---|---|---|
| `deterministic` | rules engine / compiled plan over TDB state — no LLM call | byte-identical from the branch |
| `ranked` | engine produces the ranked, constrained option set; LLM/human picks within it; pick recorded in the commit | same options + recorded pick |
| `free` | LLM codemode/tool-calling (sensing, drafting only); outputs stored with confidence+source | from cache + recorded outputs |

The dispatcher (`facty serve` / `facty turn`) is deterministic code that reads
the next step's mode and routes. Every turn commits a `Turn` doc
`{mode, inputCommit, options?, choice?, outputCommit}` — the audit trail can
state per turn whether it was deterministic, engine-constrained, or LLM-free.
**Invariant (ADR-0003, unchanged): verdict-path turns are always
`deterministic`.** `ranked` only fills slots (answers, prose); `free` only
senses/ingests.

### 4. Parity invariants (the domain-model strengthening)

1. **CLI ↔ Web UI.** Every CLI operation is a `facty serve` endpoint; the UI
   is a client of it. No logic lives in the UI. **Surface priority: the Web UI
   is the primary human/demo surface; the CLI is the headless driver** invoked
   from Dagster pipelines and CI (`selftest`, `ingest`, `run`, `export`) —
   op-set parity unchanged, demo parity is UI-first.
2. **MCP coverage ↔ operations.** Every facty operation is exposed as an MCP
   tool (TerminusDB's built-in MCP for DB-level ops; a facty MCP server for
   case-level ops), so the machine loop and the human harness call the
   *same* interfaces.
3. **Machine loop ↔ human loop.** Anything one loop can do, the other can:
   the human loop gets the machine loop's tools through the harness (MCP
   integration), and the machine loop gets human input through the same
   `Question`/slot-filling artifacts the UI renders as questionnaires. Same
   interfaces, no duplicated code paths. The dynamic questionnaire is driven
   by **intent recognition + slot filling** (see
   [USE-CASE-DOC-ASSEMBLY.md](../USE-CASE-DOC-ASSEMBLY.md)): rules match known
   intents deterministically first (pack + goal + hypothesis space), the LLM
   proposes typed intent candidates only for unrecognized utterances (`ranked`
   mode, pick recorded in the `Turn` doc); free-text answers are slot-filled
   via pydantic-ai typed output into committed Facts, and the engine's gap
   analysis opens ranked `Question` docs only for the remaining gaps. Slots are
   filler-agnostic: human (questionnaire), LLM (sensing), or Dagster (pipeline
   assets) may fill a slot, gated by the pack's per-slot `fillers` list plus
   user confirmation (`confirm: true` → ranked confirmation Question, recorded
   in the `Turn` doc); every fill is a committed Fact tagged with its filler
   source (`answer:` / `sense:` / `pipeline:`), so the proof tree shows who
   filled what. Each turn also carries a `surface` (`chat` | `wizard`) recorded
   in the `Turn` doc: the human loop can switch between free chat and the
   engine-driven questionnaire at any turn boundary — both surfaces write the
   same artifacts and call the same ops, so chains replay identically
   regardless of surface switches.

### 5. Model provider registry

Model choice is config, not code: aliases (`facty-large`, `facty-local`, …) map
to pydantic-ai providers / Vibe `[[providers]]` entries (any OpenAI-compatible
`api_base` + key env). BYO open-weight models are first-class; **local in-VM
serving** (ollama / llama.cpp / vLLM on `localhost`) is the zero-egress,
maximum-sovereignty option. Non-US hosted providers ride the per-deployment
egress allow-list + host-secret substitution (ADR-0005). **US closed models
are not a support target**: they are absent from the default allow-list and
default profiles and facty contains no special-casing for them — they work only
if a user explicitly allow-lists an endpoint (the OpenAI-compatible API is the
lingua franca, so this costs zero code either way).

### 6. TrustGraph: deferred, with re-evaluation triggers

TrustGraph (Apache-2.0, surveyed 2026-11-17 — see deps-log) was **not adopted**:
it has no rule/reasoning engine (SPARQL service is query-only, in-memory joins
over triple-pattern lookups; "not a full OWL reasoner") and no time-travel
versioning (live graph table has no version column; context cores are
timestamped snapshots, not a commit DAG). Its strengths — ingestion decoders,
PROV-O lineage, SHACL-AF policy filtering, workspace IAM, decider models —
are all solvable more simply for now (docling/unstructured libs, our custody
layer, signed bundles, our sensor ladder). **Re-evaluate when:** we serve
multi-tenant at scale (workspaces/IAM/policies on Cassandra), need PROV-O
pipeline lineage at evidence-mill scale, or want its Laya/cloze deciders as an
alternative to the Strom/label tiers.

## Considered options

- **TrustGraph as the store replacing TerminusDB** — rejected: loses WOQL
  reasoning and git-for-data (invariants 1 and 3), adds Pulsar+Cassandra+Qdrant+S3
  footprint that doesn't fit the single-image SmolVM model.
- **TrustGraph as evidence mill only** — deferred per §6 triggers.
- **Hand-rolled pipeline runner** — rejected: reinvents Dagster's DAG/retries/
  lineage/checks/CI.
- **dbt** — rejected as chassis: SQL-over-warehouse doesn't fit decode→OCR→
  embed→LLM steps. DuckDB inside one Dagster asset covers future SQL transforms.
- **Custom MCP glue instead of built-ins** — rejected: TerminusDB ships MCP;
  dagster-mcp exists; write our own MCP server only for facty case-level ops.

## Consequences

- Positive: no ETL wheel reinvented; one op set behind CLI/UI/MCP (parity by
  construction); determinism is explicit per-turn data with an auditable mode
  trail; providers are user config; the image stays the portable artifact.
- Costs accepted: more moving parts in the image (dagster + two MCP servers +
  `facty serve`); two lineage systems exist (Dagster run history vs TerminusDB
  commits) — **TerminusDB is authoritative**, Dagster is telemetry; `facty
  selftest` replays from TDB commits only.
- Neutral: harness swappable later without touching engine/CLI.

## Validation

- `facty selftest` stays green (byte-identical replay from commits) after the
  dispatcher lands.
- Parity checklist in CI: every CLI op has a `facty serve` endpoint and an MCP
  tool; every machine-loop capability has a human-loop path through the harness.
- Replay test: a mixed-mode case session replays deterministically with
  `FACTY_SENSE=cache`.

## References

- Worked exemplar (happy path): [docs/USE-CASE-DOC-ASSEMBLY.md](../USE-CASE-DOC-ASSEMBLY.md)
  — interactive legal document assembly (Docassemble / BC CRT Solution
  Explorer style; Gavel→Relativity), mapping the triadic runtime onto
  pack → case branch → Dagster ingest → abductive discovery threads →
  deterministic assembly → data-product asset.
- deps-log 2026-11-17 entries: TrustGraph survey, Dagster portability/MCP,
  TerminusDB built-in MCP plugin (`terminusdb/terminusdb` `builtin_plugins/mcp.pl`,
  `docs/MCP_UAT_PLAN.md`).
- docs.dagster.io: Dagster Pipes, instance config (`dagster.yaml`), deployment
  (local/Docker/K8s helm/gRPC/Cloud); PyPI `dagster-mcp`.
- terminusdb.com: ai-agent-setup, WOQL/Datalog docs, version control docs.
