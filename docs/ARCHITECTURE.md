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

## Why socket-path-only mattered (historical, ADR-0001)

Under gondolin's pid-based session GC, sandbox signal failures could delete
live sessions' registry files; socket-path IPC avoided it. SmolVM machines are
addressable by name, so the issue does not arise; the rule's spirit (never
signal foreign processes from a sandbox) still applies.
