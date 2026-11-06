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
