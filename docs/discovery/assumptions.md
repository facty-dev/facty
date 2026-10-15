---
# Discovery — Assumptions
---

# Assumptions — per solution, marked testable/untestable

**Status:** draft · **Version:** 0.1 · **Date:** 2026-10-15
**Parent:** `solutions.md` (S1-a…S3-c)

Marks:
- **testable** — has a concrete validation command/spike runnable now.
- **untestable** — validated only by usage/judgment; state the fallback
  evidence (dogfooding, interview).

---

## S1-a: client manifests + make wrapper

- **ASM-1a-1 (testable):** every USE-CASES.md scenario (§1–§6) is
  expressible as a flat manifest — fields: mount path, secret env names +
  target hosts, allow-list, snapshot ref; no per-client branching logic.
  - **How to test:** encode all six scenarios as manifests, render, diff
    against the hand-typed commands in USE-CASES.md.
  - **Risk if wrong:** schema needs conditionals/types → effort grows.
- **ASM-1a-2 (testable):** a rendered invocation is flag-equivalent to the
  proven manual one, so the ADR-0001 isolation guarantees transfer
  unmodified.
  - **How to test:** render + diff for the six use cases; boot one rendered
    session and run `make vm-status`.
  - **Risk if wrong:** new flag composition introduces untested isolation
    paths.
- **ASM-1a-3 (untestable):** operators will trust manifests + one-command
  boots and will commit client manifests to their workflow.
  - **Fallback evidence:** dogfood the manifest flow for one real client
    week + one outside-user interview.
  - **Risk if wrong:** tooling unused; manual rituals persist.

## S1-b: tenant registry CLI

- **ASM-1b-1 (testable):** concurrent per-client sessions keep isolated
  registries (`.agentic/tenants/<client>.json`, no cross-talk) with 3+
  clients running at once.
  - **How to test:** boot 3 scratch clients concurrently; probe each socket
    and mount from its own session.
  - **Risk if wrong:** registry corruption → exec into the wrong session.
- **ASM-1b-2 (untestable):** operators prefer a registry CLI over make
  targets.
  - **Fallback evidence:** A/B the two interfaces during dogfooding.
  - **Risk if wrong:** dead tooling surface.

## S1-c: runbooks only

- **ASM-1c-1 (untestable, presumed false):** runbooks prevent invocation
  mistakes.
  - **Risk if wrong (accepted):** wrong allow-list = egress hole. This is
    why S1-c is not recommended.

## S2-a: launchd-hosted detached sessions

- **ASM-2a-1 (testable):** a launchd-owned session process survives
  terminal/SSH death and user logout; the recorded socket path stays valid.
  - **How to test:** install plist, boot, kill the hosting terminal,
    `make vm-status`, exec one phase.
  - **Risk if wrong:** detached hosting fundamentally broken on macOS →
    unattended operation blocked; fall back to S2-b.
- **ASM-2a-2 (testable):** gondolin session GC does not reap
  launchd-hosted sessions (GC probes pids via `process.kill(pid, 0)`;
  launchd-owned pids are alive and probeable from a normal shell —
  contrast ADR-0001's sandboxed-probe failure mode).
  - **How to test:** with a launchd-hosted session up, run `gondolin list`
    from an unsandboxed shell; confirm registry files persist over 10 min.
  - **Risk if wrong:** sessions orphaned/reaped → same class of sharp edge
    as ADR-0001, host-side.
- **ASM-2a-3 (untestable):** macOS-first hosting is acceptable; other hosts
  adopt S2-b ephemeral boots instead.
  - **Fallback evidence:** ADR-0001 context is a mac host; USE-CASES.md has
    no non-mac scenario today.
  - **Risk if wrong:** launchd work doesn't port; re-implement per OS.

## S2-b: ephemeral per-run boots

- **ASM-2b-1 (testable):** snapshot boot cost per run is acceptable for
  unattended/batch use (session boot already proven ~76s end-to-end in
  the 2026-10-15 discovery run).
  - **How to test:** time N cold boots + one trivial phase each; set an
    explicit budget (≤ 2 min wall per run).
  - **Risk if wrong:** batch latency dominates; restrict ephemerality to CI
    where wall time matters less.
- **ASM-2b-2 (testable):** agent runs are stateless across boots — all
  phase state lives in `/workspace` (repo + `.agentic/`) or git, never in
  guest-only state.
  - **How to test:** run discovery in boot 1, PRD in a fresh boot 2;
    verify artifact continuity + audit chain.
  - **Risk if wrong:** phases lose context → quality drop; need warm-state
    snapshots per client.

## S3-a: GitHub Actions wiring

- **ASM-3a-1 (testable):** GitHub-hosted ubuntu runners can execute
  gondolin/QEMU micro-VMs (software virtualization) within usable time.
  - **How to test:** spike workflow — boot the snapshot, run one trivial pi
    phase, measure wall time.
  - **Risk if wrong:** CI infeasible on hosted runners → self-hosted runner
    or containerized fallback (highest-impact risk of this round).
- **ASM-3a-2 (testable):** the qcow2 snapshot is cacheable/restorable in CI
  within size/download limits.
  - **How to test:** actions-cache spike; measure restore time + hit rate
    across runs.
  - **Risk if wrong:** per-run snapshot fetch dominates CI time.
- **ASM-3a-3 (testable):** host-secret injection works in ephemeral CI
  boots with the real key held only as a GitHub Actions secret (placeholder
  in guest; host proxy substitution identical to local).
  - **How to test:** e2e phase run in CI with a canary key value; grep the
    audit log + guest env for the real value (must be absent).
  - **Risk if wrong:** broken auth in CI or (worse) secret leakage.
- **ASM-3a-4 (untestable):** reviewers will use PR labels/approvals as the
  SDLC gates.
  - **Fallback evidence:** operate one full spiral (ost→prd→bdd→impl) on a
    real feature; observe gate usage.
  - **Risk if wrong:** gates ignored → spiral bypassed; CI triggers become
    noise.

## S3-b: local merge-triggered dispatcher

- **ASM-3b-1 (testable):** phase progression is detectable locally from git
  (merge of `sdlc/<phase>/<slug>` into main) without a central service.
  - **How to test:** prototype a post-merge hook dispatching the next make
    target in a scratch repo; include a squash-merge case.
  - **Risk if wrong:** hook state fragile under rebase/squash merges.
- **ASM-3b-2 (untestable):** operators keep the human-in-terminal loop for
  interactive work even after CI exists.
  - **Fallback evidence:** dogfood both trigger paths for one feature.
  - **Risk if wrong:** two competing triggers race on the same phase.

---

## Validation priority

1. **ASM-3a-1/3a-2/3a-3** — CI feasibility spike; highest risk + blocks the
   largest solution. Cheap spike, big decision value.
2. **ASM-2a-1/2a-2** — launchd detachment; unlocks unattended operation.
3. **ASM-1a-1/1a-2** — manifest schema; cheapest, unlocks P-1 immediately.
