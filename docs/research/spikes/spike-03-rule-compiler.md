# Spike 03 — rule-DSL → Cypher compiler with the EXPLAIN gate

**Date:** 2026-10-20 · **Status:** PASS
**Question:** Can pack rules compile from a schema-validated DSL into
Ladybug-valid Cypher behind an `EXPLAIN` gate (the durable no-retry guarantee),
forward-chain to fixpoint, and record the derivation trace as graph edges?
**Complements:** [../stack-survey.md](../stack-survey.md) §4.3, §5

## Method

Session VM, `@ladybugdb/wasm-core`. A minimal rule DSL —

```json
{ "id": "R1-high-value",
  "when":  [{ "var": "c", "label": "Claim", "props": { "status": "filed" } }],
  "where": [{ "var": "c", "prop": "amount", "op": ">", "value": 10000 }],
  "rels":  [["f", "DERIVED_FROM", "c"]],
  "then":  { "fact": { "id": "{c.id}:high_value",
                       "props": { "type": "high_value", "subject": { "ref": "c.id" }, "confidence": 0.9 } },
             "link": { "to": "c", "type": "DERIVED_FROM" } } }
```

—compiled by a closed-template compiler to:

```cypher
MATCH (c:Claim {status: 'filed'}) WHERE c.amount > 10000
WITH c, c.id + ':high_value' AS fid
OPTIONAL MATCH (ex:Fact {id: fid}) WITH c, fid, ex IS NULL AS isNew
MERGE (__derived:Fact {id: fid}) ON CREATE SET __derived.type = 'high_value', …
MERGE (__derived)-[:DERIVED_FROM {rule: 'R1-high-value'}]->(c)
RETURN isNew, __derived.id AS derived
```

Seeded with 2 claims / 2 accounts; R2 chained off R1's derived fact. Every
compiled query passed through `EXPLAIN` before execution.

## Results — PASS

- Both rules compile and pass the EXPLAIN gate.
- **Negative tests**: unknown label (`Nonsense`) → binder exception, rejected;
  syntax error → parser exception, rejected. The gate rejects bad output.
- **Forward chaining to fixpoint**: round 1 derived 2 facts (R1 from the claim,
  R2 chained off R1's derived fact — chaining off derived facts works);
  round 2 derived 0 (fixpoint).
- **Trace as edges**: `(f:Fact)-[:DERIVED_FROM {rule}]->(source)` — both facts
  traceable to their source claim and firing rule.
- **Idempotent**: re-running the chain leaves the fact count unchanged (MERGE).

## Ladybug dialect findings (verified in-VM — these shape the real compiler)

1. **String concatenation is `+`**: template `"{c.id}:high_value"` must compile
   to `c.id + ':high_value'` (segment-join with `+`).
2. **MERGE patterns can't contain expressions** — compute the id in a `WITH`,
   `MERGE` on the projected variable.
3. **Multiple MATCH patterns are comma-separated.**
4. **Reserved internal variables**: the compiler's generated node variable must
   not collide with rule variables (variable capture bit us: rule var `f` vs
   the derived node `f`). Use a reserved prefix (`__derived`); the DSL forbids
   user vars starting with `__`.
5. **EXPLAIN validates syntax AND semantics** (unknown table/label rejected at
   bind time) — it is a real gate, not just a parser.
6. **`query()` throws on parse/binder errors** — catch, don't rely on
   `isSuccess()` alone (see spike 02).

## Implication

The no-retry guarantee is viable end-to-end: schema-validated rule DSL (JSON) →
closed-template compiler → `EXPLAIN` runtime gate → (CI: openCypher TCK against
the template outputs). The LLM never emits Cypher; dialect errors are impossible
by construction, and the gate proves it at runtime.
