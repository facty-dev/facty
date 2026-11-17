# Architecture — Facty on SmolVM (ADR-0005)

> The gondolin/pi isolation model this page used to describe is retired
> (ADR-0005, 2026-10-30): `gondolin/`, `scripts/vm-session.sh`, and
> `scripts/agent-pi.sh` are deleted. ADR-0001's socket-path-only rule is
> superseded accordingly. The pack-factory agents port to Vibe-in-SmolVM (T9,
> docs/CLEANROOM-METHOD.md).

## The model

```
┌────────────────────────────── HOST ──────────────────────────────┐
│                                                                    │
│  User's terminal            SmolVM machine (one OCI image)        │
│  ┌────────────────────┐    ┌──────────────────────────────────┐  │
│  │ docker build -t    │    │ rootfs: Alpine + python3.14 +    │  │
│  │   facty .          │───►│   facty (src/facty) + vibe CLI   │  │
│  │ docker save facty  │    │ + terminusdb-server (in-VM)      │  │
│  │   | smolvm machine │    │                                  │  │
│  │   run --net --image│    │ /workspace = repo (rw, mounted)  │  │
│  │   - -- bash        │    │ guest env: MISTRAL_API_KEY =     │  │
│  └────────────────────┘    │   <placeholder> (host-secret —   │  │
│                             │   OPEN ITEM, see ADR-0005)       │  │
│  real MISTRAL_API_KEY       │ egress: api.mistral.ai,          │  │
│  (host-side only) ─────────►│   registry.npmjs.org,            │  │
│                             │   api.uprelic.com (allow-list;   │  │
│                             │   no web search — sensitive data)│  │
│                             └──────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

- **One SmolVM machine per workspace**, booted from the root `Dockerfile`;
  persistent machines via `smolvm machine create --net --name facty` +
  `smolvm machine start` + `smolvm machine exec --name facty -- <cmd>`;
  one-off: `docker save facty | smolvm machine run --net --image - -- bash`.
  Branchable/checkpointed micro-VMs replace gondolin sessions.
- **TerminusDB runs inside the VM** (started by `entrypoint.sh`, storage at
  `/app/terminusdb/storage`); `compose.yaml` runs the same two processes as
  plain Docker services for host-side iteration.
- **Secrets**: host-side placeholder + host proxy substitution (the SmolVM
  host-secret flag mapping is the open item in ADR-0005). Never log, echo, or
  read API keys; local dev exports the subscription token from
  `~/.pi/agent/auth.json` (see AGENTS.md).
- **Egress allow-list** unchanged: api.mistral.ai + registry.npmjs.org +
  api.uprelic.com. No web-search tooling — cases handle sensitive data.
- Engine + CLI: `./facty` → `src/facty` (stdlib-only core; pydantic-ai sensing;
  Vibe CLI for human-in-the-loop). Persistence/audit = TerminusDB commits
  (git-for-data), not files.

## The triadic runtime (ADR-0010, proposed 2026-11-17)

Inside the same VM, three planes glued through MCP and one op set
([ADR-0010](adr/0010-triadic-runtime-parity.md)):

```
┌─ harness plane ─────────────────────────────────────────────┐
│  Vibe CLI (human surface; any MCP-capable harness later)     │
│     │ MCP stdio                  │ MCP stdio                 │
│     ▼                            ▼                           │
│  terminusdb MCP (built-in)    dagster-mcp (evidence plane)   │
│     │                            │                           │
│     └────────► facty serve ◄─────┘  one op set, one          │
└───────────────────┬─────────────────────────────────────────┘
                    │ CLI / Web UI / machine loop (pydantic-ai)
                    ▼ turn dispatcher (reads Step.mode per turn)
   TerminusDB case branch = system of record (commits, signed
   config docs); Dagster assets commit via a TDB resource
```

- **TerminusDB** — store, ontology, WOQL reasoning, audit. Built-in MCP
  plugin (`builtin_plugins/mcp.pl`, stdio + `POST /api/mcp`).
- **Dagster** — evidence pipelines as a thin shell over framework-agnostic
  asset functions; per-case pipeline config is a signed doc on the case
  branch; TDB commits are the authoritative lineage (Dagster run history is
  telemetry); `dagster-mcp` stdio in-VM; headless fallback runner = no Dagster.
- **Parity invariants**: CLI ↔ Web UI (both are clients of `facty serve`);
  MCP coverage ↔ op set; machine loop ↔ human loop (same interfaces; humans
  answer `Question` docs as UI questionnaires — slot filling).
- **Turn modes** per signed step config: `deterministic` (engine only,
  byte-identical replay) / `ranked` (engine-constrained pick, recorded) /
  `free` (LLM sensing only). Verdict-path turns are always `deterministic`.
- **Providers are config**: model aliases → pydantic-ai/Vibe providers; BYO
  open-weight and local in-VM serving (ollama/llama.cpp/vLLM, zero egress)
  first-class; non-US hosted via per-deployment egress allow-list +
  host-secret; US closed models not supported by default (absent from the
  default allow-list, no special-casing in code).
- **TrustGraph deferred** (no reasoner, no versioned history — see deps-log
  2026-11-17); re-evaluate on multi-tenant scale / evidence-mill lineage /
  decider-tier needs.

## Why socket-path-only mattered (historical, ADR-0001)

Under gondolin's pid-based session GC, sandbox signal failures could delete
live sessions' registry files; socket-path IPC avoided it. SmolVM machines are
addressable by name, so the issue does not arise; the rule's spirit (never
signal foreign processes from a sandbox) still applies.
