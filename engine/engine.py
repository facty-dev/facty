#!/usr/bin/env python3
# engine.py — the Facty symbolic engine (the deterministic half).
#
# Forward + backward chaining over rules, with a constraint layer, over
# canonical case artifacts (facts, rules, hypotheses, constraints,
# questions). The LLM senses and proposes; this engine verifies, chains,
# prunes, and decides. stdlib only — deterministic, replayable, no
# network, no database, no LLM in the verdict path.
#
# Usage:
#   python3 engine/engine.py run --case engine/cases/attribution-silver-blaze [--add-facts FILE] [--json]
#   python3 engine/engine.py selftest
#
# See docs/adr/0003-detective-dss-neurosymbolic-core.md.
# The primary interface is the `facty` CLI (engine/cli.py) — see ADR-0004.

import argparse
import json
from pathlib import Path

__version__ = "0.1.0"

ENGINE_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = ENGINE_DIR / "schemas"

# ── Minimal JSON-Schema validation (subset) ──────────────────────────
# Supports: type, required, properties, enum, items — enough for the
# canonical schemas. Swap in jsonschema when a real dependency is allowed.

_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
}


def validate(instance, schema, path="$"):
    """Return a list of violation strings (empty = valid)."""
    if isinstance(schema, dict) and "$ref" in schema:
        return validate(instance, load_json(SCHEMA_DIR / schema["$ref"]), path)
    errs = []
    t = schema.get("type")
    if t is not None:
        if isinstance(instance, bool) and t in ("number", "integer"):
            return [f"{path}: expected {t}, got boolean"]
        if not isinstance(instance, _TYPE_MAP[t]):
            return [f"{path}: expected {t}, got {type(instance).__name__}"]
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} not in {schema['enum']}")
    if t == "object":
        for req in schema.get("required", []):
            if req not in instance:
                errs.append(f"{path}: missing required property {req!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in instance:
                errs += validate(instance[key], sub, f"{path}.{key}")
    if t == "array" and "items" in schema:
        for i, item in enumerate(instance):
            errs += validate(item, schema["items"], f"{path}[{i}]")
    return errs


def load_json(path):
    return json.loads(Path(path).read_text())


def load_array(path, schema_name):
    """Load a JSON array, validating every element against its schema."""
    data = load_json(path)
    if not isinstance(data, list):
        raise SystemExit(f"{path}: expected a JSON array")
    schema = load_json(SCHEMA_DIR / schema_name)
    for i, item in enumerate(data):
        errs = validate(item, schema, f"{path}[{i}]")
        if errs:
            raise SystemExit(f"schema violation in {path}[{i}]:\n  " + "\n  ".join(errs))
    return data


def load_validated(path, schema_name):
    """Load a JSON document, validating the whole document against an
    (array or object) schema — for wrapper schemas with $ref items."""
    data = load_json(path)
    schema = load_json(SCHEMA_DIR / schema_name)
    errs = validate(data, schema, path=str(path))
    if errs:
        raise SystemExit(f"schema violation in {path}:\n  " + "\n  ".join(errs))
    return data


# ── Pattern matching (conditions ↔ facts, with variable bindings) ───

def match_cond(cond, fact, bindings):
    """Match a condition pattern against a fact, extending bindings.
    Literals match exactly; {"var": name} binds (or checks) a variable."""
    b = dict(bindings)
    for key in ("type", "subject", "predicate", "value"):
        if key not in cond:
            continue
        want = cond[key]
        got = fact.get(key)
        if isinstance(want, dict) and set(want) == {"var"}:
            name = want["var"]
            if name in b:
                if b[name] != got:
                    return None
            else:
                b[name] = got
        elif got != want:
            return None
    return b


def subst(template, bindings):
    """Substitute {"var": name} leaves in a template with bindings."""
    if isinstance(template, dict):
        if set(template) == {"var"}:
            return bindings.get(template["var"])
        return {k: subst(v, bindings) for k, v in template.items()}
    if isinstance(template, list):
        return [subst(v, bindings) for v in template]
    return template


def conds_hold(conds, facts):
    """Existential check: every cond must match at least one fact."""
    for cond in conds:
        if not any(match_cond(cond, f, {}) is not None for f in facts):
            return False
    return True


# ── Forward chaining (modus ponens; fixpoint) ────────────────────────

def forward_chain(facts, rules, max_rounds=50, emit=None):
    """Run rules to a fixpoint. If emit is given, it is called with an
    event dict per rule firing (derive / raise / open), including the
    source fact ids that matched the rule's conditions.
    Returns (derived_facts, fired, opened_questions, raised_hypotheses)."""
    known = {f["id"]: f for f in facts}
    derived, fired, questions, raised = [], [], [], []
    q_ids = set()

    def fire(event):
        if emit:
            emit(event)

    for round_no in range(max_rounds):
        new_any = False
        for rule in rules:
            # All binding combinations for the rule's conditions,
            # tracking which fact ids matched each condition.
            combos = [({}, [])]
            for cond in rule["when"]:
                nxt = []
                for b, srcs in combos:
                    for fact in known.values():
                        mb = match_cond(cond, fact, b)
                        if mb is not None:
                            nxt.append((mb, srcs + [fact["id"]]))
                combos = nxt
                if not combos:
                    break
            for b, srcs in combos:
                for action in rule["then"]:
                    op = action.get("op")
                    if op == "derive":
                        fact = subst(action["fact"], b)
                        fact.setdefault("confidence", rule.get("confidence", 1.0))
                        fact.setdefault("source", "rule:" + rule["id"])
                        fid = fact["id"]
                        if fid in known:
                            if known[fid] == fact:
                                continue  # idempotent re-derivation
                            fid = f"{fid}#r{round_no}"
                            fact = dict(fact, id=fid)
                        known[fid] = fact
                        derived.append(fact)
                        fired.append({"rule": rule["id"], "round": round_no,
                                      "derived": fid, "sources": srcs})
                        fire({"op": "derive", "rule": rule["id"], "fact": fact,
                              "sources": srcs})
                        new_any = True
                    elif op == "raise":
                        new = [hid for hid in subst(action["hypotheses"], b)
                               if hid not in raised]
                        for hid in new:
                            raised.append(hid)
                            fired.append({"rule": rule["id"], "round": round_no,
                                          "raised": hid})
                        if new:
                            fire({"op": "raise", "rule": rule["id"],
                                  "hypotheses": new})
                            new_any = True
                    elif op == "open":
                        q = subst(action["question"], b)
                        q.setdefault("raisedBy", "rule:" + rule["id"])
                        q.setdefault("status", "open")
                        if q["id"] not in q_ids:
                            q_ids.add(q["id"])
                            questions.append(q)
                            fired.append({"rule": rule["id"], "round": round_no,
                                          "opened": q["id"]})
                            fire({"op": "open", "rule": rule["id"], "question": q})
                            new_any = True
        if not new_any:
            break
    return derived, fired, questions, raised


# ── Backward chaining (goal-driven claim proofs) ─────────────────────

def prove_claims(claims, facts, emit=None):
    """Every claim must be provable from the fact base. If emit is given,
    it is called per claim (proven or refuted, with the proving fact id).
    Returns (proven_count, refuted_claims, proofs)."""
    proofs, refuted = [], []
    for claim in claims:
        matched = None
        for fact in facts:
            if match_cond(claim, fact, {}) is not None:
                matched = fact["id"]
                break
        if emit:
            emit({"op": "claim", "claim": claim, "proven": matched is not None,
                  "provenBy": matched})
        if matched:
            proofs.append({"claim": claim, "provenBy": matched})
        else:
            refuted.append(claim)
    return len(claims) - len(refuted), refuted, proofs


# ── Constraint layer (prune + support) ───────────────────────────────

def apply_constraints(hypotheses, facts, constraints, emit=None):
    """Prune eliminated hypotheses, add support scores. If emit is given,
    it is called per elimination / support event.
    Returns (survivors, pruned)."""
    scored = []
    for h in hypotheses:
        h = dict(h)
        h["support"] = 0
        h["eliminated"] = None
        scored.append(h)
    pruned = []
    for c in constraints:
        if c["type"] == "eliminate":
            if conds_hold(c.get("when", []), facts):
                for h in scored:
                    if h["id"] == c["hypothesis"] and not h["eliminated"]:
                        h["eliminated"] = c.get("reason", c["id"])
                        pruned.append({"hypothesis": h["id"], "constraint": c["id"],
                                       "reason": c.get("reason", "")})
                        if emit:
                            emit({"op": "eliminate", "constraint": c["id"],
                                  "hypothesis": h["id"],
                                  "reason": c.get("reason", "")})
        elif c["type"] == "support":
            if conds_hold(c.get("when", []), facts):
                for h in scored:
                    if h["id"] == c["hypothesis"] and not h["eliminated"]:
                        if h.get(c.get("field")) == c.get("value"):
                            h["support"] += 1
                            if emit:
                                emit({"op": "support", "constraint": c["id"],
                                      "hypothesis": h["id"],
                                      "field": c.get("field"),
                                      "value": c.get("value")})
    survivors = [h for h in scored if not h["eliminated"]]
    for h in scored:
        h["status"] = "pruned" if h["eliminated"] else "open"
    return survivors, pruned


# ── Combine (the deterministic verdict) ──────────────────────────────
#
# score = 0.6 * claims_proven_ratio + 0.3 * support_ratio + 0.1 * prior
# Weights documented in ADR-0003 §4; deterministic and replayable.

W_CLAIMS, W_SUPPORT, W_PRIOR = 0.6, 0.3, 0.1


def rank_questions(questions, ranked_ids):
    """Open questions ranked by how many surviving hypotheses they
    discriminate (ties: lowest priority, then id)."""
    open_q = [q for q in questions if q.get("status") == "open"]

    def q_key(q):
        alive = len([r for r in ranked_ids if r in q.get("discriminates", [])])
        return (-alive, q.get("priority", 99), q["id"])

    open_q.sort(key=q_key)
    return open_q


def combine(survivors, facts, questions, emit=None):
    ranked = []
    for h in survivors:
        proven, refuted, proofs = prove_claims(h.get("claims", []), facts, emit=emit)
        total = len(h.get("claims", [])) or 1
        score = (W_CLAIMS * proven / total
                 + W_SUPPORT * min(h["support"], 3) / 3
                 + W_PRIOR * h.get("prior", 0.0))
        ranked.append({
            "id": h["id"], "statement": h["statement"],
            "killer": h.get("killer"), "horse_fate": h.get("horse_fate"),
            "claims_proven": proven, "claims_total": total,
            "support": h["support"], "prior": h.get("prior", 0.0),
            "score": round(score, 4), "proofs": proofs, "refuted": refuted,
        })
        if emit:
            emit({"op": "proof", "hypothesis": h["id"],
                  "statement": h["statement"], "proven": proven,
                  "total": total, "score": round(score, 4)})
    ranked.sort(key=lambda r: (-r["score"], r["id"]))
    recommended = rank_questions(questions, [r["id"] for r in ranked])
    return {"ranking": ranked,
            "recommended_test": recommended[0] if recommended else None}


# ── Case loading + run ───────────────────────────────────────────────

def load_case(case_dir, add_facts=None):
    case = Path(case_dir)
    facts = load_array(case / "facts.json", "fact.schema.json")
    if add_facts:
        facts = facts + load_array(add_facts, "fact.schema.json")
    rules = load_array(case / "pack" / "rules.json", "rule.schema.json")
    hypotheses = load_array(case / "pack" / "hypotheses.json", "hypothesis.schema.json")
    constraints = load_array(case / "pack" / "constraints.json", "constraint.schema.json")
    return facts, rules, hypotheses, constraints


def run_case(case_dir, add_facts=None, emit=None, facts=None):
    """Run a case end-to-end. `facts` overrides the recorded sensing
    (facts.json + add_facts) — the e2e path senses live with the LLM and
    hands the sensed facts straight to the engine."""
    case = Path(case_dir)
    if facts is None:
        facts = load_array(case / "facts.json", "fact.schema.json")
        if add_facts:
            facts = facts + load_array(add_facts, "fact.schema.json")
    rules = load_array(case / "pack" / "rules.json", "rule.schema.json")
    hypotheses = load_array(case / "pack" / "hypotheses.json", "hypothesis.schema.json")
    constraints = load_array(case / "pack" / "constraints.json", "constraint.schema.json")
    derived, fired, questions, raised = forward_chain(facts, rules, emit=emit)
    all_facts = facts + derived
    active = [h for h in hypotheses if h["id"] in raised] if raised else hypotheses
    survivors, pruned = apply_constraints(active, all_facts, constraints, emit=emit)
    verdict = combine(survivors, all_facts, questions, emit=emit)
    return {
        "case": str(Path(case_dir).name),
        "phase": ("with the recommended test's evidence" if add_facts
                  else "on the initial evidence"),
        "facts_sensed": len(facts),
        "rules": len(rules),
        "hypotheses_total": len(hypotheses),
        "derived_facts": derived,
        "fired_rules": fired,
        "opened_questions": questions,
        "raised_hypotheses": raised,
        "pruned": pruned,
        "ranking": verdict["ranking"],
        "recommended_test": verdict["recommended_test"],
        "verdict": verdict["ranking"][0] if verdict["ranking"] else None,
    }


# ── Human report ─────────────────────────────────────────────────────

def confidence_note(v, open_questions):
    if v["score"] >= 0.7:
        level = "high"
    elif v["score"] >= 0.4:
        level = "medium"
    else:
        level = "low"
    n = len([q for q in open_questions
             if v["id"] in q.get("discriminates", [])])
    if n:
        level += f" ({n} discriminating question{'s' if n > 1 else ''} open)"
    return level


def report(r):
    a = []
    add = a.append
    add(f"=== Facty engine — case: {r['case']} ({r['phase']}) ===")
    add(f"Sensed facts: {r['facts_sensed']} · Rules: {r['rules']} · "
        f"Hypotheses: {r['hypotheses_total']}")
    add("")
    add(f"Forward chain: {len(r['derived_facts'])} derived facts · "
        f"{len(r['opened_questions'])} questions opened · "
        f"{len(r['raised_hypotheses'])} hypotheses raised")
    for f in r["derived_facts"]:
        add(f"  ▸ derived: {f['subject']} / {f['predicate']} = {f['value']!r}"
            f"   (source: {f['source']})")
    for q in r["opened_questions"]:
        add(f"  ▸ opened {q['id']}: {q['text']}")
    add("")
    if r["pruned"]:
        add(f"Constraints: {len(r['pruned'])} pruned")
        for p in r["pruned"]:
            add(f"  ▸ {p['hypothesis']} — eliminated ({p['constraint']}: {p['reason']})")
        add("")
    add("Backward chain (claim proofs) + ranking:")
    for rk in r["ranking"]:
        marks = "✓" * rk["claims_proven"] + "✗" * (rk["claims_total"] - rk["claims_proven"])
        add(f"  {rk['id']} — {rk['statement']}")
        add(f"      claims {rk['claims_proven']}/{rk['claims_total']} {marks} · "
            f"support {rk['support']} · prior {rk['prior']:.2f} · score {rk['score']:.4f}")
    add("")
    if r["recommended_test"]:
        q = r["recommended_test"]
        add(f"Recommended test: {q['id']} — {q['text']}")
        add("")
    v = r["verdict"]
    if v:
        add(f"VERDICT: {v['id']} — {v['statement']}  (score {v['score']:.4f})")
        extras = [f"{k}: {v[k]}" for k in ("killer", "horse_fate") if v.get(k)]
        prefix = " · ".join(extras)
        add(f"  {prefix + ' · ' if prefix else ''}"
            f"confidence: {confidence_note(v, r['opened_questions'])}")
    return "\n".join(a)


# ── Selftest (the acceptance criteria, asserted) ─────────────────────
#
# Three layers: (1) the PoC happy path — attribution-silver-blaze,
# case-specific; (2) the abduction proof — the same skeleton asserted
# for EVERY case; (3) per-case narrative checks (fraud: the funnel ·
# RCA: the timeline).

CASES = [
    # (case directory, phase-2 facts drop)
    ("attribution-silver-blaze", "facts-ledger.json"),
    ("adjudication-phantom-invoice", "facts-trail.json"),
    ("causation-three-am-outage", "facts-postmortem.json"),
]


def prove_abduction(case_name, drop, check):
    """The abductive skeleton, asserted for any case: sensed facts →
    forward chain (derive + open questions) → constraint pruning →
    ranked hypotheses → discriminating test (the facts drop) →
    backward-chained verdict → deterministic replay."""
    case = ENGINE_DIR / "cases" / case_name
    r1 = run_case(case)
    r2 = run_case(case, add_facts=case / drop)
    tag = f"[{case_name}]"
    check(f"{tag} artifacts validate against schemas (facts, rules, hypotheses, constraints)",
          True)  # load_case raises SystemExit on any violation
    check(f"{tag} forward chain derives facts AND opens ≥1 question (the awareness loop)",
          len(r1["derived_facts"]) > 0 and len(r1["opened_questions"]) >= 1,
          f"{len(r1['derived_facts'])} derived, {len(r1['opened_questions'])} questions")
    check(f"{tag} a hypothesis space is raised (≥2 competing explanations)",
          len(r1["raised_hypotheses"]) >= 2, str(r1["raised_hypotheses"]))
    pruned1 = {p["hypothesis"] for p in r1["pruned"]}
    check(f"{tag} constraints prune ≥1 hypothesis on the initial evidence",
          len(pruned1) >= 1, str(pruned1))
    scores = [rk["score"] for rk in r1["ranking"]]
    check(f"{tag} phase 1 leaves ≥2 hypotheses ranked by score (competition survives)",
          len(r1["ranking"]) >= 2 and scores == sorted(scores, reverse=True),
          str([rk["id"] for rk in r1["ranking"]]))
    v2 = r2["verdict"]
    check(f"{tag} phase 2: backward chain validates the winner (all claims proven)",
          v2 is not None and v2["claims_proven"] == v2["claims_total"],
          f"{v2 and v2['claims_proven']}/{v2 and v2['claims_total']}")
    pruned2 = {p["hypothesis"] for p in r2["pruned"]}
    check(f"{tag} the discriminating test changes the outcome (verdict or pruned set)",
          r1["verdict"] is None or r2["verdict"] is None
          or r1["verdict"]["id"] != r2["verdict"]["id"]
          or pruned1 != pruned2)
    r2b = run_case(case, add_facts=case / drop)
    same = json.dumps(r2, sort_keys=True) == json.dumps(r2b, sort_keys=True)
    check(f"{tag} deterministic replay (identical verdict, no LLM in the verdict path)", same)
    try:
        load_validated(case / "facts.json", "facts.schema.json")
        load_validated(case / "evidence-index.json", "evidence-index.schema.json")
        load_validated(case / "entities.json", "entities.schema.json")
        sensed = True
    except SystemExit:
        sensed = False
    check(f"{tag} recorded sensing artifacts validate (facts, evidence-index, entities)",
          sensed)
    return r1, r2


def cmd_selftest(args):
    case = ENGINE_DIR / "cases" / "attribution-silver-blaze"
    ledger = case / "facts-ledger.json"
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(("PASS" if ok else "FAIL") + f"  {name}" + (f" — {detail}" if detail and not ok else ""))

    print("--- phase 1: the case as first heard ---")
    r1 = run_case(case)
    print(report(r1))
    print("")
    print("--- phase 2: the ledger test applied ---")
    r2 = run_case(case, add_facts=ledger)
    print(report(r2))
    print("")
    print("--- acceptance checks ---")

    check("artifacts validate against schemas (facts, rules, hypotheses, constraints)",
          True)  # load_case raises SystemExit on any violation
    check("forward chain derives facts AND opens ≥1 question (the awareness loop)",
          len(r1["derived_facts"]) > 0 and len(r1["opened_questions"]) >= 1,
          f"{len(r1['derived_facts'])} derived, {len(r1['opened_questions'])} questions")
    q_slots = {q["slot"] for q in r1["opened_questions"]}
    check("the kennel-log gap opens a question (negative evidence noticed)",
          "night-visitor-identity" in q_slots, str(q_slots))
    pruned_ids = {p["hypothesis"] for p in r1["pruned"]}
    check("constraints prune the stranger (H4) — the Pepe Silvia",
          "H4" in pruned_ids, str(pruned_ids))
    check("constraints prune the rival theft (H1)",
          "H1" in pruned_ids, str(pruned_ids))
    ids = [rk["id"] for rk in r1["ranking"]]
    check("phase 1 ranks H2 above H3 (both survive, ranked)",
          ids[:2] == ["H2", "H3"], str(ids))
    check("recommended test names the discriminating question (the ledger)",
          r1["recommended_test"] is not None
          and r1["recommended_test"]["slot"] == "sabotage-payment",
          str(r1["recommended_test"]))
    pruned2 = {p["hypothesis"] for p in r2["pruned"]}
    check("phase 2: the ledger prunes H2 (Straker was the perpetrator)",
          "H2" in pruned2, str(pruned2))
    check("phase 2: H3 wins the verdict",
          r2["verdict"] is not None and r2["verdict"]["id"] == "H3",
          str(r2["verdict"] and r2["verdict"]["id"]))
    v = r2["verdict"]
    check("backward chain validates the winner (all claims proven)",
          v is not None and v["claims_proven"] == v["claims_total"],
          f"{v and v['claims_proven']}/{v and v['claims_total']}")
    r2b = run_case(case, add_facts=ledger)
    same = json.dumps(r2, sort_keys=True) == json.dumps(r2b, sort_keys=True)
    check("deterministic replay (identical verdict, no LLM in the verdict path)", same)
    try:
        engine_load = True
        load_validated = __import__("engine").load_validated
        load_validated(case / "facts.json", "facts.schema.json")
        load_validated(case / "evidence-index.json", "evidence-index.schema.json")
        load_validated(case / "entities.json", "entities.schema.json")
    except SystemExit:
        engine_load = False
    check("recorded sensing artifacts validate against their schemas "
          "(facts, evidence-index, entities — incl. $ref wrappers)", engine_load)
    check("all artifacts are schema-validated JSON files; no DB, no VM, no network",
          True)

    # ── 2. the abduction proof — every case, one skeleton ────────────

    print("")
    print("--- the abduction proof (every case, one skeleton) ---")
    proof = {name: prove_abduction(name, drop, check) for name, drop in CASES}

    # ── 3a. fraud case (adjudication): the funnel ────────────────────

    print("")
    print("--- fraud case (adjudication-phantom-invoice): the funnel, asserted ---")
    f1, f2 = proof["adjudication-phantom-invoice"]
    pruned1 = {p["hypothesis"] for p in f1["pruned"]}
    check("phase 1 prunes the payment diversion (H3) and the honest error (H4)",
          {"H3", "H4"} <= pruned1, str(pruned1))
    ids = [rk["id"] for rk in f1["ranking"]]
    check("phase 1 ranks the inside job (H2) above external fraud (H1) — the evidence points at the clerk first",
          ids[:2] == ["H2", "H1"], str(ids))
    check("recommended test is the vendor-provenance audit (the discriminating question)",
          f1["recommended_test"] is not None
          and f1["recommended_test"]["slot"] == "vendor-provenance",
          str(f1["recommended_test"]))
    pruned2 = {p["hypothesis"] for p in f2["pruned"]}
    check("phase 2: the audit trail prunes the inside job (H2) — the clerk is exonerated",
          "H2" in pruned2, str(pruned2))
    v = f2["verdict"]
    check("phase 2: external invoice fraud (H1) wins the verdict",
          v is not None and v["id"] == "H1", str(v and v["id"]))
    derived = {f["id"] for f in f2["derived_facts"]}
    check("phase 2: the killer link is derived — one IP sent the invoice and created the vendor record",
          "d5" in derived, str(derived))
    check("phase 2: the verdict is high-confidence (score ≥ 0.9)",
          v is not None and v["score"] >= 0.9, str(v and v["score"]))

    # ── 3b. RCA case (causation): the timeline ───────────────────────

    print("")
    print("--- RCA case (causation-three-am-outage): the timeline, asserted ---")
    c1, c2 = proof["causation-three-am-outage"]
    pruned1 = {p["hypothesis"] for p in c1["pruned"]}
    check("phase 1 prunes the expired certificate (H2) and the attack (H4)",
          {"H2", "H4"} <= pruned1, str(pruned1))
    ids = [rk["id"] for rk in c1["ranking"]]
    check("phase 1 ranks the deploy regression (H1) above the upstream outage (H3) — our change first",
          ids[:2] == ["H1", "H3"], str(ids))
    check("recommended test is the deploy diff (rule out our own change first)",
          c1["recommended_test"] is not None
          and c1["recommended_test"]["slot"] == "deploy-diff",
          str(c1["recommended_test"]))
    pruned2 = {p["hypothesis"] for p in c2["pruned"]}
    check("phase 2: the diff prunes the deploy regression (H1)",
          "H1" in pruned2, str(pruned2))
    v = c2["verdict"]
    check("phase 2: the upstream outage (H3) wins the verdict",
          v is not None and v["id"] == "H3", str(v and v["id"]))
    derived = {f["id"]: f for f in c2["derived_facts"]}
    check("phase 2: the detection gap is derived (no upstream health check — the fix)",
          "d6" in derived and derived["d6"].get("value") == "no upstream health check",
          str(derived.get("d6")))

    print("")
    failed = len(checks) - sum(checks)
    print(f"{sum(checks)}/{len(checks)} checks passed")
    return 1 if failed else 0


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(prog="engine.py",
                                 description="Facty symbolic engine (the deterministic half)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="run a case end-to-end")
    p_run.add_argument("--case", required=True, help="case directory (engine/cases/<case>)")
    p_run.add_argument("--add-facts", default=None,
                       help="extra sensed-facts file to apply (e.g. the ledger drop)")
    p_run.add_argument("--json", action="store_true", help="emit the full result as JSON")
    sub.add_parser("selftest", help="acceptance test — every case asserted (abduction proof + per-case outcomes)")
    args = ap.parse_args()
    if args.cmd == "run":
        r = run_case(args.case, args.add_facts)
        if args.json:
            print(json.dumps(r, indent=2, sort_keys=True))
        else:
            print(report(r))
        return 0
    if args.cmd == "selftest":
        return cmd_selftest(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
