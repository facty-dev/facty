# Sensing record — the 3 a.m. outage (the probabilistic half)

**Recorded:** facty dev session · **Date:** 2026-10-17
**Role:** the LLM senses and proposes; the engine (`engine/engine.py`)
verifies, chains, prunes, and decides. No LLM call sits in the verdict
path — the selftest proves the verdict replays from these artifacts
alone. Re-derive live from a terminal with the credential:
`./facty sense causation-three-am-outage --op facts` (streams; falls
back to this record when the LLM is unreachable).

## The sensing motion

Schema-guided structured extraction: a JSON schema + a messy piece of
input from the field → a typesafe, schema-validated structured object
the logic engine consumes (`engine/sensing.py`). Entity extraction and
classification are **sensing operations** — the engine never extracts
or classifies; it verifies what the senses produce.

## The operations (phase 1)

1. **Classify** the evidence pile → `evidence-index.json` — each raw
   file typed: monitoring log / deploy log / alert / transcript /
   service roster.
2. **Extract entities** → `entities.json` — the incident, the deploy,
   the certificate, checkout, Payline, monitoring, the on-call, the
   status page.
3. **Extract facts** → `facts.json` — guided by the classification +
   the entities; includes negative evidence (no deploys in the window,
   zero TLS handshake errors, zero WAF blocks) and the sensed date
   comparisons (cert valid through the window; incident after the last
   deploy).

Phase 2: **extract facts** from the provider incident record, the deploy
diff, and the detection review → `facts-postmortem.json`.

## What was read (raw evidence)

- `evidence/monitoring.txt` — the error-rate export, the 502 signature, app-tier health, traffic, cert validity
- `evidence/deploy-log.txt` — d-2214 (18:40, checkout, retry backoff) and the deploy-log gap
- `evidence/alert.txt` — the pager payload and the timeline anchors
- `evidence/slack.txt` — the on-call transcript (WAF silence, cert check)
- `evidence/services.txt` — the service roster (checkout → Payline; no synthetic check)
- `evidence/provider-incident.txt` — (phase 2) Payline's incident record (window + root cause)
- `evidence/deploy-diff.txt` — (phase 2) the d-2214 diff (one constant, no error path)
- `evidence/detection.txt` — (phase 2) the detection review (no upstream health check)

## Notable sensing calls

- **f09, f12, f13** — negative evidence read from absences: no deploys
  in the incident window, zero TLS handshake errors, zero WAF blocks.
  Confidence 0.9–0.95.
- **f11, f17** — date comparisons done by the senses: the certificate
  was valid through the incident window; the incident started after
  the last deploy. Confidence 0.9–0.95.
- **f22** — (phase 2) the window match: Payline's incident window
  equals ours to the minute. Confidence 0.95.
- **f24, f25** — (phase 2) the diff touches no error path; monitoring
  has no synthetic check on Payline (the detection gap).

The engine then does the rest deterministically: the timeline
derivations (R1–R3), question discovery (R4–R6), constraint pruning
(C1, C2), the phase-2 exoneration + confirmation + detection-gap
derivations (R7–R9), constraint pruning (C5), and the verdict + trace.
See `expected.md` for the outcome the selftest asserts.
