"""Rule DSL → WOQL compiler (closed template set).

Pack Rule documents are TerminusDB JSON-LD (see schema.py): `when` is a set of
Condition subdocuments with typed value fields (valueString/valueBool/valueNum)
or `var` (bind-any existence). Each condition matches ANY Fact independently —
condition i binds node variable Fi and selects the fact id as Fiid.

The compiler emits only woql.py helpers, so every query is valid WOQL JSON-LD
by construction (live-verified against terminusdb-server v12.0.9).
"""

from __future__ import annotations

from . import woql


def value_literal(cond: dict):
    """The typed WOQL literal for a condition's value, or None for `var`."""
    if cond.get("var"):
        return None
    if "valueBool" in cond:
        return {"@type": "Value", "data": {"@type": "xsd:boolean", "@value": cond["valueBool"]}}
    if "valueNum" in cond:
        return {"@type": "Value", "data": {"@type": "xsd:decimal", "@value": cond["valueNum"]}}
    if "valueString" in cond:
        return {"@type": "Value", "data": {"@type": "xsd:string", "@value": cond["valueString"]}}
    raise ValueError(f"condition has no value/var: {cond}")


def compile_when(conditions: list[dict]) -> tuple[dict, list[str]]:
    """Compile a rule's `when`. Returns (query, premise_id_vars)."""
    parts = []
    id_vars = []
    for i, c in enumerate(conditions):
        v = f"F{i}"
        vid = f"F{i}id"
        id_vars.append(vid)
        parts.append(woql.fact_pattern(v, subject=c["subject"], predicate=c["predicate"],
                                       value=value_literal(c)))
        parts.append(woql.triple(v, "id", woql.V(vid)))
    body = woql.and_(*parts)
    query = woql.select(id_vars, body) if id_vars else body
    return query, id_vars


def compile_constraint_when(conditions: list[dict]) -> dict:
    """A constraint's `when` as a Select-topped existence query."""
    parts = []
    vars_ = []
    for i, c in enumerate(conditions):
        v = f"C{i}"
        vars_.append(v)
        parts.append(woql.fact_pattern(v, subject=c["subject"], predicate=c["predicate"],
                                       value=value_literal(c)))
    return woql.select(vars_, woql.and_(*parts))


def compile_claim(claim: dict, var: str = "Cl") -> dict:
    """A hypothesis claim as a Select-topped existence query against Facts."""
    return woql.select([var], woql.fact_pattern(
        var, subject=claim["subject"], predicate=claim["predicate"], value=value_literal(claim)))


def compile_rule(rule: dict) -> tuple[dict, list[str]]:
    return compile_when(list(rule.get("when", [])))
