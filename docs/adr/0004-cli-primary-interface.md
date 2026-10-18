# ADR-0004: The `facty` CLI as the primary interface; the stdlib-only rule retired

**Status:** accepted · **Date:** 2026-10-17
**Deciders:** PO (in-session direction) + coding agent (implementation)
**Supersedes:** the "stdlib only" bullet in the repo conventions (AGENTS.md)

## Context

The interface was a stepping stone: `engine/cli.py` was an interactive
walkthrough, and the Makefile's `dss-*` targets were the de-facto
interface. The PO directed (2026-10-17): the primary first-class
interface and control should be a world-class CLI, and pointed at
[Textual](https://textual.textualize.io) for it. The repo convention was
*stdlib only* ("deterministic, portable, no install step — the VM
snapshot has no pip guarantees").

The tension: knowledge-developer experience wants libraries; the golden
path (engine, selftest, VM runs, CI) must run anywhere.

## Decision drivers

1. **#1 focus: knowledge-developer experience** (PO, 2026-10-17).
2. The real invariant is not stdlib-ness but **auditable text-file
   records** — case records are JSON artifacts now, a DB later. The
   artifact model is the audit trail (PO, 2026-10-17).
3. The verdict path stays deterministic — no LLM call, clock, or random
   source in it; same artifacts → byte-identical verdict.
4. The engine core + control plane must run in the gondolin VM snapshot
   (no pip guarantees, no pypi in the egress allow-list) and in CI (no
   TTY).
5. The dev host has pypi access; the sandbox/VM does not.

## Considered options

### Option 1: full Textual TUI as the only interface — rejected

A TUI cannot be the control interface: CI has no TTY, agents in VMs
script the CLI, and `--json` verdicts are the audit surface. The TUI is
the *primary human* interface, not the only one.

### Option 2: third-party CLI framework (Click / Typer / cyclopts) for the control plane — deferred

Nice-to-have polish, but the control plane's job is reliability,
scriptability, and running in the VM. A framework dependency would break
the VM path unless baked into the snapshot, for marginal gain over a
well-built argparse CLI (subcommands, tables, colors, `--json`, shell
completion). Revisit if the control plane's DX demands it.

### Option 3: stdlib control plane + Textual workbench as the primary interface — chosen

Bare `./facty` opens the Textual workbench (the primary interface: case
picker + interactive case board). The subcommands are the scriptable
control plane. The engine core and control plane stay dependency-free.

### Option 4: keep stdlib-only everywhere — rejected

The PO retired the rule (2026-10-17). What survives of it is a *choice*,
not a blanket constraint: the verdict path and the VM/CI path stay
dependency-free because that is the audit/replay contract.

## Decision

1. **The stdlib-only rule is retired** (PO, 2026-10-17). Replacement
   invariants: (a) deterministic verdict path; (b) auditable text-file
   case artifacts (JSON now, DB later); (c) engine core + CLI control
   plane dependency-free (VM snapshot, CI, audit); optional DX layers
   import lazily and degrade gracefully.
2. **The primary interface is the `facty` CLI**: `./facty` (repo-root
   launcher, prefers the project venv) = `python3 engine/cli.py`.
   Subcommands: `run`, `cases`, `selftest`, `test`, `sense`,
   `walkthrough`, `tui`, `emit`, `completion`, `version`. `--json` on
   `run`/`cases`. Shell completion for bash/zsh/fish. The `dss-*` make
   targets are thin wrappers.
3. **Textual is the workbench layer** (`engine/tui.py`, behind bare
   `./facty` and `./facty tui <case>`): case picker, case board
   (evidence · streamed chain log · ranking + verdict), read-only
   evidence viewer, live LLM sensing streamed into the log. Latest
   available version (`requirements.txt`, unpinned — refresh with
   `uv pip install -U -r requirements.txt`; `make deps`).
4. **Demo cases are typed and prefixed** (`<type>-<slug>`):
   `attribution-silver-blaze`, `adjudication-phantom-invoice`,
   `causation-three-am-outage`. See
   [docs/INVESTIGATION-TYPES.md](../INVESTIGATION-TYPES.md).
5. **The workbench is tested headless** (`engine/test_tui.py`, Textual's
   `run_test` pilot — no TTY needed), wired into `./facty test` /
   `make dss-test`.

## Consequences

**Positive**

- The knowledge-developer experience is now the centerpiece: one command
  (`./facty`) opens an interactive board over the deterministic engine.
- The audit story is unchanged and strengthened: the control plane
  (`run --json`, `selftest`) is dependency-free and runs everywhere.
- The TUI is tested for real (headless pilot), not just by construction.

**Costs / risks**

- The VM cannot run the workbench until the gondolin snapshot bakes in
  Textual (and a modern Python — the sandbox's system python3 is 3.9;
  `make deps` uses uv's managed Python). Snapshot rebuild:
  `gondolin-pi.sh build --force`. The control plane is unaffected.
- `requirements.txt` is unpinned (latest available, per PO) — pin after
  the first stable host run if reproducibility demands it.
- The TUI's live-sensing path (`s` key) needs the LLM credential; it
  falls back to the recorded sensing, same as the walkthrough.

**Follow-ups**

- Consider Click/Typer for the control plane if its DX demands it
  (Option 2).
- Pin the Textual version after the first stable host run.

## Update — 2026-10-17 (later same day)

- The workbench runs the **full e2e pipeline**: the LLM senses the
  evidence (induction, streamed behind clickable log lines), then the
  engine decides (deduction). Before, "run" replayed the recorded facts
  only — which is why it completed instantly.
- **Response cache** (`.agentic/cache/sensing/`): live calls are cached
  as raw responses; `FACTY_SENSE=cache` replays them without the LLM
  (offline, reproducible demos). See engine/README.md.
- **Workbench authentication**: the `a` key (or the command palette)
  drives pi's `/login` — the pi-mistral-subscription extension's browser
  OAuth — behind the scenes; the credential lands in pi's auth storage.
- **The gondolin snapshot bakes textual + git** (`build-snapshot.sh`),
  so the CLI and the workbench run in the VM with zero runtime installs;
  the runner injects `MISTRAL_API_KEY` via gondolin's host-secret
  interface (guest sees a placeholder; the host proxy substitutes the
  real value). The earlier "VM caveat" is resolved.
- **Custom providers are contemplated** (PO, 2026-10-17): the env seams
  (`FACTY_PROVIDER` / `FACTY_MODEL`, per-provider `auth.status`) are in
  place; the providers config + UI are future work — see
  [docs/PROVIDERS.md](../PROVIDERS.md).
