# E2E demo — insurance-claim-fraud on the cleanroom stack

The easiest end-to-end test of a realistic knowledge scenario: the committed
`packs/insurance-claim-fraud` pack (4 competing hypotheses about a claim:
staged accident / inflated estimate / pre-existing damage / legitimate),
run by `scripts/e2e.sh` against TerminusDB.

## What it showcases

| Stage | What happens | Neurosymbolic point |
|---|---|---|
| sense | LLM (mistral-large-4, pydantic-ai, typed output) reads 5 evidence files → 18 facts with confidence + source spans | LLM does what it's good at: reading messy evidence |
| run phase 1 | Rules fire to fixpoint (d1–d4 derived), constraint with `{"var"}` semantics prunes H4 (repeat parking-lot claims), ranking H2 0.630 > H1 0.625 > H3 0.620 | abduction = hypotheses raised by rules, pruned by constraints, ranked by score — all WOQL, zero LLM |
| determinism A | re-run with `MISTRAL_API_KEY` **unset** and `FACTY_SENSE=cache` → verdict hash identical | no LLM in the verdict path, byte-identical replay |
| phase 2 | discriminating-test results applied (`demos/fraud-phase2-drop.json`: paint transfer found, second estimate comparable) → H1 and H2 eliminated → **H3 (pre-existing damage) wins** | new evidence flips the abductive verdict deterministically |
| determinism B | `TERMINUSDB_REF=commit:<id>` replays the phase-1 verdict from the immutable commit | the audit trail is the git-for-data history |
| trace | Derivation edges + prunes printed from the graph | explanation = queryable data |

## Run it

```bash
docker compose -f compose.yaml up -d        # terminusdb-server:v12 on :6363
scripts/e2e.sh                              # offline, golden facts, no key needed
scripts/e2e.sh --live                       # live sensing via pydantic-ai (MISTRAL_API_KEY)
# or inside the SmolVM machine:
#   docker build -t facty 
#   docker save facty | smolvm machine run --net --image - -- bash
#   scripts/e2e.sh
```

## Expected output (golden, offline mode)

Phase 1: derived `d1 d2 d2b d3 d4`; pruned `H4` by `c-repeat-parking-lot-claims-undercuts-legitimate`
(variable condition `{"var": "p"}` = existence); ranking **H2 0.6300 > H1 0.6250 > H3 0.6200**, H4 pruned.
Phase 2: `H1` pruned by `c-police-report-corroborates`, `H2` by `c-independent-estimate-comparable`,
winner **H3** at 0.6200. Verdict hash identical across replays; phase-1 verdict replayable from the head commit.

## Acceptance checklist

- [ ] `e2e.sh` exits 0 offline with no `MISTRAL_API_KEY` in the environment
- [ ] phase-1 ranking matches the golden scores above (±0.001)
- [ ] determinism proof A prints `DETERMINISM OK`
- [ ] phase-2 winner is H3 with the two prunes shown in the trace
- [ ] `--live` sensed facts land within a reasonable edit distance of `tests/facts-staged.json`
      (sensing quality is reported, never asserted — the verdict never depends on it)

## Pack format

Packs live as TerminusDB JSON-LD under `<case>/terminusdb/` (one-time conversion by
`python -m facty.migrate`; typed `valueString/valueBool/valueNum` values,
decimal confidences). The cleanroom loads them with plain inserts — no runtime
conversion. `python -m facty selftest` golden-matches the PoC's
attribution-silver-blaze case against the live DB (PASS 2026-10-29).

## Live run 2026-10-29 (docker terminusdb-server:v12.0.9, mistral-large-4 via pydantic-ai)

`scripts/e2e.sh --live` completed end to end:

- sense: mistral-large-4 extracted **13 facts** from the 5 evidence files (golden has 18 —
  sensing drift is reported, never decided on; the prompt pins the pack's exact vocabulary).
- phase 1 (engine only): derived d2, d2b, d3; pruned H4 (repeat parking-lot claims);
  ranking H2 0.6300 > H3 0.6200 > H1 0.4250.
- determinism A: re-run with `MISTRAL_API_KEY` **unset** → `DETERMINISM OK`
  (byte-identical verdict hash; derivation ids are content-hashed, the verdict trace is a
  pure function of DB state, generated `@id`s are stripped before hashing).
- phase 2 (drop applied): H1 pruned by `c-police-report-corroborates`, H2 by
  `c-independent-estimate-comparable` → **winner H3 (pre-existing damage) at 0.6200**.
- time-travel: `GET /api/document/.../local/commit/<phase-1-commit>` shows only the phase-1
  verdict — the audit trail is the commit history.

Runtime fixes this run forced (all recorded in `docs/research/deps-log.md`): schema via
document endpoint `graph_type=schema`, `Set` not `Array`, upsert = PUT→POST fallback,
`as_list=true` reads, WOQL JSON-LD variable objects, FactTemplate subdocument for derive
blueprints, `pydantic-ai[mistral]` extra.

## Why this is the right demo shape

The LLM's unreliability is confined to *sensing* (fact extraction), where a wrong
confidence or a missed span degrades gracefully and is visible in the trace.
Every *decision* — which rules fire, which hypothesis is pruned, the ranking, the
verdict — is a deterministic WOQL/commit operation that replays byte-identically
without any LLM. That is the ADR-0003 split demonstrated end to end.
