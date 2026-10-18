# Vertical research — where the framework goes

**Status:** decided (product direction) · **Date:** 2026-10-15
**Inputs:** market scan (ddgr), session brainstorm, [docs/vision.md](../vision.md)
lineage, docassemble internals research

## Market scan

- Agentic SDLC / agentic coding is saturated: 120+ tools across 11 categories
  (StackOne 2026 map), a Forrester "Agentic Development Platforms" landscape
  (Q3 2026), Gartner ~$206.5B agent software spend in 2026.
- Consequence: the wedge is not "another coding agent". The differentiator is
  the reasoning architecture — abduction, deterministic rules, provenance.

## The Holmes reframing

A healthcare-targeted DSS was initially parked because the *domain* carries a
brutal regulatory/liability burden. Reframe (PO, 2026-10-15): the product is
the *method*, not the domain. Abduction — evidence → hypotheses →
discriminating tests → best explanation — is what detectives do; "medical" or
"fraud" is the costume. The burden attaches to the *pack*, not the engine.

**Thesis: abductive reasoning as infrastructure. Domains are packs:
configuration + learned rules, not code.**

Healthcare / clinical DSS is **explicitly not a target vertical** (PO
decision, 2026-10-15).

## Landscape (condensed)

| Tier | Verticals | Fit |
|---|---|---|
| 1 — strongest | AML/fraud investigation · regulatory change mgmt · abductive incident RCA | abduction-native, audit-required, measurable |
| 2 — strong | security assessment · contract due diligence | fit high, barriers vary |
| 3 — adjacent | scientific discovery ops · RFP/solutions eng · M&A tech DD | longer cycles |
| declined | clinical DSS | regulatory/liability burden; not a target |

## Decision

**Detective DSS** — a domain-agnostic abductive decision-support workbench.
Product name: **Facty** (`facty.dev`).
Beachhead pack: the *detective pack* (fraud / incident RCA / security triage
share one abductive skeleton). Compliance + contracts = next ring. SDLC
management = a **future vertical application** of this framework, not its
foundation.

## docassemble research (vocabulary input)

[docassemble](https://docassemble.org) (v1.6.5, verified via PyPI metadata)
builds questionnaires that **dynamically reorder based on the user's
continuous answers** — the same shape as our case loop, with one key
difference: in docassemble the *human* is the sensing layer. The engine never
observes anything; it waits for answers, then deterministically computes what
to ask next, what is mandatory, and what to skip. We swap the human sensor
for the LLM sensor; the deterministic engine's role is unchanged.

- An **interview** is a YAML *data* file: metadata + questions. Each question
  has `fields` (slots to fill), `mandatory`, `condition` (an expression
  evaluated against the answers so far), `event` / `action` (side effects on
  answer).
- `reorder: true` compiles the interview into a DAG and topologically
  reorders it as answers arrive; false conditions drop questions out;
  mandatory gaps surface.
- Source internals (`docassemble/base/parse.py` builds the interview DAG from
  YAML; `docassemble/base/interview.py` evaluates it) — source-level fetch was
  blocked from this sandbox (docs site is JS-rendered; PyPI sdist is a
  metadata stub); the semantics above are from the public documentation,
  flagged accordingly.

Vocabulary mapping (docassemble → detective DSS):

| docassemble | detective DSS |
|---|---|
| interview | **case** |
| question | **open question** (Question artifact) |
| field | **slot to fill** (evidence to collect) |
| `mandatory` | **required evidence** |
| `condition` | rule **`when`** clause |
| `event` / `action` | rule **`then`** actions (derive / raise / open / collect / test) |
| `reorder` | **forward-chaining question/opportunity discovery** |
| the human's answers | **LLM sensing** (the swap point) |
| interviews-as-YAML | **artifacts-as-JSON** (logic as data, evaluated against a context) |

Takeaways: (1) logic stays *data* evaluated against a context, never baked
into code; (2) the reordering engine *is* the "what do I still need to know"
engine — our forward chain must emit questions, not just conclusions;
(3) conditions-as-expressions is the pragmatic middle between free-form LLM
reasoning and rigid code — our rules are the same idea, JSON-shaped.

## Artifacts

- [ADR-0003](../adr/0003-detective-dss-neurosymbolic-core.md) — the architecture decision
- [detective-dss-poc.md](detective-dss-poc.md) — the PoC plan (case vocabulary)
- [docs/vision.md](../vision.md) — the method's lineage
