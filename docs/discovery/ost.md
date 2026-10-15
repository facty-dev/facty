---
# Opportunity Solution Tree (OST)
# Continuous Discovery — Design Thinking
---

# Opportunity Solution Tree — drawbridge

**Date:** 2026-10-15
**Facilitator:** decision agent (drawbridge SDLC discovery run, zai-glm-5-3)
**Status:** draft <!-- draft | in-review | approved -->
**Version:** 0.1

---

## Desired Outcome

A single operator runs the full agentic SDLC for multiple concurrent clients
on one machine — isolation by construction, zero secret exposure — with
one-command client onboarding, unattended (detached or CI) phase runs, and
merge-triggered phase progression, by 2027-01-31.

---

## Opportunities (Problems)

What problems do our users/stakeholders face? (From continuous discovery)

### OPP-001: Multi-client session management is a hand-typed CLI ritual
- **Description:** every USE-CASES.md scenario (§1–§6) requires hand-composing
  a long `gondolin bash` invocation — mount, host-secrets, allow-list — per
  client, per project. No client registry; errors are silent policy holes.
- **Evidence:** `docs/USE-CASES.md` §1–§6 (all manual); README roadmap bullet
  1; ARCHITECTURE.md "Naming conventions (future multi-tenant layer)" —
  conventions named, no tooling implements them.
- **Impact:** every multi-client user; isolation mistakes are security holes
  (wrong allow-list = egress leak, wrong secret = credential misuse).
- **Frequency:** every session boot, per client, per project.
- **Source:** README.md roadmap + USE-CASES.md gap analysis, discovery run
  2026-10-15.

### OPP-002: Sessions die with the hosting terminal — no unattended operation
- **Description:** the VM session lives exactly as long as the terminal
  running `make vm-up`; a closed terminal or dropped SSH kills every agent
  run in flight. No overnight runs, no scheduled phases, no CI-shared
  session.
- **Evidence:** README "Known sharp edges" #3 + roadmap bullet 2
  ("launchd-hosted persistent sessions"); ARCHITECTURE.md "Session
  lifecycle" step 1; ADR-0001 Option A (ephemeral per-run boots) named but
  never built for unattended use.
- **Impact:** the solo operator on every disconnect/unattended window; hard
  blocker for CI flows.
- **Frequency:** constant constraint.
- **Source:** README.md sharp edges + roadmap, ADR-0001.

### OPP-003: Nothing triggers the next SDLC phase — merges don't materialize downstream work
- **Description:** the git-native pipeline is designed as "merges are
  materializations" (GIT-NATIVE-PIPELINE.md, PRD-006; gates in
  GITHUB-GATES.md), but today every phase is a manual
  `make agent-decision PHASE=…`. Gates have no enforcement point.
- **Evidence:** README quick start (all phases hand-invoked) vs roadmap
  bullet 3 ("GitHub Actions wiring: CI runs agents in ephemeral gondolin
  VMs"); GITHUB-GATES.md pipeline (design) vs Makefile (reality).
- **Impact:** operator + reviewers; pipeline reliability collapses to human
  memory.
- **Frequency:** once per phase per feature.
- **Source:** README.md roadmap, docs/GIT-NATIVE-PIPELINE.md +
  docs/GITHUB-GATES.md vs implementation gap.

---

## Solutions

For each opportunity, what are potential solutions?

### For OPP-001: Multi-client session management is a hand-typed CLI ritual

#### SOL-001-A: Declarative client manifests + make wrapper
- **Description:** `clients/<client>.yaml` (mount, secret env names + target
  hosts, allow-list, snapshot ref); `make client-up CLIENT=acme` renders the
  gondolin invocation and records session metadata to
  `.agentic/tenants/<client>.json` (socket-path pattern per ADR-0001).
- **How it addresses the problem:** every use case becomes one command;
  policy becomes reviewable versioned data instead of a typed command line.
- **Effort:** M
- **Confidence:** high

**Assumptions:**
- **ASM-001-A-1:** *(testable)* all six USE-CASES.md scenarios are
  expressible as flat manifests — no per-client branching logic.
  - How to test: encode all six scenarios, render, diff against the
    hand-typed commands in USE-CASES.md.
  - Risk if wrong: schema needs conditionals/types → effort grows.
- **ASM-001-A-2:** *(testable)* a rendered invocation is flag-equivalent to
  the proven manual one, so ADR-0001 isolation guarantees transfer
  unmodified.
  - How to test: render + diff for the six use cases; boot one rendered
    session and run `make vm-status`.
  - Risk if wrong: new flag composition introduces untested isolation paths.
- **ASM-001-A-3:** *(untestable)* operators will trust manifests +
  one-command boots and commit client manifests to their workflow.
  - How to test: untestable directly — dogfood one real client week + one
    outside-user interview.
  - Risk if wrong: tooling unused; manual rituals persist.

#### SOL-001-B: Tenant registry CLI
- **Description:** `scripts/tenant.sh add|list|status|down` keeps per-client
  state in `.agentic/tenants/`, wrapping the same gondolin calls.
- **How it addresses the problem:** adds lifecycle management beyond boot,
  at the cost of a second interface to learn and maintain.
- **Effort:** M–L
- **Confidence:** medium

**Assumptions:**
- **ASM-001-B-1:** *(testable)* 3+ concurrent per-client sessions keep
  isolated registries with no cross-talk.
  - How to test: boot 3 scratch clients concurrently; probe each socket and
    mount from its own session.
  - Risk if wrong: registry corruption → exec into the wrong session.
- **ASM-001-B-2:** *(untestable)* operators prefer a registry CLI over make
  targets.
  - How to test: untestable directly — A/B the two interfaces during
    dogfooding.
  - Risk if wrong: dead tooling surface.

### For OPP-002: Sessions die with the hosting terminal — no unattended operation

#### SOL-002-A: launchd-hosted detached sessions (macOS-first)
- **Description:** ship a LaunchAgent plist template; `make vm-up
  --detached` installs and loads it. The session process is owned by
  launchd and survives terminal/SSH death. `vm-status`/`vm-down` keep using
  the recorded socket path.
- **How it addresses the problem:** unattended windows no longer kill runs;
  no daemon beyond the OS-native one.
- **Effort:** M
- **Confidence:** medium-high

**Assumptions:**
- **ASM-002-A-1:** *(testable)* a launchd-owned session survives
  terminal/SSH death and logout; the recorded socket path stays valid.
  - How to test: install plist, boot, kill the hosting terminal,
    `make vm-status`, exec one phase.
  - Risk if wrong: detached hosting broken on macOS → fall back to
    SOL-002-B.
- **ASM-002-A-2:** *(testable)* gondolin session GC does not reap
  launchd-hosted sessions (GC probes pids; launchd-owned pids are alive and
  probeable from a normal shell — contrast ADR-0001's sandboxed-probe
  failure mode).
  - How to test: with a launchd-hosted session up, run `gondolin list` from
    an unsandboxed shell; confirm registry files persist over 10 min.
  - Risk if wrong: sessions orphaned/reaped — same sharp-edge class as
    ADR-0001, host-side.

#### SOL-002-B: Ephemeral per-run boots
- **Description:** for unattended work, every agent run boots a fresh VM
  from the snapshot (`--resume`), runs one phase, writes artifacts to
  `/workspace`, exits — ADR-0001 Option A restricted to unattended/CI
  contexts.
- **How it addresses the problem:** nothing to keep alive; session lifetime
  becomes a non-issue for batch runs. Shares machinery with SOL-003-A.
- **Effort:** M
- **Confidence:** medium

**Assumptions:**
- **ASM-002-B-1:** *(testable)* snapshot boot cost per run is acceptable for
  unattended/batch use (session boot already proven ~76s end-to-end,
  2026-10-15 discovery run).
  - How to test: time N cold boots + one trivial phase each; budget ≤ 2 min
    wall per run.
  - Risk if wrong: batch latency dominates; restrict ephemerality to CI.
- **ASM-002-B-2:** *(testable)* agent runs are stateless across boots — all
  phase state lives in `/workspace` (repo + `.agentic/`) or git.
  - How to test: run discovery in boot 1, PRD in a fresh boot 2; verify
    artifact continuity + audit chain.
  - Risk if wrong: phases lose context → need per-client warm-state
    snapshots.

### For OPP-003: Nothing triggers the next SDLC phase — merges don't materialize downstream work

#### SOL-003-A: GitHub Actions wiring — ephemeral VMs in CI
- **Description:** label-triggered workflows (`sdlc:discov|prd|bdd|impl`)
  boot an ephemeral gondolin VM from a cached snapshot, exec the right agent
  role, open a phase PR. Human gates = PR approvals (GITHUB-GATES.md).
  Allow-list + host-secret injection reproduce the local isolation model
  in the runner.
- **How it addresses the problem:** merging a phase PR actually materializes
  the asset and triggers the downstream phase; gates become enforced.
- **Effort:** L
- **Confidence:** medium

**Assumptions:**
- **ASM-003-A-1:** *(testable)* GitHub-hosted ubuntu runners can execute
  gondolin/QEMU micro-VMs (software virtualization) within usable time.
  - How to test: spike workflow — boot the snapshot, run one trivial pi
    phase, measure wall time.
  - Risk if wrong: CI infeasible on hosted runners → self-hosted runner or
    container fallback (highest-impact risk this round).
- **ASM-003-A-2:** *(testable)* the qcow2 snapshot is cacheable/restorable
  in CI within size/download limits.
  - How to test: actions-cache spike; measure restore time + hit rate
    across runs.
  - Risk if wrong: per-run snapshot fetch dominates CI time.
- **ASM-003-A-3:** *(testable)* host-secret injection works in ephemeral CI
  boots with the real key held only as a GitHub Actions secret (placeholder
  in guest; proxy substitution identical to local).
  - How to test: e2e phase run in CI with a canary key value; grep audit log
    + guest env for the real value (must be absent).
  - Risk if wrong: broken auth in CI or secret leakage.
- **ASM-003-A-4:** *(untestable)* reviewers will use PR labels/approvals as
  the SDLC gates.
  - How to test: untestable directly — operate one full spiral
    (ost→prd→bdd→impl) on a real feature; observe gate usage.
  - Risk if wrong: gates ignored → spiral bypassed; CI triggers become
    noise.

#### SOL-003-B: Local merge-triggered dispatcher
- **Description:** a post-merge hook / watcher on `sdlc/<phase>/*` merges
  launches the next phase locally via existing make targets + session.
- **How it addresses the problem:** merge-triggered progression without a
  CI dependency; humans stay in the terminal loop.
- **Effort:** M
- **Confidence:** medium

**Assumptions:**
- **ASM-003-B-1:** *(testable)* phase progression is detectable locally from
  git (merge of `sdlc/<phase>/<slug>` into main) without a central service.
  - How to test: prototype a post-merge hook dispatching the next make
    target in a scratch repo; include a squash-merge case.
  - Risk if wrong: hook state fragile under rebase/squash merges.
- **ASM-003-B-2:** *(untestable)* operators keep the human-in-terminal loop
  for interactive work even after CI exists.
  - How to test: untestable directly — dogfood both trigger paths for one
    feature.
  - Risk if wrong: two competing triggers race on the same phase.

---

## OST Visualization

```
                    ┌──────────────────────────────────────┐
                    │           DESIRED OUTCOME            │
                    │ multi-client agentic SDLC, zero     │
                    │ secret exposure, unattended + CI    │
                    └──────────────────┬───────────────────┘
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         ▼                             ▼                             ▼
  ┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
  │     OPP-001      │        │     OPP-002      │        │     OPP-003      │
  │ client sessions  │        │ sessions die     │        │ merges trigger   │
  │ are hand-typed   │        │ with terminal    │        │ nothing          │
  └────────┬─────────┘        └────────┬─────────┘        └────────┬─────────┘
           │                            │                            │
      ┌────┴────┐                   ┌───┴────┐                   ┌───┴────┐
      ▼         ▼                   ▼        ▼                   ▼        ▼
  ┌────────┐ ┌────────┐        ┌────────┐ ┌────────┐        ┌────────┐ ┌────────┐
  │SOL-    │ │SOL-    │        │SOL-    │ │SOL-    │        │SOL-    │ │SOL-    │
  │001-A   │ │001-B   │        │002-A   │ │002-B   │        │003-A   │ │003-B   │
  │client  │ │tenant  │        │launchd │ │ephemer.│        │GH      │ │local   │
  │manif.  │ │CLI     │        │detach  │ │boots   │        │Actions │ │dispatch│
  │+A1..A3 │ │+B1,B2  │        │+A1,A2  │ │+B1,B2  │        │+A1..A4 │ │+B1,B2  │
  └────▲───┘ └────────┘        └────▲───┘ └────────┘        └────▲───┘ └────────┘
       │                            │                            │
       └── Selected path (draft): SOL-001-A · SOL-002-A (+002-B for CI)
                                   · SOL-003-A — pending human gate
```

---

## Selected Path

*Draft selection — pending human review gate (status: draft).*

| Field | Value |
|-------|-------|
| **Opportunity** | OPP-001: multi-client session management is a hand-typed CLI ritual |
| **Solution** | SOL-001-A: declarative client manifests + make wrapper |
| **Rationale** | Cheapest unlock with highest confidence; produces the per-client session/policy substrate that OPP-002 and OPP-003 wiring build on; every USE-CASES.md scenario depends on it. |
| **Key Assumptions** | ASM-001-A-1, ASM-001-A-2 (both testable, cheap) |
| **Confidence** | high |
| **Effort** | M |

| Field | Value |
|-------|-------|
| **Opportunity** | OPP-002: sessions die with the hosting terminal |
| **Solution** | SOL-002-A: launchd-hosted detached sessions, with SOL-002-B ephemeral boots for CI contexts |
| **Rationale** | Keeps the proven long-lived-session model (ADR-0001 Option B) and makes it unattended; ephemeral boots are the natural CI companion and share machinery with SOL-003-A. |
| **Key Assumptions** | ASM-002-A-1, ASM-002-A-2, ASM-002-B-1, ASM-002-B-2 (all testable) |
| **Confidence** | medium-high |
| **Effort** | M |

| Field | Value |
|-------|-------|
| **Opportunity** | OPP-003: merges don't trigger the next phase |
| **Solution** | SOL-003-A: GitHub Actions wiring with ephemeral gondolin VMs |
| **Rationale** | Implements the already-designed gates (GITHUB-GATES.md) and roadmap bullet 3; makes the spiral self-driving. Highest effort/risk — gate on the CI feasibility spike before committing. |
| **Key Assumptions** | ASM-003-A-1, ASM-003-A-2, ASM-003-A-3 (testable — spike first), ASM-003-A-4 (untestable) |
| **Confidence** | medium |
| **Effort** | L |

**Sequencing:** OPP-001 (substrate) → OPP-002 (unattended) → OPP-003 (CI),
with the ASM-3a-1/2/3 CI feasibility spike run early and in parallel.

---

## Assumptions Log (All)

| ID | Assumption | Solution | How to Test | Risk if Wrong | Status |
|----|-----------|----------|-------------|---------------|--------|
| ASM-001-A-1 | Six use cases fit flat manifests | SOL-001-A | Render + diff vs USE-CASES.md commands | Schema complexity grows | unvalidated (testable) |
| ASM-001-A-2 | Rendered invocation flag-equivalent to proven manual one | SOL-001-A | Render + diff; boot rendered session | Untested isolation paths | unvalidated (testable) |
| ASM-001-A-3 | Operators trust + commit manifests | SOL-001-A | Dogfood week + interview | Tooling unused | unvalidated (untestable) |
| ASM-001-B-1 | 3+ concurrent clients, isolated registries | SOL-001-B | Boot 3 scratch clients, probe sockets/mounts | Exec into wrong session | unvalidated (testable) |
| ASM-001-B-2 | Operators prefer CLI over make | SOL-001-B | A/B during dogfooding | Dead tooling surface | unvalidated (untestable) |
| ASM-002-A-1 | launchd session survives terminal/SSH death | SOL-002-A | Kill hosting terminal, vm-status, exec phase | Fall back to ephemeral boots | unvalidated (testable) |
| ASM-002-A-2 | GC doesn't reap launchd-hosted sessions | SOL-002-A | `gondolin list` from unsandboxed shell, 10 min watch | Host-side orphan/reap sharp edge | unvalidated (testable) |
| ASM-002-B-1 | Per-run boot cost acceptable (≤ 2 min budget) | SOL-002-B | Time N cold boots + phase | Batch latency dominates | unvalidated (testable) |
| ASM-002-B-2 | Agent runs stateless across boots | SOL-002-B | Discovery in boot 1, PRD in boot 2, check continuity | Need warm-state snapshots | unvalidated (testable) |
| ASM-003-A-1 | GH ubuntu runners can run gondolin/QEMU VMs | SOL-003-A | CI spike: boot snapshot + trivial phase | CI infeasible → self-hosted/container | unvalidated (testable) |
| ASM-003-A-2 | Snapshot cacheable within CI limits | SOL-003-A | actions-cache spike, measure restore | Snapshot fetch dominates CI | unvalidated (testable) |
| ASM-003-A-3 | Host-secret injection safe + functional in CI | SOL-003-A | E2E with canary key; grep audit + guest env | Broken auth or secret leakage | unvalidated (testable) |
| ASM-003-A-4 | Reviewers use PR gates as designed | SOL-003-A | One full spiral on a real feature | Gates ignored, triggers = noise | unvalidated (untestable) |
| ASM-003-B-1 | Merges detectable locally without central service | SOL-003-B | Post-merge hook prototype incl. squash case | Fragile hook state | unvalidated (testable) |
| ASM-003-B-2 | Terminal loop stays preferred interactively | SOL-003-B | Dogfood both trigger paths | Competing triggers race | unvalidated (untestable) |

---

## Stakeholder Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product Owner | chart (per ADR-0001 deciders) | — | pending |
| Tech Lead | — | — | pending |
| Design Lead | — | — | pending |

---

## Next Steps

1. → Human gate: review this draft OST; approve/adjust the selected path
2. → Validate top assumptions (CI feasibility spike ASM-3a-1/2/3; launchd
   detachment ASM-002-A-1/2; manifest schema ASM-001-A-1/2)
3. → Generate **PRD** from the approved path (decision agent) — PRD-007
   onward, one PRD per opportunity in sequence
4. → Generate **BDD specs** from PRD (decision agent) → **Implement**
   (coding agent)
