# The neurosymbolic abductive methodology on the cleanroom stack

ADR-0005 replaced the PoC runtime with the cleanroom stack
(TerminusDB + SmolVM + Vibe CLI + pydantic-ai). This doc maps the **original
methodology** (ADR-0003, PHILOSOPHY, INVESTIGATION-TYPES — unchanged) onto what
the new stack can do **natively**, and triages the patterns that are not yet
native into implementation planning. Everything marked ✅ is live-verified
against terminusdb-server v12.0.9 (`./facty selftest`, `scripts/e2e.sh`).

## Methodology → cleanroom mapping

| Methodology pattern | PoC implementation | Cleanroom implementation | Status |
|---|---|---|---|
| Forward chaining (modus ponens → fixpoint) | Python loop over rules | Each rule's `when` compiles to WOQL (`.../rules.py`); derived facts + `Derivation` edges committed per firing | ✅ native |
| Backward chaining (prove hypothesis claims) | per-claim fact lookup | per-claim existence WOQL queries; proofs recorded as graph edges | ✅ native (claim-level — see T1 for full proof trees) |
| Abduction: raise candidate explanations | rules `raise` hypotheses | same — hypotheses are documents; rules raise them | ✅ native |
| Abduction: prune impossible explanations | constraint layer (eliminate) | constraint `when` → WOQL existence query; prune = status write + commit | ✅ native |
| Abduction: rank survivors | fixed score 0.6·claims + 0.3·support + 0.1·prior | identical formula, computed from query results | ✅ native |
| Discriminating tests / questions | engine opens questions, ranks by discrimination | `OpenQuestion` docs; ranked by (alive discriminations, priority, id) | ✅ native (app-side ranking; WOQL-able later) |
| Deterministic replay | re-run Python on same JSON files | branch/commit/time-travel: `local/commit/<id>` replays byte-identical verdicts (selftest asserts) | ✅ native (better: the audit trail *is* the replay) |
| Sensing: messy evidence → facts | pi RPC one-shot | pydantic-ai `Agent(tools=[], output_type=SensedFacts)`, schema-validated on insert, disk-cached (`FACTY_SENSE=cache` replays) | ✅ native |
| Pack/hypothesis authoring (meta-Facty loop) | Pack Studio TUI + pi | Vibe CLI `pack-author` agent (mistral-large-4, optional TerminusDB MCP) drafts JSON-LD packs; DB validates on insert | ✅ native (interview FSM → T9) |
| Commentary / plain-language explanation | `facty explain` | one-shot pydantic-ai over the committed trace | ✅ native |
| Audit trail / git-native pipeline | git branches on JSON files | TerminusDB git-for-data: branch = case/pack asset, merge = materialization, `_commits` queryable via WOQL | ✅ native |
| What-if / counterfactuals | re-run with modified files | branch per scenario, run, `diff` the branches | ✅ native |
| Secrets isolation | gondolin host-secret proxy | SmolVM image; host-secret path **open** (see ADR-0005 open items) | 🟡 planned |

## Triage — reasoning patterns not yet native (implementation planning)

| # | Pattern | Why not native yet | Plan | Priority |
|---|---|---|---|---|
| T1 | Full backward-chaining **proof trees** (recursive SLD goal resolution) | WOQL is Datalog: per-claim existence queries don't construct recursive proofs | compile rule heads into recursive WOQL path queries; fallback: TerminusDB's Prolog query interface (`terminusdb query`, v/1) or the clingo-wasm tier | P2 |
| T2 | ASP answer-set enumeration + **global optimization** (`#optimize`, choice rules, mutex/cardinality over explanation sets) | WOQL has no choice/optimize; abduction is enumerate-and-filter | clingo-wasm as optional pack-level solver tier (`solver: woql \| asp`), results committed back as docs — already designed in cleanroom-stack §4.4 | P2 |
| T3 | Non-stratified negation / paraconsistent constraints | WOQL negation is stratified only | pack-load-time stratification check with a clear error; non-stratified packs route to the ASP tier (T2) | P3 |
| T4 | Bitemporal edges (`validAt`/`invalidAt`, explicit retraction — the Graphiti model) | TerminusDB time-travel gives transaction time (commit) but not per-edge validity intervals; facts carry `observedAt` only | add optional `validAt`/`invalidAt` to Fact/Derivation + WOQL interval filters; commit time covers transaction time | P2 |
| T5 | Incremental / semi-naive re-evaluation as facts stream in | engine re-runs to fixpoint per phase | delta evaluation: only re-run rules whose premises changed; v12 WOQL has `AddedTriple`/`DeletedTriple` for delta queries | P3 |
| T6 | Principled uncertainty propagation (noisy-OR, calibration) beyond the fixed score | the 0.6/0.3/0.1 formula is fixed by ADR-0003 | keep the formula; feed calibrated confidences from the Strom decider tier as fact inputs (already possible); revisit only if the PO wants full probabilistic logic | P3 |
| T7 | Cross-pack shared ontology, multi-tenant isolation + access control | TerminusDB is per-database; capabilities/roles exist but aren't wired | pack-registry database + role capabilities (see USE-CASES.md scenarios); per-tenant db or scoped branches | P2 |
| T8 | Vector/hybrid retrieval over large evidence corpora | TerminusDB VectorLink exists but isn't wired | embed evidence chunks at sense time, retrieve top-k before the LLM read | P3 |
| T9 | Pack-factory interview as an explicit state machine (meta-Facty loop) | Vibe CLI session + MCP works, but there's no in-code FSM/checkpointing | pydantic-graph (or LangGraph) FSM for the interview, checkpoints in TerminusDB commits; engine validates + commits the drafted pack | P2 |
| T10 | Streaming verdict updates (watch a case branch live) | not needed for MVP | poll `/api/log` or WebSocket on branch updates | P4 |

Rule: anything in the triage list must never weaken the core invariants — the
verdict path stays deterministic, and the LLM stays induction-only. T2/T3 are
the only ones that change *what the engine can express*; everything else is
performance, scale, or UX.

## Doc map (post-ADR-0005)

- Vision/method (unchanged): [PHILOSOPHY.md](PHILOSOPHY.md), [vision.md](vision.md), ADR-0003 (superseded in part by ADR-0005)
- Decision: [ADR-0005](adr/0005-cleanroom-stack-replaces-poc.md); survey: [docs/research/stack-survey.md](research/stack-survey.md); dependency docs log: [docs/research/deps-log.md](research/deps-log.md)
- Implementation: [docs/IMPLEMENTATION.md](../docs/IMPLEMENTATION.md), this repo's `./facty`
- Legacy: [ARCHITECTURE.md](ARCHITECTURE.md) (gondolin model — pack-factory runtime until ported), `engine/README.md` (PoC oracle)
