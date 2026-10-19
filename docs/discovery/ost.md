# Opportunity Solution Tree — Pack Studio (the knowledge authoring workbench)

**Date:** 2026-10-18
**Facilitator:** PO session (chart) + coding agent, collaborative discovery
**Status:** draft <!-- draft | in-review | approved -->
**Version:** 0.1

---

## Desired Outcome

A domain expert (fraud analyst, SRE, claims adjuster — not a Facty engineer) can create a complete, tested, deterministic knowledge engine (a **pack**) on Facty in a single sitting — by describing their domain and answering questions — with the LLM as their pair programmer and the symbolic engine as the validator. By 2026-12-31.

---

## Opportunities (Problems)

### OPP-001: Pack authoring is hand-coded JSON — the knowledge acquisition bottleneck
- **Description:** every pack today is hand-edited JSON (rules, constraints, hypotheses, labels). This is the exact bottleneck that caused the 1980s AI winter — expert systems needed human knowledge engineers and didn't scale. The Facty team is the bottleneck for every new vertical.
- **Evidence:** `engine/cases/*/pack/` (all hand-authored); no pack-authoring UI in `engine/tui.py`; the pack factory (`scripts/agent-pi.sh`) is internal-only.
- **Impact:** every potential Facty user who is not a Facty engineer. The "domains are packs" thesis is unproven at the user level.
- **Frequency:** every new domain, every pack iteration.
- **Source:** PO session 2026-10-18; AI-winter literature; `docs/discovery/verticals.md`.

### OPP-002: No structured way to elicit domain expertise — the "interview" is ad-hoc
- **Description:** there is no question-driven process for extracting a domain expert's knowledge. Pack authors guess what entities, predicates, rules, and hypotheses matter. Gaps surface only when a case fails.
- **Evidence:** `docs/discovery/detective-dss-poc.md` (hand-written, no elicitation protocol); the SDLC discovery phase is open-ended, not question-driven.
- **Impact:** pack quality depends on the author's domain knowledge, not the expert's. The expert is not in the loop.
- **Frequency:** every new pack, every pack refinement.
- **Source:** PO session 2026-10-18.

### OPP-003: No LLM-assisted authoring — the LLM is sensing-only
- **Description:** the LLM in Facty only senses (reads evidence into facts). It never helps author the pack — never drafts a rule, suggests a label set, or reviews constraints for gaps.
- **Evidence:** `engine/sensing.py` (extraction only); `engine/label.py` (hand-written config); `engine/strom.py` (one-shot `--op decide`, not interactive).
- **Impact:** rule authoring is slow and error-prone. Authors miss edge cases.
- **Frequency:** every rule, every label set, every schema.
- **Source:** PO session 2026-10-18.

### OPP-004: No test harness during authoring — blind iteration
- **Description:** there is no way to test a pack incrementally. You write rules, run a full case, and hope. No "what fires on this fact set" preview, no gap analysis.
- **Evidence:** `engine/engine.py` (`run_case` is all-or-nothing); `./facty run <case>` runs the full pipeline; no authoring mode.
- **Impact:** pack authors iterate blind. Pack quality is low; authoring is frustrating.
- **Frequency:** every rule change, every constraint change.
- **Source:** PO session 2026-10-18.

---

## Solutions

### For OPP-001: hand-coded JSON pack authoring

#### SOL-001-A: Pack Studio TUI — the knowledge authoring workbench *(recommended)*
- **Description:** a new section in the Textual workbench with four surfaces: schema curator, rule editor, label sensor config, test harness. JSON-backed, with live schema validation.
- **How it addresses the problem:** pack authoring becomes a first-class UI, not a JSON-editing exercise.
- **Effort:** L · **Confidence:** high

#### SOL-001-B: CLI-first pack authoring
- **Description:** `./facty pack new|edit|test` — terminal-only workflow. Faster to build, less polished.
- **Effort:** M · **Confidence:** medium

#### SOL-001-C: External editor + validation only (status quo + tooling)
- **Description:** keep hand-editing JSON, add `./facty pack validate`. Doesn't help author.
- **Effort:** S · **Confidence:** low

### For OPP-002: no structured domain elicitation

#### SOL-002-A: The meta-Facty loop — question-driven domain composition *(recommended, the key innovation)*
- **Description:** Pack Studio's embedded agent runs a structured interview with the user. The engine generates questions (what entities? what predicates? what rules?), the user answers, the agent generates symbolic representations (schemas, rules, constraints, hypotheses, labels), the test harness validates, and the loop iterates until the user is satisfied.
- **How it addresses the problem:** the domain expert's knowledge is systematically extracted, not guessed. The pack is complete by construction.
- **Key insight:** this is **literally using Facty to compose a domain** — the same question-generation and sensing machinery that investigates a case is used to investigate the user's domain knowledge.
- **Question UI:** [`@adeilo/pi-ask-questions`](https://github.com/felipeadeildo/pi-harness/tree/main/packages/ask-questions) (chosen 2026-10-19 — see decision log). The extension renders engine-generated questions as a questionnaire dialog in pi's TUI: options with previews, **notes on options** (domain expertise is nuanced — notes capture context), free-text answers, multi-select, and a **review tab** before submitting. Over RPC, questions go one at a time through the host's select/input dialogs. Chosen over `@zhushanwen/pi-ask-user` (decision-making philosophy, no notes, no review tab) and the skill-based options (`@rmrdeveloper/sideroom-pi`, `@geminixiang/pi-jev`). Installed in the gondolin VM snapshot (`gondolin/build-snapshot.sh`); the `pack-factory` skill (`gondolin/skills/pack-factory/`) instructs the agent to use it.
- **Docassemble model:** questions are data, not code; the engine generates them dynamically (gap analysis drives the next question); conditions are the engine's gap analysis; the output is the pack. See `gondolin/skills/pack-factory/SKILL.md` for the full mapping.
- **Effort:** L · **Confidence:** high (the machinery exists; it's a re-application)

#### SOL-002-B: Template-based pack scaffolding
- **Description:** `./facty pack new <domain>` scaffolds from a template. User fills in blanks.
- **Effort:** M · **Confidence:** medium

#### SOL-002-C: Free-form agent interview (no engine-driven questions)
- **Description:** the agent asks free-form questions. No structured elicitation.
- **Effort:** M · **Confidence:** low

### For OPP-003: no LLM-assisted authoring

#### SOL-003-A: Embedded pi agent — the knowledge engineer's pair programmer *(recommended)*
- **Description:** a persistent chat pane in Pack Studio. The agent drafts rules, suggests labels, reviews for gaps, drafts Strom questions, explains engine behavior. Same pi RPC transport as sensing.
- **How it addresses the problem:** the LLM becomes the authoring assistant. The human is the knowledge engineer; the LLM is their pair programmer.
- **Effort:** M · **Confidence:** high

#### SOL-003-B: One-shot LLM ops (status quo extended)
- **Description:** `./facty pack draft-rules`, `./facty pack suggest-labels` — one-shot CLI ops.
- **Effort:** M · **Confidence:** medium

### For OPP-004: no test harness during authoring

#### SOL-004-A: Live test harness in Pack Studio *(recommended)*
- **Description:** a "Test" tab: drop sample evidence → run engine → see verdict + trace + gap analysis (unproven hypotheses, dead rules, missing constraints). Tight authoring loop.
- **Effort:** M · **Confidence:** high

#### SOL-004-B: CLI test mode
- **Description:** `./facty pack test <name> --facts <file>` — terminal-only.
- **Effort:** S · **Confidence:** medium

---

## Recommended path

**SOL-001-A + SOL-002-A + SOL-003-A + SOL-004-A** — the full Pack Studio.

**Build order (smallest slices first):**
1. **SOL-004-B** (CLI test mode) — proves the test harness; smallest slice
2. **SOL-003-B** (one-shot LLM ops) — proves the LLM authoring path
3. **SOL-001-A** (TUI surfaces) — the workbench
4. **SOL-003-A** (embedded agent pane) — the pair programmer
5. **SOL-002-A** (meta-Facty loop) — the full elicitation loop; ties everything together

**Then:** build the insurance fraud pack *using* Pack Studio (dogfood).

---

## The meta-Facty loop (central design)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  THE META-FACTY LOOP (domain composition)                               │
│                                                                         │
│  User describes their domain (free text, examples, sample evidence)     │
│       │                                                                 │
│       ▼                                                                 │
│  Engine generates QUESTIONS (what entities? what predicates? what       │
│  rules? what hypotheses? what labels?) — driven by the pack schema      │
│       │                                                                 │
│       ▼                                                                 │
│  User answers (the "evidence" is the conversation)                       │
│       │                                                                 │
│       ▼                                                                 │
│  Agent generates SYMBOLIC REPRESENTATIONS (schemas, rules, constraints,  │
│  hypotheses, labels) — schema-guided extraction from the answers        │
│       │                                                                 │
│       ▼                                                                 │
│  Validate (run the engine on sample scenarios, check for gaps)          │
│       │                                                                 │
│       ▼                                                                 │
│  User reviews and refines — iterate until satisfied                     │
│       │                                                                 │
│       ▼                                                                 │
│  Pack is complete (exportable, testable, versioned in git)              │
└─────────────────────────────────────────────────────────────────────────┘
```

| Case loop (Facty today) | Meta-Facty loop (Pack Studio) |
|---|---|
| Evidence (messy files) | User's answers (conversation) |
| Facts (sensed by LLM) | Domain concepts (entities, predicates) |
| Rules (chain facts) | Rules (authored from concepts) |
| Hypotheses (explanations) | Hypotheses (the explanation space) |
| Constraints (prune) | Constraints (prune invalid packs) |
| Open questions (engine asks) | Open questions (engine asks the user) |
| Verdict (deterministic) | Validated pack (deterministic, testable) |

---

## Decision log

| Date | Decision | Decider | Rationale |
|---|---|---|---|
| 2026-10-18 | Scope Pack Studio as a new discovery round; archive the 2026-10-15 OST (multi-client session management) | PO (chart) | The pack authoring workbench is the highest-value next step; it closes the knowledge acquisition bottleneck and makes "domains are packs" real for users. |
| 2026-10-18 | The meta-Facty loop (SOL-002-A) is the central design — re-apply Facty's question-generation and sensing machinery to domain composition | PO (chart) | "Literally use facty itself to help composing a domain by generating and asking questions until the user has fully explained their expertise." The machinery exists; it's a re-application, not a new build. |
| 2026-10-18 | Build order: CLI test mode → one-shot LLM ops → TUI surfaces → embedded agent → meta-Facty loop | PO (chart) | Smallest slices first; each step proves a capability before the next builds on it. |
| 2026-10-18 | Dogfood: build the insurance fraud pack using Pack Studio | PO (chart) | Proves the platform works; gives us the flagship demo. |
| 2026-10-19 | Question UI for the meta-Facty loop: `@adeildo/pi-ask-questions` | PO (chart) | Notes on options + review tab fit domain elicitation (nuanced expertise); questionnaire philosophy ("ask instead of guessing") matches the use case. `@zhushanwen/pi-ask-user` is decision-making-focused (no notes, no review). Installed in the VM snapshot; the `pack-factory` skill wraps it. |
| 2026-10-19 | Pack Studio MVP complete: CLI test mode (task 004) + one-shot LLM ops (task 005) | PO (chart) | `./facty pack list/validate/test/draft-*/review` all work; `test_pack.py` 71/71; `./facty selftest` 69/69. The deterministic half + the LLM half of the MVP are done. Follow-up: TUI surfaces, embedded agent pane, meta-Facty loop integration. |
| 2026-10-19 | Mistral credential bridge: local dev uses the subscription token (no per-token overage) | PO (chart) | `vm-session.sh` / `agent-pi.sh` read the `mistral-subscription` token from `~/.pi/agent/auth.json` and pass it as `MISTRAL_API_KEY` to gondolin's host-secret. Production: set `MISTRAL_API_KEY` explicitly. Documented in AGENTS.md. |
