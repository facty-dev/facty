"""WOQL AST builders — the only place WOQL JSON is constructed.

Shapes verified live against terminusdb-server v12.0.9 (WOQL JSON-LD):
  node variable   {"@type":"NodeValue","variable":"F0"}
  node id         {"@type":"NodeValue","node":"doc:X"}
  value variable  {"@type":"Value","variable":"F0id"}
  literal         {"@type":"Value","data":{"@type":"xsd:string","@value":"claim"}}
  Triple          {"@type":"Triple","subject":…,"predicate":{"@type":"NodeValue","node":"subject"},…}
  And/Or/Select   {"and":[…]} / {"or":[…]} / {"variables":[Value var],"query":…}
  OrderBy         {"ordering":[{"variable":…,"order":"asc"}],"query":…}
No `Isa` and no `@type` triples — field names (subject/predicate/value) are
unique to Fact, so class matching is implicit.

The LLM never emits WOQL text; the rule compiler (rules.py) builds queries
through these helpers, so every query is valid by construction. The server
validates again at bind time.
"""

from __future__ import annotations


def NV(name: str) -> dict:  # node variable
    return {"@type": "NodeValue", "variable": name}


def NN(name: str) -> dict:  # node id
    return {"@type": "NodeValue", "node": name}


def VV(name: str) -> dict:  # value variable
    return {"@type": "Value", "variable": name}


def LIT(s: str) -> dict:  # string literal
    return {"@type": "Value", "data": {"@type": "xsd:string", "@value": s}}


def V(name: str) -> str:
    """Mark a name as a value-variable for triple()'s object position."""
    return "v:" + name


def triple(subject: str, predicate: str, obj) -> dict:
    s = NV(subject) if not subject.startswith("d:") else NN(subject[2:])
    if isinstance(obj, str) and obj.startswith("v:"):
        o = VV(obj[2:])
    elif isinstance(obj, str):
        o = LIT(obj)
    else:
        o = obj  # already a Value/NodeValue literal dict
    return {"@type": "Triple", "subject": s, "predicate": NN(predicate), "object": o}


def and_(*queries) -> dict:
    qs = [q for q in queries if q is not None]
    if not qs:
        return {"@type": "True"}
    if len(qs) == 1:
        return qs[0]
    return {"@type": "And", "and": qs}


def or_(*queries) -> dict:
    return {"@type": "Or", "or": list(queries)}


def not_(query) -> dict:
    return {"@type": "Not", "not": query}


def select(variables: list[str], query) -> dict:
    return {"@type": "Select", "variables": [VV(v) for v in variables], "query": query}


def order_by(query, *specs: tuple[str, str]) -> dict:
    return {"@type": "OrderBy", "query": query,
            "ordering": [{"variable": v, "order": o} for v, o in specs]}


def fact_pattern(var: str, subject=None, predicate=None, value=None) -> dict:
    """Match Fact documents by field values.

    `value` is a typed WOQL literal dict (see rules.value_literal) or None for
    existence. Class discrimination without Isa/@type (neither parses in v12):
    Fact is the only class with a `confidence` field, so binding it (unselected)
    restricts matches to Facts, not embedded Condition subdocuments.
    """
    qs = [triple(var, "source", V(var + "_s"))]
    if subject is not None:
        qs.append(triple(var, "subject", LIT(subject)))
    if predicate is not None:
        qs.append(triple(var, "predicate", LIT(predicate)))
    if value is not None:
        qs.append(triple(var, "value" + suffix_for(value), value))
    return and_(*qs)


def suffix_for(literal: dict) -> str:
    """Fact stores typed values in valueString/valueBool/valueNum."""
    t = literal["data"]["@type"]
    return {"xsd:string": "String", "xsd:boolean": "Bool", "xsd:decimal": "Num"}[t]
