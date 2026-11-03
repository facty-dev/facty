---
# Architecture Decision Record (ADR)
---

# ADR-0001

> **Superseded by ADR-0005 (2026-10-30):** the gondolin runtime this ADR
> governs is deleted; isolation is now SmolVM (see docs/ARCHITECTURE.md).
> Retained for history.: Session-based agent execution under host-side sandboxing

**Date:** 2026-10-15
**Status:** accepted
**Deciders:** chart (product owner)
**Technical Story:** PRD-003 (agent orchestration)

---

## Context

Facty's SDLC agents (decision + coding) run inside gondolin micro-VM
sessions. The orchestrating sessions on the development host run under
**pi-sandbox** (Seatbelt on macOS), which restricts filesystem reads, network
egress, and — critically — **process signals and cross-process discovery**.
Proven end-to-end on 2026-10-15: a discovery-phase agent run completed in 76s
with zero secret exposure to the orchestrating session.

**What problem are we solving?**

How do sandboxed host sessions drive long-lived VM agent sessions safely —
secrets usable but never readable, sessions discoverable without being
destroyed, and the whole thing operable by one developer?

**What constraints do we have?**

- Orchestrating sessions are sandboxed: no signaling foreign processes, no
  reading `auth.json`/`~/.ssh`, no cross-project reads.
- Secrets must never be readable by guest agents or the driving session.
- Sessions must outlive individual tool calls and shell escapes (both tear
  down their process groups on exit).
- Single-developer operability: minimal ceremony, no always-on daemons
  required for interactive work.

---

## Decision Drivers

- Secret confidentiality (usable-but-not-readable across all layers)
- Robustness of session discovery under sandbox restrictions
- Operational simplicity on a single dev machine

---

## Considered Options

### Option A: ephemeral VM per agent run (status: rejected for interactive use)

Every `make agent-decision` boots a fresh VM from the snapshot. Works and is
the CI model — but interactive SDLC work loses warm state, and the driving
session must hold the API key (env) to inject it, exposing the key to the
sandboxed orchestrator.

### Option B: long-lived session booted by the user, driven over IPC (status: chosen)

The user boots the session from their own terminal (`make vm-up`) — that
process holds the secret host-side. Sandboxed agents exec into it over the
session's unix socket, passing only commands and receiving only output.

---

## Decision

**Long-lived, user-hosted sessions + socket-path IPC + host-side secrets.**

1. **Boot** (`scripts/vm-session.sh up`, user's terminal): key resolved from
   the user's env or `pi auth` (stored credential); injected via
   `--host-secret` → guest env holds only a placeholder; a watcher records
   `{id, pid, socketPath}` to `.agentic/vm-session.json`.
2. **Discovery**: socket-path only. Liveness is probed by connecting to the
   recorded socket; **never** `gondolin list` or id-based `exec` from
   sandboxed sessions.
3. **Execution** (`scripts/agent-pi.sh`): prompts staged via `@file`;
   `gondolin exec --sock <path>` runs pi inside the VM; exec'd commands
   source the placeholder from `/root/.session-env/` (exec does not inherit
   the boot environment); the host proxy substitutes the real key into
   outbound requests to allowed hosts only.
4. **Audit**: every run (success or failure) appended to
   `.agentic/audit.jsonl` with model, runtime, exit code, duration.
5. **Teardown**: `make vm-down` from the user's terminal.

---

## Consequences

**Positive:**

- The real API key exists only in the user-launched session's host proxy
  process: not in the sandboxed orchestrator's env, not in the guest, not in
  IPC traffic, not in artifacts (verified — placeholder absent from all
  outputs).
- Sessions survive tool calls and shell escapes (hosted by a real terminal).
- Warm session state: skills mounted once, faster phase runs.

**Negative / obligations:**

- The hosting terminal must stay open during SDLC work; `Ctrl-]` on the
  originating session **kills** it (only `gondolin attach` sessions detach
  safely). Documented in `vm-session.sh` output.
- Two gondolin sharp edges must be respected permanently:
  1. **Session GC vs sandbox signals** — pid-based liveness probing
     (`process.kill(pid, 0)`) is denied for foreign processes under the
     sandbox; id-based discovery from sandboxed sessions misclassifies live
     sessions as stale and deletes their registry files.
  2. **Exec env inheritance** — `gondolin exec` commands start with a minimal
     environment; host-secret placeholders must be stashed at boot and
     sourced explicitly.
- Unattended operation (CI, remote dev) needs a session host that outlives
  terminals: launchd user agent or ephemeral `--resume` boots (roadmap).

---

## Links

- Implementation: `scripts/vm-session.sh`, `scripts/agent-pi.sh`
- Architecture: [docs/ARCHITECTURE.md](../ARCHITECTURE.md)
- Runtime template: `~/code/gondolin-pi` (snapshot + skills)
- Gondolin secrets model: earendil-works.github.io/gondolin/secrets/
