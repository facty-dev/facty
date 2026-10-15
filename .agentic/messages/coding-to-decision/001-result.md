---
task: 001
result: approved
reporter: decision agent (code review)
phase: review
date: 2026-10-15
---

# Review 001: AGENT_RUNTIME override in scripts/agent-pi.sh

**Verdict: APPROVED.** All 6 acceptance criteria verified (AC6 by
inspection — see below). 0 blockers, 2 concerns (both process/follow-up,
neither in the reviewed code), 5 nits. Decision recorded in
[ADR-0002](../../../docs/adr/0002-agent-runtime-override.md).

## Acceptance criteria

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `ephemeral` skips session detection even with a session running | PASS | `bash -x` trace: **0** `vm-session.sh status` calls; the probe sits inside the `!= ephemeral` guard (scripts/agent-pi.sh:76-78), so a live session cannot be detected. No live session exists in this sandbox to test against — structural proof is conclusive (a session can only enter via that probe). |
| 2 | `session` with no reachable session fails fast, no fallback | PASS | rc=1, "AGENT_RUNTIME=session but no SDLC VM session is reachable / run 'make vm-up'…" (scripts/agent-pi.sh:81-84); exactly 1 status probe; no ephemeral boot attempted |
| 3 | `bogus` exits 1 with usage error | PASS | rc=1, "invalid AGENT_RUNTIME: bogus (expected auto\|session\|ephemeral)" + usage (scripts/agent-pi.sh:63-66) |
| 4 | `AGENT_RUNTIME` unset → behavior identical to today | PASS | trace: same probe → fallback path as pre-change; mode selection, key resolution, audit shape unchanged. Stdout differs by design (info line scripts/agent-pi.sh:152 now prints `(runtime: auto)`) — scope item 3; see nit 4 |
| 5 | `bash -n scripts/agent-pi.sh` | PASS | clean |
| 6 | Audit records effective runtime as before | PASS (inspection) | audit block unchanged (scripts/agent-pi.sh:179-192, `--arg runtime "$RUN_MODE"`); `RUN_MODE` is only ever set to `gondolin-pi-session` (:80) or `gondolin-pi` (:86). End-to-end append not exercisable in this sandbox: `jq` is missing (my test runs stop at line 179, rc=127) — same environment limitation the coding agent hit; pre-existing, not a regression |

## Findings

### Blockers

None.

### Concerns

1. **Hand-appended corrective audit entry** — .agentic/audit.jsonl:7
   (2026-10-15T02:18:18Z, `note` field). AGENTS.md rule 4: only
   `scripts/agent-pi.sh` writes entries. The coding agent hand-appended a
   clearly-labeled corrective entry after the wrapper crashed before its
   own audit append (jq unavailable). Honest and better than a silent
   gap — but a process deviation. Recommend a sanctioned mechanism
   (e.g., an `--audit-note` escape in the script, or a documented
   manual-entry procedure in AGENTS.md) before the next such event.
   Not a defect in the reviewed change; ADR-0002 lists it as an open
   decision.
2. **CI does not pin the new "CI mode"** — .github/workflows/
   agent-decision.yml and agent-coding.yml (env blocks of the agent
   steps). Both still rely on `auto`'s fallback, which works today
   (fresh CI checkout has no `.agentic/vm-session.json` → status down →
   ephemeral), but the explicit contract this task created is not
   exercised where it is meant to be used. Follow-up task (out of scope
   here by design): set `AGENT_RUNTIME: ephemeral` in both workflow env
   blocks.

### Nits

1. scripts/agent-pi.sh:39 — usage range `sed -n '2,25p'` includes line 25
   (`set -euo pipefail`), so usage output ends with a stray
   "set -euo pipefail" line (verified by rendering usage). Fix:
   `sed -n '2,24p'`. One-line change, fold into the next touch.
2. scripts/agent-pi.sh:93-95 — under explicit `AGENT_RUNTIME=ephemeral`
   with no key, the error says "no SDLC VM session running" and
   suggests `make vm-up`: misleading when the caller opted out of
   sessions. Mode-aware copy would be clearer.
3. scripts/agent-pi.sh:53 — `AGENT_RUNTIME` is validated after the
   `GONDOLIN_PI` existence check, so in an environment without the
   gondolin-pi template a bogus runtime reports the dependency error
   first. Deliberate per the implementation report; acceptable.
4. AC4's "byte-identical" wording: stdout differs by design
   (scripts/agent-pi.sh:152). The AC holds in the behavioral sense —
   record only, no action.
5. scripts/agent-pi.sh file mode is `-rwx--x--x` (group/other read
   stripped; sibling scripts are `-rwxr-xr-x`) — likely a sandbox
   chmod artifact around the edit (the audit note's "chmod +x
   restored" suggests the same). Harmless for `make` targets; restore
   `chmod 755` host-side at next touch.

## Verification log (this review, sandboxed session)

- `bash -n scripts/agent-pi.sh` — clean.
- `AGENT_RUNTIME=bogus` (GONDOLIN_PI=/bin/true): rc=1, invalid-runtime
  error + usage.
- `AGENT_RUNTIME=session`, no live session (`vm-session.sh status` →
  down): rc=1, fail-fast, one status probe, no ephemeral attempt.
- `AGENT_RUNTIME=ephemeral` (GONDOLIN_PI=/bin/true as boot stub):
  0 status probes (trace), ephemeral boot invoked, info lines
  "runtime: ephemeral" / "via ephemeral boot (gondolin-pi)"; run then
  stops at :179 (`jq: command not found`) — sandbox lacks jq, noted
  above.
- `AGENT_RUNTIME` unset: 1 status probe, same fallback path,
  "runtime: auto".
- Audit block inspected (scripts/agent-pi.sh:179-192): shape and
  `runtime` argument unchanged from pre-task.
- Scope check: `grep -rln AGENT_RUNTIME` → only scripts/agent-pi.sh plus
  the task/result messages. No git in this sandbox, so the
  "only-file-touched" claim could not be diff-verified; inspection of
  Makefile, vm-session.sh, and the workflows found no related edits.
- scripts/agent-pi.sh is executable (Makefile invokes it directly).

## Implementation report (coding agent — condensed, superseded by this review)

- Only scripts/agent-pi.sh touched. `AGENT_RUNTIME` =
  auto|session|ephemeral with startup validation (:62-66); probe guard
  (:76-78); session-mode hard fail (:81-84); key resolution unchanged
  per mode (session never resolves a key, ephemeral/auto fall back to
  env `MISTRAL_API_KEY` then stored pi credential, :86-99); header docs
  (:20-23); info line (:152); audit untouched (:179-192).
- Their verification claims were re-tested and confirmed (see log);
  their "byte-identical" claim is qualified per nit 4.

## Disposition

Approved as-is. Follow-ups: (a) corrective-audit mechanism (concern 1),
(b) pin `AGENT_RUNTIME: ephemeral` in the CI workflows (concern 2),
(c) nits 1-2 as one-liners on the next touch of the script. The
no-fallback and probe-skipping invariants are recorded in ADR-0002 —
treat them as load-bearing (they guard ADR-0001's secret isolation).
