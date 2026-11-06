"""The deterministic engine: chain → prune → rank → questions → verdict.

Pure functions over TerminusDB query results. No LLM, no clock, no randomness
in this module — same artifacts in → byte-identical verdict out. Sensing (the
LLM half) happens only in sensing.py, outside this path.

Score (identical to the PoC engine, engine/engine.py):
    score = 0.6 * claims_proven_ratio + 0.3 * min(support, 3)/3 + 0.1 * prior
"""

from __future__ import annotations

import json
from pathlib import Path

from . import rules, woql

W_CLAIMS, W_SUPPORT, W_PRIOR = 0.6, 0.3, 0.1


# ── loaders: pack files are already TerminusDB JSON-LD → plain inserts ──────

def load_facts(client, facts_path: Path, message: str, embed: bool = True) -> int:
    docs = json.loads(Path(facts_path).read_text())
    client.insert_docs(docs, message=message)
    if embed:
        # Embed fact strings on the BYO-key path (disk-cached) and record the
        # vector hash on the Fact doc — so the deterministic engine can later
        # flag semantic contradiction candidates WITHOUT any live model call
        # (replays read the recorded vectors; offline runs replay byte-identical).
        from . import search
        texts = [f'{d.get("subject")} {d.get("predicate")} = '
                 f'{d.get("valueString", d.get("valueBool", d.get("valueNum", "")))}'
                 for d in docs]
        embs = search.embed_texts(texts)
        updates = []
        for d, emb in zip(docs, embs):
            if emb:
                d["embeddingModel"] = search.EMBED_MODEL
                d["embeddingDim"] = len(emb)
                d["embeddingSha256"] = search.store_embedding(emb, search.EMBED_MODEL)
                updates.append(d)
        if updates:
            client.insert_docs(updates, message=f"{message} (embeddings)")
    return len(docs)


def _goal_key(g: dict) -> str:
    v = g.get("valueString", g.get("valueBool", g.get("valueNum", g.get("var", "*"))))
    return f"{g.get('subject')}|{g.get('predicate')}|{v}"


def _template_matches_goal(t: dict, goal: dict) -> bool:
    if t.get("subject") != goal.get("subject") or t.get("predicate") != goal.get("predicate"):
        return False
    for k in ("valueString", "valueBool", "valueNum"):
        if k in goal:
            return t.get(k) == goal[k]
    return True  # goal without value = existence query


def prove(client, goal: dict, seen: set | None = None, depth: int = 0) -> dict | None:
    """Backward chaining (GOFAI deduction): prove a goal condition.

    1. entailed directly by a fact → leaf proof
    2. else by a rule whose derive action produces the goal → recursively prove
       the rule's premises → proof tree (mirrors the Derivation docs the
       forward pass writes). Deterministic: rules sorted by id, depth-capped.
    Returns a proof tree dict, or None if unprovable."""
    seen = seen if seen is not None else set()
    key = _goal_key(goal)
    if depth > 10 or key in seen:
        return None
    seen = seen | {key}
    if any(k in goal for k in ("valueString", "valueBool", "valueNum")):
        hit = _exists(client, rules.compile_claim(goal))
    else:  # existence goal (no value): match any value
        hit = _exists(client, woql.select(["G"], woql.fact_pattern(
            "G", subject=goal.get("subject"), predicate=goal.get("predicate"))))
    if hit:
        facts = [d for d in _docs_of(client, "Fact")
                 if d.get("subject") == goal.get("subject")
                 and d.get("predicate") == goal.get("predicate")]
        fid = facts[0]["id"] if facts else "?"
        return {"goal": {k: goal[k] for k in ("subject", "predicate") if k in goal},
                "by": "fact", "fact": fid, "source": next((d.get("source") for d in facts), "")}
    for r in sorted(_docs_of(client, "Rule"), key=lambda d: d["id"]):
        for action in r.get("then", []):
            if action.get("op") != "derive":
                continue
            f = action.get("fact")
            if isinstance(f, str):
                f = client.get_doc(f)
            if not _template_matches_goal(f, goal):
                continue
            premises = [prove(client, c, seen, depth + 1) for c in r.get("when", [])]
            if all(premises):
                return {"goal": {k: goal[k] for k in ("subject", "predicate") if k in goal},
                        "by": "rule", "rule": r["id"], "premises": premises}
    return None


def semantic_contradictions(client, threshold: float = 0.93) -> list[dict]:
    """Deterministic-side semantic search (logged, ADR-0009): pairwise cosine
    over the RECORDED fact embeddings; near-duplicate facts with conflicting
    values are contradiction candidates. No LLM call — vectors come from the
    case record (object store). Returns [{a, b, score}]."""
    from . import search
    from .ingest import DATA_DIR
    facts = [d for d in _docs_of(client, "Fact") if d.get("embeddingSha256")]
    objdir = DATA_DIR / "objects"
    vecs = {}
    for d in facts:
        blob = objdir / d["embeddingSha256"]
        if not blob.exists():
            continue
        rec = json.loads(blob.read_text())
        vec = rec["embedding"] if isinstance(rec, dict) and "embedding" in rec else rec
        # portability: only compare within the same model AND dim
        if d.get("embeddingDim") not in (None, len(vec)):
            continue
        vecs[d["id"]] = (d.get("embeddingModel"), vec)
    out = []
    ids = sorted(vecs)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if vecs[a][0] != vecs[b][0]:
                continue  # different embedding models are not comparable
            fa, fb = next(d for d in facts if d["id"] == a), next(d for d in facts if d["id"] == b)
            va = fa.get("valueString", fa.get("valueBool", fa.get("valueNum")))
            vb = fb.get("valueString", fb.get("valueBool", fb.get("valueNum")))
            if va == vb:
                continue  # same value — not a contradiction
            score = search.cosine(vecs[a][1], vecs[b][1])
            if score >= threshold:
                out.append({"a": a, "b": b, "score": round(score, 6)})
    return sorted(out, key=lambda c: (-c["score"], c["a"], c["b"]))


def fact_from_template(t: dict, rule_id: str = "") -> dict:
    """Instantiate a derive action's FactTemplate subdocument as a real Fact."""
    doc = {"@type": "Fact", "id": t["id"], "type": t.get("type", "derived"),
           "subject": t["subject"], "predicate": t["predicate"],
           "confidence": t.get("confidence", 1.0), "source": f"rule:{rule_id}"}
    for k in ("valueString", "valueBool", "valueNum"):
        if k in t:
            doc[k] = t[k]
    return doc


# ── queries over the store ───────────────────────────────────────────────────

def _docs_of(client, cls: str) -> list[dict]:
    return [d for d in client.get_all_docs() if d.get("@type") == cls]


def _exists(client, query: dict) -> bool:
    return bool(client.query_docs(query).get("bindings"))


# ── the loop ─────────────────────────────────────────────────────────────────

def forward_chain(client) -> tuple[list[str], list[str]]:
    """Run rules to fixpoint. Returns (derived fact ids, raise events)."""
    rule_docs = sorted(_docs_of(client, "Rule"), key=lambda d: d["id"])  # deterministic order
    fact_ids = {d["id"] for d in _docs_of(client, "Fact")}
    deriv_ids = {d["id"] for d in _docs_of(client, "Derivation")}
    derived: list[str] = []
    raises: list[str] = []
    changed = True
    while changed:
        changed = False
        for r in rule_docs:
            query, id_vars = rules.compile_rule(r)
            for row in client.query_docs(query).get("bindings", []):
                premises = [row[v].get("@value") if isinstance(row[v], dict) else row[v]
                            for v in id_vars if v in row]
                for action in r.get("then", []):
                    op = action["op"]
                    if op == "derive":
                        f = action["fact"]
                        if isinstance(f, str):  # tolerate a reference read
                            f = client.get_doc(f)
                        if f["id"] in fact_ids:
                            continue
                        client.insert_docs([fact_from_template(f, r["id"])], message=f"derive {f['id']} by {r['id']}")
                        # deterministic derivation id: same rule + same premises →
                        # same id, so re-runs are idempotent (no accumulating trace)
                        import hashlib
                        did = "der-" + hashlib.sha1(
                            f"{r['id']}:{','.join(sorted(premises))}".encode()).hexdigest()[:12]
                        if did not in deriv_ids:
                            client.insert_docs([{
                                "@type": "Derivation", "id": did, "fact": f["id"],
                                "rule": r["id"], "via": premises,
                            }], message=f"trace {did}")
                            deriv_ids.add(did)
                        fact_ids.add(f["id"])
                        derived.append(f["id"])
                        changed = True
                    elif op == "raise":
                        raises.append(f"raise {','.join(action['hypotheses'])} by {r['id']}")
                    elif op == "open":
                        q = action["question"]
                        if isinstance(q, str):
                            q = client.get_doc(q)
                        oq = {"@type": "OpenQuestion", "id": q["id"], "text": q["text"], "slot": q["slot"],
                              "mandatory": q.get("mandatory", False), "priority": q.get("priority", 99),
                              "status": "open", "raisedBy": q.get("raisedBy", f"rule:{r['id']}"),
                              "discriminates": q.get("discriminates", [])}
                        client.insert_docs([oq], message=f"open {q['id']} by {r['id']}")
                        raises.append(f"open {q['id']} by {r['id']}")
    return derived, raises


def apply_constraints(client) -> tuple[list[str], dict[str, int]]:
    """Eliminate/support. Returns (pruned events, {hypothesis: support})."""
    hyps = {h["id"]: h for h in sorted(_docs_of(client, "Hypothesis"), key=lambda d: d["id"])}
    # recompute from scratch each run (like the PoC): reset status so replays
    # are deterministic regardless of persisted state
    for h in hyps.values():
        h["status"] = "open"
        h.pop("prunedBy", None)
        h.pop("support", None)
    support = {hid: 0 for hid in hyps}
    events: list[str] = []
    for c in sorted(_docs_of(client, "Constraint"), key=lambda d: d["id"]):
        h = hyps.get(c["hypothesis"])
        if h is None or h.get("status") == "pruned":
            continue
        hit = _exists(client, rules.compile_constraint_when(c.get("when", [])))
        if not hit:
            continue
        if c["type"] == "eliminate":
            h["status"] = "pruned"
            h["prunedBy"] = c["id"]
            client.insert_docs([h], message=f"prune {h['id']} by {c['id']}")
            events.append(f"pruned {h['id']} by {c['id']}")
        elif c["type"] == "support":
            cv = next((c[k] for k in ("valueNum", "valueString", "valueBool") if k in c), None)
            if c.get("field") and h.get(c["field"]) != cv:
                continue
            support[h["id"]] = support.get(h["id"], 0) + 1
            h["support"] = float(support[h["id"]])
            client.insert_docs([h], message=f"support {h['id']} by {c['id']}")
            events.append(f"support {h['id']} by {c['id']}")
    for h in hyps.values():  # persist recomputed status/support (upsert)
        client.insert_docs([h], message="constraint recompute")
    return events, support


def rank_hypotheses(client, support: dict[str, int]) -> list[dict]:
    """score = 0.6*claims_proven + 0.3*min(support,3)/3 + 0.1*prior, desc."""
    ranking = []
    for h in _docs_of(client, "Hypothesis"):
        if h.get("status") == "pruned":
            ranking.append({"hypothesis": h["id"], "status": "pruned",
                            "score": 0.0, "claimsProven": 0.0,
                            "support": float(support.get(h["id"], 0)),
                            "prior": float(h.get("prior", 0.0))})
            continue
        claims = h.get("claims", [])
        proven = sum(1 for c in claims if _exists(client, rules.compile_claim(c)))
        ratio = proven / len(claims) if claims else 0.0
        sup = float(support.get(h["id"], 0))
        prior = float(h.get("prior", 0.0))
        score = W_CLAIMS * ratio + W_SUPPORT * min(sup, 3) / 3 + W_PRIOR * prior
        ranking.append({"hypothesis": h["id"], "status": "open", "score": score,
                        "claimsProven": ratio, "support": sup, "prior": prior})
    ranking.sort(key=lambda r: (-r["score"], r["hypothesis"]))
    return ranking


def rank_questions(client, alive: set[str]) -> list[dict]:
    qs = [q for q in _docs_of(client, "OpenQuestion") if q.get("status") == "open"]
    out = []
    for q in qs:
        alive_disc = len(set(q.get("discriminates", [])) & alive)
        out.append({**q, "_alive": alive_disc})
    out.sort(key=lambda q: (-q["_alive"], q.get("priority", 99), q["id"]))
    return out


def run_phase(client, case: str, phase: str) -> dict:
    """One deterministic pass: chain → prune → rank → questions → verdict doc."""
    derived, raises = forward_chain(client)
    events, support = apply_constraints(client)
    # trace is a pure function of DB state → re-runs produce byte-identical verdicts
    trace = sorted(d["id"] for d in _docs_of(client, "Derivation"))
    trace += sorted(f"pruned {h['id']} by {h['prunedBy']}"
                    for h in _docs_of(client, "Hypothesis") if h.get("status") == "pruned")
    trace += sorted(set(raises))
    ranking = rank_hypotheses(client, support)
    alive = {r["hypothesis"] for r in ranking if r["status"] == "open"}
    questions = rank_questions(client, alive)
    recommended = questions[0]["id"] if questions else None
    winner = ranking[0]["hypothesis"] if len(alive) == 1 else None
    # deterministic-side semantic search (logged, ADR-0009): contradiction
    # candidates from recorded embeddings — trace events + queryable Facts
    contradictions = semantic_contradictions(client)
    for c in contradictions:
        client.insert_docs([{"@type": "Fact", "id": f"sc-{c['a']}-{c['b']}",
                             "type": "derived", "subject": c["a"],
                             "predicate": "semanticContradictionWith",
                             "valueString": c["b"], "confidence": c["score"],
                             "source": "engine:semantic"}],
                           message=f"semantic contradiction candidate {c['a']}~{c['b']}")
    trace += sorted(f"semantic-contradiction-candidate {c['a']}~{c['b']} ({c['score']:.3f})"
                    for c in contradictions)
    events += [f"semantic-contradiction-candidate {c['a']}~{c['b']} ({c['score']:.3f})"
               for c in contradictions]
    verdict = {
        "@type": "Verdict",
        "id": f"verdict-{case}-{phase}",
        "case": case,
        "phase": phase,
        **({"winner": winner} if winner else {}),
        "ranking": [{
            "@type": "Ranking", "hypothesis": r["hypothesis"], "status": r["status"],
            "score": round(r["score"], 6), "claimsProven": round(r["claimsProven"], 6),
            "support": round(r["support"], 6), "prior": round(r["prior"], 6),
        } for r in ranking],
        "questions": [q["id"] for q in questions],
        **({"recommendedTest": recommended} if recommended else {}),
        "trace": trace,
    }
    client.insert_docs([verdict], message=f"verdict {case} {phase}")
    return {"derived": derived, "ranking": ranking, "recommendedTest": recommended,
            "winner": winner, "verdict_id": verdict["id"], "events": events,
            "trace": trace}
