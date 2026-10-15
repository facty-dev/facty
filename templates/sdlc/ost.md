---
# Opportunity Solution Tree (OST)
# Continuous Discovery — Design Thinking
---

# Opportunity Solution Tree — {{PROJECT_NAME}}

**Date:** {{DATE}}
**Facilitator:** {{FACILITATOR}}
**Status:** {{STATUS}} <!-- draft | in-review | approved -->
**Version:** {{VERSION}}

---

## Desired Outcome

> What business outcome are we trying to achieve?

{{OUTCOME}}

**Example:** "Increase user retention by 20% in Q4"

---

## Opportunities (Problems)

What problems do our users/stakeholders face? (From continuous discovery)

### OPP-001: {{PROBLEM_TITLE}}
- **Description:** {{PROBLEM_DESCRIPTION}}
- **Evidence:** {{EVIDENCE}} <!-- user interviews, data, support tickets -->
- **Impact:** {{IMPACT}} <!-- who is affected, how severely -->
- **Frequency:** {{FREQUENCY}} <!-- how often -->
- **Source:** {{SOURCE}} <!-- stakeholder, research session, etc. -->

### OPP-002: {{PROBLEM_TITLE}}
- **Description:** {{PROBLEM_DESCRIPTION}}
- **Evidence:** {{EVIDENCE}}
- **Impact:** {{IMPACT}}
- **Frequency:** {{FREQUENCY}}
- **Source:** {{SOURCE}}

### OPP-003: {{PROBLEM_TITLE}}
- **Description:** {{PROBLEM_DESCRIPTION}}
- **Evidence:** {{EVIDENCE}}
- **Impact:** {{IMPACT}}
- **Frequency:** {{FREQUENCY}}
- **Source:** {{SOURCE}}

---

## Solutions

For each opportunity, what are potential solutions?

### For OPP-001: {{PROBLEM_TITLE}}

#### SOL-001-A: {{SOLUTION_TITLE}}
- **Description:** {{SOLUTION_DESCRIPTION}}
- **How it addresses the problem:** {{MECHANISM}}
- **Effort:** {{EFFORT}} <!-- S | M | L | XL -->
- **Confidence:** {{CONFIDENCE}} <!-- low | medium | high -->

**Assumptions:**
- **ASM-001-A-1:** {{ASSUMPTION}}
  - How to test: {{TEST_METHOD}}
  - Risk if wrong: {{RISK}}
- **ASM-001-A-2:** {{ASSUMPTION}}
  - How to test: {{TEST_METHOD}}
  - Risk if wrong: {{RISK}}

#### SOL-001-B: {{SOLUTION_TITLE}}
- **Description:** {{SOLUTION_DESCRIPTION}}
- **How it addresses the problem:** {{MECHANISM}}
- **Effort:** {{EFFORT}}
- **Confidence:** {{CONFIDENCE}}

**Assumptions:**
- **ASM-001-B-1:** {{ASSUMPTION}}
  - How to test: {{TEST_METHOD}}
  - Risk if wrong: {{RISK}}

### For OPP-002: {{PROBLEM_TITLE}}

#### SOL-002-A: {{SOLUTION_TITLE}}
- **Description:** {{SOLUTION_DESCRIPTION}}
- **How it addresses the problem:** {{MECHANISM}}
- **Effort:** {{EFFORT}}
- **Confidence:** {{CONFIDENCE}}

**Assumptions:**
- **ASM-002-A-1:** {{ASSUMPTION}}
  - How to test: {{TEST_METHOD}}
  - Risk if wrong: {{RISK}}

### For OPP-003: {{PROBLEM_TITLE}}

#### SOL-003-A: {{SOLUTION_TITLE}}
- **Description:** {{SOLUTION_DESCRIPTION}}
- **How it addresses the problem:** {{MECHANISM}}
- **Effort:** {{EFFORT}}
- **Confidence:** {{CONFIDENCE}}

**Assumptions:**
- **ASM-003-A-1:** {{ASSUMPTION}}
  - How to test: {{TEST_METHOD}}
  - Risk if wrong: {{RISK}}

---

## OST Visualization

```
                    ┌─────────────────┐
                    │  DESIRED OUTCOME │
                    │  {{OUTCOME}}     │
                    └────────┬────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
  │  OPP-001    │     │  OPP-002    │     │  OPP-003    │
  │ {{PROBLEM}} │     │ {{PROBLEM}} │     │ {{PROBLEM}} │
  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
         │                   │                   │
    ┌────┼────┐         ┌────┼────┐         ┌────┼────┐
    ▼    ▼    ▼         ▼    ▼    ▼         ▼    ▼    ▼
  ┌────┐┌────┐┌────┐  ┌────┐┌────┐┌────┐  ┌────┐┌────┐┌────┐
  │S-A ││S-B ││S-C │  │S-A ││S-B ││S-C │  │S-A ││S-B ││S-C │  ← Solutions
  │+A1 ││+A1 ││+A1 │  │+A1 ││+A1 ││+A1 │  │+A1 ││+A1 ││+A1 │     (+ Assumptions)
  │+A2 ││+A2 ││+A2 │  │+A2 ││+A2 ││+A2 │  │+A2 ││+A2 ││+A2 │
  └────┘└────┘└────┘  └────┘└────┘└────┘  └────┘└────┘└────┘
    ↑                    ↑                    ↑
    └── Selected: SOL-001-A (highest confidence × impact / effort)
```

---

## Selected Path

| Field | Value |
|-------|-------|
| **Opportunity** | OPP-{{N}}: {{TITLE}} |
| **Solution** | SOL-{{N}}-{{X}}: {{TITLE}} |
| **Rationale** | {{WHY_SELECTED}} |
| **Key Assumptions** | ASM-{{N}}-{{X}}-1, ASM-{{N}}-{{X}}-2, ... |
| **Confidence** | {{CONFIDENCE}} |
| **Effort** | {{EFFORT}} |

---

## Assumptions Log (All)

| ID | Assumption | Solution | How to Test | Risk if Wrong | Status |
|----|-----------|----------|-------------|---------------|--------|
| ASM-001-A-1 | {{ASSUMPTION}} | SOL-001-A | {{TEST}} | {{RISK}} | {{STATUS}} |
| ASM-001-A-2 | {{ASSUMPTION}} | SOL-001-A | {{TEST}} | {{RISK}} | {{STATUS}} |
| ASM-001-B-1 | {{ASSUMPTION}} | SOL-001-B | {{TEST}} | {{RISK}} | {{STATUS}} |
| ... | ... | ... | ... | ... | ... |

---

## Stakeholder Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product Owner | {{NAME}} | {{DATE}} | ✅ |
| Tech Lead | {{NAME}} | {{DATE}} | ✅ |
| Design Lead | {{NAME}} | {{DATE}} | ✅ |

---

## Next Steps

1. → Generate **PRD** from selected path (decision agent)
2. → Validate top assumptions (continuous discovery)
3. → Generate **BDD specs** from PRD (decision agent)
4. → **Implement** (coding agent)
