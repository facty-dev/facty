# BDD Feature Spec (Gherkin)
# Generated from PRD-007 (Pack Studio) — decision-to-coding task 003.
#
# Scope: the MVP CLI half — `./facty pack validate` / `pack test` (with gap
# analysis) and the one-shot LLM authoring ops (draft-rules, suggest-labels,
# draft-hypotheses, draft-questions, review). The TUI surfaces, the embedded
# agent pane, and the meta-Facty loop are follow-up phases (PRD-007 §2, §10)
# — deliberately NOT specified here.
#
# Scenario tags map to the PRD acceptance criteria: @AC-1 … @AC-8 (PRD-007 §7)
# and @REQ-001 … @REQ-016 (PRD-007 §4). Task-003 acceptance criteria are
# covered by the same scenarios (the task list mirrors §7 + the CLI surface).

@PRD-007
@feature:pack-studio
@task:003
Feature: Pack Studio MVP — CLI test mode and one-shot LLM authoring ops
  As a domain expert (fraud analyst, SRE, claims adjuster — not a Facty engineer)
  I want to validate, test, and draft my own knowledge pack from the CLI
  So that I can author a complete, tested, deterministic pack on Facty in a
  single sitting — with the LLM as pair programmer and the symbolic engine
  as validator.

  # Background context — runs before each scenario
  Background:
    Given the Facty repo root as the working directory with the ./facty CLI
    And the canonical artifact schemas under engine/schemas/
    And a valid seeded example pack at packs/example (a demo case's pack plus
      one tests/ scenario), so pack list / validate / test are demonstrable
    And a fixture pack with one known dead rule, one unraised hypothesis, and
      one question its fact set leaves unanswered

  # ── Happy Path ─────────────────────────────────────────────────────────────

  @REQ-008 @smoke @happy-path
  Scenario: List the packs under packs/
    When I run "./facty pack list"
    Then the command exits 0
    And the seeded example pack is listed with its artifact counts

  @AC-1 @REQ-001 @REQ-002 @smoke @happy-path
  Scenario: Validate a well-formed pack
    When I run "./facty pack validate packs/example"
    Then the command exits 0
    And the report is clean — no schema or cross-artifact violations

  @AC-2 @REQ-003 @NFR-002 @smoke @happy-path
  Scenario: Run the pack against a fact set — deterministic verdict + trace
    When I run "./facty pack test packs/example --facts <fixture-facts>"
    Then the command exits 0
    And the output shows the verdict and the full trace: derived facts, fired
      rules, open questions, pruned hypotheses
    And the result matches the equivalent engine run_case output
    When I run the same command a second time
    Then the two runs are byte-identical
    And the run completes in under 1 second

  @AC-2 @REQ-005 @happy-path
  Scenario: Emit the machine-readable test result
    When I run "./facty pack test packs/example --facts <fixture-facts> --json"
    Then stdout is parseable JSON with "verdict", "trace", and "gaps" keys

  @AC-3 @REQ-004 @happy-path
  Scenario: Gap analysis flags the fixture's known gaps
    When I run "./facty pack test packs/gap-fixture --facts <fixture-facts>"
    Then the gap analysis flags the known dead rule (never fires)
    And flags the unraised hypothesis (in the pack, never raised)
    And flags the question left unanswered by the fact set
    And flags any pruned hypothesis with its constraint reason

  @REQ-006 @happy-path
  Scenario: Run every scenario in a tests directory and assert expected outcomes
    When I run "./facty pack test packs/example --tests packs/example/tests"
    Then every facts-*.json scenario in the directory runs
    And each scenario with an expected outcome is asserted
    And the command exits 0 when all assertions pass

  @AC-4 @REQ-010 @REQ-015 @happy-path
  Scenario: Draft rules from a plain-language domain description
    When I run "./facty pack draft-rules packs/example --domain \"invoice fraud: duplicate invoices, round amounts, new vendors\""
    Then a draft is staged at packs/example/pack/rules.draft.json
    And the draft validates against rule.schema.json
    And the draft passes the cross-artifact checks (unique IDs, raise targets exist)
    And the target pack/rules.json is untouched
    And a summary of the draft is printed

  @AC-5 @REQ-011 @REQ-015 @happy-path
  Scenario: Suggest a label set from sample evidence
    When I run "./facty pack suggest-labels packs/example --evidence <sample-evidence>"
    Then a draft is staged at packs/example/classify.draft.json
    And the draft is structurally valid: required keys present, labels
      non-empty, threshold in range
    And the target classify.json is untouched

  @REQ-012 @REQ-015 @happy-path
  Scenario: Draft hypotheses from a plain-language domain description
    When I run "./facty pack draft-hypotheses packs/example --domain \"invoice fraud\""
    Then a draft is staged at packs/example/pack/hypotheses.draft.json
    And the draft validates against hypothesis.schema.json
    And the target pack/hypotheses.json is untouched

  @REQ-013 @REQ-015 @happy-path
  Scenario: Draft the Strom decision questions for the pack
    When I run "./facty pack draft-questions packs/example"
    Then a draft is staged at packs/example/sensor/decisions.draft.json
    And the draft passes the same judge as "./facty sense <case> --op decide"
    And the target sensor/decisions.json is untouched

  @REQ-014 @happy-path
  Scenario: Get an advisory review of the pack — prose, never written
    When I run "./facty pack review packs/example"
    Then advisory prose about gaps (dead rules, unproven hypotheses, missing
      constraints) is printed
    And the pack directory is byte-identical before and after

  @AC-6 @REQ-016 @NFR-004 @happy-path
  Scenario: Replay an LLM op from the response cache — byte-identical, no LLM
    Given a cached response for a previous draft-rules run
    When I run "FACTY_SENSE=cache ./facty pack draft-rules packs/example --domain \"invoice fraud\""
    Then the op replays byte-identically to the live run
    And no LLM call is made
    And the run log prints the cache summary like the sense ops

  @AC-7 @happy-path
  Scenario: The pack test suite passes with a stubbed runner
    When I run "python3 engine/test_pack.py"
    Then the suite passes with no LLM and no network
    When I run "./facty selftest"
    And I run "./facty test"
    Then both pass with engine/test_pack.py in the test script list

  # ── Alternative Paths ──────────────────────────────────────────────────────

  @REQ-008 @edge-case
  Scenario: List packs when packs/ is empty
    Given an empty packs/ directory
    When I run "./facty pack list"
    Then the command exits 0
    And the output says there are no packs yet

  @AC-4 @REQ-015 @edge-case
  Scenario: Accept a draft explicitly with --write
    Given a staged draft at packs/example/pack/rules.draft.json
    When I run "./facty pack draft-rules packs/example --domain \"invoice fraud\" --write"
    Then the draft replaces the target pack/rules.json
    And the staged draft is consumed

  @AC-6 @REQ-016 @edge-case
  Scenario: Replay an LLM op in offline mode
    Given a cached response for a previous suggest-labels run
    When I run "./facty pack suggest-labels packs/example --evidence <sample-evidence> --offline"
    Then the op replays from the cache byte-identically
    And no LLM call is made

  @REQ-007 @edge-case
  Scenario: Run the pack against sample evidence without a full case directory
    When I run "./facty pack test packs/example --evidence <sample-evidence-dir>"
    Then sample evidence is sensed to facts (live or from cache) and the engine
      produces a verdict
    And the verdict matches the recorded-facts run of the same pack

  @task-003 @edge-case
  Scenario: The pack help documents every op
    When I run "./facty pack --help"
    Then every op is documented: list, validate, test (--facts/--tests/--evidence/--json),
      draft-rules, suggest-labels, draft-hypotheses, draft-questions, review
    And the draft write policy (staged draft, --write to accept) is stated

  # ── Error Handling ─────────────────────────────────────────────────────────

  @AC-1 @REQ-001 @error-handling
  Scenario: Reject a pack with a schema violation
    Given a pack whose rules.json violates rule.schema.json
    When I run "./facty pack validate <that-pack>"
    Then the command exits 1
    And the error names the file and the violation

  @AC-1 @REQ-002 @error-handling @parametrized
  Scenario Outline: Reject cross-artifact violations with a named error
    Given a pack with <violation>
    When I run "./facty pack validate <that-pack>"
    Then the command exits 1
    And the error names <expected-error>

    Examples:
      | violation                                             | expected-error                                  |
      | a constraint referencing a missing hypothesis          | the constraint's missing hypothesis             |
      | a duplicate rule ID                                   | the duplicated rule ID                          |
      | a rule whose raise target does not exist               | the rule's missing raise target                 |
      | a pack field that does not match the directory name   | the pack/directory name mismatch                |
      | a structurally invalid classify.json (missing key,    | the classify.json violation (key, empty labels, |
      | empty labels, or threshold out of range)              | or threshold range)                             |

  @REQ-006 @error-handling
  Scenario: A failing test scenario exits non-zero and names the scenario
    Given a tests directory where one scenario's expected outcome does not
      match the engine's verdict
    When I run "./facty pack test packs/example --tests <that-tests-dir>"
    Then the command exits 1
    And the output names the failing scenario

  @REQ-001 @error-handling
  Scenario: A missing pack path fails cleanly
    When I run "./facty pack validate packs/does-not-exist"
    Then the command exits 1
    And the error says the pack directory does not exist

  @NFR-005 @REQ-015 @security
  Scenario: Draft ops never overwrite the target without --write
    Given a valid target artifact at packs/example/pack/rules.json
    When I run "./facty pack draft-rules packs/example --domain \"invoice fraud\""
    Then the target artifact is byte-identical before and after
    And only the staged .draft.json file is added

  @NFR-005 @security
  Scenario: No API keys are logged by any pack op
    When I run a pack LLM op with output captured
    Then no API key material appears in stdout, stderr, or the run log
    And "./facty env" is untouched by the op

  # ── Data-Driven Scenarios ──────────────────────────────────────────────────

  @REQ-015 @edge-case @parametrized
  Scenario Outline: Every draft op stages its artifact beside the target
    When I run "./facty pack <op> packs/example <args>"
    Then a draft is staged at <staged-draft>
    And the target <target> is untouched
    And the run log prints the cache summary

    Examples:
      | op               | args                          | staged-draft                                  | target                          |
      | draft-rules      | --domain "invoice fraud"      | packs/example/pack/rules.draft.json           | packs/example/pack/rules.json   |
      | suggest-labels   | --evidence <sample-evidence>  | packs/example/classify.draft.json             | packs/example/classify.json     |
      | draft-hypotheses | --domain "invoice fraud"      | packs/example/pack/hypotheses.draft.json      | packs/example/pack/hypotheses.json |
      | draft-questions  |                               | packs/example/sensor/decisions.draft.json     | packs/example/sensor/decisions.json |

  @AC-8 @NFR-003 @parametrized
  Scenario Outline: The pack path runs with third-party packages unavailable
    Given the gondolin VM snapshot environment (no pip site-packages)
    When I import <module> and run "./facty pack validate packs/example"
    Then the import and the command succeed — stdlib only

    Examples:
      | module            |
      | engine.engine     |
      | engine.cli        |
      | engine.pack       |

  # ── Assumption Validation ──────────────────────────────────────────────────

  @AC-2 @NFR-001 @assumption-ASM-4a-1
  Scenario: Validate assumption ASM-4a-1 — authoring-mode engine is fast enough
    Given a demo-scale pack (100 rules, 200 facts)
    When I run "./facty pack test <demo-pack> --facts <demo-facts>"
    Then the run (verdict + trace + gap analysis) completes in under 1 second
    # If this fails, assumption ASM-4a-1 is invalid — escalate to decision agent

  @REQ-007 @assumption-ASM-4a-2
  Scenario: Validate assumption ASM-4a-2 — evidence → facts → verdict without a case dir
    Given sample evidence for the example pack
    When I run "./facty pack test packs/example --evidence <sample-evidence-dir>"
    Then the sensed-facts verdict matches the recorded-facts run of the same pack
    # If this fails, assumption ASM-4a-2 is invalid — escalate to decision agent

  @AC-4 @assumption-ASM-2a-2
  Scenario: Validate assumption ASM-2a-2 — schema-guided extraction yields useful drafts
    When I run "./facty pack draft-rules packs/example --domain \"invoice fraud\""
    Then the draft validates against rule.schema.json
    And the draft passes the cross-artifact checks
    And the author accepts the draft (with at most minor edits)
    # If this fails, assumption ASM-2a-2 is invalid — escalate to decision agent

  # ── Out of scope (follow-up phases — recorded so the boundary is explicit) ──
  # NON-GOAL-1: TUI surfaces (schema curator, rule editor, label sensor config,
  #   test harness tab) — follow-up phase 1
  # NON-GOAL-2: embedded pi agent pane — follow-up phase 2
  # NON-GOAL-3: the meta-Facty loop — follow-up phase 3
  # NON-GOAL-4: `pack new` template scaffolding
  # NON-GOAL-6: any change to the verdict path or engine semantics
