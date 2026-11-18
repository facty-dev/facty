"""The canonical facty op set — the ONE layer that owns op logic.

Thinnest-possible API wrapper (ADR-0010 §4 parity by construction): the CLI
commands (`cli.py`), the `facty serve` HTTP/JSON endpoints (`serve.py`), and
the facty MCP tools (`mcp_server.py`) are all thin adapters over these
functions. Transports only marshal arguments and results — every op takes a
Client plus plain keyword args and returns a JSON-able dict. No op logic
lives in any transport layer, so there is exactly one implementation of each
op and no indirection to diverge.

Client convention: case ops set `client.ref` to the case branch themselves
(`_work_ref`); registry ops (case_init/list/show/branch/delete) operate on the
client's current ref (main). `fact_doc` is the single sensed-fact → Fact doc
shaping used everywhere.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import bundle as bundle_mod
from . import cases as cases_mod
from . import engine, ingest, sensing
from . import search as search_mod

REPO = Path(__file__).resolve().parents[2]
BUNDLES = REPO / "bundles"


def _work_ref(client, case: str | None, ref: str | None = None):
    if ref:
        client.ref = ref.replace("/", "-")
    elif case:
        client.ref = cases_mod._slug(case)
    return client


def fact_doc(f: dict) -> dict:
    """A sensed fact (polymorphic value) → a typed Fact document."""
    v = f["value"]
    doc = {"@type": "Fact", "id": f["id"], "type": f.get("type", "evidence"),
           "subject": f["subject"], "predicate": f["predicate"],
           "confidence": f.get("confidence", 1.0), "source": f.get("source", "")}
    if isinstance(v, bool):
        doc["valueBool"] = v
    elif isinstance(v, (int, float)):
        doc["valueNum"] = v
    else:
        doc["valueString"] = str(v)
    if f.get("observedAt"):
        doc["observedAt"] = f["observedAt"]
    return doc


# ── case registry (operate on the client's current ref — main) ───────────────

def case_init(client, case_id: str, bundle_dir: str, model: str | None = None) -> dict:
    return cases_mod.case_init(client, case_id, bundle_dir, model=model)


def case_list(client) -> dict:
    return {"cases": cases_mod.case_list(client)}


def case_show(client, case_id: str) -> dict:
    return cases_mod.case_show(client, case_id)


def case_branch(client, case_id: str, name: str) -> dict:
    return cases_mod.case_branch(client, case_id, name)


def case_delete(client, case_id: str) -> dict:
    return cases_mod.case_delete(client, case_id)


def bundles(client=None) -> dict:
    """The signed bundles in bundles/ — the only pack/case/demo form."""
    out = []
    if BUNDLES.is_dir():
        for d in sorted(BUNDLES.iterdir()):
            if (d / bundle_mod.MANIFEST).exists():
                m = json.loads((d / bundle_mod.MANIFEST).read_text())
                out.append({"id": d.name, "version": m["version"],
                            "signed": (d / bundle_mod.SIG).exists(),
                            "fingerprint": m.get("fingerprint", "")})
    return {"bundles": out}


# ── case ops (set the case branch as the working ref) ────────────────────────

def ingest(client, case: str | None = None, dir: str | None = None,
           source: str = "ui", ocr: bool = False, no_embed: bool = False,
           ref: str | None = None) -> dict:
    c = _work_ref(client, case, ref)
    return ingest.ingest_dir(c, Path(dir), source, ocr=ocr, embed=not no_embed)


def load_facts(client, case: str, path: str, message: str = "load facts") -> dict:
    c = _work_ref(client, case)
    n = engine.load_facts(c, Path(path), message)
    return {"loaded": n}


def sense_evidence(evidence: str, docs: list | None, rag: str | None = None,
                   client=None) -> list[dict]:
    """The ONE sensing implementation: evidence text + pack vocab → prompt →
    pydantic-ai typed output (disk-cached) → Fact docs. Induction only — never
    in the verdict path."""
    if rag and client is not None:
        hits = search_mod.search_case(client, rag)
        if hits:
            evidence = ("RELEVANT EVIDENCE CHUNKS (semantic search, induction-side only):\n"
                        + "\n\n".join(f"--- chunk {h['id']} (score {h['score']:.3f}) ---\n{h['text']}"
                                      for h in hits)
                        + "\n\n" + evidence)
    vocab = {"subjects": set(), "predicates": set()}
    for item in docs or []:
        for c in item.get("when", []) + item.get("claims", []):
            vocab["subjects"].add(c["subject"]); vocab["predicates"].add(c["predicate"])
    vocab = {k: sorted(v) for k, v in vocab.items()}
    prompt = (
        "Read the evidence below and emit a JSON object {\"facts\": [...]} — one entry per "
        "distinct fact. Each fact: {\"id\": \"fNN\", \"type\": \"case\"|\"evidence\", "
        "\"subject\", \"predicate\", \"value\" (string or boolean), \"confidence\" (0..1), "
        "\"source\": \"<file>:<line>\", \"observedAt\": \"YYYY-MM-DD\"}. "
        "CRITICAL: use ONLY these exact subject strings: " + json.dumps(vocab["subjects"]) +
        " and ONLY these exact predicate strings: " + json.dumps(vocab["predicates"]) +
        ". Do not paraphrase, hyphenate differently, or invent new terms — the symbolic "
        "engine matches these strings literally. Booleans as true/false. Numbers as numbers. "
        "Do not conclude anything — facts only.\n\nEVIDENCE:\n" + evidence
    )
    o = sensing.sense_json(prompt, getattr(sensing, "SensedFacts", None))
    if hasattr(o, "model_dump"):
        o = o.model_dump()
    facts_list = o["facts"] if isinstance(o, dict) and "facts" in o else o
    return [fact_doc(f) for f in facts_list]


def sense(client, case: str, rag: str | None = None) -> dict:
    """Sense from a case branch's extracted texts → Fact docs committed."""
    c = _work_ref(client, case)
    ext = [d for d in c.get_all_docs() if d.get("@type") == "ExtractedText"]
    origs = {d["id"]: d for d in c.get_all_docs() if d.get("@type") == "Original"}
    evidence = "\n\n".join(
        f"--- {origs.get(e['original'], {}).get('path', e['original'][:12])} ---\n{e['text']}"
        for e in sorted(ext, key=lambda d: d["id"]))
    docs = bundle_mod.Bundle.from_db(c, "case").docs
    fact_docs = sense_evidence(evidence, docs, rag=rag, client=c)
    c.insert_docs(fact_docs, message="sense")
    return {"sensed": len(fact_docs), "facts": fact_docs}


def run(client, case: str, phase: str = "1", ref: str | None = None) -> dict:
    c = _work_ref(client, case, ref)
    return engine.run_phase(c, case, phase)


def parse_goal(subject: str, predicate: str, value=None) -> dict:
    """CLI/API value string → typed goal: true/false → bool, numeric → num."""
    goal = {"subject": subject, "predicate": predicate}
    if value is not None:
        if value == "true":
            goal["valueBool"] = True
        elif value == "false":
            goal["valueBool"] = False
        else:
            try:
                goal["valueNum"] = float(value)
            except (TypeError, ValueError):
                goal["valueString"] = str(value)
    return goal


def prove(client, case: str, subject: str, predicate: str, value=None,
          ref: str | None = None) -> dict:
    c = _work_ref(client, case, ref)
    goal = parse_goal(subject, predicate, value)
    tree = engine.prove(c, goal)
    return {"provable": tree is not None, "goal": goal, **({"proof": tree} if tree else {})}


def assemble(client, case: str, goal: str | None = None, ref: str | None = None) -> dict:
    c = _work_ref(client, case, ref)
    return engine.assemble(c, case, goal)


def answer(client, case: str, question: str, value, actor: str = "human",
           ref: str | None = None) -> dict:
    c = _work_ref(client, case, ref)
    return engine.answer_question(c, question, value, actor=actor)


def turn(client, case: str, pipeline: str | None = None, choice=None, value=None,
         surface: str | None = None, actor: str = "human", all: bool = False,
         ref: str | None = None) -> dict:
    from . import turn as turn_mod  # lazy: turn.py calls back into ops.sense
    c = _work_ref(client, case, ref)
    return turn_mod.run_turn(c, case, pipeline_id=pipeline, choice=choice, value=value,
                             surface=surface, actor=actor, run_all=all)


def search(client, case: str, query: str, top_k: int = 5) -> dict:
    c = _work_ref(client, case)
    return {"hits": search_mod.search_case(c, query, top_k=top_k)}


# WOQL AST node types that mutate the graph — a `query` op must never contain
# them (the LLM's tight read surface stays read-only; writes go through the
# gated ops below/above, which commit typed artifacts).
WOQL_WRITE_OPS = {"Insert", "Delete", "Update", "Replace", "Erase",
                  "InsertTriple", "DeleteTriple", "UpdateTriple"}


def _assert_read_only(node) -> None:
    if isinstance(node, dict):
        t = node.get("@type")
        if t in WOQL_WRITE_OPS:
            raise ValueError(f"read-only query op: WOQL write operator {t!r} is not allowed "
                             "here — writes go through the gated ops (ingest/load_facts/sense/...)")
        for v in node.values():
            _assert_read_only(v)
    elif isinstance(node, list):
        for v in node:
            _assert_read_only(v)


def query(client, case: str | None = None, query: dict | None = None,
          ref: str | None = None) -> dict:
    """Read-only WOQL passthrough — the LLM's tightest read integration with
    TerminusDB (GraphRAG/dialect patterns compile to this). Any write operator
    in the AST is rejected; mutations only via the gated ops."""
    if not isinstance(query, dict):
        raise ValueError("query: expected a WOQL JSON AST object")
    _assert_read_only(query)
    c = _work_ref(client, case, ref)
    return c.query_docs(query)


# ── reads ────────────────────────────────────────────────────────────────────

_STATE_TYPES = ("Fact", "Hypothesis", "Constraint", "OpenQuestion", "Derivation",
                "Verdict", "Goal", "Snippet", "AssembledDocument", "Case",
                "Original", "Quarantine", "ExtractedText", "Pipeline", "Turn")


def state(client, case: str) -> dict:
    c = _work_ref(client, case)
    docs = c.get_all_docs()
    return {"case": case, "branch": c.ref,
            "docs": [d for d in docs if d.get("@type") in _STATE_TYPES]}


def log(client, case: str) -> dict:
    c = _work_ref(client, case)
    return {"log": c.commit_log()}


def strip_ids(x):
    """Remove generated @id keys recursively — content hash must ignore them."""
    if isinstance(x, dict):
        return {k: strip_ids(v) for k, v in x.items() if k != "@id"}
    if isinstance(x, list):
        return [strip_ids(v) for v in x]
    return x


def verdict(client, case: str | None = None) -> dict:
    """Verdict docs, @id-stripped and ranking-sorted (stable hashing)."""
    c = _work_ref(client, case)
    vs = [d for d in c.get_all_docs() if d.get("@type") == "Verdict"]
    vs = strip_ids(sorted(vs, key=lambda d: d["id"]))
    for v in vs:
        if isinstance(v.get("ranking"), list):
            v["ranking"] = sorted(v["ranking"], key=lambda r: str(r.get("hypothesis")))
    return {"verdicts": vs}
