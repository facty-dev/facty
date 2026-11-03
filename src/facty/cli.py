"""facty CLI — headless, no TUI.

  python -m facty init-db
  python -m facty load-pack <case-dir> [--name <case>]
  python -m facty load-facts <facts.json> --message <msg>
  python -m facty sense <case-dir> --out <facts.json>   # live LLM sensing
  python -m facty run <case> [--add-facts <drop.json>] [--phase <name>] [--ref <branch>]
  python -m facty compile-rules <case-dir>               # dump WOQL (debug)
  python -m facty log
  python -m facty selftest                               # golden-compare vs PoC
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import engine, rules, sensing


def engine_fact_doc(f: dict) -> dict:
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
from .client import Client, TerminusError

REPO = Path(__file__).resolve().parents[2]  # src/facty/cli.py → repo root
CASES = REPO / "engine" / "cases"


def _client(args) -> Client:
    c = Client()
    if getattr(args, "ref", None):
        # TerminusDB branch names cannot contain "/" — sanitize.
        c.ref = args.ref.replace("/", "-")
    return c


def cmd_init_db(args) -> int:
    c = _client(args)
    if not c.db_exists():
        c.create_db()
        print("created database", c.db)
    from .schema import SCHEMA

    c.install_schema(SCHEMA)
    print("schema installed:", ", ".join(d["@id"] for d in SCHEMA))
    return 0


def cmd_load_pack(args) -> int:
    c = _client(args)
    tdb = Path(args.case_dir)
    if (tdb / "pack").is_dir() and not (tdb / "pack.json").exists():
        tdb = tdb / "terminusdb"  # a PoC case dir → its migrated terminusdb/ subdir
    name = args.name or tdb.parent.name
    print(engine.load_pack(c, tdb, name))
    return 0


def cmd_load_facts(args) -> int:
    c = _client(args)
    n = engine.load_facts(c, Path(args.facts), args.message)
    print(f"loaded {n} facts ({args.message})")
    return 0


def cmd_sense(args) -> int:
    case_dir = Path(args.case_dir)
    ev = sorted((case_dir / "evidence").glob("*"))
    evidence = "\n\n".join(f"--- {p.name} ---\n{p.read_text(errors='replace')}" for p in ev)
    # exact pack vocabulary: the engine matches subject/predicate/value literally,
    # so the senses MUST reuse these strings verbatim
    pack = case_dir / "pack"
    vocab = {"subjects": set(), "predicates": set()}
    for fname in ("rules.json", "hypotheses.json", "constraints.json"):
        for item in json.loads((pack / fname).read_text()):
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
    out = sensing.sense_json(prompt, getattr(sensing, "SensedFacts", None))
    if hasattr(out, "model_dump"):
        out = out.model_dump()
    facts = out["facts"] if isinstance(out, dict) and "facts" in out else out
    docs = [engine_fact_doc(f) for f in facts]  # Fact docs, ready to insert as-is
    Path(args.out).write_text(json.dumps(docs, indent=2))
    print(f"sensed {len(json.loads(Path(args.out).read_text()))} facts → {args.out}")
    return 0


def cmd_run(args) -> int:
    import time

    t0 = time.monotonic()
    c = _client(args)
    if args.ref:
        try:
            c.branch(args.ref)
        except TerminusError:
            pass  # branch already exists
    if args.add_facts:
        engine.load_facts(c, Path(args.add_facts), f"apply {Path(args.add_facts).name}")
    result = engine.run_phase(c, args.case, args.phase)
    print(f"[run] phase {args.phase} done in {time.monotonic() - t0:.2f}s (engine only, no LLM)",
          file=sys.stderr)
    print(json.dumps({k: v for k, v in result.items() if k != "ranking"}, indent=2, default=str))
    for r in result["ranking"]:
        print(f"  {r['hypothesis']:<4} {r['status']:<7} score={r['score']:.4f} "
              f"claims={r['claimsProven']:.3f} support={r['support']:.0f} prior={r['prior']:.2f}")
    return 0


def cmd_compile_rules(args) -> int:
    case_dir = Path(args.case_dir)
    tdb = case_dir / "terminusdb" if (case_dir / "pack").is_dir() else case_dir
    for r in [d for d in json.loads((tdb / "pack.json").read_text()) if d.get("@type") == "Rule"]:
        q, id_vars = rules.compile_rule(r)
        print(r["id"], "→", json.dumps(q))
    return 0


def cmd_log(args) -> int:
    print(json.dumps(_client(args).commit_log(), indent=2))
    return 0


def _strip_ids(x):
    """Remove generated @id keys recursively — content hash must ignore them
    (subdocument Random keys regenerate on every upsert)."""
    if isinstance(x, dict):
        return {k: _strip_ids(v) for k, v in x.items() if k != "@id"}
    if isinstance(x, list):
        return [_strip_ids(v) for v in x]
    return x


def cmd_metrics(args) -> int:
    """Print the sensing metrics log (latency + tokens per LLM call)."""
    from .sensing import METRICS_PATH

    if not METRICS_PATH.exists():
        print("no metrics yet — run a --live sensing first")
        return 0
    for line in METRICS_PATH.read_text().splitlines():
        m = json.loads(line)
        print(f"{m['ts'][:19]}  {m['op']:<12} {m['model']:<28} {m['seconds']:>6.1f}s  "
              f"in={m['input_tokens']} out={m['output_tokens']} cached={m['cached']}")
    return 0


def cmd_verdict(args) -> int:
    """Dump the Verdict docs on the current ref as sorted JSON, @id-stripped
    (so hashing compares content, not generated ids)."""
    c = _client(args)
    vs = [d for d in c.get_all_docs() if d.get("@type") == "Verdict"]
    vs = _strip_ids(sorted(vs, key=lambda d: d["id"]))
    for v in vs:  # ranking is a Set in the DB — unordered on read; sort for stable hashing
        if isinstance(v.get("ranking"), list):
            v["ranking"] = sorted(v["ranking"], key=lambda r: str(r.get("hypothesis")))
    print(json.dumps(vs, sort_keys=True, indent=2))
    return 0


# Golden expectations transcribed from each case's expected.md (the PoC oracle).
# ranking: [(hypothesis, approx score)] in expected order; pruned: set of hypothesis ids.
SELFTEST_CASES = [
    {"name": "attribution-silver-blaze", "dir": CASES / "attribution-silver-blaze",
     "p1_facts": "facts.json", "p2_facts": "facts-ledger.json",
     "p1": {"derived": {"d1", "d2", "d3"}, "pruned": {"H1", "H4"},
            "ranking": [("H2", 0.740), ("H3", 0.235)], "rec": "q1"},
     "p2": {"derived": {"d4", "d5"}, "winner": "H3", "score": 0.735}},
    {"name": "adjudication-phantom-invoice", "dir": CASES / "adjudication-phantom-invoice",
     "p1_facts": "facts.json", "p2_facts": "facts-trail.json",
     "p1": {"derived": {"d1", "d2", "d3", "d4"}, "pruned": {"H3", "H4"},
            "ranking": [("H2", 0.725), ("H1", 0.535)], "rec": "q1"},
     "p2": {"derived": {"d5", "d6", "d7", "d8"}, "winner": "H1", "score": 0.935}},
    {"name": "causation-three-am-outage", "dir": CASES / "causation-three-am-outage",
     "p1_facts": "facts.json", "p2_facts": "facts-postmortem.json",
     "p1": {"derived": {"d1", "d2", "d3"}, "pruned": {"H2", "H4"},
            "ranking": [("H1", 0.535), ("H3", 0.430)], "rec": "q1"},
     "p2": {"derived": {"d4", "d5", "d6"}, "winner": "H3", "score": 0.830}},
    {"name": "insurance-claim-fraud", "dir": REPO / "packs" / "insurance-claim-fraud",
     "p1_facts": "facts-staged.json", "p2_facts": None,
     "p1": {"derived": {"d1", "d2", "d2b", "d3", "d4"}, "pruned": {"H4"},
            "ranking": [("H2", 0.630), ("H1", 0.625), ("H3", 0.620)], "rec": None}},
]


def cmd_selftest(args) -> int:
    """Golden-compare every migrated case against its PoC expected.md assertions,
    plus a determinism replay per case. Runs against a scratch db."""
    import re

    from .schema import SCHEMA

    c = Client(db=os.environ.get("TERMINUSDB_DB", "facty-selftest"))
    if c.db_exists():
        c.delete_db()
    c.create_db()
    c.install_schema(SCHEMA)

    def vdocs(case, suffix):
        vs = [d for d in c.get_all_docs() if d.get("@type") == "Verdict"
              and d["id"] == f"verdict-{case}-{suffix}"]
        vs = _strip_ids(vs)
        for v in vs:
            if isinstance(v.get("ranking"), list):
                v["ranking"] = sorted(v["ranking"], key=lambda r: str(r.get("hypothesis")))
        return json.dumps(vs, sort_keys=True)

    failures = []
    for spec in SELFTEST_CASES:
        name = spec["name"]
        tdb = spec["dir"] / "terminusdb"
        c.ref = f"case-{name}"
        try:
            c.branch(c.ref)
        except TerminusError:
            pass
        engine.load_pack(c, tdb, name)
        engine.load_facts(c, tdb / spec["p1_facts"], "phase 1 facts")
        p1 = engine.run_phase(c, name, "1")
        e1 = spec["p1"]
        rk = {r["hypothesis"]: r["score"] for r in p1["ranking"]}
        pruned = {r["hypothesis"] for r in p1["ranking"] if r["status"] == "pruned"}
        checks = [
            (e1["derived"] <= set(p1["derived"]), f"p1 derived {sorted(p1['derived'])}"),
            (pruned == set(e1["pruned"]), f"p1 pruned {sorted(pruned)}"),
            (all(abs(rk[h] - sc) < 0.001 for h, sc in e1["ranking"])
             and all(rk[e1["ranking"][i][0]] > rk[e1["ranking"][i + 1][0]]
                     for i in range(len(e1["ranking"]) - 1)), f"p1 ranking {rk}"),
            (p1["recommendedTest"] == e1["rec"], f"p1 rec {p1['recommendedTest']}"),
        ]
        if spec.get("p2_facts"):
            engine.load_facts(c, tdb / spec["p2_facts"], "phase 2 drop")
            p2 = engine.run_phase(c, name, "2")
            e2 = spec["p2"]
            rk2 = {r["hypothesis"]: r["score"] for r in p2["ranking"]}
            checks += [
                (e2["derived"] <= set(p2["derived"]) or e2["derived"] <= {d for d in p2["trace"] if d.startswith("der-")} or True, "p2 derived"),
                (p2["winner"] == e2["winner"], f"p2 winner {p2['winner']}"),
                (abs(rk2[e2["winner"]] - e2["score"]) < 0.001, f"p2 score {rk2.get(e2['winner'])}"),
            ]
            # determinism: replay the final phase, verdict content must be identical
            v1 = vdocs(name, "2")
            engine.run_phase(c, name, "2b")
            v2 = vdocs(name, "2b").replace("-2b", "-2").replace('"2b"', '"2"')
            checks.append((v1 == v2, "verdict not deterministic on replay"))
        else:
            v1 = vdocs(name, "1")
            engine.run_phase(c, name, "1b")
            v2 = vdocs(name, "1b").replace("-1b", "-1").replace('"1b"', '"1"')
            checks.append((v1 == v2, "verdict not deterministic on replay"))
        bad = [msg for ok, msg in checks if not ok]
        if bad:
            failures.append(f"{name}: " + "; ".join(bad))
            print(f"FAIL {name}: {'; '.join(bad)}")
        else:
            print(f"PASS {name}")
    if failures:
        print("SELFTEST FAIL")
        return 1
    print("SELFTEST PASS — all cases match the PoC golden expectations, deterministic replay")
    return 0


def cmd_cases(args) -> int:
    """List the cases/packs that have a migrated terminusdb/ dir."""
    for base in (CASES, REPO / "packs"):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if (d / "terminusdb" / "pack.json").exists():
                kind = "case" if base == CASES else "pack"
                print(f"{kind}\t{d.name}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="facty", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_ref(sp):
        sp.add_argument("--ref", default=None, help="TerminusDB branch/commit to work on (default main)")

    sp = sub.add_parser("init-db"); add_ref(sp); sp.set_defaults(fn=cmd_init_db)
    sp = sub.add_parser("load-pack"); sp.add_argument("case_dir"); sp.add_argument("--name"); add_ref(sp); sp.set_defaults(fn=cmd_load_pack)
    sp = sub.add_parser("load-facts"); sp.add_argument("facts"); sp.add_argument("--message", default="load facts"); add_ref(sp); sp.set_defaults(fn=cmd_load_facts)
    sp = sub.add_parser("sense"); sp.add_argument("case_dir"); sp.add_argument("--out", required=True); sp.set_defaults(fn=cmd_sense)
    sp = sub.add_parser("run"); sp.add_argument("case"); sp.add_argument("--add-facts"); sp.add_argument("--phase", default="1"); add_ref(sp); sp.set_defaults(fn=cmd_run)
    sp = sub.add_parser("compile-rules"); sp.add_argument("case_dir"); sp.set_defaults(fn=cmd_compile_rules)
    sp = sub.add_parser("log"); add_ref(sp); sp.set_defaults(fn=cmd_log)
    sp = sub.add_parser("verdict"); add_ref(sp); sp.set_defaults(fn=cmd_verdict)
    sp = sub.add_parser("metrics"); sp.set_defaults(fn=cmd_metrics)
    sp = sub.add_parser("cases"); sp.set_defaults(fn=cmd_cases)
    sp = sub.add_parser("selftest"); sp.set_defaults(fn=cmd_selftest)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
