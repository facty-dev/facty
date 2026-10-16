# Architecture — redyarn on Gondolin micro-VMs

> Key operational decision: [ADR-0001 — session execution under host-side
> sandboxing](./adr/0001-session-execution-under-sandboxing.md).

## The model

```
┌────────────────────────────── HOST ───────────────────────────────┐
│                                                                    │
│  User's terminal                Sandboxed pi session (orchestrator)│
│  ┌────────────────────┐        ┌────────────────────────────────┐ │
│  │ make vm-up         │        │ pi + pi-sandbox (Seatbelt)     │ │
│  │ └─ gondolin bash   │        │ └─ scripts/agent-pi.sh         │ │
│  │    (foreground;    │        │    └─ gondolin exec --sock      │ │
│  │     hosts session) │        │       <SOCKET PATH>            │ │
│  │                    │        │       (bypasses session GC;   │ │
│  │ env: real API key  │        │        never id-based)         │ │
│  │  (or `pi auth`)    │        └───────────────┬────────────────┘ │
│  └─────────┬──────────┘                        │ unix socket      │
│            │                                   ▼                  │
│            │            ┌──────────────────────────────────────┐  │
│            └───────────►│ GONDOLIN VM SESSION                  │  │
│                         │ (booted from pi-sandbox snapshot)     │  │
│            boot-time    │                                      │  │
│            injection ──►│  rootfs: Alpine + pi + ddgr + 88     │  │
│            --host-secret│  skills (~/code/gondolin-pi template) │  │
│                         │                                      │  │
│                         │  /workspace  = redyarn repo (rw)  │  │
│                         │  guest env:  MISTRAL_API_KEY =        │  │
│                         │      <random-placeholder>             │  │
│                         │  egress: api.mistral.ai,              │  │
│                         │      duckduckgo.com(+html/lite),      │  │
│                         │      registry.npmjs.org               │  │
│                         └──────────────────────────────────────┘  │
│                                                                    │
│  Host-side secret flow:                                            │
│  agent → "Authorization: Bearer <placeholder>" → gondolin host      │
│  proxy → substitutes REAL key → api.mistral.ai (only)               │
│                                                                    │
│  Never mounted into the VM: ~/.ssh, ~/.aws, other projects,         │
│  keychains, ~/.pi/agent/auth.json                                   │
└────────────────────────────────────────────────────────────────────┘
```

## Isolation guarantees

| Guarantee | Mechanism | Enforcement |
|---|---|---|
| **Secrets** | `--host-secret NAME@HOST` at session boot | Guest env holds a placeholder only; host proxy substitutes the real value into outbound headers, scoped to allowed hosts |
| **Project** | `--mount-hostfs <dir>:/workspace` | Unmounted host paths do not exist in the guest |
| **Network** | Programmable TCP stack + synthetic DNS | Explicit `--allow-host` list; denied hosts are unreachable |
| **Process** | Hypervisor (QEMU micro-VM; krun optional) | No shared kernel with the host |
| **State** | Snapshot boot (`--resume pi-sandbox.qcow2`) | Fresh, deterministic guest per session; nothing persists unless written to `/workspace` |
| **Host orchestration** | pi-sandbox on the driving session + socket-path-only IPC | The orchestrating agent cannot signal foreign processes (session GC safe), cannot read host secrets, can only exec into the VM |

## Components

| Component | Role |
|---|---|
| `scripts/vm-session.sh` | Session lifecycle: `up` (foreground boot + metadata watcher), `status` (socket liveness probe — sandbox-safe), `exec` (socket-path IPC), `down` |
| `scripts/agent-pi.sh` | Role runner: composes role prompt + assignment (`templates/sdlc/agents/`), execs pi in the VM, appends audit entries to `.agentic/audit.jsonl` |
| `.agentic/vm-session.json` | Session record `{id, pid, socketPath}` written at boot by a user-side watcher; the ONLY sanctioned discovery mechanism from sandboxed sessions |
| `/root/.session-env/` (guest) | Placeholder env stashed at boot; exec'd agents source it (exec commands don't inherit boot env) |
| `~/code/gondolin-pi/` | VM template: snapshot builder + skills (bigpowers 81, ponytail 6, ddgr) — infra, shared across projects |

## Session lifecycle

1. **Boot** — user runs `make vm-up` in a dedicated terminal (the session lives
   as long as that process). Key resolved from their env or `pi auth`
   (stored credential). Watcher records session metadata to
   `.agentic/vm-session.json`.
2. **Use** — any session (including sandboxed agents) execs phases via
   `make agent-decision` / `make agent-coding` → socket-path IPC.
3. **Stop** — `make vm-down` from the user's terminal (sandboxed sessions
   cannot signal the host process).

CI/remote: host sessions via launchd or run agents in ephemeral
`--resume` boots (roadmap, ADR-0001).

## Why socket-path-only discovery (the GC interaction)

Gondolin's session GC probes liveness with `process.kill(pid, 0)`. From a
Seatbelt-sandboxed process, signaling a foreign process is **denied**, so a
live user-hosted session reads as "stale" and its registry files
(`<id>.json`, `<id>.sock`) get deleted — orphaning a running session. Passing
the **socket path** to `exec` returns before the GC runs, and our own liveness
probe is a direct unix-socket connect. Hence: never `gondolin list` or
id-based `exec` from sandboxed sessions. Full write-up: ADR-0001.

## Naming conventions (future multi-tenant layer)

- Sessions: `pi-<client>-<provider>`
- Host-secrets (credentials): `<client>-<provider>-<credential>`
