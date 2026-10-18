---
# Discovery — Problems
---

# Problems — Facty discovery

**Status:** draft · **Version:** 0.1 · **Date:** 2026-10-15
**Sources:** `docs/USE-CASES.md`, `README.md` (roadmap + known sharp edges), `docs/ARCHITECTURE.md`, ADR-0001
**Scope note:** PRD-001…006 already cover the asset model, rules engine, agent
orchestration, audit reification, neurosymbolic bridge, and the git-native
pipeline *design*. This round derives the top 3 **unbuilt** opportunities on
the current architecture (gondolin micro-VMs + pi coding agent).

---

## P-1: Multi-client session management is a hand-typed CLI ritual

Every scenario in `docs/USE-CASES.md` (§1–§6: freelancer, agency, consultant,
solo, OSS maintainer, enterprise lead) requires composing a long
`gondolin bash --resume … --mount-hostfs … --allow-host … --host-secret …`
invocation by hand, per client, per project.

- **What goes wrong:** wrong mount path, wrong allow-list, or wrong secret
  env var produces a silent policy hole or a broken session. No registry
  says which sessions exist, for which client, with which policy.
- **Evidence:** USE-CASES.md §1–§6 (all manual); README roadmap bullet 1
  ("multi-tenant client management"); ARCHITECTURE.md "Naming conventions
  (future multi-tenant layer)" — conventions named, no tooling implements
  them.
- **Impact:** any user with ≥2 clients/projects — the entire target
  population of USE-CASES.md. Severity: isolation mistakes are security
  holes (wrong allow-list = egress leak; wrong secret = credential misuse).
- **Frequency:** every session boot, per client, per project.

## P-2: Sessions die with the hosting terminal — no unattended operation

The VM session lives exactly as long as the terminal running `make vm-up`
(README sharp edge 3; ARCHITECTURE.md "Session lifecycle" step 1).

- **What goes wrong:** closing a terminal or dropping SSH kills every agent
  run in flight. No overnight runs, no scheduled phases, CI cannot rely on
  a shared long-lived session.
- **Evidence:** README "Known sharp edges" #3 and roadmap bullet 2
  ("launchd-hosted persistent sessions for unattended operation"); ADR-0001
  Option A (ephemeral per-run boots) is named but rejected for interactive
  use and never built for unattended use.
- **Impact:** the solo operator on every disconnect/unattended window; a
  hard blocker for any CI/scheduled flow.
- **Frequency:** constant constraint.

## P-3: Nothing triggers the next SDLC phase — merges don't materialize downstream work

The git-native pipeline is designed as "merges are materializations"
(`docs/GIT-NATIVE-PIPELINE.md`, PRD-006; gates in `docs/GITHUB-GATES.md`),
but today every phase is a manual `make agent-decision PHASE=…`.

- **What goes wrong:** the spiral stalls whenever the human forgets the next
  make target; PR labels and human gates have no enforcement point; the
  phase-to-phase audit chain has manual gaps.
- **Evidence:** README quick start (all phases hand-invoked) vs roadmap
  bullet 3 ("GitHub Actions wiring: CI runs agents in ephemeral gondolin
  VMs"); GITHUB-GATES.md pipeline (design) vs Makefile (reality).
- **Impact:** operator + reviewers; pipeline reliability collapses to human
  memory.
- **Frequency:** once per phase per feature.

---

## Deferred (out of scope this round)

- Non-macOS session hosting (P-2 is macOS-first per ADR-0001 context;
  Linux/Windows can adopt the P-2 ephemeral-boot solution instead).
- Central multi-user service — USE-CASES.md §6 explicitly requires none
  (per-user sessions, shared snapshot file).
- Audit-trail depth — PRD-004 owns it.
