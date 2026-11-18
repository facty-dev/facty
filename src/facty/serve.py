"""`facty serve` — the one HTTP/JSON gateway inside the image.

The Web UI and the CLI are both clients of it (parity by construction, ADR-0010):
every op below maps 1:1 to a CLI command. Stdlib only (http.server) — the engine
core + control plane stay dependency-free and run in the SmolVM image snapshot.

  GET  /                     static UI (web/dist) or a pointer if not built
  GET  /api/cases            Case registry docs
  POST /api/case/init        {id, bundle}            → facty case init
  POST /api/ingest           {case, dir, source, ocr?} → facty ingest
  POST /api/load-facts       {case, path}            → facty load-facts
  POST /api/sense            {case, rag?}            → facty sense --case
  POST /api/run              {case, phase?}          → facty run
  POST /api/prove            {case, subject, predicate, value?} → facty prove
  POST /api/assemble         {case}                  → facty assemble
  POST /api/answer           {case, question, value} → slot filling (human loop)
  GET  /api/state?case=…     all case docs (Facts, Hypotheses, Constraints,
                             OpenQuestions, Derivations, Verdicts, Goal, Snippets,
                             AssembledDocument, Case) — the UI's render input
  GET  /api/log?case=…       branch commit log (the turn timeline)
  GET  /api/watch?case=…     SSE: full state on connect, then a commit event per
                             new commit on the case branch (live bullseye/graph)
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import bundle as bundle_mod
from . import cases as cases_mod
from . import engine, ingest

REPO = Path(__file__).resolve().parents[2]
WEB_DIST = REPO / "web" / "dist"

# The op registry — one op set behind CLI / `facty serve` / MCP (parity by
# construction, ADR-0010 §4). `/api/ops` exposes it; the MCP server maps its
# tool names onto these.
POST_OPS = ["case/init", "case/show", "case/branch", "case/delete", "ingest",
            "load-facts", "sense", "run", "prove", "assemble", "answer", "turn",
            "search"]
GET_OPS = ["cases", "state", "log", "watch", "ops", "verdict"]


def _state(client, case: str) -> dict:
    client.ref = cases_mod._slug(case)
    docs = client.get_all_docs()
    keep = ("Fact", "Hypothesis", "Constraint", "OpenQuestion", "Derivation",
            "Verdict", "Goal", "Snippet", "AssembledDocument", "Case",
            "Original", "Quarantine", "ExtractedText", "Pipeline", "Turn")
    return {"case": case, "branch": client.ref,
            "docs": [d for d in docs if d.get("@type") in keep]}


def make_handler(get_client):
    class H(BaseHTTPRequestHandler):
        server_version = "facty-serve/0.1"

        def log_message(self, fmt, *args):  # quiet
            pass

        # ── helpers ──
        def _json(self, obj, status=200):
            body = json.dumps(obj, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def _case_client(self, case: str):
            c = get_client()
            c.ref = cases_mod._slug(case)
            return c

        # ── routing ──
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/api/cases":
                return self._json({"cases": cases_mod.case_list(get_client())})
            if u.path == "/api/ops":
                return self._json({"post": POST_OPS, "get": GET_OPS})
            if u.path == "/api/verdict":
                c = get_client()
                if q.get("case"):
                    c.ref = cases_mod._slug(q["case"][0])
                from .cli import _strip_ids
                vs = [d for d in c.get_all_docs() if d.get("@type") == "Verdict"]
                vs = _strip_ids(sorted(vs, key=lambda d: d["id"]))
                for v in vs:
                    if isinstance(v.get("ranking"), list):
                        v["ranking"] = sorted(v["ranking"], key=lambda r: str(r.get("hypothesis")))
                return self._json({"verdicts": vs})
            if u.path == "/api/state":
                case = q["case"][0]
                return self._json(_state(get_client(), case))
            if u.path == "/api/log":
                case = q["case"][0]
                return self._json(self._case_client(case).commit_log())
            if u.path == "/api/watch":
                return self._watch(q["case"][0])
            return self._static(u.path)

        def do_POST(self):
            u = urlparse(self.path)
            b = self._body()
            try:
                if u.path == "/api/case/init":
                    c = get_client()
                    r = cases_mod.case_init(c, b["id"], b["bundle"])
                    return self._json(r)
                if u.path == "/api/case/show":
                    return self._json(cases_mod.case_show(get_client(), b["case"]))
                if u.path == "/api/case/branch":
                    return self._json(cases_mod.case_branch(get_client(), b["case"], b["name"]))
                if u.path == "/api/case/delete":
                    return self._json(cases_mod.case_delete(get_client(), b["case"]))
                if u.path == "/api/ingest":
                    c = self._case_client(b["case"])
                    s = ingest.ingest_dir(c, Path(b["dir"]), b.get("source", "ui"),
                                          ocr=b.get("ocr", False), embed=not b.get("noEmbed", True))
                    return self._json(s)
                if u.path == "/api/load-facts":
                    c = self._case_client(b["case"])
                    n = engine.load_facts(c, Path(b["path"]), b.get("message", "load facts"))
                    return self._json({"loaded": n})
                if u.path == "/api/sense":
                    from . import cli as cli_mod
                    c = self._case_client(b["case"])
                    ext = [d for d in c.get_all_docs() if d.get("@type") == "ExtractedText"]
                    origs = {d["id"]: d for d in c.get_all_docs() if d.get("@type") == "Original"}
                    evidence = "\n\n".join(
                        f"--- {origs.get(e['original'], {}).get('path', e['original'][:12])} ---\n{e['text']}"
                        for e in sorted(ext, key=lambda d: d["id"]))
                    bd = bundle_mod.Bundle.from_db(c, "case")
                    vocab = {"subjects": set(), "predicates": set()}
                    for item in bd.docs:
                        for cc in item.get("when", []) + item.get("claims", []):
                            vocab["subjects"].add(cc["subject"]); vocab["predicates"].add(cc["predicate"])
                    prompt = (
                        "Read the evidence below and emit a JSON object {\"facts\": [...]} — one entry per "
                        "distinct fact. Each fact: {\"id\": \"fNN\", \"type\": \"case\"|\"evidence\", "
                        "\"subject\", \"predicate\", \"value\" (string or boolean), \"confidence\" (0..1), "
                        "\"source\": \"<file>:<line>\", \"observedAt\": \"YYYY-MM-DD\"}. "
                        "CRITICAL: use ONLY these exact subject strings: " + json.dumps(sorted(vocab["subjects"])) +
                        " and ONLY these exact predicate strings: " + json.dumps(sorted(vocab["predicates"])) +
                        ". Booleans as true/false. Numbers as numbers. Do not conclude anything — facts only.\n\nEVIDENCE:\n" + evidence)
                    from . import sensing
                    o = sensing.sense_json(prompt, getattr(sensing, "SensedFacts", None))
                    if hasattr(o, "model_dump"):
                        o = o.model_dump()
                    fl = o["facts"] if isinstance(o, dict) and "facts" in o else o
                    docs = [cli_mod.engine_fact_doc(f) for f in fl]
                    c.insert_docs(docs, message="sense (via facty serve)")
                    return self._json({"sensed": len(docs), "facts": docs})
                if u.path == "/api/run":
                    c = self._case_client(b["case"])
                    r = engine.run_phase(c, b["case"], b.get("phase", "1"))
                    return self._json({k: v for k, v in r.items()})
                if u.path == "/api/prove":
                    c = self._case_client(b["case"])
                    goal = {"subject": b["subject"], "predicate": b["predicate"]}
                    if b.get("value") is not None:
                        v = b["value"]
                        if v == "true": goal["valueBool"] = True
                        elif v == "false": goal["valueBool"] = False
                        else:
                            try: goal["valueNum"] = float(v)
                            except (TypeError, ValueError): goal["valueString"] = str(v)
                    tree = engine.prove(c, goal)
                    return self._json({"provable": tree is not None, "goal": goal, "proof": tree})
                if u.path == "/api/assemble":
                    c = self._case_client(b["case"])
                    return self._json(engine.assemble(c, b["case"], b.get("goal")))
                if u.path == "/api/answer":
                    c = self._case_client(b["case"])
                    return self._json(engine.answer_question(c, b["question"], b["value"]))
                if u.path == "/api/turn":
                    from . import turn as turn_mod
                    c = self._case_client(b["case"])
                    r = turn_mod.run_turn(c, b["case"], pipeline_id=b.get("pipeline"),
                                          choice=b.get("choice"), value=b.get("value"),
                                          surface=b.get("surface"), actor=b.get("actor", "human"),
                                          run_all=b.get("all", False))
                    return self._json(r)
                if u.path == "/api/search":
                    from . import search as search_mod
                    c = self._case_client(b["case"])
                    return self._json({"hits": search_mod.search_case(
                        c, b["query"], top_k=b.get("top_k", 5))})
                return self._json({"error": f"unknown op {u.path}"}, 404)
            except Exception as e:  # no tracebacks with locals over HTTP
                return self._json({"error": str(e)}, 500)

        # ── SSE watch: full state, then one event per new branch commit ──
        def _watch(self, case: str):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

            def send(event, data):
                payload = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
                self.wfile.write(payload.encode())
                self.wfile.flush()

            try:
                send("state", _state(get_client(), case))
                seen = {c.get("identifier") for c in self._case_client(case).commit_log()}
                while True:
                    time.sleep(1.0)
                    log = self._case_client(case).commit_log()
                    fresh = [c for c in log if c.get("identifier") not in seen]
                    for c in fresh:
                        seen.add(c.get("identifier"))
                        send("commit", c)
                    if fresh:
                        send("state", _state(get_client(), case))
            except (BrokenPipeError, ConnectionResetError):
                pass

        # ── static UI ──
        def _static(self, path: str):
            if not WEB_DIST.exists():
                body = (b"<h1>facty serve</h1><p>API up. UI not built yet - "
                        b"run <code>npm ci &amp;&amp; npm run build</code> in <code>web/</code>.</p>")
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            p = (WEB_DIST / (path.lstrip("/") or "index.html")).resolve()
            if not str(p).startswith(str(WEB_DIST.resolve())) or not p.exists():
                p = WEB_DIST / "index.html"  # SPA fallback
            body = p.read_bytes()
            ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                     ".svg": "image/svg+xml", ".json": "application/json"}.get(p.suffix, "application/octet-stream")
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return H


def serve(host: str = "127.0.0.1", port: int = 8080, client_factory=None):
    from .client import Client
    factory = client_factory or (lambda: Client())
    httpd = ThreadingHTTPServer((host, port), make_handler(factory))
    print(f"facty serve on http://{host}:{port}  (API /api/…, UI /, web dist {WEB_DIST})", flush=True)
    httpd.serve_forever()
