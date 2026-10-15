---
task: 001
title: Agent runtime selection (AGENT_RUNTIME)
type: feature
priority: P1
created: 2026-10-15
author: orchestrator (verification cycle)
---

# Task 001: Add AGENT_RUNTIME override to the agent runner

## Goal

Make the agent execution runtime an explicit, testable contract so that the
same API (`make agent-decision` / `make agent-coding` / `scripts/agent-pi.sh`)
works identically for human developers, sandboxed agentic sessions, and CI
runners — with the runtime selectable and recorded per run.

## Scope

**In scope — `scripts/agent-pi.sh` only:**

1. Add an `AGENT_RUNTIME` environment variable with three values:
   - `auto` (default, current behavior): use the SDLC VM session if one is
     reachable; otherwise ephemeral boot
   - `session`: require the SDLC VM session; fail with a clear error if
     none is reachable
   - `ephemeral`: skip session detection entirely; boot an ephemeral VM
     (this is the CI mode)
2. Honor the override in the run-mode detection logic (the existing
   `SESSION_SID` / `RUN_MODE` block) and in the key-resolution rules:
   - `session` mode never needs a host-side API key (the session holds it)
   - `ephemeral` mode resolves the key exactly as CI does: `MISTRAL_API_KEY`
     env, then the stored pi credential fallback
   - `auto` keeps today's behavior
3. Update the header comment (usage/env docs) and the run info lines to show
     the selected runtime.
4. Validate the value: reject unknown `AGENT_RUNTIME` values with a usage
   error (exit 1).

**Out of scope:** Makefile changes, vm-session.sh changes, docs beyond the
script header, tests (none exist yet), any behavior change to `auto`.

## Acceptance criteria

- `AGENT_RUNTIME=ephemeral ./scripts/agent-pi.sh decision --phase discovery --task "probe"` \
  skips session detection even with a session running
- `AGENT_RUNTIME=session` with no reachable session fails fast with a clear
  message (no ephemeral fallback)
- `AGENT_RUNTIME=bogus` exits 1 with a usage error
- With `AGENT_RUNTIME` unset, behavior is byte-identical to today
- `bash -n scripts/agent-pi.sh` passes
- The audit entry records the effective runtime as before
  (`gondolin-pi-session` or `gondolin-pi`)

## Context

- ADR-0001 (docs/adr/0001-session-execution-under-sandboxing.md) defines the
  two runtimes and the CI model (ephemeral boots).
- Do not modify decision-agent artifacts or other docs.
- Repo conventions: strict bash, colored helpers (match existing style in the
  script).
