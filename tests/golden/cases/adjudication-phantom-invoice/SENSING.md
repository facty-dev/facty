# Sensing record — the phantom invoice (the probabilistic half)

**Recorded:** facty dev session · **Date:** 2026-10-17
**Role:** the LLM senses and proposes; the engine (`engine/engine.py`)
verifies, chains, prunes, and decides. No LLM call sits in the verdict
path — the selftest proves the verdict replays from these artifacts
alone. Re-derive live from a terminal with the credential:
`./facty sense adjudication-phantom-invoice --op facts` (streams; falls
back to this record when the LLM is unreachable).

## The sensing motion

Schema-guided structured extraction: a JSON schema + a messy piece of
input from the field → a typesafe, schema-validated structured object
the logic engine consumes (`engine/sensing.py`). Entity extraction and
classification are **sensing operations** — the engine never extracts
or classifies; it verifies what the senses produce.

## The operations (phase 1)

1. **Classify** the evidence pile → `evidence-index.json` — each raw
   file typed: register / vendor-master log / correspondence / workflow
   log / complaint / note / policy.
2. **Extract entities** → `entities.json` — the two Northwinds, the
   clerk, the invoice, the payment, the receiving account.
3. **Extract facts** → `facts.json` — guided by the classification +
   the entities; includes negative evidence (the blank callback field,
   the missing PO, the unused account, the absent change request).

Phase 2: **extract facts** from the audit trail, session logs, mail
headers, and bank record → `facts-trail.json`.

## What was read (raw evidence)

- `evidence/ap-register.txt` — the payment register (the payment + the real vendor's standing payments)
- `evidence/vendor-master.txt` — the two vendor records (the blank callback field, the unchanged real vendor)
- `evidence/email-thread.txt` — the invoice thread (the "new account" exchange)
- `evidence/approval-log.txt` — the workflow log (same user entered + approved)
- `evidence/complaint.txt` — the real vendor's denial
- `evidence/hart-note.txt` — the clerk's self-flag
- `evidence/policy.txt` — the AP controls (three-way match, callback, SoD)
- `evidence/audit-log.txt` — (phase 2) the vendor-master audit trail (foreign service-account session)
- `evidence/session-log.txt` — (phase 2) the clerk's endpoint/VPN logs (no session overnight)
- `evidence/email-headers.txt` — (phase 2) SPF/DKIM failures + originating IP
- `evidence/bank-record.txt` — (phase 2) the fresh mule account

## Notable sensing calls

- **f06, f09, f10, f19** — negative evidence read from absences: the
  account not in vendor history, the blank callback field, the missing
  PO, the absent change request. Confidence 0.9–0.95.
- **f14** — the lookalike-domain judgement: `northwind-facilities.com`
  vs the real `northwindfacilityservices.com`. Confidence 0.9.
- **f22** — the self-report: the clerk flagged the payment herself.
  Confidence 0.9.
- **f29** — (phase 2) the clerk had no session in the creation window,
  read from the log gap. Confidence 0.95.
- **f30 + f26** — (phase 2) the same originating IP (185.220.44.7) in
  the mail headers and the vendor-master audit — the link the engine
  derives as d5.

The engine then does the rest deterministically: control-bypass
derivations (R1–R3), question discovery (R5–R8), constraint pruning
(C1, C2), the phase-2 IP link and exoneration derivations (R9–R12),
constraint pruning (C6), and the verdict + trace. See `expected.md` for
the outcome the selftest asserts.
