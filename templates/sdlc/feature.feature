# BDD Feature Spec (Gherkin)
# Generated from PRD — {{PRD_ID}}

@PRD-{{NNN}}
@feature:{{FEATURE_SLUG}}
Feature: {{FEATURE_TITLE}}
  As a {{ROLE}}
  I want {{GOAL}}
  So that {{BENEFIT}}

  # Background context — runs before each scenario
  Background:
    Given {{PRECONDITION_1}}
    And {{PRECONDITION_2}}

  # ── Happy Path ─────────────────────────────────────────────────────────────

  @REQ-{{NNN}} @smoke @happy-path
  Scenario: {{SCENARIO_TITLE}}
    When {{ACTION}}
    Then {{EXPECTED_RESULT}}
    And {{ADDITIONAL_ASSERTION}}

  # ── Alternative Paths ──────────────────────────────────────────────────────

  @REQ-{{NNN}} @edge-case
  Scenario: {{EDGE_CASE_TITLE}}
    When {{EDGE_ACTION}}
    Then {{EDGE_RESULT}}

  @REQ-{{NNN}} @security
  Scenario: {{SECURITY_SCENARIO_TITLE}}
    When {{SECURITY_ACTION}}
    Then {{SECURITY_RESULT}}
    And {{SECURITY_ASSERTION}}

  # ── Error Handling ─────────────────────────────────────────────────────────

  @REQ-{{NNN}} @error-handling
  Scenario: {{ERROR_SCENARIO_TITLE}}
    When {{ERROR_TRIGGER}}
    Then {{ERROR_MESSAGE}}
    And {{ERROR_RECOVERY}}

  # ── Data-Driven Scenarios ──────────────────────────────────────────────────

  @REQ-{{NNN}} @edge-case @parametrized
  Scenario Outline: {{OUTLINE_TITLE}}
    When {{ACTION_WITH_PARAMETERS}}
    Then {{RESULT_WITH_PARAMETERS}}

    Examples:
      | {{PARAM_1}} | {{PARAM_2}} | {{EXPECTED}} |
      | {{VAL_1A}}  | {{VAL_2A}}  | {{EXP_A}}    |
      | {{VAL_1B}}  | {{VAL_2B}}  | {{EXP_B}}    |
      | {{VAL_1C}}  | {{VAL_2C}}  | {{EXP_C}}    |

  # ── Assumption Validation ──────────────────────────────────────────────────

  @REQ-{{NNN}} @assumption-{{ASM_ID}}
  Scenario: Validate assumption {{ASM_ID}} — {{ASSUMPTION_DESCRIPTION}}
    Given {{ASSUMPTION_SETUP}}
    When {{ASSUMPTION_TEST_ACTION}}
    Then {{ASSUMPTION_EXPECTED_RESULT}}
    # If this fails, assumption {{ASM_ID}} is invalid — escalate to decision agent
