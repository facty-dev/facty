# Assumptions — Pack Studio, per solution, marked testable/untestable

**Status:** draft · **Version:** 0.1 · **Date:** 2026-10-18
**Parent:** `solutions.md` (S1-a…S4-b)

Marks:
- **testable** — has a concrete validation command/spike runnable now.
- **untestable** — validated only by usage/judgment; state the fallback evidence (dogfooding, interview).

---

## S1-a: Pack Studio TUI

- **ASM-1a-1 (testable):** the four surfaces (schema curator, rule editor, label config, test harness) can share one pack state object (the canonical JSON artifacts) without conflicting writes.
  - **How to test:** build a minimal TUI with two panes editing the same `rules.json`; verify changes propagate and validate.
  - **Risk if wrong:** need a state-management layer (e.g., a pack model with change events) → effort grows.

- **ASM-1a-2 (testable):** Textual can render a split-pane layout (editor + agent chat + test output) at 80x24 without performance issues.
  - **How to test:** prototype the layout in `engine/tui.py`; measure render time with a 100-rule pack.
  - **Risk if wrong:** need a different layout (tabs instead of panes) or a lighter framework.

- **ASM-1a-3 (untestable):** domain experts (non-engineers) will use a TUI for pack authoring.
  - **Fallback evidence:** dogfood Pack Studio with 3 domain experts (fraud analyst, SRE, claims adjuster); measure time-to-first-pack.
  - **Risk if wrong:** need a web UI or a guided wizard instead of a free-form TUI.

## S2-a: The meta-Facty loop (question-driven domain composition)

- **ASM-2a-1 (testable):** the engine's question-generation (`op: open`) can be repurposed to generate *elicitation* questions (what entities? what predicates? what rules?) — not just case questions (what evidence to collect?).
  - **How to test:** extend `engine/engine.py` with an "elicitation mode" that opens questions about the pack schema (missing predicates, unproven hypotheses); run against a half-authored pack; verify the questions are relevant.
  - **Risk if wrong:** the engine's question model is too case-specific; need a separate elicitation question generator.

- **ASM-2a-2 (testable):** schema-guided extraction (`engine/sensing.py` `extract_structured`) can turn free-text domain descriptions into structured pack artifacts (rules, constraints, hypotheses) with the same judge-and-correct loop.
  - **How to test:** feed a domain description ("I investigate insurance claims; entities are policyholder, vehicle, repair shop; rules flag inflated line items…") into `extract_structured` with the rule schema; verify the output validates and is useful.
  - **Risk if wrong:** the extraction quality is too low for rule authoring; need a more structured prompt or a multi-turn loop.

- **ASM-2a-3 (testable):** the elicitation loop converges — after N rounds of question → answer → generate → validate, the pack is complete (no unproven hypotheses, no dead rules, no missing constraints).
  - **How to test:** run the loop on a known domain (insurance fraud); measure rounds-to-complete; verify the test harness shows no gaps.
  - **Risk if wrong:** the loop doesn't converge (oscillates, asks the same questions); need a convergence criterion or a human gate.

- **ASM-2a-4 (untestable):** domain experts will answer structured questions better than they can write rules from scratch.
  - **Fallback evidence:** A/B test — one expert authors a pack via the meta-Facty loop, another via hand-editing JSON; compare pack quality (measured by test harness gap analysis) and time.
  - **Risk if wrong:** experts prefer free-form description; the loop is just a guided editor.

## S3-a: Embedded pi agent (pair programmer)

- **ASM-3a-1 (testable):** the pi RPC transport (`pi --mode rpc`) can run as a persistent subprocess inside the TUI (one process per Pack Studio session), streaming responses to a chat pane.
  - **How to test:** embed a pi RPC subprocess in a Textual app; send a prompt; verify the response streams to the pane; verify the process is reused across turns.
  - **Risk if wrong:** need a different transport (HTTP API, or a pi session file); or the TUI event loop conflicts with the subprocess.

- **ASM-3a-2 (testable):** the agent can see the current pack state (schemas, rules, constraints, hypotheses, labels) and generate useful suggestions (draft a rule, suggest labels, review for gaps).
  - **How to test:** give the agent a half-authored pack; ask "what rules am I missing?"; verify the suggestions are relevant and validate against the schema.
  - **Risk if wrong:** the agent hallucinates rules; need a judge layer (same as sensing) to validate suggestions before showing them.

- **ASM-3a-3 (untestable):** domain experts will use the agent as a pair programmer (asking for help, not just accepting suggestions).
  - **Fallback evidence:** dogfood with 3 experts; measure how often they use the agent vs. hand-editing.
  - **Risk if wrong:** the agent is a one-shot generator, not an interactive assistant.

## S4-a: Live test harness

- **ASM-4a-1 (testable):** the engine can run in "authoring mode" — given a pack + a fact set, it produces a trace + gap analysis (unproven hypotheses, dead rules, missing constraints) in < 1s.
  - **How to test:** extend `engine/engine.py` with a `diagnose` function; run against a pack with known gaps; verify the gap analysis is correct and fast.
  - **Risk if wrong:** gap analysis is too slow or too noisy; need a simpler validation (schema-only, no engine run).

- **ASM-4a-2 (testable):** the test harness can reuse the existing sensing pipeline (`engine/sensing.py`, `engine/label.py`) to go from sample evidence → facts → verdict, without a full case directory.
  - **How to test:** build a "test" function that takes a pack + evidence files (in-memory or temp dir) → runs sense → derive → constrain → verdict; verify it matches a full case run.
  - **Risk if wrong:** the sensing pipeline is too coupled to case directories; need a refactor.

- **ASM-4a-3 (untestable):** authors will use the test harness iteratively (write rule → test → refine) rather than batch-editing.
  - **Fallback evidence:** dogfood with 3 authors; measure test runs per pack vs. hand-authoring.
  - **Risk if wrong:** authors prefer to write the whole pack then test once.
