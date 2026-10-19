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
./facty pack list        # the Pack Studio: the packs under packs/ (artifact counts)
./facty pack validate <pack>       # validate a pack (schema + cross-artifact)
./facty pack test <pack> --facts <file>    # run the pack on a fact set + gap analysis
./facty pack test <pack> --tests <dir>     # run every scenario, assert expected
./facty pack draft-rules <pack> --domain "..." [--write]   # draft rules.json (LLM, judged, staged)
./facty pack suggest-labels <pack> --evidence <file> [--write]   # draft classify.json (LLM, staged)
./facty pack draft-hypotheses <pack> --domain "..." [--write]   # draft hypotheses.json (LLM, staged)
./facty pack draft-questions <pack> [--write]   # draft sensor/decisions.json (LLM, judged, staged)
./facty pack review <pack>     # advisory gap review (prose, never written)
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
- `label.py` — the label sensor: the sensor ladder (a small CPU-only
  zero-shot classifier + the Strom decision tier; see "The label
  sensor" below)
- `strom.py` — the Strom decision-tier client (stdlib-only: retries,
  rate-limit throttle, typed errors; the key never logged)
- `dotenv.py` — the dotenv setup (`~/.facty/.env` + `./.env`,
  setdefault — the real environment always wins)
- `test_retry.py` — the correction loop, tested with a stubbed runner
  (no LLM needed)
- `test_label.py` — the label sensor, tested with a stubbed classifier
  (no model needed)
- `test_strom.py` — the decision tier + backend dispatch + the
  question judge, tested with stubbed clients (no API, no key)
- `test_dotenv.py` — the dotenv setup + `facty env` (no real secrets)
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
- `pack.py` — the Pack Studio library: validate, test, and diagnose
  knowledge packs (`packs/<slug>/`) — the authoring side of the
  detective DSS (PRD-007). stdlib only; the deterministic half
  (schema + cross-artifact validation, the test run with gap
  analysis, the scenario runner, the draft staging policy)
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
Env knobs: `FACTY_PROVIDER`, `FACTY_MODEL`, `FACTY_THINKING`.

Sessions are **scoped one per run** (a case phase instance):
`sensing.session_scope()` wraps a run (the workbench's `do_run`, the
walkthrough), so its LLM calls share one pi process and one conversation
prefix — the provider's prompt cache hits across the calls (measured
19–77% of input served from cache on the demo cases; the run log prints
the summary). A new run — another case or another phase — starts a
fresh session: nothing crosses case/phase boundaries, and the
conversation holds only the senses' own Q&A, never the engine's
conclusions — the cache benefits without the bias.

To debug the sensing steps:

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
| `classifier · induction` | the label sensor, tier 1 — a small CPU-only classifier labels the evidence pile (per-row + aggregate facts, confidence-gated) | induction |
| `decider · induction` | the label sensor, tier 2 — the Strom decision model adjudicates rows (calibrated probabilities; drafted question set; API usage logged) | induction |
| `offline` | offline mode — LLM ops replay the response cache; the label sensor runs the local tier only | — |
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

## The label sensor (the sensor ladder)

The numeric sense for categorical evidence (`engine/label.py` +
`engine/strom.py`). A case declares its labeling task in
`classify.json` — the evidence file, the text column, the label set, a
confidence threshold, the model, the prep mode, the **backend** — and
the sensor scores every row against the labels, emitting one fact per
row plus aggregate facts. Below the threshold the fact says
`unclassified` — the confidence-gated handoff (the next tier or the LLM
picks those rows up). The sensors never touch the verdict path; they
emit facts, the engine decides.

The **backend** knob selects the tiers:

- `strom` (default) — the **Strom decider tier** (`engine/strom.py`:
  Uprelic's hosted decision model, `strom-1.0.7`, EU/Paris GPUs,
  calibrated probabilities, ~$0.04 per 1M input tokens) scores every
  row; the local classifier is the automatic fallback when the API is
  unreachable, the key is missing, or the balance is empty. Measured on
  the demo pile: 96.0% vs the classifier's 75.6% on the rows that
  clear the gate. Note the decider tier is probabilistic (re-asked
  rows wobble past the 4th decimal; rows near the gate can flip) and
  rate-bound (500 req/min) — the recorded facts + response cache are
  the deterministic layer.
- `hybrid` — tier 1 scores the bulk; the decider tier adjudicates the
  rows tier 1 gated (the confidence-gated handoff, calibrated). Faster
  and less egress at volume; the demo case pins this to show the ladder.
- `local` — tier 1 only (the offline mode; also forced by `--offline` /
  `FACTY_OFFLINE=1`): the small local NLI classifier scores every row
  (zero-shot: premise = the row text, hypothesis = the template with
  the label, entailment − contradiction softmaxed across the labels).
  Deterministic, free, local, unlimited.

The Strom question set is drafted once per pack by the LLM
(`--op decide` → `sensor/decisions.json`, a committed artifact) in a
capped correction loop (1 initial + 2 revisions) judged by a
**decision-question judge**: structure (schema), label coverage (a
choice question whose criteria keys are exactly the labels), and a dry
run against the API on a row sample. The drafted questions may add
`noul`/`score` decision questions whose answers become per-row
`dq-*` facts (the question name is the predicate). The key rides
`UPRELIC_API_KEY` (env / gondolin host-secret injection) — never
logged, never committed. With no key, a 402, or an outage, the decider
tier is skipped (logged) and the gated rows stay `unclassified`.

```bash
make deps-sensors                                   # onnxruntime + transformers<5 (host/CI)
./facty sense alert-flood --op label                # label the pile (streamed log, both tiers)
./facty sense alert-flood --op label --json         # machine-readable facts
./facty sense alert-flood --op parser               # generate sensor/extract.py (prep=parser cases)
./facty sense alert-flood --op decide               # draft sensor/decisions.json (LLM, judged)
./facty sense alert-flood --op label --offline      # offline mode: local tier live, LLM ops from cache
FACTY_SENSE=cache ./facty sense alert-flood --op label   # replay the cache, no model call
```

Secrets ride the dotenv setup (`engine/dotenv.py`, loaded at startup):
real keys live in `~/.facty/.env` (machine-local, never committed —
the repo is mounted into the VMs); `./facty env` prints the status
(never values) and `eval "$(./facty env --exports)"` hoists the keys
into the launching shell for the gondolin VMs (host-side `--host-secret`
injection; the guest only ever sees placeholders). See `.env.example`.

`classify.json` knobs: `labels` + `template` (the pack owns the
vocabulary — phrasing is pack design, measured to matter), `scoring`
(`margin` default — calibrated confidences; `entail`), `threshold`
(per-pack calibration knob), `model` (an ONNX repo) + `precision`
(`fp32` | `int8`), `backend` (`local` | `hybrid` | `strom`), optional
`criteria` (label → description, for the Strom choice question), and
`prep`:

- `none` (default) — structured evidence (CSV): read the columns
  directly; the LLM never sees the pile (the token-saving case).
- `parser` — semi-structured mess: a generated, committed, tested,
  stdlib-only parser (`sensor/extract.py` + `sensor/extract_test.py`)
  extracts the rows. The parser is written once per evidence format by
  an LLM (`--op parser`) in a capped correction loop (1 initial + 2
  revisions) judged by a **code judge**: a static contract check
  (stdlib-only imports, no dangerous builtins, a `parse(text)` function),
  an execution check in a subprocess with a timeout, its unit tests,
  a completeness check (no silent line drops), and the row schema.
- `llm-filter` — the LLM reads the messy evidence and emits candidate
  rows (its judgment strength: relevance); the classifier labels them.

Fallback ladder (logged, never silent): rows → classifier → facts;
prep or classifier failure → raw chunks (classify the messy text
as-is, threshold-gated) → facts; everything failed → the response cache,
then the recorded facts. Sensor-sourced evidence is excluded from the
LLM's phase-1 files (`cli.phase1_evidence`), so the pile never enters an
LLM call. The demo case `triage-alert-flood` shows the ladder in the
verdict loop (classifier bulk + Strom adjudication); see its
`SENSING.md` for the measured accuracy and calibration notes.

## Pack Studio — the LLM authoring ops

The one-shot authoring ops (`pack draft-rules` / `suggest-labels` /
`draft-hypotheses` / `draft-questions` / `review`) are the "pair
programmer" half of the Pack Studio MVP (PRD-007 REQ-010…016): the LLM
drafts a pack artifact, the judge layer checks it (the artifact's
schema + the pack's cross-artifact rules — unique ids, raise targets
that exist, the pack field matching the directory; `suggest-labels`
checks the classify.json structure; `draft-questions` reuses the
`--op decide` decision-question judge, dry run against Strom
included), and the human accepts. Like the sensing ops they are
induction only — never in the verdict path — and the prompts carry the
author's domain description plus the pack's ontology (its hypotheses
and term vocabulary), never the engine's conclusions. The `review` op
is the exception by design: it is advisory commentary *about* the pack,
fed the artifacts plus the deterministic gap analysis over the pack's
test scenarios (dead rules, unraised hypotheses, unanswered questions).

The draft write policy (REQ-015): a draft op **never writes the pack**.
It stages `<artifact>.draft.json` beside the target and prints a
summary; the human accepts explicitly with `--write` (or re-runs the
op with `--write`). `pack review` prints advisory prose and never
writes — the pack directory is byte-identical before and after.

The plumbing (REQ-016) is the sensing path's: the LLM's response
streams live, the raw response is cached (`.agentic/cache/sensing/`,
keyed by the pack + the prompt), and `FACTY_SENSE=cache` or
`--offline` replays it byte-identically with no LLM call. One pi
session per `pack` command (the CLI wraps it in
`sensing.session_scope()`), so the provider's prompt cache hits across
the op's correction turns. When the LLM is unreachable or the judge
rejects, the op logs the failure and exits with a clear error — no
silent fallback (the draft is the point; re-run when the LLM is back).
Locally the ops run through the pi agent's RPC mode and bill on the
Mistral **subscription** (the same credential as the workbench's `a`
key — no per-token overage; see AGENTS.md); `draft-questions`
additionally needs `UPRELIC_API_KEY` for the judge's dry run.

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
