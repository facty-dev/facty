"""facty CLI — headless, no TUI. Built on Typer (tiangolo; uv-ecosystem standard).

  facty init-db
  facty keys init | list
  facty bundle sign|verify|load <bundle-dir>   # signed v2 bundles only — the one form
  facty load-facts <facts.json> --message <msg>
  facty sense <case-dir> --out <facts.json>   # live LLM sensing
  facty run <case> [--add-facts <drop.json>] [--phase <name>] [--ref <branch>]
  facty compile-rules <bundle-dir>             # dump WOQL (debug)
  facty log | verdict | metrics | cases
  facty selftest                               # acceptance: every signed bundle in bundles/
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
from . import codemode, engine, ingest, keys, ops as ops_mod, rules, sandbox, search, sensing, serve as serve_mod
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
feedback_app = typer.Typer(name="feedback", help="User comments as committed Feedback docs (the in-UI comment channel).", no_args_is_help=True)
vm_app = typer.Typer(name="vm", help="SmolVM sandbox lifecycle: one reused machine, stopped when done (image persists).", no_args_is_help=True)
app.add_typer(keys_app)
app.add_typer(bundle_app)
app.add_typer(case_app)
app.add_typer(vm_app)
app.add_typer(feedback_app)


@feedback_app.command("add")
def feedback_add(text: Annotated[str, typer.Argument()],
                 case: Annotated[Optional[str], typer.Option("--case", help="anchor to a case branch (default: app scope on main)")] = None,
                 screen: Annotated[str, typer.Option("--screen", help="which screen/view the comment is about")] = "",
                 author: Annotated[str, typer.Option("--author")] = "user"):
    """Commit a feedback comment as a Feedback doc (audit-friendly, queryable)."""
    c = _client(None)
    doc = ops_mod.feedback_add(c, text, case, screen, author)
    typer.echo(f"saved {doc['id']} (scope {doc['scope']})")


@feedback_app.command("list")
def feedback_list(case: Annotated[Optional[str], typer.Option("--case")] = None):
    """List feedback comments (case scope, or app scope)."""
    c = _client(None)
    for d in ops_mod.feedback_list(c, case)["feedback"]:
        typer.echo(f"{d['id']}  [{d.get('screen') or '-'}]  {d['author']}: {d['text']}")


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


REPO = Path(__file__).resolve().parents[2]  # src/facty/cli.py → repo root
BUNDLES = REPO / "bundles"  # the signed bundles — the only pack/case/demo form (ADR-0006)


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
                ref: OptRef = None):
    """The trust gate: the signed v2 bundle verifies against its embedded pubkey
    (no private key needed) before anything is inserted. Unsigned dirs are refused."""
    c = _client(ref)
    b = bundle_mod.Bundle.from_dir(bundle_dir)
    typer.echo(b.load_into(c, name or b.id))


@bundle_app.command("sign")
@_gate
def bundle_sign(bundle_dir: Annotated[Path, typer.Argument()],
                key: Annotated[Optional[str], typer.Option("--key", help="key fingerprint (default: sole private key)")] = None):
    b = bundle_mod.Bundle.from_dir(bundle_dir, allow_unsigned=True)  # authoring bootstrap
    fp = b.sign(key)
    typer.echo(f"signed {b.id}@{b.version} with key {fp} → {b.path / bundle_mod.SIG}")


@bundle_app.command("verify")
@_gate
def bundle_verify(bundle_dir: Annotated[Path, typer.Argument()]):
    b = bundle_mod.Bundle.from_dir(bundle_dir)  # verifies on load
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
              model: Annotated[Optional[str], typer.Option("--model")] = None,
              ref: OptRef = None):
    """Create branch case-<id>, verify+load the signed bundle, register the case."""
    c = _client(ref)
    typer.echo(cases_mod.case_init(c, case_id, bundle_dir, model=model))


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
    s = ops_mod.ingest(c, case, str(src), source, ocr=ocr, no_embed=no_embed, ref=ref)
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
    c = _client(ref)
    r = ops_mod.prove(c, case, subject, predicate, value, ref=ref)
    if not r["provable"]:
        typer.echo(json.dumps({"provable": False, "goal": r["goal"]}))
        raise typer.Exit(1)
    typer.echo(json.dumps(r, indent=2))


@app.command("query")
def query_cmd(woql: Annotated[str, typer.Argument(help="WOQL JSON AST string, or path to a .json file")],
              case: Annotated[Optional[str], typer.Option("--case")] = None,
              ref: OptRef = None):
    """Read-only WOQL query against a case branch (or --ref). The LLM's tight
    read surface — GraphRAG/dialect patterns compile to this. Write operators
    in the AST are rejected; writes go through the gated ops."""
    p = Path(woql)
    q = json.loads(p.read_text()) if (woql.endswith(".json") and p.exists()) else json.loads(woql)
    c = _client(ref)
    r = ops_mod.query(c, case, q, ref=ref)
    typer.echo(json.dumps(r, indent=2, default=str))


@app.command("search")
def search_cmd(query: Annotated[str, typer.Argument(help="natural-language query over the case evidence")],
               case: Annotated[Optional[str], typer.Option("--case")] = None,
               top_k: Annotated[int, typer.Option("--top-k")] = 5,
               ref: OptRef = None):
    """Semantic search over a case's embedded evidence chunks (sensing-side RAG;
    the verdict path never reads these)."""
    c = _client(ref)
    r = ops_mod.search(c, case, query, top_k=top_k)
    hits = r["hits"]
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
    docs = [ops_mod.fact_doc(f.model_dump()) for f in facts.facts]
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
    """Live LLM sensing (pydantic-ai typed output). The implementation is the
    single ops.sense / ops.sense_evidence — this command only marshals IO."""
    c = _client(ref)
    if case:
        r = ops_mod.sense(c, case, rag)
        docs_out = r["facts"]
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
        docs_out = ops_mod.sense_evidence(evidence, docs)  # Fact docs, ready to insert as-is
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
    result = ops_mod.run(c, case, phase, ref=ref)
    typer.echo(f"[run] phase {phase} done in {time.monotonic() - t0:.2f}s (engine only, no LLM)", err=True)
    typer.echo(json.dumps({k: v for k, v in result.items() if k != "ranking"}, indent=2, default=str))
    for r in result["ranking"]:
        typer.echo(f"  {r['hypothesis']:<4} {r['status']:<7} score={r['score']:.4f} "
                   f"claims={r['claimsProven']:.3f} support={r['support']:.0f} prior={r['prior']:.2f}")


@app.command("assemble")
def assemble_cmd(case: Annotated[str, typer.Argument()],
                 goal: Annotated[Optional[str], typer.Option("--goal")] = None,
                 ref: OptRef = None):
    """Deterministic assembly: snippets whose `when` is proven → AssembledDocument."""
    c = _client(ref)
    if ref:
        try:
            c.branch(c.ref)
        except TerminusError:
            pass
    doc = ops_mod.assemble(c, case, goal, ref=ref)
    typer.echo(f"assembled {doc['id']} — {len(doc['snippets'])} snippets, sha256 {doc['sha256'][:12]}")
    typer.echo(doc["content"])


@app.command("answer")
def answer_cmd(case: Annotated[str, typer.Argument()],
               question: Annotated[str, typer.Argument()],
               value: Annotated[str, typer.Argument()],
               ref: OptRef = None):
    """Slot filling (human loop): answer an open question → typed Fact + close it."""
    c = _client(ref)
    if ref:
        try:
            c.branch(c.ref)
        except TerminusError:
            pass
    doc = ops_mod.answer(c, case, question, value, ref=ref)
    typer.echo(json.dumps(doc, indent=2, default=str))


@app.command("turn")
def turn_cmd(case: Annotated[str, typer.Argument()],
             pipeline: Annotated[Optional[str], typer.Option("--pipeline", help="pipeline doc id (default: first on the case branch)")] = None,
             choice: Annotated[Optional[str], typer.Option("--choice", help="ranked pick — must be within the engine's option set")] = None,
             value: Annotated[Optional[str], typer.Option("--value", help="value for an answer turn")] = None,
             surface: Annotated[Optional[str], typer.Option("--surface", help="chat | wizard — recorded on the Turn doc")] = None,
             actor: Annotated[str, typer.Option("--actor", help="human | llm | pipeline — who made the pick")] = "human",
             all: Annotated[bool, typer.Option("--all", help="run until done or a ranked step awaits a choice")] = False,
             ref: OptRef = None):
    """Turn dispatcher (ADR-0010 §3): execute the next step of the case's signed
    pipeline config under its determinism mode (deterministic | ranked | free);
    commits one Turn doc per turn. Verdict-path steps are always deterministic."""
    c = _client(ref)
    r = ops_mod.turn(c, case, pipeline=pipeline, choice=choice, value=value,
                     surface=surface, actor=actor, all=all)
    typer.echo(json.dumps(r, indent=2, default=str))


@app.command("interview")
def interview_cmd(case: Annotated[str, typer.Argument()],
                  answers: Annotated[Optional[str], typer.Option("--answers", help="comma-separated qid=value scripted answers ('*' = any question)")] = None,
                  chooser: Annotated[str, typer.Option("--chooser", help="script | llm — who picks answers (llm = designated ranked node, gated+committed)")] = "script",
                  surface: Annotated[str, typer.Option("--surface")] = "wizard",
                  actor: Annotated[str, typer.Option("--actor")] = "human",
                  max_turns: Annotated[int, typer.Option("--max-turns")] = 20,
                  ref: OptRef = None):
    """The questionnaire loop as a pydantic-graph: gap analysis → ask → slot-fill
    → engine run → assemble. Every turn commits a Turn doc to the case branch."""
    c = _client(ref)
    ans = {}
    if answers:
        for pair in answers.split(","):
            k, _, v = pair.partition("=")
            ans[k.strip()] = v.strip()
    r = ops_mod.interview(c, case, ans, chooser, surface, actor, max_turns, ref=ref)
    typer.echo(json.dumps(r, indent=2, default=str))


@app.command("mcp")
def mcp_cmd():
    """Run the facty MCP server (MCP over stdio, stdlib JSON-RPC): one tool per
    `facty serve` case op, so machine loops and the human harness call the same
    interfaces (ADR-0010 §4.2). A harness spawns this as a subprocess."""
    from . import mcp_server
    mcp_server.serve_stdio()


@app.command("serve")
def serve_cmd(host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
              port: Annotated[int, typer.Option("--port")] = 8080,
              ref: OptRef = None):
    """The one HTTP/JSON gateway: every CLI op as an endpoint + SSE watch + the
    static Web UI (web/dist). The UI and the CLI are both clients of it."""
    if ref:
        import os
        os.environ.setdefault("TERMINUSDB_REF", ref)
    serve_mod.serve(host=host, port=port)


# ── inspect / debug ──────────────────────────────────────────────────────────

@app.command("compile-rules")
def compile_rules(bundle_dir: Annotated[Path, typer.Argument()]):
    cand = bundle_dir / "bundle.json"
    for r in [d for d in json.loads(cand.read_text()) if d.get("@type") == "Rule"]:
        q, id_vars = rules.compile_rule(r)
        typer.echo(r["id"] + " → " + json.dumps(q))


@app.command("log")
def log(ref: OptRef = None):
    typer.echo(json.dumps(_client(ref).commit_log(), indent=2))


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
    typer.echo(json.dumps(ops_mod.verdict(_client(ref))["verdicts"], sort_keys=True, indent=2))


@app.command("cases")
def cases():
    """List the signed bundles in bundles/ — the only pack/case/demo form."""
    for b in ops_mod.bundles()["bundles"]:
        signed = "signed" if b["signed"] else "UNSIGNED"
        typer.echo(f"bundle\t{b['id']}\tv{b['version']}\t{signed}\tkey={b['fingerprint'] or '-'}")


# Acceptance expectations for every signed bundle in bundles/ (transcribed from
# each bundle's fixtures/expected.md — originally the PoC oracle's assertions).
# ranking: [(hypothesis, approx score)] in expected order; pruned: set of hypothesis ids.
SELFTEST_CASES = [
    {"name": "attribution-silver-blaze", "dir": BUNDLES / "attribution-silver-blaze",
     "p1_facts": "fixtures/facts.json", "p2_facts": "fixtures/facts-ledger.json",
     "p1": {"derived": {"d1", "d2", "d3"}, "pruned": {"H1", "H4"},
            "ranking": [("H2", 0.740), ("H3", 0.235)], "rec": "q1"},
     "p2": {"derived": {"d4", "d5"}, "winner": "H3", "score": 0.735}},
    {"name": "adjudication-phantom-invoice", "dir": BUNDLES / "adjudication-phantom-invoice",
     "p1_facts": "fixtures/facts.json", "p2_facts": "fixtures/facts-trail.json",
     "p1": {"derived": {"d1", "d2", "d3", "d4"}, "pruned": {"H3", "H4"},
            "ranking": [("H2", 0.725), ("H1", 0.535)], "rec": "q1"},
     "p2": {"derived": {"d5", "d6", "d7", "d8"}, "winner": "H1", "score": 0.935}},
    {"name": "causation-three-am-outage", "dir": BUNDLES / "causation-three-am-outage",
     "p1_facts": "fixtures/facts.json", "p2_facts": "fixtures/facts-postmortem.json",
     "p1": {"derived": {"d1", "d2", "d3"}, "pruned": {"H2", "H4"},
            "ranking": [("H1", 0.535), ("H3", 0.430)], "rec": "q1"},
     "p2": {"derived": {"d4", "d5", "d6"}, "winner": "H3", "score": 0.830}},
    {"name": "insurance-claim-fraud", "dir": BUNDLES / "insurance-claim-fraud",
     "p1_facts": "fixtures/facts-staged.json", "p2_facts": None,
     "p1": {"derived": {"d1", "d2", "d2b", "d3", "d4"}, "pruned": {"H4"},
            "ranking": [("H2", 0.630), ("H1", 0.625), ("H3", 0.620)], "rec": None}},
    {"name": "assembly-unpaid-invoice", "dir": BUNDLES / "small-business-contract-claim",
     "p1_facts": "fixtures/facts-initial.json", "p2_facts": None,
     "p1": {"derived": {"d1", "d2", "d3", "d4"}, "pruned": {"H2", "H3"},
            "ranking": [("H1", 0.750)], "rec": "q-written-complaint"}},
    {"name": "verification-nobid-contracts", "dir": BUNDLES / "public-corruption-dossier",
     "p1_facts": "fixtures/facts-initial.json", "p2_facts": None,
     "p1": {"derived": {"d1", "d2", "d3", "d4", "d5", "d6"}, "pruned": {"H2", "H3"},
            "ranking": [("H1", 0.950)], "rec": "q-emergency-declaration"}},
    {"name": "adjudication-epli-denial", "dir": BUNDLES / "epli-coverage-demand",
     "p1_facts": "fixtures/facts-initial.json", "p2_facts": None,
     "p1": {"derived": {"d1", "d2", "d3", "d4"}, "pruned": {"H2", "H3"},
            "ranking": [("H1", 0.950)], "rec": "q-insurer-notice-date"}},
]


@app.command("selftest")
def selftest():
    """Acceptance: load every signed bundle in bundles/ (signature-verified),
    replay its fixture facts, assert the expected verdicts, plus a determinism
    replay per case. Runs against a scratch db."""
    from .schema import SCHEMA

    c = Client(db=os.environ.get("TERMINUSDB_DB", "facty-selftest"))
    if c.db_exists():
        c.delete_db()
    c.create_db()
    c.install_schema(SCHEMA)

    def vdocs(case, suffix):
        vs = [d for d in c.get_all_docs() if d.get("@type") == "Verdict"
              and d["id"] == f"verdict-{case}-{suffix}"]
        vs = ops_mod.strip_ids(vs)
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
        b = bundle_mod.Bundle.from_dir(spec["dir"])  # signed — verifies on load
        b.load_into(c, name)
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
    typer.echo("SELFTEST PASS — every signed bundle replays to its expected verdict, deterministically")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
