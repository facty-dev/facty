# engine — the Facty symbolic engine

The deterministic half of the neurosymbolic split
([ADR-0003](../docs/adr/0003-detective-dss-neurosymbolic-core.md)):
forward + backward chaining over rules, with a constraint layer, over
canonical case artifacts. The LLM (Mistral Large 4) senses and proposes;
this engine verifies, chains, prunes, and decides. stdlib only —
deterministic, replayable, no network, no database, no LLM in the verdict
path.

## Run

The primary interface is the **`facty` CLI** (`./facty`, or
`python3 engine/cli.py`):

```bash
./facty                  # the Textual workbench (TUI — the primary interface)
./facty tui <case>       # the workbench, straight into a case
./facty cases            # the demo cases (type · pack · phase-2 drop)
./facty run <case>       # run a case (phase 1) · --add-facts <drop> = phase 2 · --json
./facty selftest         # acceptance test — every case, asserted
./facty test             # all tests: selftest + retry loop + the TUI (headless)
./facty sense <case> --op facts    # one sensing op, standalone (streamed LLM)
./facty walkthrough <case>         # terminal step-through (VMs, no-TTY)
./facty emit             # codegen projections (TS types + Datalog per case)
./facty completion bash  # shell completion (bash|zsh|fish)
make deps                # install the optional deps (Textual — the workbench)
```

The engine core (`engine/engine.py`) and the control plane stay
dependency-free — they run in the gondolin VM snapshot and CI. Textual
(`engine/tui.py`) is the one optional dependency, imported lazily with a
graceful fallback. See
[ADR-0004](../docs/adr/0004-cli-primary-interface.md).

## Layout

- `schemas/` — the canonical artifact schemas (the common protocol)
- `engine.py` — the symbolic engine (library + CLI: `run`, `selftest`)
- `sensing.py` — the probabilistic half: schema-guided structured
  extraction (schema + messy input → validated object, LLM streamed),
  with a judge layer (schema + compute checks) and a capped correction
  loop — rejections feed back to the LLM, max 3 turns
- `test_retry.py` — the correction loop, tested with a stubbed runner
  (no LLM needed)
- `cli.py` — the `facty` CLI: the workbench entry (bare `./facty`) +
  the scriptable control plane (subcommands)
- `tui.py` — the Textual workbench (the primary interface; optional dep)
- `test_tui.py` — the workbench, tested headless (Textual's pilot)
- `cases/<type>-<slug>/` — the demo cases, prefixed with the
  investigation type
  ([docs/INVESTIGATION-TYPES.md](../docs/INVESTIGATION-TYPES.md)).
  Each case: `evidence/` (raw files), `pack/` (rules, constraints,
  hypotheses), the recorded sensing (`evidence-index.json`,
  `entities.json`, `facts.json`, `facts-<drop>.json`),
  `sensing-prompt.md` (the facts task), `SENSING.md` (the sensing
  record), `expected.md` (the outcome the selftest asserts):
  - `attribution-silver-blaze/` — the exemplar (detective work)
  - `adjudication-phantom-invoice/` — invoice fraud (adjudication)
  - `causation-three-am-outage/` — incident RCA (causation)
- `emit.py` → `emit/` — codegen projections (TypeScript types, Datalog)

## The protocol

Every artifact is JSON validated against `schemas/`. Facts are sensed by
the LLM (confidence + source spans); rules, constraints, and hypotheses
are the pack (authored with the pack factory, hypotheses proposed by the
sensing half); the engine's verdict is a deterministic function of those
artifacts alone.

## Debugging

The golden path for the LLM transport is the **pi agent, driven over its
RPC mode** (`pi --mode rpc`) — pi owns the credential and the engine
process never sees it (ADR-0003; the same isolation posture as the VM
host-secret mechanism). The runner sends the staged assignment inline as
a JSONL `prompt` command and streams the response back as `text_delta`
events — real live output (unlike `pi -p`, which prints the whole
response at the end). Each call is lean and one-shot: no tools, no
skills/context files/MCP, no session files, thinking off (a measured
~4.5x faster end-to-end on the demo cases), and pi is shut down the
moment the agent settles — no lingering process after the response.
Env knobs: `FACTY_PROVIDER`, `FACTY_MODEL`, `FACTY_THINKING`. To debug
the sensing steps:

```bash
# one sensing op, standalone (fast prompt iteration)
make dss-sense OP=facts          # or: classify | entities | ledger

# loud failures: no fallback, staged prompt path + exact pi command,
# raw LLM response on rejection
FACTY_DEBUG=1 make dss-live
# or: python3 engine/cli.py --debug ...

# the staged prompts persist for inspection:
ls .agentic/tmp/sensing-*.md

# reproduce a call manually (RPC mode; the staged prompt is the message):
pi --mode rpc --no-session --no-tools --provider mistral-subscription \
  --model mistral-large-4 --thinking off
# then write {"id":"s","type":"prompt","message":<staged prompt contents>}
# to its stdin and read the JSONL events on stdout
```

The fallback contract: when the LLM is unreachable (e.g. under an agent
sandbox, where pi cannot read its credential), the CLI logs the failure
and uses the recorded sensing (`SENSING.md`). In debug mode it fails loud
instead (exit 2, no fallback).

## The score (deterministic, documented)

```
score = 0.6 * claims_proven_ratio   (backward chaining)
      + 0.3 * support_ratio         (constraint layer)
      + 0.1 * prior                 (LLM plausibility, static input)
```

Rules take precedence over probabilities: the LLM's prior is the
smallest term, and the verdict never calls the LLM.

## The run log — tools and inference types

Every line in a run log (the walkthrough, the workbench) is tagged with
the tool that produced it and whether the inference was a **deduction**
(the engine) or an **induction** (the LLM senses). Facts are expressed
as triples: `subject / predicate = value`.

| Tag | Tool | Inference |
|---|---|---|
| `llm · induction` | the senses — messy evidence → facts; proposes hypotheses + tests | induction |
| `llm · commentary` | out-of-band LLM explanations (entities / ranking / verdict) — presentation only, never the verdict path | commentary |
| `fwd chain · deduction` | rules fire: derive facts, open questions, raise the hypothesis space | deduction |
| `constraint solver · deduction` | prune impossible explanations, support the survivors | deduction |
| `bwd chain · deduction` | prove claims, rank, deliver the verdict | deduction |

The workbench's run log is the colourful log: content is colour-coded
by event. Lines that carry more detail — a streamed LLM response — are
**expandable**: the LIVE line (the last line while the LLM streams;
press `e` for the latest) reveals the response inline, and the detail
live-appends while the response is still streaming (collapsed by
default, so the main output stays uncluttered). The same machinery
carries the out-of-band commentary (`x` — explain the verdict).

The senses are guided by the pack's **term vocabulary** (the predicates
and subjects the rules, constraints, and hypotheses reference) so a
fresh extraction speaks the pack's ontology — and the recommended
test's evidence is sensed with the engine's **open questions** and the
hypothesis space (statements only — never scores, rankings, derived
facts, or pruning verdicts: the engine's conclusions are never fed back
into the senses). The live path is a fresh LLM roll each run; the
recorded sensing and the response cache are the exact, replayable
paths.

## The response cache

Live LLM calls are cached as raw responses (`.agentic/cache/sensing/`,
machine-local, gitignored), keyed by a content hash of the case's input
evidence plus the prompt-template version (`PROMPT_VERSION` — bump it
when the templates change, so stale entries orphan instead of
replaying). The recommended test's sensing is keyed by its engine
context too (the open questions + hypothesis statements) — a changed
question set means a fresh key, never a stale response under new
questions. The out-of-band commentary is cached the same way (keyed by
the full prompt). Demos stay live by default; `FACTY_SENSE=cache` never
calls the LLM — it replays the cached responses (parsed + judged
deterministically) or falls back to the recorded sensing. So the
deterministic side runs offline, and demos replay reproducibly. Live
mode falls back: cache → recorded sensing. The workbench has a **Run
without the LLM (cached responses)** checkbox — enabled only when the
cache has an entry for every sensing step of the case
(`cli.cache_ready`); it is enabled automatically once a live run has
populated the cache.

## Workbench authentication

`./facty` (the workbench) authenticates the user's Mistral subscription
**through the pi-mistral-subscription extension**: the `a` key (or the
command palette) runs the extension's own OAuth login (a small node
driver, `engine/mistral-oauth-login.mjs`) and the credential lands in
pi's auth storage, where the sensing path reads it. The workbench
shows the auth status (never token values). The same machinery is the
seam for **custom providers** — see
[docs/PROVIDERS.md](../docs/PROVIDERS.md) (contemplated design).

## In the gondolin VM

The image config (runner + snapshot build + skills) is **vendored in this
repo at `gondolin/`** — the tooling (`scripts/agent-pi.sh`,
`scripts/vm-session.sh`, `make vm-up`) passes this copy in by default.
Build the snapshot once per machine with `make vm-image` (it lands in
`gondolin/snapshots/`, gitignored). The snapshot bakes `textual` (pip,
system python3) and git, so the CLI and the workbench run inside the VM
with zero runtime installs (the runtime egress allow-list has no pypi,
by design). The runner injects
`MISTRAL_API_KEY` via gondolin's host-secret interface — the guest sees
a placeholder, the host proxy substitutes the real value into outbound
requests to api.mistral.ai. The `facty` launcher prefers the project
venv only when it actually runs (a mounted host venv's binaries don't
run in the guest — the system python3 takes over).
