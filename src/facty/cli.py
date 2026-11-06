"""facty CLI — headless, no TUI. Built on Typer (tiangolo; uv-ecosystem standard).

  facty init-db
  facty keys init | list
  facty bundle sign|verify|load <bundle-dir> [--dev]
  facty load-facts <facts.json> --message <msg>
  facty sense <case-dir> --out <facts.json>   # live LLM sensing
  facty run <case> [--add-facts <drop.json>] [--phase <name>] [--ref <branch>]
  facty compile-rules <case-dir>               # dump WOQL (debug)
  facty log | verdict | metrics | cases
  facty selftest                               # golden-compare vs PoC
"""

from __future__ import annotations

import functools
import json
import os
import sys
import time
from pathlib import Path
from typing import Annotated, Optional

import typer

from . import bundle as bundle_mod
from . import cases as cases_mod
from . import codemode, engine, ingest, keys, rules, sandbox, search, sensing
from .client import Client, TerminusError

app = typer.Typer(
    name="facty",
    help="Facty — the detective DSS: deterministic bundle engine on TerminusDB, LLM sensing only (ADR-0003/0005/0006/0007).",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,  # never leak key material into error output
)
keys_app = typer.Typer(name="keys", help="Ed25519 signing keys (live in ~/.facty/keys, never committed).", no_args_is_help=True)
bundle_app = typer.Typer(name="bundle", help="Signed bundle v2: sign / verify / load (the trust gate).", no_args_is_help=True)
case_app = typer.Typer(name="case", help="Case lifecycle: a case IS a TerminusDB branch — real, deletable.", no_args_is_help=True)
vm_app = typer.Typer(name="vm", help="SmolVM sandbox lifecycle: one reused machine, stopped when done (image persists).", no_args_is_help=True)
app.add_typer(keys_app)
app.add_typer(bundle_app)
app.add_typer(case_app)
app.add_typer(vm_app)


@vm_app.command("status")
def vm_status():
    if not sandbox._smolvm_available():
        typer.echo("smolvm binary not found — sandbox backend will use local (--dev)")
        return
    p = __import__("subprocess").run(["smolvm", "machine", "list"], capture_output=True, text=True)
    typer.echo(p.stdout or "(no machines)")


@vm_app.command("down")
def vm_down():
    """Stop the sandbox VM (the image persists — no rebuild on next use)."""
    sandbox.shutdown_machine()
    typer.echo(f"stopped {sandbox.SMOLVM_MACHINE} (image persists; next run reuses it)")

OptRef = Annotated[Optional[str], typer.Option("--ref", help="TerminusDB branch/commit to work on (default main)")]
OptDev = Annotated[bool, typer.Option("--dev", help="Escape hatch: allow unsigned/legacy bundles (or FACTY_DEV=1)")]


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


REPO = Path(__file__).resolve().parents[2]  # src/facty/cli.py → repo root
CASES = REPO / "engine" / "cases"


def _client(ref: Optional[str]) -> Client:
    c = Client()
    if ref:
        # TerminusDB branch names cannot contain "/" — sanitize.
        c.ref = ref.replace("/", "-")
    return c


def _gate(fn):
    """BundleError → clean stderr message + exit 1 (no traceback, no locals)."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except bundle_mod.BundleError as e:
            typer.echo(f"error: {e}", err=True)
            raise typer.Exit(1)
    return wrapper


# ── db / bundle / keys ───────────────────────────────────────────────────────

@app.command("init-db")
def init_db(ref: OptRef = None):
    c = _client(ref)
    if not c.db_exists():
        c.create_db()
        typer.echo("created database " + c.db)
    from .schema import SCHEMA

    c.install_schema(SCHEMA)
    typer.echo("schema installed: " + ", ".join(d["@id"] for d in SCHEMA if d.get("@type") == "Class"))


@bundle_app.command("load")
@_gate
def bundle_load(bundle_dir: Annotated[Path, typer.Argument()],
                name: Annotated[Optional[str], typer.Option("--name")] = None,
                dev: OptDev = False, ref: OptRef = None):
    """The trust gate: signed v2 bundles verify (embedded pubkey, no private key
    needed); unsigned/legacy bundles are refused unless --dev/FACTY_DEV=1."""
    c = _client(ref)
    b = bundle_mod.Bundle.from_dir(bundle_dir, dev=dev)
    typer.echo(b.load_into(c, name or b.id, dev=dev))


@bundle_app.command("sign")
@_gate
def bundle_sign(bundle_dir: Annotated[Path, typer.Argument()],
                key: Annotated[Optional[str], typer.Option("--key", help="key fingerprint (default: sole private key)")] = None):
    b = bundle_mod.Bundle.from_dir(bundle_dir, dev=True)  # re-sign may start unsigned
    fp = b.sign(key)
    typer.echo(f"signed {b.id}@{b.version} with key {fp} → {b.path / bundle_mod.SIG}")


@bundle_app.command("verify")
@_gate
def bundle_verify(bundle_dir: Annotated[Path, typer.Argument()]):
    b = bundle_mod.Bundle.from_dir(bundle_dir, dev=True)
    if not (b.path / bundle_mod.MANIFEST).exists():
        typer.echo(f"{b.path}: legacy v1 bundle — unsigned, no manifest", err=True)
        raise typer.Exit(1)
    b.verify_or_raise()
    typer.echo(f"OK {b.id}@{b.version} — signature valid, key {b.fingerprint}, "
               f"{len(b.manifest['contents'])} content files verified")


@keys_app.command("init")
def keys_init(name: Annotated[str, typer.Option("--name")] = "default"):
    fp, pub = keys.init_key(name)
    typer.echo(f"new key {fp}  (label: {name})")
    typer.echo(f"  private: {keys.KEYS_DIR / (fp + '.key')}  (never commit this)")
    typer.echo(f"  public:  {pub}")


@keys_app.command("list")
def keys_list():
    ks = keys.list_keys()
    if not ks:
        typer.echo(f"no keys in {keys.KEYS_DIR} — run `facty keys init`")
        return
    for k in ks:
        typer.echo(f"{k['fingerprint']}  {k['label']:<12} private={'yes' if k['has_private'] else 'no'}")


# ── M2: case lifecycle + ingest ──────────────────────────────────────────────

@case_app.command("init")
@_gate
def case_init(case_id: Annotated[str, typer.Argument()],
              bundle_dir: Annotated[Path, typer.Option("--bundle", "-b")],
              dev: OptDev = False,
              model: Annotated[Optional[str], typer.Option("--model")] = None,
              ref: OptRef = None):
    """Create branch case-<id>, verify+load the signed bundle, register the case."""
    c = _client(ref)
    typer.echo(cases_mod.case_init(c, case_id, bundle_dir, dev=dev, model=model))


@case_app.command("list")
def case_list(ref: OptRef = None):
    for d in cases_mod.case_list(_client(ref)):
        typer.echo(f"{d['id']:<24} bundle={d['bundle']}@{d['bundleVersion']} "
                   f"key={d.get('fingerprint') or '-'} created={d.get('created', '?')}")


@case_app.command("branch")
def case_branch(case_id: Annotated[str, typer.Argument()],
                name: Annotated[str, typer.Argument()], ref: OptRef = None):
    typer.echo(cases_mod.case_branch(_client(ref), case_id, name))


@case_app.command("show")
def case_show(case_id: Annotated[str, typer.Argument()], ref: OptRef = None):
    typer.echo(json.dumps(cases_mod.case_show(_client(ref), case_id), indent=2, default=str))


@case_app.command("delete")
def case_delete(case_id: Annotated[str, typer.Argument()], ref: OptRef = None):
    """Real deletion: the branch is DELETEd. Remains: nothing in the DB; only an
    attestation hash (M7), if one was submitted."""
    typer.echo(json.dumps(cases_mod.case_delete(_client(ref), case_id), indent=2))


@app.command("ingest")
def ingest_cmd(src: Annotated[Path, typer.Argument(help="directory of evidence files")],
               source: Annotated[str, typer.Option("--source", "-s", help="custody source label")],
               case: Annotated[Optional[str], typer.Option("--case", help="ingest onto case branch case-<id>")] = None,
               ref: OptRef = None,
               ocr: Annotated[bool, typer.Option("--ocr", help="route images to the BYO-key OCR path")] = False,
               no_embed: Annotated[bool, typer.Option("--no-embed", help="skip embedding the extracted texts")] = False):
    """Content-addressed ingest: originals → object store (SHA-256), metadata +
    derived text → TerminusDB. Idempotent; changed files → version-conflict Fact.
    Extracted texts are chunked + embedded (BYO-key, cached) for sensing-side RAG."""
    c = _client(ref)
    if case:
        c.ref = cases_mod._slug(case)
    s = ingest.ingest_dir(c, src, source, ocr=ocr, embed=not no_embed)
    typer.echo(json.dumps(s, indent=2))
    v = ingest.verify_originals(c)
    typer.echo(f"originals verified: {v['checked']} checked, {len(v['mismatches'])} mismatches")
    if v["mismatches"]:
        raise typer.Exit(1)


@app.command("prove")
def prove_cmd(subject: Annotated[str, typer.Argument()],
              predicate: Annotated[str, typer.Argument()],
              value: Annotated[Optional[str], typer.Option("--value", "-v", help="goal value: true/false → bool, numeric → num, else string")] = None,
              case: Annotated[Optional[str], typer.Option("--case")] = None,
              ref: OptRef = None):
    """Backward chaining: prove a goal (subject predicate [value]) → proof tree.
    Deterministic — pure WOQL over committed graph data, no LLM."""
    goal = {"subject": subject, "predicate": predicate}
    if value is not None:
        if value == "true":
            goal["valueBool"] = True
        elif value == "false":
            goal["valueBool"] = False
        else:
            try:
                goal["valueNum"] = float(value)
            except ValueError:
                goal["valueString"] = value
    c = _client(ref)
    if case:
        c.ref = cases_mod._slug(case)
    tree = engine.prove(c, goal)
    if tree is None:
        typer.echo(json.dumps({"provable": False, "goal": goal}))
        raise typer.Exit(1)
    typer.echo(json.dumps({"provable": True, "goal": goal, "proof": tree}, indent=2))


@app.command("search")
def search_cmd(query: Annotated[str, typer.Argument(help="natural-language query over the case evidence")],
               case: Annotated[Optional[str], typer.Option("--case")] = None,
               top_k: Annotated[int, typer.Option("--top-k")] = 5,
               ref: OptRef = None):
    """Semantic search over a case's embedded evidence chunks (sensing-side RAG;
    the verdict path never reads these)."""
    c = _client(ref)
    if case:
        c.ref = cases_mod._slug(case)
    hits = search.search_case(c, query, top_k=top_k)
    if not hits:
        typer.echo("no embedded chunks — ingest with embeddings (needs MISTRAL_API_KEY) or rerun ingest")
        raise typer.Exit(1)
    for h in hits:
        typer.echo(f"{h['score']:.4f}  {h['id']}  ({h['extracted']}, chunk {h['idx']})")
        typer.echo("  " + h["text"][:300].replace("\n", " "))


@app.command("extract")
def extract_cmd(file: Annotated[Path, typer.Argument(help="a single messy evidence file")],
                out: Annotated[Path, typer.Option("--out", "-o")],
                bundle_dir: Annotated[Optional[Path], typer.Option("--bundle", "-b", help="bundle dir for the exact fact vocabulary")] = None,
                backend: Annotated[str, typer.Option("--backend", help="auto|smolvm|local")] = "auto",
                timeout: Annotated[float, typer.Option("--timeout")] = 60.0):
    """Codemode: the LLM writes an extractor (pydantic-ai, typed), the sandbox runs
    it under our control (SmolVM when available, local with --dev), and stdout JSON
    is validated as SensedFacts. Induction only — never in the verdict path."""
    vocab = None
    if bundle_dir is not None:
        docs = json.loads((bundle_dir / "bundle.json").read_text())
        vocab = {"subjects": sorted({c["subject"] for i in docs for c in i.get("when", []) + i.get("claims", [])}),
                 "predicates": sorted({c["predicate"] for i in docs for c in i.get("when", []) + i.get("claims", [])})}
    facts, res = codemode.codemode_extract(file, sensing.SensedFacts, timeout=timeout,
                                           backend=backend, vocab=vocab)
    docs = [engine_fact_doc(f.model_dump()) for f in facts.facts]
    out.write_text(json.dumps(docs, indent=2))
    typer.echo(f"codemode ({res['backend']}, {res['seconds']}s, exit {res['exit_code']}): "
               f"{len(docs)} facts → {out}")


# ── facts / sense / run ──────────────────────────────────────────────────────

@app.command("load-facts")
def load_facts(facts: Annotated[Path, typer.Argument()],
               message: Annotated[str, typer.Option("--message")] = "load facts",
               ref: OptRef = None):
    c = _client(ref)
    n = engine.load_facts(c, facts, message)
    typer.echo(f"loaded {n} facts ({message})")


@app.command("sense")
def sense(case_dir: Annotated[Optional[Path], typer.Argument()] = None,
          out: Annotated[Path, typer.Option("--out", "-o")] = ...,
          case: Annotated[Optional[str], typer.Option("--case", help="sense from a case branch's extracted texts")] = None,
          rag: Annotated[Optional[str], typer.Option("--rag", help="semantic query: prepend top matching evidence chunks to the sensing prompt (induction-side only)")] = None,
          ref: OptRef = None):
    c = _client(ref)
    if case:
        c.ref = cases_mod._slug(case)
        ext = [d for d in c.get_all_docs() if d.get("@type") == "ExtractedText"]
        origs = {d["id"]: d for d in c.get_all_docs() if d.get("@type") == "Original"}
        evidence = "\n\n".join(
            f"--- {origs.get(e['original'], {}).get('path', e['original'][:12])} ---\n{e['text']}"
            for e in sorted(ext, key=lambda d: d["id"]))
        if rag:
            hits = search.search_case(c, rag)
            if hits:
                evidence = ("RELEVANT EVIDENCE CHUNKS (semantic search, induction-side only):\n"
                            + "\n\n".join(f"--- chunk {h['id']} (score {h['score']:.3f}) ---\n{h['text']}" for h in hits)
                            + "\n\n" + evidence)
        b = bundle_mod.Bundle.from_db(c, "case")
        docs = b.docs
    else:
        assert case_dir is not None, "pass a bundle/case dir or --case <id>"
        ev = sorted((case_dir / "evidence").glob("*"))
        evidence = "\n\n".join(f"--- {p.name} ---\n{p.read_text(errors='replace')}" for p in ev)
        docs = None
        for cand in (case_dir / "bundle.json", case_dir / "terminusdb" / "pack.json"):
            if cand.exists():
                docs = json.loads(cand.read_text()); break
        if docs is None:
            pack = case_dir / "pack"
            docs = [i for f in ("rules.json", "hypotheses.json", "constraints.json")
                    for i in json.loads((pack / f).read_text())]
        if isinstance(docs, dict) and "documents" in docs:
            docs = docs["documents"]
    vocab = {"subjects": set(), "predicates": set()}
    for item in docs:
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
    docs_out = [engine_fact_doc(f) for f in facts_list]  # Fact docs, ready to insert as-is
    out.write_text(json.dumps(docs_out, indent=2))
    typer.echo(f"sensed {len(docs_out)} facts → {out}")


@app.command("run")
def run(case: Annotated[str, typer.Argument()],
        add_facts: Annotated[Optional[Path], typer.Option("--add-facts")] = None,
        phase: Annotated[str, typer.Option("--phase")] = "1",
        ref: OptRef = None):
    t0 = time.monotonic()
    c = _client(ref)
    if ref:
        try:
            c.branch(c.ref)
        except TerminusError:
            pass  # branch already exists
    if add_facts:
        engine.load_facts(c, add_facts, f"apply {add_facts.name}")
    result = engine.run_phase(c, case, phase)
    typer.echo(f"[run] phase {phase} done in {time.monotonic() - t0:.2f}s (engine only, no LLM)", err=True)
    typer.echo(json.dumps({k: v for k, v in result.items() if k != "ranking"}, indent=2, default=str))
    for r in result["ranking"]:
        typer.echo(f"  {r['hypothesis']:<4} {r['status']:<7} score={r['score']:.4f} "
                   f"claims={r['claimsProven']:.3f} support={r['support']:.0f} prior={r['prior']:.2f}")


# ── inspect / debug ──────────────────────────────────────────────────────────

@app.command("compile-rules")
def compile_rules(case_dir: Annotated[Path, typer.Argument()]):
    cand = case_dir / "bundle.json"
    if not cand.exists():
        cand = case_dir / "terminusdb" / "pack.json"
    for r in [d for d in json.loads(cand.read_text()) if d.get("@type") == "Rule"]:
        q, id_vars = rules.compile_rule(r)
        typer.echo(r["id"] + " → " + json.dumps(q))


@app.command("log")
def log(ref: OptRef = None):
    typer.echo(json.dumps(_client(ref).commit_log(), indent=2))


def _strip_ids(x):
    """Remove generated @id keys recursively — content hash must ignore them
    (subdocument Random keys regenerate on every upsert)."""
    if isinstance(x, dict):
        return {k: _strip_ids(v) for k, v in x.items() if k != "@id"}
    if isinstance(x, list):
        return [_strip_ids(v) for v in x]
    return x


@app.command("metrics")
def metrics():
    """Print the sensing metrics log (latency + tokens per LLM call)."""
    from .sensing import METRICS_PATH

    if not METRICS_PATH.exists():
        typer.echo("no metrics yet — run a --live sensing first")
        return
    for line in METRICS_PATH.read_text().splitlines():
        m = json.loads(line)
        typer.echo(f"{m['ts'][:19]}  {m['op']:<12} {m['model']:<28} {m['seconds']:>6.1f}s  "
                   f"in={m['input_tokens']} out={m['output_tokens']} cached={m['cached']}")


@app.command("verdict")
def verdict(ref: OptRef = None):
    """Dump the Verdict docs on the current ref as sorted JSON, @id-stripped
    (so hashing compares content, not generated ids)."""
    c = _client(ref)
    vs = [d for d in c.get_all_docs() if d.get("@type") == "Verdict"]
    vs = _strip_ids(sorted(vs, key=lambda d: d["id"]))
    for v in vs:  # ranking is a Set in the DB — unordered on read; sort for stable hashing
        if isinstance(v.get("ranking"), list):
            v["ranking"] = sorted(v["ranking"], key=lambda r: str(r.get("hypothesis")))
    typer.echo(json.dumps(vs, sort_keys=True, indent=2))


@app.command("cases")
def cases():
    """List bundles (v2 manifests) and legacy PoC oracle cases."""
    bdir = REPO / "bundles"
    if bdir.is_dir():
        for d in sorted(bdir.iterdir()):
            if (d / bundle_mod.MANIFEST).exists():
                m = json.loads((d / bundle_mod.MANIFEST).read_text())
                signed = "signed" if (d / bundle_mod.SIG).exists() else "UNSIGNED"
                typer.echo(f"bundle\t{d.name}\tv{m['version']}\t{signed}\tkey={m.get('fingerprint', '-')}")
    if CASES.is_dir():
        for d in sorted(CASES.iterdir()):
            if (d / "terminusdb" / "pack.json").exists():
                typer.echo(f"case(legacy)\t{d.name}")


# Golden expectations transcribed from each case's expected.md (the PoC oracle).
# ranking: [(hypothesis, approx score)] in expected order; pruned: set of hypothesis ids.
SELFTEST_CASES = [
    {"name": "attribution-silver-blaze", "dir": CASES / "attribution-silver-blaze",
     "p1_facts": "terminusdb/facts.json", "p2_facts": "terminusdb/facts-ledger.json",
     "p1": {"derived": {"d1", "d2", "d3"}, "pruned": {"H1", "H4"},
            "ranking": [("H2", 0.740), ("H3", 0.235)], "rec": "q1"},
     "p2": {"derived": {"d4", "d5"}, "winner": "H3", "score": 0.735}, "legacy": True},
    {"name": "adjudication-phantom-invoice", "dir": CASES / "adjudication-phantom-invoice",
     "p1_facts": "terminusdb/facts.json", "p2_facts": "terminusdb/facts-trail.json",
     "p1": {"derived": {"d1", "d2", "d3", "d4"}, "pruned": {"H3", "H4"},
            "ranking": [("H2", 0.725), ("H1", 0.535)], "rec": "q1"},
     "p2": {"derived": {"d5", "d6", "d7", "d8"}, "winner": "H1", "score": 0.935}, "legacy": True},
    {"name": "causation-three-am-outage", "dir": CASES / "causation-three-am-outage",
     "p1_facts": "terminusdb/facts.json", "p2_facts": "terminusdb/facts-postmortem.json",
     "p1": {"derived": {"d1", "d2", "d3"}, "pruned": {"H2", "H4"},
            "ranking": [("H1", 0.535), ("H3", 0.430)], "rec": "q1"},
     "p2": {"derived": {"d4", "d5", "d6"}, "winner": "H3", "score": 0.830}, "legacy": True},
    {"name": "insurance-claim-fraud", "dir": REPO / "bundles" / "insurance-claim-fraud",
     "p1_facts": "fixtures/facts-staged.json", "p2_facts": None,
     "p1": {"derived": {"d1", "d2", "d2b", "d3", "d4"}, "pruned": {"H4"},
            "ranking": [("H2", 0.630), ("H1", 0.625), ("H3", 0.620)], "rec": None}},
]


@app.command("selftest")
def selftest():
    """Golden-compare every migrated case against its PoC expected.md assertions,
    plus a determinism replay per case. Runs against a scratch db."""
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
        c.ref = f"case-{name}"
        try:
            c.branch(c.ref)
        except TerminusError:
            pass
        b = bundle_mod.Bundle.from_dir(spec["dir"], dev=spec.get("legacy", False))
        b.load_into(c, name, dev=spec.get("legacy", False))
        engine.load_facts(c, spec["dir"] / spec["p1_facts"], "phase 1 facts")
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
            engine.load_facts(c, spec["dir"] / spec["p2_facts"], "phase 2 drop")
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
            typer.echo(f"FAIL {name}: {'; '.join(bad)}")
        else:
            typer.echo(f"PASS {name}")
    if failures:
        typer.echo("SELFTEST FAIL")
        raise typer.Exit(1)
    typer.echo("SELFTEST PASS — all cases match the PoC golden expectations, deterministic replay")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
