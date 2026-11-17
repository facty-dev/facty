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


# comparison operators (v12 JSON-LD — live-verified against terminusdb-server
# v12.1.0-rc2; shapes from src/core/query/json_woql.pl: 'Less'/'Greater'/'Gte'/'Lte'
# with left/right operands)
CMP_OPS = {"lt": "Less", "le": "Lte", "gt": "Greater", "ge": "Gte"}


def _condition_parts(c: dict, v: str) -> list[dict]:
    """Query parts for one condition against fact-node variable `v`.

    Normal condition: exact typed value (or `var` = bind-any existence).
    Comparison condition (`cmp` in lt|le|gt|ge): binds the fact's typed value and
    compares it — either against a literal (valueNum/valueString/valueBool on the
    condition) or against another fact's value (compareToSubject/compareToPredicate).
    """
    if "cmp" in c:
        if c["cmp"] not in CMP_OPS:
            raise ValueError(f"unknown cmp operator: {c['cmp']}")
        if c.get("compareToSubject"):
            # compare against another fact's value — the value field must be
            # named explicitly (no literal to infer it from); default valueNum
            field = c.get("valueField", "valueNum")
            lit = None
        else:
            lit = value_literal(c)  # the literal picks the value field
            field = "value" + woql.suffix_for(lit)
        vval = f"{v}val"
        parts = [woql.fact_value_pattern(v, c["subject"], c["predicate"], field, vval)]
        if lit is not None:
            parts.append(woql.compare(CMP_OPS[c["cmp"]], woql.VV(vval), lit))
        else:
            w = f"{v}ct"
            parts.append(woql.fact_value_pattern(w, c["compareToSubject"],
                                                 c["compareToPredicate"], field, f"{v}ctval"))
            parts.append(woql.compare(CMP_OPS[c["cmp"]], woql.VV(vval), woql.VV(f"{v}ctval")))
        return parts
    return [woql.fact_pattern(v, subject=c["subject"], predicate=c["predicate"],
                              value=value_literal(c))]


def compile_when(conditions: list[dict]) -> tuple[dict, list[str]]:
    """Compile a rule's `when`. Returns (query, premise_id_vars)."""
    parts = []
    id_vars = []
    for i, c in enumerate(conditions):
        v = f"F{i}"
        vid = f"F{i}id"
        id_vars.append(vid)
        parts.extend(_condition_parts(c, v))
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
        parts.extend(_condition_parts(c, v))
    return woql.select(vars_, woql.and_(*parts))


def compile_claim(claim: dict, var: str = "Cl") -> dict:
    """A hypothesis claim as a Select-topped existence query against Facts."""
    return woql.select([var], woql.and_(*_condition_parts(claim, var)))


def compile_rule(rule: dict) -> tuple[dict, list[str]]:
    return compile_when(list(rule.get("when", [])))
