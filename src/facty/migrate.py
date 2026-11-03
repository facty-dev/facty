#!/usr/bin/env python3
"""One-time migration: PoC pack JSON → TerminusDB JSON-LD documents.

Reads a PoC case/pack dir (pack/{rules,hypotheses,constraints}.json, optional
facts*.json) and writes <dir>/terminusdb/{pack.json, facts-*.json} in the
the TerminusDB schema shape (src/facty/schema.py) — ready to
insert with zero runtime conversion. The PoC files are left untouched.

Usage: uv run --python 3.14 python scripts/migrate_pack.py <case-or-pack-dir> [facts.json ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def typed_value(v):
    """PoC value (bool/num/str/{"var":name}) → typed TerminusDB field(s)."""
    if isinstance(v, dict) and set(v) == {"var"}:
        return {"var": v["var"]}
    if isinstance(v, bool):
        return {"valueBool": v}
    if isinstance(v, (int, float)):
        return {"valueNum": v}
    return {"valueString": str(v)}


def cond(c: dict) -> dict:
    return {"@type": "Condition", "subject": c["subject"], "predicate": c["predicate"],
            **typed_value(c["value"])}


def action(a: dict) -> dict:
    doc = {"@type": "Action", "op": a["op"]}
    if a.get("fact"):
        f = a["fact"]
        doc["fact"] = {"@type": "FactTemplate", "id": f["id"], "type": f.get("type", "derived"),
                       "subject": f["subject"], "predicate": f["predicate"],
                       **typed_value(f["value"]),
                       "confidence": f.get("confidence", 1.0)}  # no source: Fact-only discriminator
    if a.get("hypotheses"):
        doc["hypotheses"] = a["hypotheses"]
    if a.get("question"):
        q = a["question"]
        doc["question"] = {"@type": "Question", "id": q["id"], "text": q["text"], "slot": q["slot"],
                           "mandatory": bool(q.get("mandatory", False)),
                           "priority": int(q.get("priority", 99)), "status": "open",
                           "raisedBy": "rule:" + a.get("_rule", ""), "discriminates": q.get("discriminates", [])}
    return doc


def rule(r: dict) -> dict:
    return {"@type": "Rule", "id": r["id"], "version": str(r.get("version", "1")), "pack": r["pack"],
            "when": [cond(c) for c in r.get("when", [])],
            "then": [dict(action(a), ) for a in [{**a, "_rule": r["id"]} for a in r.get("then", [])]]}


def hypothesis(h: dict) -> dict:
    doc = {"@type": "Hypothesis", "id": h["id"], "statement": h["statement"],
           "status": h.get("status", "open"), "prior": h.get("prior", 0.0),
           "claims": [cond(c) for c in h.get("claims", [])]}
    for k in ("killer", "horse_fate", "mechanism", "evidenceFor", "evidenceAgainst", "discriminatingTests"):
        if h.get(k) is not None:
            doc[k] = h[k]
    return doc


def constraint(c: dict) -> dict:
    doc = {"@type": "Constraint", "id": c["id"], "type": c["type"], "hypothesis": c["hypothesis"],
           "when": [cond(w) for w in c.get("when", [])]}
    for k in ("reason", "field"):
        if c.get(k) is not None:
            doc[k] = c[k]
    if c.get("value") is not None:
        doc.update(typed_value(c["value"]))
    return doc


def fact(f: dict) -> dict:
    doc = {"@type": "Fact", "id": f["id"], "type": f.get("type", "case"),
           "subject": f["subject"], "predicate": f["predicate"],
           **typed_value(f["value"]), "confidence": f.get("confidence", 1.0),
           "source": f.get("source", "")}
    if f.get("observedAt"):
        doc["observedAt"] = f["observedAt"]
    return doc


def main() -> int:
    src = Path(sys.argv[1])
    out = src / "terminusdb"
    out.mkdir(exist_ok=True)
    pack_dir = src / "pack"
    docs = []
    for r in json.loads((pack_dir / "rules.json").read_text()):
        docs.append(rule(r))
    for h in json.loads((pack_dir / "hypotheses.json").read_text()):
        docs.append(hypothesis(h))
    for c in json.loads((pack_dir / "constraints.json").read_text()):
        docs.append(constraint(c))
    (out / "pack.json").write_text(json.dumps(docs, indent=2))
    print(f"{out}/pack.json: {len(docs)} docs")
    for fpath in sys.argv[2:]:
        fp = Path(fpath)
        facts = [fact(f) for f in json.loads(fp.read_text())]
        (out / fp.name).write_text(json.dumps(facts, indent=2))
        print(f"{out}/{fp.name}: {len(facts)} fact docs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
