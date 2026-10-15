---
# Architecture Decision Record (ADR)
---

# ADR-0002: Explicit agent runtime selection (AGENT_RUNTIME)

**Date:** 2026-10-15
**Status:** accepted
**Deciders:** chart (product owner, via task 001 verification cycle)
**Technical Story:** task 001 (.agentic/messages/decision-to-coding/001-task.md); extends [ADR-0001](0001-session-execution-under-sandboxing.md)

---

## Context

`scripts/agent-pi.sh` had a single implicit run mode: probe the SDLC VM
session (`vm-session.sh status`); if reachable run inside it, otherwise
boot an ephemeral gondolin VM. The same entry point (`make agent-decision`
/ `make agent-coding` / the script itself) serves three contexts with
different requirements: interactive developers (session preferred —
ADR-0001), sandboxed orchestrators (session over socket IPC only), and CI
runners (ephemeral only, ADR-0001 roadmap item).

Implicit selection cannot express "must use a session" or "must not touch
sessions" — it can only be observed after the fact.

**What problem are we solving?**

Make the agent execution runtime an explicit, testable contract: the
caller states which runtime it requires, the script enforces it, and the
effective runtime stays auditable.

**What constraints do we have?**

- The interactive default must not change: ADR-0001's session model is
  the chosen architecture for local work.
- Sandboxed orchestrators must never need the real API key. A silent
  ephemeral fallback would force the key into the launching (possibly
  sandboxed) environment — the exact exposure ADR-0001 eliminates.
- CI has no long-lived session host; it must boot ephemeral
  deterministically, without probing host-local session state.
- One entry point for all contexts: no context-specific CLI wrappers.

---

## Decision Drivers

- Determinism and testability of the runtime contract
- Secret isolation (ADR-0001): fail rather than silently degrade to a
  mode that requires an exposed key
- Operational simplicity: `make` targets work unchanged everywhere
- CI parity with local invocation

---

## Considered Options

### Option 1: keep implicit auto-only detection (status quo)

Every run probes and falls back; intent is invisible.

**Pros:**
- ✅ Zero new surface; no knobs to document
- ✅ Already proven end-to-end

**Cons:**
- ❌ Cannot assert a session-only policy — its violation surfaces as a
  confusing key error, not a runtime error
- ❌ Session probe runs even when the caller knows it wants ephemeral
  (pointless host-local state access from CI)

**Effort:** S
**Risk:** low (but leaves the contract untestable)

---

### Option 2: CLI flag (e.g., `--runtime session|ephemeral`)

Runtime chosen per invocation on the command line.

**Pros:**
- ✅ Explicit at the call site
- ✅ Discoverable via `usage`

**Cons:**
- ❌ `Makefile` targets would need argument plumbing for a
  rarely-changed knob
- ❌ Breaks the established override pattern (`AGENT_MODEL`,
  `AGENT_THINKING` are env vars) and CI wiring (env blocks)

**Effort:** M
**Risk:** medium (Makefile/CI churn beyond the script)

---

### Option 3: `AGENT_RUNTIME` env var (`auto`|`session`|`ephemeral`) — status: chosen

Environment override with three values, `auto` default, validated at
startup; unknown values exit 1 with usage.

**Pros:**
- ✅ Consistent with `AGENT_MODEL`/`AGENT_THINKING` override convention
- ✅ Flows through `make` and CI env blocks unchanged
- ✅ `auto` preserves today's behavior exactly (zero-change default)

**Cons:**
- ❌ One more env var to document (header, done)
- ❌ Env vars are less visible than flags at the call site (mitigated by
  the run info line printing the selected runtime)

**Effort:** S
**Risk:** low

---

## Decision

**Chosen option:** **Option 3: `AGENT_RUNTIME` env var**

`auto` (default) keeps the existing probe → session-or-ephemeral logic.
`session` requires the SDLC VM session. `ephemeral` skips session
detection entirely (CI mode).

Three invariants are part of this decision — they look unfriendly but
guard ADR-0001's security model. Do not "fix" them:

1. **`session` fails hard; it never falls back to ephemeral.** A
   fallback would demand the API key in the launching (possibly
   sandboxed) environment. A missing session is an operator action
   (`make vm-up`), not a reason to silently change secret-exposure mode.
2. **`ephemeral` skips the session probe at the source** (the probe is
   inside the `!= ephemeral` guard), rather than probing and ignoring
   the result. A reachable session can never leak into an ephemeral-mode
   decision; CI runs never touch host-local session state — including the
   sandbox-unsafe session GC paths (ADR-0001 sharp edge #1).
3. **The audit trail records the effective runtime**
   (`gondolin-pi-session` | `gondolin-pi`), not the requested mode: the
   trail reflects what actually ran.

### What Worked
- ✅ Verified by `bash -x` traces: 0 session probes under `ephemeral`,
  exactly 1 under `auto`; fail-fast paths exit 1 with actionable copy
- ✅ Default callers see no behavioral change (same probe, same fallback,
  same key resolution)

### What Didn't Work
- ❌ End-to-end audit append could not be exercised in the reviewing
  sandbox (`jq` unavailable); verified by inspection instead

### Tradeoffs Accepted
- `session` mode is stricter: operators must boot the session before
  pinned runs (that is the point)
- Info-line output changed for all modes (`(runtime: <mode>)`) — a
  deliberate scope item, so "unset ≡ byte-identical" holds only
  behaviorally, not byte-for-byte on stdout

---

## Consequences

### Positive
- ➕ One `make` API works for human developers, sandboxed agents, and CI
- ➕ Runtime intent is explicit, validated, and visible per run
- ➕ Session-only policy is enforceable and testable
- ➕ CI can pin `AGENT_RUNTIME: ephemeral` (follow-up: wire it into
  `.github/workflows/agent-decision.yml` and `agent-coding.yml` env
  blocks; `auto`'s fallback remains correct until then)

### Negative
- ➖ One more env var in the script contract (documented in the header)
- ➖ `session` mode converts a previously "working" fallback run into an
  explicit failure when no session is up

### Neutral
- ➖ Empty `AGENT_RUNTIME` ≡ unset ≡ `auto`

---

## Validation

| Metric | Target | Measurement | Review Date |
|--------|--------|-------------|-------------|
| Unknown runtime rejected | exit 1 + usage | `AGENT_RUNTIME=bogus … agent-pi.sh` | 2026-10-15 ✅ |
| Ephemeral skips detection | 0 `vm-session.sh status` calls | `bash -x` trace grep | 2026-10-15 ✅ |
| Session mode fails fast, no fallback | exit 1, no ephemeral boot | run w/o live session | 2026-10-15 ✅ |
| Auto unchanged | same probe → fallback path | `bash -x` trace vs pre-change | 2026-10-15 ✅ |
| CI pins ephemeral | both workflow env blocks | grep `AGENT_RUNTIME` in `.github/workflows/` | open (follow-up) |

---

## Related Decisions

- ADR-0001: Session-based agent execution under host-side sandboxing —
  this ADR operationalizes its two runtimes into an explicit contract and
  preserves all of its invariants
- (open, ADR pending) corrective audit-entry mechanism — sanctioned
  out-of-band audit notes; raised by review 001, not yet decided

## References

- Task 001: `.agentic/messages/decision-to-coding/001-task.md`
- Implementation + review: `.agentic/messages/coding-to-decision/001-result.md`
- Implementation: `scripts/agent-pi.sh` (runtime block, lines 62-99)
- CI wiring (follow-up target): `.github/workflows/agent-decision.yml`, `.github/workflows/agent-coding.yml`

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-10-15 | drawbridge decision agent | Initial proposal (implemented as task 001) |
| 1.0 | 2026-10-15 | drawbridge decision agent | Accepted after code review (review 001) |
