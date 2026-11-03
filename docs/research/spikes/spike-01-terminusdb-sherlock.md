# Spike 01 — the Sherlock loop on TerminusDB (golden vs the PoC engine)

**Goal:** prove the cleanroom stack (TerminusDB + SmolVM + Vibe CLI,
mistral-large-4) reproduces the PoC's verdict on the attribution demo case,
deterministically, with the trace as committed graph data.

**Stack under test:** `terminusdb/terminusdb-server` (Docker or in the SmolVM
image) + `facty` (this directory) + headless `vibe -p` for sensing.

## Steps

1. `docker compose -f compose.yaml up -d` (terminusdb-server:v12 on :6363), or boot the
   SmolVM machine: `docker build -t facty  && docker save facty | smolvm machine run --net --image - -- bash`.
2. `pip install -e  && python -m facty init-db`
3. `python -m facty load-pack engine/cases/attribution-silver-blaze`
4. Offline first: `FACTY_SENSE=cache python -m facty run attribution-silver-blaze`
   with the PoC's `facts.json` loaded via `load-facts` (the cache).
5. Live sensing: `python -m facty sense engine/cases/attribution-silver-blaze --out /tmp/facts.json`
   (default backend: PydanticAI programmatic, `mistral:mistral-large-4`, typed
   `SensedFacts` output; `FACTY_SENSE_BACKEND=vibe` exercises the headless-CLI
   fallback). Compare the sensed facts against the PoC's `facts.json` (sensing
   quality, not verdict).
6. `python -m facty run attribution-silver-blaze --add-facts engine/cases/attribution-silver-blaze/facts-ledger.json --phase 2`
7. `python -m facty selftest`

## Acceptance (mirrors engine/cases/attribution-silver-blaze/expected.md)

Phase 1:
- [ ] forward chain derives d1 (fate=wandered), d2 (role=acquaintance), d3 (killed=John Straker)
- [ ] C1 prunes H4, C2 prunes H1
- [ ] ranking H2 0.740 > H3 0.235 (score = 0.6·claims + 0.3·min(support,3)/3 + 0.1·prior)
- [ ] recommended test = q1

Phase 2 (ledger drop applied):
- [ ] d4 (wasSabotaging), d5 (role=accomplice) derived
- [ ] C3 prunes H2; winner = H3 at 0.735

Cross-cutting:
- [ ] verdict + derivations committed as documents; `commit_log` shows one commit per phase on the case branch
- [ ] determinism: re-run at the same commit → byte-identical verdict (selftest asserts)
- [ ] no LLM in the verdict path: `FACTY_SENSE=cache` run works with no key present
- [ ] WOQL validity: every compiled rule passes server bind-time validation (no retry loop)

## Known gaps to verify, not assume

- REST/WOQL shapes were verified against the v12 docs + official python client
  (see `docs/research/deps-log.md`): document/woql paths are
  `/api/{document,woql}/{org}/{db}/local/branch/{branch}`, `OrderBy.ordering`,
  `GroupBy{group_by,grouped,group_template,query}`, `@key = {"@type":"Hash","@fields":[...]}`.
  Remaining unknowns at first live contact: `GET /api/document/...` pagination
  params (case scale is fine without), `/api/schema/{org}/{db}` exact params,
  and the `local/commit/<id>` time-travel path. `client.py` is the single
  place to adjust.
- SmolVM boot of the built image (`docker save` → `smolvm machine run --image -`),
  and the host-secret path for `MISTRAL_API_KEY` into the VM (same mechanism as
  the gondolin sessions).
