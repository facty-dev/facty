---
# Discovery — Solutions
---

# Solutions — candidates per problem

**Status:** draft · **Version:** 0.1 · **Date:** 2026-10-15
**Parent:** `problems.md` (P-1…P-3) · Assumptions detailed in `assumptions.md`

---

## For P-1: hand-typed client-session rituals

### S1-a: Declarative client manifests + make wrapper *(recommended)*
- **Description:** `clients/<client>.yaml` declares mount path, secret env
  names + target hosts, egress allow-list, snapshot ref.
  `make client-up CLIENT=acme` renders the gondolin invocation from the
  manifest and records session metadata to `.agentic/tenants/<client>.json`
  (same socket-path pattern as `.agentic/vm-session.json`).
- **How it addresses the problem:** every USE-CASES.md scenario becomes one
  command; policy becomes reviewable versioned data instead of a typed
  command line; the README's naming conventions get an implementation.
- **Effort:** M · **Confidence:** high

### S1-b: Tenant registry CLI
- **Description:** `scripts/tenant.sh add|list|status|down` keeps per-client
  state in `.agentic/tenants/`, wrapping the same gondolin calls.
- **How it addresses the problem:** adds lifecycle management beyond S1-a's
  boot path, at the cost of a second interface to learn and maintain.
- **Effort:** M–L · **Confidence:** medium

### S1-c: Runbooks only (status quo + docs)
- **Description:** document the exact command per use case; no tooling.
- **How it addresses the problem:** it doesn't — it documents the ritual
  without removing the error surface.
- **Effort:** S · **Confidence:** low

## For P-2: sessions die with the hosting terminal

### S2-a: launchd-hosted detached sessions *(recommended, macOS-first)*
- **Description:** ship a LaunchAgent plist template
  (`scripts/com.facty.vm.plist`); `make vm-up --detached` installs and
  loads it. The session process is owned by launchd, so it survives
  terminal/SSH death. `make vm-status`/`vm-down` keep using the recorded
  socket path.
- **How it addresses the problem:** unattended windows (overnight, SSH
  disconnects) no longer kill runs; no daemon beyond the OS-native one.
- **Effort:** M · **Confidence:** medium-high

### S2-b: Ephemeral per-run boots
- **Description:** for unattended work, drop long-lived sessions entirely:
  every agent run boots a fresh VM from the snapshot (`--resume`), runs one
  phase, writes artifacts to `/workspace`, exits. This is ADR-0001's
  Option A, restricted to unattended/CI contexts where warm state doesn't
  matter.
- **How it addresses the problem:** nothing to keep alive; session lifetime
  becomes a non-issue for batch runs. Shares machinery with P-3's CI
  solution.
- **Effort:** M · **Confidence:** medium

### S2-c: tmux/nohup supervisor
- **Description:** keep the session foreground inside a detached tmux;
  scripts reconnect to it.
- **How it addresses the problem:** partially — the session still depends on
  a human-owned process tree and machine session.
- **Effort:** S–M · **Confidence:** low

## For P-3: merges don't trigger phases

### S3-a: GitHub Actions wiring — ephemeral VMs in CI *(recommended)*
- **Description:** label-triggered workflows (`sdlc:discov|prd|bdd|impl`)
  boot an ephemeral gondolin VM from a cached snapshot artifact, exec the
  right agent role, and open a phase PR. Human gates are PR approvals, per
  GITHUB-GATES.md. Egress allow-list + host-secret injection reproduce the
  local isolation model inside the runner.
- **How it addresses the problem:** merge of a phase branch PR actually
  materializes the asset and triggers the downstream phase; gates become
  enforced; unattended phases get a home (pairs with S2-b).
- **Effort:** L · **Confidence:** medium

### S3-b: Local merge-triggered dispatcher
- **Description:** a post-merge hook / watcher on `sdlc/<phase>/*` merges
  launches the next phase locally via existing make targets + session.
- **How it addresses the problem:** merge-triggered progression without CI
  dependency; humans stay in the terminal loop.
- **Effort:** M · **Confidence:** medium

### S3-c: Manual with checklists (status quo)
- **Description:** keep `make agent-*`; document the spiral in the README.
- **How it addresses the problem:** it doesn't — human memory remains the
  trigger.
- **Effort:** S · **Confidence:** low
