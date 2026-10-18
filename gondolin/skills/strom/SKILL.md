---
name: strom
description: >
  Strom by Uprelic is a decision API: send text, JSON or up to 8 images with named questions, and get typed
  answers (yes/no probability, one choice from your options, or a score on your rubric) with calibrated
  probabilities, in roughly 100–500 ms. Use when code needs a judgment that rules or regexes can't make
  (routing, triage, tagging, moderation, guardrails, checking an LLM's output, image checks), when an LLM
  prompt-and-parse step only picks from known options, or when every row of a dataset needs scoring.
  Not for generating text.
---

# Strom

Strom is an API by Uprelic (Berlin) at `https://api.uprelic.com`. You send content (the **state**) and
named **questions**; Strom answers each one with a typed value and a probability. It never writes text:
it scores the options you define, so it can't break the schema or invent an option.

- **Answer types:** `noul` (probability of yes), `choice` (one of your named options, with
  probabilities for all), `score` (a position on your ordered rubric, with probabilities per level).
- **Input:** text or JSON, plus up to 8 images per request. Up to 256 questions per request, all
  answered on the same input, and up to 32,000 input tokens per request.
- **Price:** $0.042 per 1M input tokens. Output tokens are free. A typical request costs a
  thousandth of a cent.
- **Speed:** ~90 ms model time for one question on a short text, ~180 ms on 2,000 tokens, plus your
  network round trip.
- **Calibrated:** on held-out data, answers given at 90% are right about 90% of the time.
- **Data:** runs on GPU servers in the EU (Paris). No request goes to a third-party AI provider.
  Request contents are deleted after 90 days and never used for training.
- **Access:** sign up at https://platform.uprelic.com and create an API key in the console. Verifying a
  card on the console's Overview adds 5 units of credit in the account's currency (USD, EUR, GBP or CHF),
  once per card; the card isn't charged.

## When a decision model fits

A decision model like Strom doesn't generate text. It reads the input once and answers each question
with a single token: the probabilities of the options you defined. That's why it's fast and cheap,
why every answer fits your schema, and why the probabilities are meaningful enough to act on.

**How it compares:**

- **Rules and regexes** are free and exact, but break on wording nobody anticipated. Strom handles
  the phrasing, language and context a rule can't, from a question in plain language.
- **An LLM with structured output** can reason step by step and explain itself, but it's slower and
  costlier per decision, can still break the schema, and its stated confidence isn't calibrated.
- **A fine-tuned classifier** can beat a general model on one narrow, stable task, but needs labeled
  data and retraining whenever a label changes. With Strom, a new label is a new line in `criteria`.

**It fits when:**

- The possible answers can be written down: yes/no, one of a set, a level on a scale.
- Everything needed to decide is in the state (the text, record fields, images, the policy to check).
- A person would decide it in a few seconds, without research or long calculation.
- The volume or latency matters: every ticket, every row, every video frame, a user-facing feature,
  or an agent acting step by step.

**It doesn't fit when:**

- The answer has to be written: replies, summaries, plans, code, or extracting values you can't list
  as candidates.
- The decision needs multi-step reasoning, arithmetic, or facts that aren't in the state.
- You need an explanation of why, not just the answer and its probability.
- The state, images and a question don't fit in 32,768 tokens.
- Plain code is exact: thresholds, lookups, date math, known rules.
- There are only a handful of decisions, so an LLM's cost and latency don't matter.

Most real systems combine them: Strom triages, an LLM drafts the one step that needs words, Strom
checks the draft against policy, and code decides whether to send it or ask a person. Examples of
Strom's part: which team, how urgent, is it spam, does this draft follow policy, is the right size
selected, did the grasp succeed, which element to click next.

## Switching from Jev

Strom accepts the same request format as TypeSafe's Jev (state plus typed questions). Switching means
pointing the client at `https://api.uprelic.com` with an Uprelic key.

## First request

```sh
curl https://api.uprelic.com/v1/systemone \
  -H "Authorization: Bearer $UPRELIC_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "strom-1.0.7",
    "state": "Our whole team is blocked. The app has been down since this morning.",
    "questions": {
      "team": {
        "type": "choice",
        "instructions": "Which team should handle this?",
        "criteria": {
          "engineering": "Outages and bugs",
          "billing": "Payments and invoices",
          "account": "Login and access"
        }
      },
      "urgent": {"type": "noul", "instructions": "This message needs urgent attention."}
    }
  }'
```

```json
{
  "model": "strom-1.0.7",
  "answers": {
    "team": {
      "type": "choice",
      "choice": "engineering",
      "confidence": 0.83,
      "probabilities": {"engineering": 0.89, "billing": 0.07, "account": 0.04}
    },
    "urgent": {"type": "noul", "noul": 0.96}
  },
  "usage": {"input_tokens": 283, "output_tokens": 2, "cached_input_tokens": 256, "cost": 0.000011886,
            "currency": "usd"},
  "metadata": {"server_processing_time_ms": 85}
}
```

The values above are illustrative.

### Python SDK

`pip install uprelic` (Python 3.10+). The client reads `UPRELIC_API_KEY`.

```python
from uprelic import Uprelic, Noul, Choice, Score

with Uprelic() as client:
    response = client.system_one(
        model="strom-1.0.7",
        state="I was charged twice for my subscription. Please fix this today.",
        questions={
            "billing": Noul("Is this message about billing?"),
            "tone": Choice("What is the tone?", criteria={"angry": "Upset or hostile", "calm": "Neutral or polite"}),
            "urgency": Score("How urgent is this?", criteria=["Can wait", "This week", "Today"]),
        },
    )

response.nouls["billing"].noul        # 0.98
response.choices["tone"].choice       # "angry"
response.scores["urgency"].score      # 1.8
response.usage.input_tokens
```

Images go in `images=` as http(s) or `data:image/...` URLs. `AsyncUprelic` has the same interface.
`client.extract(model=..., schema={...}, document=Path("invoice.pdf"))` calls `/v1/extract` (see Document
extraction); `document` can also be bytes or a URL.
Errors raise `uprelic.APIError` subclasses: `AuthenticationError` (401), `InsufficientBalanceError`
(402), `InvalidRequestError` (400, 413, 422), `RateLimitError` (429), `ServerError` (5xx). 429, 502–504
and connection failures are retried twice with backoff (`Uprelic(max_retries=...)`).

There is no JavaScript SDK; use `fetch` against the HTTP API.

## API reference

- `POST https://api.uprelic.com/v1/systemone` with `Authorization: Bearer <API_KEY>`.
- `POST https://api.uprelic.com/v1/extract` extracts fields from a PDF or image; see Document extraction
  below.
- `GET https://api.uprelic.com/v1/models` lists models; no key needed. Today there is one:
  `strom-1.0.7`.
- Full schema: https://api.uprelic.com/v1/openapi.json, rendered at https://api.uprelic.com/v1/docs.

### Request

| Field | Type | Meaning |
| --- | --- | --- |
| `model` | string | `strom-1.0.7` |
| `state` | string, object or array | The content every question refers to |
| `questions` | object | 1–256 questions, keyed by names you choose; answers use the same keys |
| `media` | array, optional | Up to 8 `{"type": "image", "url": ...}`, in order |

Question types:

| `type` | `instructions` | `criteria` | Answer |
| --- | --- | --- | --- |
| `noul` | The yes/no question or statement | Optional `{"true": ..., "false": ...}` describing each side | `noul`: probability of yes, 0–1 |
| `choice` | What to decide | Object of option name → description (or `null` to go by the name alone), 1–256 options | `choice`, `confidence`, `probabilities` per option |
| `score` | What to rate | Ordered list of level descriptions; the first is 0 | `score` (probability-weighted level, can be fractional), `confidence`, `legend`, `probabilities` per level |

`instructions` and criteria descriptions can be strings or JSON objects. Image URLs are
`data:image/...` or public http(s) URLs (max 10 MB, 10 s, no redirects). Images are scaled to at most
1 megapixel.

### Cost and limits

- Input tokens = the state once + each question's text + each image's tokens. An image costs one
  token per 32×32 pixels, between 64 and 1,024. Every response reports `usage.input_tokens`.
- Only answered requests (200) are charged, from a prepaid balance. An empty balance returns 402.
- Per account: 500 requests a minute and 8 concurrent, else 429 with `Retry-After`. Higher limits
  via sales@uprelic.com.
- Errors: 400 (bad image), 401 (missing or wrong key), 402, 413 (over 32,000 input tokens), 422 (invalid
  request, with the field path),
  429, 5xx. Error bodies have a `detail` field.

### Document extraction

`POST https://api.uprelic.com/v1/extract` takes one PDF (at most 8 pages) or image and a JSON Schema whose
`properties` are the fields to extract:

```json
{"model": "strom-1.0.7",
 "schema": {"properties": {"invoice_date": {"type": "string", "format": "date"},
                           "total": {"type": "number", "format": "amount", "description": "Total including tax"}}},
 "document": {"url": "https://example.com/invoice.pdf"}}
```

- `document.url`: base64 `data:` URL or public http(s) URL, up to 32 MB. Scans and images are OCR'd.
- Field types: `string` (the whole line), `string` + `format: date` (`YYYY-MM-DD`), `number`, `number` +
  `format: amount` or `percent`, `boolean`, or a string `enum`. `description` says what to look for.
- Response `fields[name]`: `text` (the line Strom picked), `value` (cleaned to the type; the whole line
  when it holds more than one value of the type), `confidence`, `page`, `box` ([left, top, right, bottom]
  as fractions of the page). `null` when the document doesn't give it. Booleans and enums have only
  `value` and `confidence`.
- Charged by input tokens like `/v1/systemone`, once done; needs a positive balance to start. Unreadable
  files, no text or more than 8 pages: 422, free.

### Latency

Model time, median, one request at a time, measured on the production API:

| Input | 1 question | 8 questions | 16 questions |
| --- | --- | --- | --- |
| 2,000-token text | 181 ms | 281 ms | 438 ms |
| One 512 px image | 66 ms | 180 ms | 239 ms |

Text with one question: 550 tokens 91 ms, 8,000 tokens 228 ms, 24,000 tokens 673 ms. A 512 px image
is often enough detail, at a quarter of the tokens of a full-size one.

## Designing questions

- **Break broad judgments into narrow ones** and combine them in code. "Should this be escalated?"
  becomes: is a team blocked (`noul`), how urgent (`score`), who owns it (`choice`). The decision rule
  stays visible and easy to change.
- **Ask independent questions over the same state in one request.** The state is read once and
  questions run in parallel, so extra questions are cheap. They can't see each other's answers; use a
  second request only when an answer decides what to ask or fetch next.
- **Give the state enough context** for the judgment: the message, the relevant record fields, the
  policy being checked. Prefer named JSON fields when the state has several parts.
- **Pick the type by what the answer means.** `noul` for whether a condition holds (one per label when
  several can apply); `choice` for exactly one of a set; `score` for degree on an ordered scale. Add
  a `none`/`other` option when nothing may fit.
- **Describe options and levels concretely.** Choice descriptions say when each applies; score levels
  describe distinct situations that stand on their own.
- **Question names are for your code** and aren't sent to the model, so put the full meaning in
  `instructions`.
- **Select instead of generate.** To extract a value, find the candidates in code and let a `choice`
  pick the right one.

## Using the probabilities

- Act automatically above a threshold and send the rest to a person or an LLM. Set thresholds on
  your own data and the cost of a mistake.
- A `noul` near 0.5 means yes and no are similarly likely, not "medium".
- `choice` and `score` `confidence` say how concentrated the probabilities are. Two acceptable options
  can split the probability; that's information, not necessarily an error.
- Strom can pick the wrong option, like any model. Validate on representative cases from the target
  domain before automating.
- Keep API keys server-side; never ship them to a browser or app.

## More

- Hands-on tour with two live calls, no key needed: https://platform.uprelic.com/getting-started-with-strom.md
- Docs: https://platform.uprelic.com/docs
- Site index for agents: https://platform.uprelic.com/llms.txt
- This file as a Claude Code skill:
  `mkdir -p .claude/skills/strom && curl -o .claude/skills/strom/SKILL.md https://platform.uprelic.com/skill.md`
