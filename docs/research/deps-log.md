# Cleanroom stack — dependency docs log

Hard rule (AGENTS.md critical rule 8): read each dependency's official docs
in detail before building on it; log version + what was read + the facts that
touch our code. Search snippets don't count. Date of this log: 2026-10-29.

## TerminusDB — `terminusdb/terminusdb-server:v12` (Apache-2.0)

Docs read (2026-10-29):
- `https://terminusdb.com/llms.txt` (agent index; points at llms-full.txt and per-page `page.md`)
- `github.com/terminusdb/terminusdb-docs` (docs source; `guides/reference-guides/document-interface.md`, `cli.md`)
- `github.com/terminusdb/terminusdb-client-python` — `client/Client.py`, `woqlquery/woql_query.py`, tests (`test_Client.py`, `test_Schema.py`) — the authoritative endpoint/JSON shapes
- Server repo `src/server/routes.pl`

Facts that touch `` code:
- Docker: `docker run -p 127.0.0.1:6363:6363 -v terminusdb_storage:/app/terminusdb/storage terminusdb/terminusdb-server:v12`; default creds **admin/root**; port **6363**. → Dockerfile/compose fixed to v12 + `/app/terminusdb/storage`.
- REST descriptor: `<org>/<db>` defaults to `<org>/<db>/local/branch/main`. Document endpoint: `POST /api/document/{org}/{db}/local/branch/{branch}?author=..&message=..&graph_type=instance&create=..&raw_json=..`. → `client.py` paths fixed.
- WOQL endpoint: `POST /api/woql/{org}/{db}/local/branch/{branch}` (body = WOQL JSON; optional `commit_info` wrapper to commit query results). → `client.py` fixed.
- Schema key syntax: `"@key": {"@type": "Hash", "@fields": ["id"]}` (Hash uses `@fields`, not `@keys`). → `schema.py` confirmed correct.
- WOQL AST field names (from `woqlquery/woql_query.py`): `Triple{subject,predicate,object}`, `And{and}`, `Or{or}`, `Select{variables}`, `OrderBy{ordering:[{variable,order}]}` — **not `order_by`**, `GroupBy{group_by,grouped,group_template,query}`, `Isa{element,class}`, `Eq{left,right}`, `Not{not}`. → `woql.py` fixed (`ordering`, group_by keys).
- Server is Prolog; WOQL variables use Prolog unification; stratified negation. Reasoning = Datalog rules/constraints at query time (no ASP choice/optimization — confirmed gap, clingo stays optional).
- Git-for-data: branch/squash/rebase/clone/push/pull, `_commits` graph queryable via WOQL, time-travel via `local/commit/<id>`.

### Live-verified against terminusdb-server v12.0.9 (docker, 2026-10-29) — divergences from the docs found by doing:

- Schema install: `POST /api/schema/{org}/{db}` → HTTP 500. Correct v12 path: POST the schema
  to the **document endpoint** `/api/document/{org}/{db}/local/branch/main?graph_type=schema&author&message`.
- `create_db` needs `"schema": true` or there is no schema graph (hence the 500).
- Field types: `Array` is gone — use `{"@type":"Set","@class":"xsd:string"}` (sets are optional by nature;
  do NOT wrap a Set in Optional — Optional's `@class` must be scalar/class text). Subdocument classes
  need `@subdocument: []` AND their own `@key` (e.g. `{"@type":"Random"}`) or "Subdocument @key missing".
- Writes: POST with an existing `@key` → 400 DocumentIdAlreadyExists (even with create=false);
  PUT replaces but 404s if missing; `full_replace=true` on POST **wipes the whole graph** — do not use.
  Upsert = try PUT, on 404 fall back to POST. Generated `@id` is read-only: strip it before writing.
- Reads: `GET /api/document/...?graph_type=instance&as_list=true` returns one JSON array (default is a
  pretty-printed NDJSON-ish stream). Subdocument class references (non-@subdocument classes) come back as
  id references even with unfold — fetch by `?id=<docid>` if needed. Embedding a Fact inside an Action
  creates a real Fact node — use a separate @subdocument FactTemplate for derive blueprints.
- Branch: `POST /api/branch/{org}/{db}/local/branch/{name}` with `{"origin":"{org}/{db}/local/branch/main"}`;
  branch names cannot contain `/`. Log: `GET /api/log/{org}/{db}/local/branch/{name}`. Time-travel:
  `local/commit/{id}` works on document and woql paths.
- WOQL: body must be a **Select-topped** bare AST (bare And → 400 "Missing parameter: query";
  non-Select must be wrapped as `{"query": ...}`). Variables are objects:
  `{"@type":"NodeValue","variable":"F0"}` / `{"@type":"Value","variable":"F0id"}`, literals
  `{"@type":"Value","data":{"@type":"xsd:string","@value":"x"}}`, predicates
  `{"@type":"NodeValue","node":"subject"}`. `Isa` and `@type` triples do not parse in this build —
  discriminate Fact by binding its unique `confidence` field. Bindings: string fields come back as
  `{"@type":"xsd:string","@value":"f03"}`, node refs as plain strings.
- `/api/ok` health check works with basic auth admin:root (v12 docker default).
- Format notes from the live e2e (2026-10-29): packs are stored as native JSON-LD
  (`@type` docs, typed `valueString/valueBool/valueNum`, decimal `confidence`) —
  load = plain insert, no conversion layer. `FactTemplate` is a @subdocument
  *without* `source` so Fact can be discriminated in WOQL by `source` existence
  (Isa/@type triples don't parse; FactTemplates would otherwise match as facts).
  Runtime-opened questions are top-level `OpenQuestion` (subdocuments can't be
  inserted standalone: "InsertedSubdocumentAsDocument"). Rules/constraints are
  applied in sorted-id order — Set read-back order is not stable. Support counts
  are recomputed from scratch each run (never incremented onto the persisted
  value) so re-runs are idempotent.

## Logfire (Pydantic AI observability) — optional, `logfire` package

Docs read (2026-10-30): `pydantic.dev/docs/logfire/integrations/llms/pydanticai/`,
alternative-backends how-to. Facts: `logfire.configure()` must run **before**
`logfire.instrument_pydantic_ai()`; the SDK is standard OTel, so
`OTEL_EXPORTER_OTLP_ENDPOINT` retargets it to any self-hosted backend;
`configure(send_to_logfire=False)` keeps data off the hosted platform.
Cleanroom default: off (`FACTY_LOGFIRE=1` to enable; `hosted` for the platform) —
the VM egress allow-list has no observability endpoint. Token usage comes from
`result.usage` (a **property**, `RunUsage`, in pydantic-ai v2.63 — not callable).

## SmolVM — `smol-machines/smolvm` v1.29.0 (Apache-2.0; npm `smolmachines`, pypi `smolmachines`)

Docs read (2026-10-29):
- `github.com/smol-machines/smolvm` README + `docs/README.md` (skill-packet layout, `llms.txt`)

Facts:
- CLI: `smolvm machine run --net --image alpine -- uname -a`; persistent: `smolvm machine create --net --name dev && smolvm machine start --name dev && smolvm machine exec --name dev -- <cmd>`.
- Local OCI images without a registry: `docker save myapp | smolvm machine run --image - -- ./app`. → spike-01/README use this for the cleanroom image.
- Features: sub-second boot, elastic memory, checkpoints (`docs/incremental-checkpoints.md`), named networks, S3/R2 mounts (`-v s3://bucket:/data`).

## PydanticAI — `pydantic-ai` (2026-10; install `pydantic-ai` or `pydantic-ai-slim[mistral]`)

Docs read (2026-10-29):
- `https://ai.pydantic.dev/llms.txt` (full index), `docs/ai/models/index.md`, `docs/ai/models/mistral/index.md`, `docs/ai/core-concepts/agent/index.md`, `docs/ai/core-concepts/output/index.md`

Facts:
- Mistral provider: model string `mistral:<canonical-name>` (e.g. `mistral:mistral-large-4`), env var **`MISTRAL_API_KEY`**; slim needs extra `pydantic-ai-slim[mistral]`. → `sensing.py` model string + env confirmed.
- `Agent(model, instructions=..., output_type=..., retries=...)`; `run_sync()`; output validated against `output_type` (Pydantic), retries on invalid *shape* only — induction side, never the verdict path. `output_type=str` = plain text. → `sensing.py` matches.
- Requires Python 3.11+ → cleanroom's >=3.14 is fine.
- Live-verified 2026-10-29: the Mistral provider needs the optional package — install
  `pydantic-ai[mistral]` (provides `mistralai`); plain `pydantic-ai` raises ImportError at
  `infer_model("mistral:...")`. Model string `mistral:mistral-large-4` + env `MISTRAL_API_KEY` works.

## Mistral Vibe CLI — `mistralai/mistral-vibe` (installed via `uv tool install mistral-vibe`)

Docs read (2026-10-29):
- `https://docs.mistral.ai/vibe/code/overview` + the in-CLI `vibe:vibe` skill (authoritative internals: CLI params, agents, config)

Facts:
- Headless one-shot: `vibe -p TEXT --agent NAME --max-turns 1 --output text|json|streaming --trust`; programmatic mode never prompts; `VIBE_ACTIVE_MODEL` env overrides the model; project-local `.vibe/config.toml` + `.vibe/agents/*.toml` load when cwd is trusted (`--trust`).
- `active_model` is an **alias**; `[[models]]` maps alias → canonical name (`mistral-large-4`) + provider + thinking. → `.vibe/config.toml` (`facty-large`) confirmed.
- MCP servers via `vibe mcp add NAME --transport stdio --command ...` (for the pack-author agent's TerminusDB access); connectors auto-discovered on the mistral provider.
- Human-facing surface only; machine-driven LLM calls go through pydantic-ai (see docs/IMPLEMENTATION.md).

## Typer — `fastapi/typer` 0.27.3 (CLI framework; PO directive 2026-10-31: use the standard uv-ecosystem CLI framework)

Docs read (2026-10-31): https://typer.tiangolo.com/ , /tutorial/ , /tutorial/first-steps/ ,
/tutorial/commands/ , /tutorial/subcommands/ , /tutorial/options/ , /tutorial/arguments/ ,
/tutorial/testing/ , /tutorial/exceptions/ ; API shapes verified against the installed
package source (`typer/main.py::get_command_name`, `Typer.add_typer`, `typer.Exit`, `typer.testing.CliRunner`).

Facts:
- Install is literally `uv add typer` (the docs' own instruction); pulls click + rich + shellingham.
- `app = typer.Typer(no_args_is_help=True)`; `@app.command()`; command name = function name with `_`→`-` (verified: `init_db` → `init-db`); groups via `sub = typer.Typer(); app.add_typer(sub)` (no name needed — group name comes from the variable).
- Params from type hints + `Annotated[..., typer.Option("--x")]` / `typer.Argument()`; `Path`, `bool` flags, `Optional[str]` all supported.
- Exit codes: `raise typer.Exit(1)`; rich pretty-exceptions ON by default, and `pretty_exceptions_show_locals` defaults to **False since 0.23** (secrets never shown in errors) — we set it explicitly False; disable rich with `TYPER_USE_RICH=0`.
- Tests: `from typer.testing import CliRunner; CliRunner().invoke(app, [...])` (wraps click's runner).
- Shell completion: `--install-completion` / `--show-completion` built in.
- → `src/facty/cli.py` rewritten on Typer; `[project.scripts] facty = "facty.cli:main"`; all prior commands/flags preserved; smoke tests in tests/test_cli.py.

## TerminusDB v12 — additional live-verified quirks (2026-10-31, M2)

- `DELETE /api/branch/{org}/{db}/local/branch/{name}` works (curl-verified), but a
  request with `Content-Type: application/json` and NO body hangs the server —
  the client now sends `Content-Length: 0` and no Content-Type for bodyless
  DELETE/POST (`client.py::_req`).
- v12 has NO branch-listing endpoint (`GET /api/branch/...` → 405) — cases are
  tracked as `Case` registry docs on `main` instead (`cases.py`).
- `DELETE /api/document/...` requires `author` + `message` query params, and the
  `id` must be the full Hash-keyed `@id` (`Case/<sha256>`), not the logical id.

## Framework choice — pydantic-ai confirmed (2026-11-06, PO question)

Surveyed (web, 2026-11-06: langfuse agent-framework comparison + ecosystem data):
LangGraph/LangChain dominate mindshare but optimize for LLM-as-controller agent
loops — the opposite of our neurosymbolic split. Pydantic AI is the one praised
for "explicit type contracts, tests, quick feedback loops" — exactly our shape
(LLM = typed induction function via output_type, tools=[], engine owns verdict).
Instructor is the closest alternative (same pydantic-output idea); DSPy adds
probabilistic prompt *optimization* (a compile step) — not needed while the
engine is deterministic. Decision: keep pydantic-ai; no change.

## TerminusDB embeddings — v12.1 RC only (live-verified divergence, 2026-11-06)

Read https://terminusdb.com/docs/versioned-search-embeddings/ (full page).
Facts: schema-driven embeddings via `@metadata.embedding` {GraphQL `query` (NO
commas allowed), Handlebars `template`}; gate = `"store_indices"` in
`@context @metadata.terminusdb.options`; default model `multilingual-e5-base`
(Q8 GGUF, `passage:`/`query:` prefixes automatic); versioned per commit
(deterministic replay of history); `VECTORLINK_EMBED_CACHE_SIZE` default 20k;
re-embedding on schema change; search answers "what is this about", not
find-by-ID (use WOQL for that).
DIVERGENCE: the page is marked "Release Candidate — TerminusDB 12.1" and our
pinned server reports version 12.0.9 (api/info) — POSTing a schema with
`store_indices` fails with "Unexpected failure in request handler". So on v12 we
embed on the BYO-key path instead: Mistral embeddings API (`mistral-embed`),
disk-cached per text (.cache/embeddings/), vectors content-addressed in the
object store, `EvidenceChunk` docs in TerminusDB, cosine client-side (case scale
= a drawer). All induction-side; verdict path never reads embeddings. Upgrade
path: TerminusDB >= 12.1 → native versioned embeddings. Implemented in
src/facty/search.py; `facty search`, `facty sense --rag`, ingest auto-embeds.

## TerminusDB 12.1.0-rc2 upgrade (2026-11-06, PO approved RC) — live-verified

- Image `terminusdb/terminusdb-server:v12.1.0-rc2` (2026-11-03, latest non-dev tag
  per Docker Hub); compose.yaml + Dockerfile bumped; container re-created; api/info
  reports 12.1.0-rc2. Selftest PASS x4 + e2e DETERMINISM OK on the new version.
- Native versioned search (VectorLink) findings, docs read in full
  (versioned-search, versioned-search-embeddings, versioned-search-indexing,
  versioned-search-quickstart, versioned-search-api-reference):
  schema `@context` with `"store_indices"` must be POSTed to the ROOT document
  endpoint (`/api/document/{org}/{db}?graph_type=schema&full_replace=true`) —
  branch paths reject contexts ("Inserting contexts is not allowed");
  class `@metadata.embedding` = {GraphQL query (NO commas), Handlebars template};
  search = `GET /api/search/{org}/{db}/{ref}?q=..&snippet=true&type=..`;
  index status = `GET /api/index/...`; vectors via `/api/plugin/search-embeddings`.
  In-process engine: `TERMINUSDB_INDEXER_BACKEND=vectorlink` (without it:
  "vectorlink endpoint is not configured"); with it, indexing runs but
  searchable_documents stays 0 until an embedding provider is attached (quickstart
  uses a separate Ollama `embeddings` service; model GGUF from hf.co).
- DECISION: we keep our BYO-key Mistral-embeddings + content-addressed-vectors +
  client-side cosine (works on any version, disk-cached = deterministic replay,
  no HF egress needed — the VM allow-list excludes huggingface.co). Schema now
  carries store_indices + embedding metadata on Fact/ExtractedText so the native
  index is ready when an embedding provider is configured. ADR-0009.
- 12.1 keeps all v12.0.9 endpoint quirks we logged (Set not Array, PUT/POST upsert,
  Hash-keyed @id for deletes, branch path shapes) — selftest green confirms.

- OPERATIONAL (12.1.0-rc2): setting TERMINUSDB_INDEXER_BACKEND=vectorlink WITHOUT an
  embedding provider wedges the server (post-commit indexer worker hangs; /api/ok
  stops answering). Plain 12.1.0-rc2 with store_indices in the schema but no backend
  is fine — commits succeed, /api/index reports the endpoint as unconfigured.
  compose.yaml therefore keeps the backend OFF (commented) until an embedding
  service is added.

## Embedding model CPU question (2026-11-06)

TerminusDB 12.1 default native model `multilingual-e5-base` (278M) is served as a
first-party Q8_0 GGUF from hf.co/vectorlink — 768-dim vectors, 768 bytes quantized;
the official quickstart runs it CPU-only with no external network after the
one-time model pull. So yes: the default runs on CPU. (Our runtime path uses
Mistral's hosted `mistral-embed` via BYO-key instead; swappable via
FACTY_EMBED_MODEL / the schema embedding metadata.)

## Embedding model choice + portability (2026-11-06, PO: local model OFF by default, dims portable, model at least open-weight)

- mistral-embed (our BYO-key default, FACTY_EMBED_MODEL): API returns fixed
  **1024-dim** vectors; the underlying weights are published open-weight by
  Mistral as `mistralai/Mistral-Embed` on HuggingFace under **Apache-2.0**
  (Mistral's open models are Apache-2.0 per help.mistral.ai). Satisfies
  "at least open weight".
- Local/native default (TerminusDB 12.1 VectorLink): `multilingual-e5-base`,
  278M params, **768-dim**, **MIT** (inherited from intfloat/multilingual-e5-base),
  Q8_0 GGUF runs CPU-only. OFF by default in compose.yaml (needs an embedding
  provider service otherwise it wedges the server — see above).
- PORTABILITY implemented: every stored vector blob records {model, dim}; Fact
  and EvidenceChunk docs carry embeddingModel + embeddingDim; search_case and
  semantic_contradictions only compare vectors of the SAME model and dim
  (mismatched vectors are skipped, never compared cross-dim). Switching
  FACTY_EMBED_MODEL re-embeds new content under the new model and leaves old
  vectors inert. Tested (test_mixed_model_vectors_never_compared).

## TrustGraph — `trustgraph-ai/trustgraph` v2.11 (Apache-2.0) — surveyed 2026-11-17, DEFERRED (ADR-0010 §6)

Docs read: repo README + `docs/tech-specs/*` (sparql-query, ontology*, entity-centric-graph, extraction-flows, audit-events, knowledge-core-completeness, data-ownership-model); docs site via `trustgraph-ai/docs.trustgraph.ai` repo (architecture/*, learn/*, guides/{knowledge-graphs,structured-processing,context-cores,policy-filtering,flows,decision-scoring}, deployment/{compose,choosing-deployment,production-considerations}, reference/{containers,maturity}, benchmarks). Code read via GitHub API: `trustgraph-flow/trustgraph/{query/sparql,storage/triples,policy,cores,librarian,extract,gateway,tables,direct/cassandra_kg.py}`.

Facts that touch our code/decisions:
- **No reasoning engine.** SPARQL service (`query/sparql/service.py` + `algebra.py`) = query-only: parse SPARQL 1.1 → triple-pattern lookups → in-memory joins; handler registry has BGP/Join/LeftJoin/Union/Minus/Filter/Group — no Path/recursion, no rules, no fixpoint. Code search for datalog/prolog/HermiT/Pellet/owlrl: zero hits. README: "not a full OWL reasoner". OWL = rdflib parse + structural validation (no circular subClassOf, domain/range reference existing classes) + per-chunk subset selection (fastembed) to guide LLM extraction + reject violating triples. SHACL-AF only for policy filtering (`policy/policy_filter.py`, `sh:SPARQLTarget`/`sh:SPARQLRule` on user context, tri-state Allowed/Filtered/Violation, `urn:graph:policy`).
- **No time-travel versioning.** Live graph table (`entity_table`: PK `((collection, entity), role, p, otype, s, o, d, dtype, lang)`) has no version column; writes LWW, deletes remove rows; no tombstones/soft-delete. Only timestamped snapshots: `triples` table `(workspace, document_id, id uuid, time, metadata, triples)` = context cores (msgpack/.tgx export/import, 3 states offline/online/loaded). Audit = pub/sub audit-events topic (fire-and-forget, unordered across partitions) + PROV-O lineage in `urn:graph:source` / retrieval traces in `urn:graph:retrieval`. Code search for branch/merge/rebase/squash/commit in storage: empty.
- **Storage**: pluggable graph store — Cassandra (own entity-centric single-table overlay; maturity page: "not a graph store per se"), Neo4j, Memgraph (prod-ready), FalkorDB (limited); vectors Qdrant/Milvus; rows Cassandra; objects S3/Garage via librarian; **Pulsar is the mandatory message backbone**. Compose baseline 12GB+ RAM / 8 CPU. No MCP server found in-repo.
- **Ingestion** (the real strength): docling/unstructured decoders, OCR container, chunking, ontology-guided KG extraction, structured rows, turtle/trig import, library docs; flows/blueprints = configurable pipelines. Benchmarks: ingest is LLM-throughput-bound.
- **IAM/workspaces**: JWT (Ed25519) + API keys, reader/writer/admin roles, workspace-scoped queues + storage partitioning + gateway enforcement; SHACL-AF query policies. Mature — the reason to revisit at served multi-tenant scale.
- Decision: defer (ADR-0010 §6). TrustGraph is an ingestion/RAG/governance platform, not a verdict store; TerminusDB keeps reasoning + git-for-data. Its deciders (Laya ONNX ~35ms, cloze DistilBERT) overlap our Strom/label tiers.

## Dagster — `dagster` + `dagster-mcp` (Apache-2.0) — surveyed 2026-11-17 (ADR-0010 §1)

Docs read: docs.dagster.io (Dagster Pipes overview, dagster-instance/`dagster.yaml`, deployment guides), PyPI `dagster-mcp`, changelog.

Facts that touch our code:
- Pure Python, pip-installable; runs anywhere Python runs (containers, SmolVM image, bare metal). **Bake into the OCI image at build time** — the VM has no PyPI egress at runtime (allow-list only).
- Instance storage pluggable via `$DAGSTER_HOME/dagster.yaml`: SQLite file (default, zero infra, single-writer — fine per VM) → Postgres/MySQL when shared. First natural "app CRUD" DB if one is ever needed.
- Execution/deployment: local (`dagster dev`/CLI), Docker code locations, Kubernetes (dagster-k8s + official Helm chart, run-per-op pods), gRPC code locations, Dagster Cloud (managed/hybrid). GraphQL API + sensors for triggering from other systems.
- **Dagster Pipes**: external code in any language/on any machine can be invoked from an asset and report materializations back — external code need not know Dagster. Anti-lock-in hatch for embedding in enterprise workflows.
- **`dagster-mcp` (PyPI)**: OSS MCP server wrapping a local instance — tools for listing assets/jobs, launching runs, reading logs. Run as stdio in the VM (`vibe mcp add`-style). Officially-supported MCP is the Dagster+ hosted one (`mcp.agent.dagster.cloud/mcp`) — unreachable from the VM (egress allow-list), so OSS stdio is the path.
- Portability rule adopted (ADR-0010): asset *logic* = plain framework-agnostic functions over the TerminusDB client; Dagster is a thin shell; pipeline code in git, per-case config as signed TDB docs; headless runner can execute the same docs without Dagster. TDB commits = authoritative lineage; Dagster run history = telemetry only. Verdict path never runs inside Dagster.

## TerminusDB MCP — built into the v12 server (`terminusdb/terminusdb` `builtin_plugins/mcp.pl`) — verified 2026-11-17

Docs read: `docs/MCP_UAT_PLAN.md`, `builtin_plugins/mcp.pl`, `src/cli/main.pl` in `terminusdb/terminusdb`; terminusdb.com `ai-agent-setup`, `llms.txt`.

Facts that touch our code:
- MCP is a **built-in plugin of the server binary**: transport-neutral JSON-RPC 2.0 core (`initialize`, `ping`, `tools/list`, `tools/call`) with two adapters — **stdio** (`run_stdio`) and **HTTP `POST /api/mcp`**.
- Tools wrap the full API surface: db create/list/delete, schema, document CRUD/patch, **WOQL query**, versioned search, branch create/delete, rebase, squash, log, reset, export/import. Their UAT runbook has an agent run the whole lifecycle over MCP alone.
- Consequence: in the SmolVM image, run `terminusdb` MCP over **stdio** and attach with `vibe mcp add <name> --transport stdio --command …` (already the plan in ADR-0005/deps-log for the pack-author agent). No extra package, no extra egress.
- No `terminusdb-mcp` package on PyPI under that name — the server itself is the MCP server.

## TerminusDB v12 WOQL comparisons (Less/Greater/Gte/Lte) — read + live-verified 2026-11-17

Context: Slice 1 demo pack (`bundles/small-business-contract-claim`) needs a numeric
comparison in a rule (`invoice.amount < jurisdiction.smallClaimsLimit`); the rule DSL
previously had equality/`var` only.

Read: `terminusdb/terminusdb` tag v12.1.0-rc2, `src/core/query/json_woql.pl`
(`json_type_to_woql_ast('Less'|'Greater'|'Gte'|'Lte', …)` — operands under `left`/`right`,
compiled to Prolog `'<'/'>'/'>='/=<`); arithmetic siblings Plus/Minus/Times/Divide/Div.
Note: the old `terminusdb-client` 10.2.6 PyPI sdist has NO comparison builders (legacy
WOQL only) — do not use it as a reference for v12 JSON-LD shapes. GitHub release tags
carry no binary assets; the server runs from the Docker image
(`terminusdb/terminusdb-server:v12.1.0-rc2`, via `compose.yaml`).

Live-verified against terminusdb-server v12.1.0-rc2 (docker, :6363): with
`{"@type":"Less","left":{"@type":"Value","variable":"V"},"right":{"@type":"Value","data":{"@type":"xsd:decimal","@value":20000}}}`
inside an `And` next to the valueNum triple, a fact with valueNum 18500 matches `Less`
and `Lte`, not `Greater`. Shapes `{"@type":"LessThan","less_than":[…]}`, `Lt/lt`,
`LessThanOrEqual/…` are REJECTED (HTTP 400 `vio:WOQLSyntaxError`) — v12 renamed them.

Implemented: `woql.compare(op, left, right)` + `woql.fact_value_pattern(...)`;
`rules._condition_parts` handles `{"cmp": "lt|le|gt|ge", …}` with either a literal
(`valueNum`/`valueString`/`valueBool` on the condition) or a fact-to-fact comparison
(`compareToSubject`/`compareToPredicate`, `valueField` default `valueNum`), in
`compile_when` / `compile_constraint_when` / `compile_claim`. All five paths
(literal-cmp rule, fact-to-fact rule, negative case, claim-cmp, constraint-cmp)
verified live on a probe db. Schema: `Condition` gained optional `cmp`,
`compareToSubject`, `compareToPredicate`, `valueField`.

## Web UI stack survey (ADR-0011) — npm metadata + official docs, 2026-11-17

Constraint recap: SmolVM runtime egress = allow-list only (api.mistral.ai,
registry.npmjs.org, api.uprelic.com) → no CDN at runtime; all JS must be baked
into the image at BUILD time (build-time egress is the host's — Dockerfile).
Base image is Debian 12 bookworm with NO node installed → UI build needs a
multi-stage Dockerfile: node 22 in a builder stage, only `web/dist` copied to
the runtime image.

Docs read: svelte.dev/docs/svelte/overview ("a compiler turns declarative
components … into lean, tightly optimized JavaScript" — Svelte 5 is compile-time,
no runtime framework; SvelteKit exists but is not needed since `facty serve` is
the backend); vite.dev/guide/build.html (`vite build` → static bundle servable by
any static host; `base: "./"` for relative asset paths); htmx.org docs + SSE
extension page (htmx 2.x moved SSE to the `hx-ext="sse"` / `sse-connect` extension;
htmx ~14KB min.gz, dependency-free). All read 2026-11-17.

npm registry metadata (latest, registry.npmjs.org, 2026-11-17):

| package | version | license | unpacked | engines | note |
|---|---|---|---|---|---|
| svelte | 5.57.3 | MIT | 2.9MB (dev-only) | node >=18 | compiler; runes $state/$derived/$effect |
| vite | 8.3.8 | MIT | 2.3MB (dev-only) | node ^20.19 \|\| >=22.12 | rolldown-based; static build |
| react / react-dom | 19.3.1 | MIT | 174KB / 7.9MB | | viable but heavier |
| htmx.org | 2.0.11 | 0BSD | ~900KB (~14KB min.gz) | none | SSE via extension |
| lit | 3.3.3 | BSD-3 | 104KB | | web components |
| d3-force | 3.0.1 | ISC | 53KB | none | chosen for the hypothesis graph |
| cytoscape | 3.35.0 | MIT | 5.7MB | | rejected: size |
| elkjs | 0.12.1 | EPL-2.0 OR GPL-3.0 | 8.0MB | | rejected: license + size |
| marked | 18.2.1 | MIT | 592KB | none | packet preview rendering |

Decision (ADR-0011, proposed): Svelte 5 + Vite 8 static build in a Docker builder
stage, served by `facty serve` from `web/dist/`; d3-force + SVG for the graph;
marked for the packet preview; browser print for PDF. No runtime JS deps, no
node in the runtime image.

## Web UI component layer / app shell survey (ADR-0011 addendum) — 2026-11-17

Method: GitHub search sorted by stars + `api.github.com/repos/...` for
license/pushed_at + `registry.npmjs.org` for versions/peers, cross-checked with
2026 "best Svelte UI libraries" lists (dev.to, cssauthor, sveltestarters,
svgrid). All 2026-11-17.

Facts that touch our code:
- **shadcn-svelte** (huntabyte/shadcn-svelte): 9,266★, MIT, pushed 2026-11-16.
  npm `shadcn-svelte` v1.8.1 = the CLI (`npx shadcn-svelte add <comp>` copies
  SOURCE into the project — no registry dependency at runtime). Built on
  **bits-ui** v2.21.0 (3,666★, MIT, peers `svelte` — runes/Svelte 5 native) +
  Tailwind v4. Has a Vite (non-SvelteKit) install guide — matches our plain-Vite
  setup. Component list includes Sidebar, Command, Data Table, Field, Forms,
  **Questionnaire**, **Trace**, and AI Elements (Chat, etc.) — maps 1:1 onto
  our panels. Blocks library ships sidebar app-shell / dashboard blocks.
- **Skeleton v4** (skeletonlabs/skeleton): 6,092★, MIT, pushed 2026-11-17 —
  Tailwind-native design system (tokens, dark mode, theme generator). Docs:
  complements headless libs (bits-ui) but does NOT integrate with Flowbite
  Svelte / daisyUI (class overlap) → pick one styling approach; we pick
  Tailwind v4 + shadcn-svelte, Skeleton optional for theming later.
- Rejected: flowbite-svelte (2,793★ but pushed 2026-06-27 — stale),
  svelteui/sveltestrap (legacy Svelte ≤4 era), attractions (deprecated),
  Svelvet node-graph lib (2,779★ but pushed 2025-02-13 — stale; keep our
  d3-force SVG graph), CMSaasStarter shell (2,377★, active but Supabase/Stripe
  coupled), flowbite-svelte-admin-dashboard (512★, stale 2025-11),
  notus-svelte (868★, stale 2024), salvia-kit (477★, stale 2023). No
  maintained Svelte-native admin shell exists → shell pattern comes from
  shadcn-svelte sidebar blocks.
- Tailwind v4 for plain Vite: `@tailwindcss/vite` 4.3.5, MIT, peers
  `vite ^5.2 || ^6 || ^7 || ^8` (works with our vite 8.3.8). Plus
  `tw-animate-css` 1.4.0 (45KB), `clsx` 2.1.1, `tailwind-merge` 3.7.0 — all MIT.
- Cross-framework pattern references only (not imported): AdminLTE 45.7k★,
  ngx-admin 25.7k★, next-shadcn-dashboard-starter 7.3k★ (all pushed 2026-11).

## Skeleton v4 themes in concert with bits-ui/shadcn-svelte (ADR-0011 theming) — 2026-11-17

Read: skeleton.dev/docs/svelte/design/themes + themes.skeleton.dev + repo tree
`packages/skeleton/src/themes/*.css` (main branch) + shadcn-svelte.com/docs/theming.

Facts that touch our code:
- **24 preset themes ship as plain CSS files**: catppuccin, cerberus, concord,
  crimson, dracula, fennec, hamlindigo, legacy, mint, modern, mona, nosh, nouveau,
  pine, reign, rocket, rose, rosepine, sahara, seafoam, terminus, vintage, vox,
  wintry. Import per theme: `@import "@skeletonlabs/skeleton/themes/{name}";`
  in the global stylesheet; activate with `<html data-theme="{name}">` — a theme
  switcher is just flipping that attribute. Each theme defines light AND dark
  variants in one file (dark mode included, no extra work).
- Themes are pure CSS custom properties under `[data-theme=...]` overriding
  **Tailwind v4's `--color-*` scale** (`--color-primary-500`, `--color-surface-*`,
  plus `--spacing`, `--radius-*`, `--typo-*` tokens). Skeleton's core import sets
  the defaults for the Tailwind `@theme` directive, themes override them → any
  Tailwind-v4-classed component (bits-ui primitives, shadcn-svelte components)
  is themed automatically where it uses the standard scale.
- shadcn-svelte uses its own var convention (`--background`/`--foreground`/
  `--primary`, `background`/`foreground` naming) — to let a Skeleton theme drive
  shadcn-svelte components, map a few lines in our global CSS, e.g.
  `--primary: var(--color-primary-500); --background: var(--color-surface-50);`
  (per theme, inside the same `[data-theme]` scope). tweakcn.com (9.8k★) is the
  shadcn-native visual theme editor exporting Tailwind v4 CSS — drops straight
  into shadcn-svelte; 16+ presets. Both systems are plain CSS, MIT.
- **Theme generator**: themes.skeleton.dev (create + copy CSS into project);
  themes.skeleton.dev also indexes community themes for import.
- Cost note from docs: each registered theme adds CSS bundle size — import only
  the themes actually shipped (we'd register 1–2 + a custom Facty brand theme).
- Fonts via Fontsource (Skeleton's recommendation) — npm, baked at build.
- Candidate presets for a forensic/legal tool: `terminus` (Avenir/Montserrat,
  technical), `sahara` (warm paper — legal-document feel), `cerberus` (neutral
  default); dark variants included in each.

## Mistral Vibe CLI — `mistral-vibe` 3.1.2 (uv tool; harness pkg `mistralai_vibe_local_harness`)

Sources read (2026-11-17):
- `vibe:vibe` skill bundled in the install (`…/site-packages/vibe/plugins/builtins/vibe/skills/vibe/SKILL.md`) — authoritative config/behavior reference; points to github.com/mistralai/mistral-vibe README and docs.mistral.ai/vibe/code/overview
- Installed source: `…/site-packages/vibe/core/config/` (orchestrator.py, layers/, _model_aliases.py) and `…/site-packages/mistralai_vibe_local_harness/vibe/completion_profile/` (compile.py, bounds.py, known_models.py)
- `vibe config schema` (JSON schema of every setting, incl. `$defs/ModelConfig`)
- Live API with MISTRAL_API_KEY: `GET /v1/models`, `GET /v1/model-catalog?surface=vibe-code`
- Verification pattern that costs no LLM call: `vibe -p "ping" --max-turns 0 --trust --output-dir DIR` → `export.json` contains the effective config (models, agents, warnings on stderr)

Facts that touch our code/config:
- **Project config is shared by design**: `.vibe/config.toml` loads only when the folder is trusted; `-p` never prompts, so the sensing fallback runs `vibe -p --agent sensing --trust` with cwd=repo root (`src/facty/sensing.py`) and reads the same file as interactive sessions. Keep it runtime-safe: models/providers/agents only, secrets in `~/.vibe/.env` (host-side). `VIBE_STRICT_CONFIG=1` refuses unknown keys — usable in CI to validate our project config.
- **Layer precedence**: builtin defaults < model-catalog / GrowthBook (session-resolved, read-only) < user `~/.vibe/config.toml` < project `.vibe/config.toml`. `[[models]]` entries merge by `name` (the model key); `alias` is what `/model` and `--model` pick. An alias that is itself a model key, or claimed by two models, resolves to nothing (`_model_aliases.py`).
- **`[[models]]` keys** (ModelConfig schema): `max_context_length`, `auto_compact_threshold`, `max_output_tokens`, `thinking`, `thinking_levels`, `supports_images`, prices, `temperature`, `top_p`.
- **Context window resolution** (harness `compile.py`): explicit `max_context_length` > catalogue entry > known-model table. For `mistral-large-4` all three now agree at **1,048,576** (known table in 3.1.2 + live `/v1/models`, verified 2026-11-17).
- **The status-bar "ctx limit" is the compaction threshold**, not the window: the catalogue/GrowthBook entry `mistral-large-4-0` (aliases `mistral-large-4-0-3`, `mistral-large-4`) ships `auto_compact_threshold=400000` — that was the "400k" we saw. Override the same model key in project config to change it.
- **Threshold bounds** (`bounds.py`): headroom = min(24_000, ceil(window/4)); threshold must be < window − headroom or it is auto-fitted with a warning. Default = min(256_000, window − 60_000). A user-level top-level `auto_compact_threshold` (ours: 200000 in `~/.vibe/config.toml`) applies to every model without its own — set it per-model to override.
- **Thinking levels for mistral-large-4-0 are `low/medium/high` only** (live model-catalog). `"max"` loads with a config warning and the Mistral SDK drops it — highest valid = `"high"`.
- **Agent profiles** live in `.vibe/agents/<name>.toml` (`description`, `safety`, `active_model`, `thinking`, `enabled_tools`, `instructions`); select with `--agent` / `-p --agent`. Our split: `facty-large` model entry `thinking="high"` (dev + pack authoring), `sensing.toml` pins `thinking="low"` (machine loop stays cheap).
- **Our repo settings** (`.vibe/config.toml`): ONE `[[models]]` entry — `name = "mistral-large-4-0"` (the catalogue id; a valid API id), `alias = "facty-large"` (= `active_model`), `thinking = "high"`, `max_context_length = 1048576`, `auto_compact_threshold = 800000`. The map is keyed by alias, so the routed row `mistral-large-4-0-3` keeps Mistral's own 400k threshold if picked manually — accepted, CLI users are devs. The alias exists as the project's stable default name, decoupled from Mistral's dated routed aliases. Verified via the export pattern: `facty-large` → session runtime-state `context_window: 1048576, compaction_threshold: 800000`, no warnings.
- **Machine loops don't read vibe config at all**: pydantic-ai takes the model from code (`mistral:` + `FACTY_MODEL`, default `mistral-large-4`) and per-request settings from `model_settings` — `MistralModelSettings` (pydantic-ai 2.63.0) supports `thinking: bool | 'minimal'|'low'|'medium'|'high'|'xhigh'|'max'`; `src/facty/sensing.py` pins `FACTY_THINKING` (default `"low"`). Only the `vibe -p` fallback backend (`FACTY_SENSE_BACKEND=vibe`) uses the project config, via the `sensing` agent profile (`thinking = "low"` pinned there).
- Env overrides: any setting via `VIBE_` prefix (e.g. `VIBE_ACTIVE_MODEL=facty-large` — used by the sensing fallback).

## MCP (Model Context Protocol) — spec 2025-06-18, implemented by hand in stdlib

Sources read (2026-11-17, via firecrawl scrape of modelcontextprotocol.io):
- `/specification/2025-06-18/basic/transports` — **stdio transport**: client spawns
  the server as a subprocess; JSON-RPC 2.0 messages on stdin/stdout, **delimited by
  newlines, MUST NOT contain embedded newlines**.
- `/specification/2025-06-18/basic/lifecycle` — `initialize` request → response
  `{protocolVersion, capabilities, serverInfo}` (server answers with a version it
  supports if the requested one is unknown); `notifications/initialized` gets **no
  response**; `ping` → `{}`.
- `/specification/2025-06-18/server/tools` — `tools/list` →
  `{tools: [{name, description, inputSchema (JSON Schema, required)}]}`;
  `tools/call {name, arguments}` → result `{content: [{type:"text", text}],
  structuredContent?, isError?}` — **tool execution errors are results with
  `isError: true`, not protocol errors**; unknown method → JSON-RPC `-32601`.

Facts that touch our code (`src/facty/mcp_server.py`, stdlib-only so it runs in
the SmolVM image with no PyPI at runtime; spawned via `facty mcp`):
- One newline-delimited JSON-RPC loop on stdin/stdout; non-JSON lines ignored;
  notifications (no `id`) never answered.
- `initialize` echoes the client's `protocolVersion` if in
  `["2024-11-05","2025-03-26","2025-06-18","2025-11-25"]`, else answers `2025-06-18`.
- `tools/call` wraps `call_tool()`; exceptions → `isError: true` result.
- Parity registry: `TOOLS[*].serve` maps every MCP tool onto its `facty serve`
  path; `tests/test_mcp.py` asserts the serve op registry (`serve.POST_OPS` /
  `GET_OPS`, minus SSE `watch` and meta `ops`) is exactly covered by MCP tools.

## SWI-Prolog inside the TerminusDB image — live-verified 2026-11-17 (ADR-0012)

- `docker exec <terminusdb-container> swipl --version` → **SWI-Prolog 10.0.2
  (aarch64-linux)** at `/usr/bin/swipl`. The terminusdb-server is itself a
  SWI-Prolog saved state, so the image ships the exact runtime the server uses.
- Consequence: a Prolog-dialect translator can run in-image via
  `swipl -l <module>.pl` with **zero new dependencies** — "the same thing
  Terminus itself uses" is literally available as a binary.
- Caveat (already logged in the v12 entry): the server exposes no Prolog-source
  query endpoint — WOQL enters as JSON AST (or GraphQL); Prolog unification
  appears only in variable binding. So a Prolog dialect must be *compiled* to
  WOQL JSON, never executed directly by the server. Design recorded in
  ADR-0012.
