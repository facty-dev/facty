# Problems — Pack Studio discovery

**Status:** draft · **Version:** 0.1 · **Date:** 2026-10-18
**Sources:** PO session 2026-10-18, `docs/discovery/verticals.md`, `docs/adr/0003-detective-dss-neurosymbolic-core.md`, `engine/README.md`, AI-winter / knowledge-acquisition literature
**Scope note:** this round scopes the *pack authoring workbench* (Pack Studio) — the tooling that lets users create their own knowledge engines (packs) on Facty. It does not cover the engine itself (shipped), the sensing half (shipped), or the SDLC pack factory (shipped, but internal-only).

---

## P-1: Pack authoring is hand-coded JSON — the knowledge acquisition bottleneck

Every pack today is authored by hand-editing JSON files: `rules.json`, `constraints.json`, `hypotheses.json`, `classify.json`, `sensor/decisions.json`. This is exactly the bottleneck that caused the 1980s AI winter — expert systems (MYCIN, DENDRAL) required human knowledge engineers to encode domain expertise as rules, and it didn't scale.

- **What goes wrong:** a domain expert (fraud analyst, SRE, claims adjuster) cannot author a pack. They must learn JSON schemas, rule syntax, constraint semantics, and the sensor ladder. The Facty team becomes the bottleneck for every new vertical.
- **Evidence:** `engine/cases/*/pack/` — all hand-authored. The pack factory (`scripts/agent-pi.sh`, SDLC agents) automates *for the Facty team*, not for end users. No UI exists for pack authoring (`engine/tui.py` is a case workbench, not a pack editor).
- **Impact:** every potential Facty user who is not a Facty engineer. The "domains are packs" thesis is unproven at the user level — we have packs, but no way for users to make their own.
- **Frequency:** every new domain, every pack iteration, every rule refinement.
- **Root cause:** the LLM is used only for *sensing* (reading evidence into facts), never for *authoring* (helping write the rules). The knowledge engineer is still a human typing JSON.

## P-2: No structured way to elicit domain expertise — the "interview" is ad-hoc

There is no structured process for extracting a domain expert's knowledge. The pack factory's discovery phase is a free-form agent run; there is no question-driven elicitation loop.

- **What goes wrong:** domain knowledge stays in the expert's head. The pack author (human or agent) has to guess what entities, predicates, rules, and hypotheses matter. Gaps surface only when a case fails — late and expensive.
- **Evidence:** `docs/discovery/detective-dss-poc.md` — the PoC plan was hand-written; no elicitation protocol. The SDLC discovery phase (`templates/sdlc/agents/decision.md`) is open-ended, not question-driven.
- **Impact:** pack quality depends on the author's domain knowledge, not the expert's. The expert is not in the loop.
- **Frequency:** every new pack, every pack refinement.
- **Root cause:** Facty has a powerful question-generation engine (the case loop opens questions, the senses fill them) — but it is used only for *cases*, not for *domain composition*. The machinery exists; it is not applied to knowledge engineering.

## P-3: No LLM-assisted authoring of rules, labels, schemas — the LLM is sensing-only

The LLM in Facty today only senses: it reads evidence into facts, classifies evidence, extracts entities. It never helps *author* the pack — never drafts a rule, never suggests a label set, never reviews a constraint set for gaps.

- **What goes wrong:** the author writes every rule from scratch. There is no "pair programmer" for knowledge engineering. The LLM's ability to generate structured output (rules, schemas, labels) is unused.
- **Evidence:** `engine/sensing.py` — schema-guided extraction works (schema + input → validated object). But there is no "schema + domain description → rules" path. `engine/label.py` — the label config is hand-written. `engine/strom.py` — decision questions are drafted by an LLM (`--op decide`), but only as a one-shot op, not as an interactive authoring assistant.
- **Impact:** rule authoring is slow and error-prone. Authors miss edge cases, write inconsistent rules, and don't know what they don't know.
- **Frequency:** every rule, every label set, every schema.
- **Root cause:** the LLM is positioned as "the senses" (ADR-0003), not as "the knowledge engineer's assistant." The authoring loop is missing.

## P-4: No test harness for validating packs during authoring — you can't see if your rules work until you run a full case

There is no way to test a pack incrementally. You write rules, then run a full case, and hope the verdict is right. There is no "unit test" for a rule, no "what fires on this fact set" preview, no gap analysis.

- **What goes wrong:** pack development is a slow feedback loop. A rule that doesn't fire, a constraint that over-prunes, a hypothesis with unprovable claims — these surface only at case runtime. Debugging is manual and slow.
- **Evidence:** `engine/engine.py` — `run_case` is all-or-nothing. `./facty run <case>` runs the full pipeline. There is no "run the engine on this fact set and show me what derives" mode. The TUI (`engine/tui.py`) shows the trace *after* a run, not during authoring.
- **Impact:** pack authors iterate blind. Pack quality is low; authoring is frustrating.
- **Frequency:** every rule change, every constraint change, every hypothesis change.
- **Root cause:** the engine is a batch processor, not an interactive tool. There is no "authoring mode" that shows live derivation.

---

## Deferred (out of scope this round)

- Pack marketplace / sharing (future — needs Pack Studio first)
- Multi-user pack collaboration (future)
- Pack versioning / diffing UI (git handles versioning; UI for diffing is future)
- Non-TUI pack authoring (CLI-first is fine for v1; the TUI is the primary interface per ADR-0004)
