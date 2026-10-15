---
task: 002
title: Ephemeral runtime parity probe (CI-mode verification)
type: verification
priority: P1
created: 2026-10-15
author: orchestrator (CI parity check)
runtime: ephemeral   # this task MUST run via AGENT_RUNTIME=ephemeral
---

# Task 002: Verify task 001 under the ephemeral (CI) runtime

## Goal

Prove feature parity: the identical API drives agents in both runtimes.
This task runs in an **ephemeral VM boot** — the exact mode CI workflows use
(no shared session, key resolved host-side, fresh VM from the snapshot).

## Scope

1. Verify the task-001 implementation (`scripts/agent-pi.sh`,
   `AGENT_RUNTIME` override) against its acceptance criteria — read
   `.agentic/messages/decision-to-coding/001-task.md` for the ACs.
2. Do NOT modify any files unless an acceptance criterion actually fails;
   if one fails, apply the minimal fix and say so.
3. Write your result to `.agentic/messages/coding-to-decision/002-result.md`:
   per-AC pass/fail, the runtime you observed, and a one-line statement of
   what differed (if anything) from a session-mode run.

## Acceptance criteria

- Every task-001 AC re-verified in this ephemeral environment
- Result message written; no unintended file changes
