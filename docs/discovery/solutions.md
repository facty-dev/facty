# Solutions — Pack Studio candidates per problem

**Status:** draft · **Version:** 0.1 · **Date:** 2026-10-18
**Parent:** `problems.md` (P-1…P-4) · Assumptions detailed in `assumptions.md`

---

## The core insight: the meta-Facty loop

Facty's case loop is: **evidence → facts → hypotheses → discriminating tests → verdict**.

Pack Studio turns this inside out: instead of investigating a *case*, it investigates the *user's domain knowledge*.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  THE META-FACTY LOOP (domain composition)                               │
│                                                                         │
│  User describes their domain (free text, examples, sample evidence)     │
│       │                                                                 │
│       ▼                                                                 │
│  Facty generates QUESTIONS (what entities? what predicates? what        │
│  rules? what hypotheses? what labels?) — driven by the pack schema      │
│       │                                                                 │
│       ▼                                                                 │
│  User answers (the "evidence" is the conversation)                       │
│       │                                                                 │
│       ▼                                                                 │
│  Facty generates SYMBOLIC REPRESENTATIONS (schemas, rules, constraints,  │
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

This is **literally using Facty to compose a domain**:

| Case loop | Meta-Facty loop |
|---|---|
| Evidence (messy files) | User's answers (conversation) |
| Facts (sensed by LLM) | Domain concepts (entities, predicates) |
| Rules (chain facts) | Rules (authored from concepts) |
| Hypotheses (explanations) | Hypotheses (the explanation space) |
| Constraints (prune) | Constraints (prune invalid packs) |
| Open questions (engine asks) | Open questions (Pack Studio asks the user) |
| Verdict (deterministic) | Validated pack (deterministic, testable) |

The engine that opens questions in a case (`engine/engine.py` `forward_chain` → `op: open`) is the same engine that opens questions during domain composition. The sensing that fills questions with evidence (`engine/sensing.py`) is the same sensing that fills questions with domain knowledge.

---

## For P-1: hand-coded JSON pack authoring

### S1-a: Pack Studio TUI — the knowledge authoring workbench *(recommended)*

- **Description:** a new section in the Textual workbench (`engine/tui.py`) — "Pack Studio" — with four surfaces:
  1. **Schema curator** — define entities (person, vehicle, shop…), predicates (`damageAmount`, `witnessRelationship`…), and the fact vocabulary. The engine validates rules against this vocabulary.
  2. **Rule editor** — author forward-chaining rules (`when` → `then`), constraints (`eliminate` / `support`), and hypotheses. JSON-backed, with live schema validation.
  3. **Label sensor config** — define labels, set threshold, choose backend (local / hybrid / strom), draft Strom decision questions (reuses `--op decide`).
  4. **Test harness** — drop sample evidence → sense → run engine → see verdict + trace. The authoring loop: write rule → test → refine → repeat.
- **How it addresses the problem:** pack authoring becomes a first-class UI, not a JSON-editing exercise. The domain expert (not just the Facty engineer) can author.
- **Effort:** L · **Confidence:** high

### S1-b: CLI-first pack authoring (no TUI)

- **Description:** `./facty pack new <name>`, `./facty pack edit <name>`, `./facty pack test <name>` — a CLI workflow with an interactive prompt loop (no Textual). Faster to build, less polished.
- **How it addresses the problem:** same as S1-a, but terminal-only. Loses the visual test harness and the embedded agent pane.
- **Effort:** M · **Confidence:** medium

### S1-c: External editor + validation only (status quo + tooling)

- **Description:** keep hand-editing JSON, but add `./facty pack validate <name>` (schema + engine dry-run). No authoring UI.
- **How it addresses the problem:** it doesn't — it validates but doesn't help author.
- **Effort:** S · **Confidence:** low

---

## For P-2: no structured domain elicitation

### S2-a: The meta-Facty loop — question-driven domain composition *(recommended, the key innovation)*

- **Description:** Pack Studio's embedded agent runs a structured interview with the user to elicit their domain expertise. The loop:
  1. The user describes their domain (free text: "I investigate insurance claims for fraud").
  2. The agent generates questions — driven by the pack schema (what entities? what predicates? what rules? what hypotheses? what labels?).
  3. The user answers. The answers are the "evidence."
  4. The agent generates symbolic representations (schemas, rules, constraints, hypotheses, labels) — schema-guided extraction from the answers (reuses `engine/sensing.py`'s extract_structured).
  5. The test harness validates: run the pack on sample scenarios, check for gaps (unprovable hypotheses, missing constraints, dead rules).
  6. The user reviews and refines. The loop repeats until the user is satisfied.
- **How it addresses the problem:** the domain expert's knowledge is systematically extracted, not guessed. The pack is complete by construction — every question was asked, every gap surfaced.
- **Key design points:**
  - The questions are **generated by the engine** (the same `op: open` mechanism that opens questions in a case), not by the LLM free-form. The engine knows what it needs: missing predicates, unproven hypotheses, dead rules.
  - The answers are **sensed into facts** (the same schema-guided extraction that senses evidence into facts).
  - The symbolic representations are **generated from the facts** (the same forward-chaining that derives facts from rules — but here, the LLM drafts the rules from the facts).
  - The validation is **deterministic** (the engine runs, the verdict is replayable).
- **Effort:** L · **Confidence:** high (the machinery exists; it's a re-application)

### S2-b: Template-based pack scaffolding

- **Description:** `./facty pack new <domain>` scaffolds a pack from a template (fraud, RCA, triage…). The user fills in the blanks.
- **How it addresses the problem:** faster start, but the user still has to know what to fill in. No elicitation.
- **Effort:** M · **Confidence:** medium

### S2-c: Free-form agent interview (no engine-driven questions)

- **Description:** the embedded agent asks free-form questions ("Tell me about your domain"). No structured question generation.
- **How it addresses the problem:** partially — the expert talks, but gaps are not systematically surfaced.
- **Effort:** M · **Confidence:** low (unstructured, misses gaps)

---

## For P-3: no LLM-assisted authoring

### S3-a: Embedded pi agent — the knowledge engineer's pair programmer *(recommended)*

- **Description:** a persistent chat pane in the Pack Studio TUI (right side, like a pair programmer). The agent:
  - Drafts rules from the user's description ("help me write a rule that flags inflated labor rates")
  - Suggests labels ("what labels should I use for classifying repair line items?")
  - Reviews for gaps ("what rules am I missing for detecting staged accidents?")
  - Drafts Strom decision questions (reuses `--op decide`)
  - Explains engine behavior ("why didn't this rule fire?")
- **Transport:** the same pi RPC mode as sensing (`engine/sensing.py`) — the agent sees the current pack state (schemas, rules, constraints, hypotheses, labels) and helps iterate.
- **How it addresses the problem:** the LLM becomes the authoring assistant, not just the sensor. The human is the knowledge engineer; the LLM is their pair programmer.
- **Effort:** M · **Confidence:** high

### S3-b: One-shot LLM ops (status quo extended)

- **Description:** `./facty pack draft-rules <description>`, `./facty pack suggest-labels <domain>` — one-shot CLI ops, no interactive pane.
- **How it addresses the problem:** helps, but loses the iterative, conversational authoring.
- **Effort:** M · **Confidence:** medium

---

## For P-4: no test harness during authoring

### S4-a: Live test harness in Pack Studio *(recommended)*

- **Description:** a "Test" tab in Pack Studio where the user:
  - Drops sample evidence (or uses the pack's demo case)
  - Clicks "Run" — the engine runs (sense → derive → constrain → verdict)
  - Sees the verdict + full trace, with each derived fact linked to the rule that produced it
  - Sees gap analysis: unproven hypotheses, dead rules, missing constraints, open questions not filled
- **How it addresses the problem:** the authoring loop is tight — write rule → test → see result → refine. No more blind iteration.
- **Effort:** M · **Confidence:** high

### S4-b: CLI test mode

- **Description:** `./facty pack test <name> --facts <file>` — run the engine on a fact set, print the trace. No TUI.
- **How it addresses the problem:** same as S4-a, but terminal-only.
- **Effort:** S · **Confidence:** medium

---

## Recommended path

**S1-a + S2-a + S3-a + S4-a** — the full Pack Studio: TUI workbench + meta-Facty elicitation loop + embedded pair-programmer agent + live test harness.

The meta-Facty loop (S2-a) is the key innovation — it reuses Facty's own question-generation and sensing machinery to compose domains. The other three solutions are the surfaces that make it usable.

**Build order:**
1. S4-b (CLI test mode) — smallest slice, proves the test harness
2. S3-b (one-shot LLM ops) — proves the LLM authoring path
3. S1-a (TUI surfaces) — the workbench
4. S3-a (embedded agent pane) — the pair programmer
5. S2-a (meta-Facty loop) — the full elicitation loop, ties everything together
