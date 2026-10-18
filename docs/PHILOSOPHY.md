# Facty Philosophy — determinism, liability, and the human role

> **Product:** Facty (`facty.dev`) — *evidence in, verdict out.*
>
> **Determinism is the baseline. It is not a "strict mode" — it is the
> product.** Everything else is tuning within that invariant.

---

## 1. The Air Canada case: why this matters

**Moffatt v. Air Canada, 2024 BCCRT 149** (February 14, 2024)

Air Canada's website chatbot told a grieving customer he could book a
full-price ticket and then request a bereavement fare refund retroactively
within 90 days. This was **the exact opposite of Air Canada's actual
policy** — bereavement fares must be requested *before* travel.

The customer followed the chatbot's advice, missed the window, and was
denied the refund. Air Canada argued the chatbot was *"a separate legal
entity responsible for its own actions."*

The British Columbia Civil Resolution Tribunal **rejected this defense**
and held Air Canada liable for **negligent misrepresentation**. Award:
~CA$812 in damages — but the precedent and reputational damage were far
larger.

**The lesson:** A company is liable for what its AI says. The chatbot's
hallucination became Air Canada's liability. There is no "the AI did it"
defense.

If Air Canada had used a Facty-style system:

| What their chatbot did | What Facty would have done |
|------------------------|------------------------------|
| Hallucinated a refund policy | **Impossible** — hypotheses must come from the pack (the actual policy) |
| Contradicted the real policy | **Impossible** — constraints eliminate contradictions at load time |
| No trace of why it said that | **Full trace** — every fact linked to source, every rule application logged |
| "The chatbot is a separate entity" | **Company is liable** — and the trace proves what the system actually knew |

The customer would have gotten the *correct* answer, or the system would
have said: *"I cannot determine the bereavement policy from available
information — please contact support."*

**Sources:**
- [Moffatt v. Air Canada — Wikipedia](https://en.wikipedia.org/wiki/Moffatt_v._Air_Canada)
- [BC Tribunal Confirms Companies Remain Liable for Information Provided by AI Chatbot — American Bar Association](https://www.americanbar.org/groups/business_law/resources/business-law-today/2024-february/bc-tribunal-confirms-companies-remain-liable-information-provided-ai-chatbot/)
- [Moffatt v. Air Canada: A Misrepresentation by an AI Chatbot — McCarthy Tétrault](https://www.mccarthy.ca/en/insights/blogs/techlex/moffatt-v-air-canada-misrepresentation-ai-chatbot)

---

## 2. LLMs are tools, not agents

**Core claim:** Machine learning models — including LLMs — can never be:

- **Conscious** — they have no subjective experience, no inner life
- **Morally agentic** — they cannot be held responsible for their outputs
- **Legal persons** — they cannot bear liability, sign contracts, or be sued

**Liability always flows back to the humans accountable for the decisions
they make, regardless of their tool choices.**

This is not a limitation of current technology — it is a category error to
attribute these properties to statistical models. An LLM is a very
sophisticated **n-gram approximator**. It retrieves and recombines patterns
from training data. It does not *know*, *believe*, *intend*, or *decide*.

> **LLMs are tools used by deterministic processes and humans.**
> The tool does not become the decision-maker. The human who wields the
> tool remains accountable.

---

## 3. The engine owns the verdict

In Facty's neurosymbolic architecture (see
[ADR-0003](adr/0003-detective-dss-neurosymbolic-core.md)):

- **The senses (LLM)** read messy evidence into facts, propose hypotheses,
  suggest discriminating tests. Probabilistic: great at reading, not at
  being right.
- **The brain (symbolic engine)** verifies, chains, prunes, and decides.
  Deterministic: every verdict replays without the LLM.

**The LLM never sits in the verdict path.** This is the LLM-Modulo design
rule (Kambhampati et al., 2024): LLMs cannot plan, cannot self-verify, and
direct self-critique doesn't work. The symbolic layer is the **soundness
critic** — it checks the LLM's proposals against rules, constraints, and
evidence.

This is not "human-in-the-loop" as an afterthought. It is **human
soundness critics made programmatic** — the symbolic rules layer is the
stand-in for the human critics that the original LLM-Modulo architecture
called for. The soundness of the framework is *derived* from the soundness
of the critics. This is a strength, not a limitation.

---

## 4. Determinism is the baseline, not a mode

Earlier drafts of this architecture considered a "risk profile" that
controlled *how deterministic* the system should be — loose for marketing,
strict for legal. **This framing was wrong.**

The corrected framing:

> **Determinism and auditability are universal requirements.** What varies
> by domain is not *whether* to be deterministic, but *how much human
> judgment, constraint, and explanation* to layer on top.

| Dimension | Always on (invariant) | Varies by risk profile |
|-----------|----------------------|------------------------|
| **Verdict ownership** | Engine decides, never LLM | — |
| **Reasoning trace** | Full, replayable | — |
| **Fact provenance** | Confidence + source spans required | — |
| **Hypothesis testability** | Must have a killer test | — |
| **Constraint enforcement** | Pack defines what's possible | Soft (warnings) vs Hard (eliminations) |
| **Hypothesis space** | — | Wide (exploratory) vs Narrow (prescriptive) |
| **Confidence threshold** | — | Lower (0.6) vs Higher (0.9) |
| **Human approval gates** | — | Fewer vs More |
| **Uncertainty handling** | — | "Best guess" acceptable vs "No verdict" preferred |
| **Explanation depth** | — | Summary vs Full trace with all derivations |

**One engine. One set of invariants. Parameterized by risk profile.**

Even marketing departments — which "take more risks" — do not want undue
liability. The Air Canada case was a customer service chatbot, not a
high-stakes legal system. Liability exposure is universal.

---

## 5. The reverse centaur: humans direct machines, not serve them

Cory Doctorow's concept of the **"reverse centaur"** (from *The Reverse
Centaur's Guide to Life After AI*, 2026) describes a human conscripted to
serve a machine:

- A delivery driver whose route, pace, and bathroom breaks are dictated by
  an algorithm
- A warehouse worker monitored by AI, denied breaks, pushed to inhuman
  speeds
- A programmer forced to crank out impossible amounts of code at machine
  pace

The **centaur** is the ideal: a human head directing a machine body —
**human-led fusion of person and machine**. The **reverse centaur** is the
inversion: the machine directs, the human serves.

**Sources:**
- [The Reverse Centaur's Guide to Life After AI — Macmillan](https://us.macmillan.com/books/9780374621568/thereversecentaursguidetolifeafterai/)
- [The Reverse Centaur: Keeping Humans at the Head of AI and Automation](https://www.stoakley.com/reverse-centaur-ai-automation/)
- [Cory Doctorow on "How to Think About AI" — Democracy Now!](https://www.democracynow.org/2026/6/25/reverse_centaur_doctorow)

**What this means for Facty UX:**

- The human is the **knowledge engineer** — curating rules, constraints,
  and hypotheses as new evidence flows through the system
- The human is the **soundness critic** — reviewing verdicts, approving
  hypotheses, refining the pack
- The human is the **accountable decision-maker** — the verdict is a
  recommendation; the human acts on it and owns the consequences
- The machine **senses, proposes, and verifies** — but never decides, never
  bears liability, never serves as a rubber stamp for human inaction

The system should **amplify human judgment**, not replace it. The goal is
to free humans to focus on harder problems — creativity, strategy,
exceptional cases — by handling the mundane computation deterministically.

**We must not become reverse centaurs.** The humans using Facty are the
original source of intelligence. The rules they curate are their
expertise, made programmatic. The LLM is a tool they wield. The engine is
the critic that keeps them honest.

---

## 6. Human knowledge engineering is the source of intelligence

There will always be times when humans are actively:

- **Curating rulesets** — adding, refining, and retiring rules as the
  domain evolves
- **Reviewing hypotheses** — approving or rejecting LLM proposals
- **Designing discriminating tests** — figuring out what evidence would
  distinguish competing explanations
- **Annotating edge cases** — teaching the system about novel situations
- **Auditing verdicts** — checking the reasoning trace for soundness

This is not a temporary phase to be automated away. **It is the ongoing
work of expertise.** The pack is a living artifact — it grows and improves
as humans learn. The LLM senses the messy world; the human gives it
structure; the engine keeps it sound.

The LLM-Modulo paper's insight applies here: *"Humans are only required
once per domain and once per problem. After that, the critic role can be
simulated programmatically."* The symbolic rules layer **is** that
simulation — but it is a simulation **authored by humans**, accountable to
humans, and improvable by humans.

---

## 7. Summary: the Facty stance

| Principle | Statement |
|-----------|-----------|
| **Determinism** | The engine owns the verdict. Every decision is replayable. |
| **Auditability** | The reasoning trace is the explanation. No black boxes. |
| **LLM as tool** | LLMs sense and propose; they never decide. |
| **Human accountability** | Liability flows to humans, regardless of tool choices. |
| **No AI personhood** | LLMs are not conscious, not morally agentic, not legal persons. |
| **Soundness critics** | The symbolic layer is the programmatic stand-in for human critics. |
| **Human intelligence** | Knowledge engineering is the ongoing source of system intelligence. |
| **No reverse centaurs** | Humans direct machines; machines never direct humans. |

---

## See also

- [ADR-0003: Detective DSS — neurosymbolic core](adr/0003-detective-dss-neurosymbolic-core.md) — the architecture
- [vision.md](vision.md) — the method's philosophical foundations
- [PRD-005: Neurosymbolic Bridge](prd/PRD-005-neurosymbolic-bridge.md) — LLM + structured data
- [LLM-Modulo paper (Kambhampati et al., 2024)](https://arxiv.org/abs/2402.01817) — LLMs can't plan, but can help planning
