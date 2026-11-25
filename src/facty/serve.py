"""`facty serve` — the one HTTP/JSON gateway inside the image.

THIN TRANSPORT ONLY: every route below is one line mapping the HTTP path to a
function in `ops.py` — the single layer that owns op logic. The Web UI and the
CLI are both clients of the gateway, and the MCP server calls the same ops
directly (parity by construction, ADR-0010 §4; thinnest-possible wrapper, no
indirection to diverge). Stdlib only (http.server) — runs in the SmolVM image
snapshot with no PyPI at runtime.

  GET  /                     static UI (web/dist) or a pointer if not built
  GET  /api/<op>?case=…      read ops (see GET_ROUTES)
  POST /api/<op>             mutation ops (see POST_ROUTES)
  GET  /api/watch?case=…     SSE: full state on connect, then a commit event per
                             new commit on the case branch (live bullseye/graph)
  GET  /api/ops              the op registry (parity test + MCP mapping read it)
"""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import ops as ops_mod

REPO = Path(__file__).resolve().parents[2]
WEB_DIST = REPO / "web" / "dist"

# ── the op registry: path → one-line adapter over ops.py ─────────────────────
# POST_OPS / GET_OPS are DERIVED from the route tables (single source of truth);
# /api/ops exposes them and tests/test_mcp.py asserts the MCP tools cover them.

POST_ROUTES = {
    "/api/case/init":   lambda c, b: ops_mod.case_init(c, b["id"], b["bundle"], b.get("model")),
    "/api/case/show":   lambda c, b: ops_mod.case_show(c, b["case"]),
    "/api/case/branch": lambda c, b: ops_mod.case_branch(c, b["case"], b["name"]),
    "/api/case/delete": lambda c, b: ops_mod.case_delete(c, b["case"]),
    "/api/ingest":      lambda c, b: ops_mod.ingest(c, b["case"], b["dir"],
                                                   b.get("source", "ui"), b.get("ocr", False),
                                                   b.get("noEmbed", False)),
    "/api/load-facts":  lambda c, b: ops_mod.load_facts(c, b["case"], b["path"],
                                                       b.get("message", "load facts")),
    "/api/sense":       lambda c, b: ops_mod.sense(c, b["case"], b.get("rag")),
    "/api/run":         lambda c, b: ops_mod.run(c, b["case"], b.get("phase", "1")),
    "/api/prove":       lambda c, b: ops_mod.prove(c, b["case"], b["subject"], b["predicate"],
                                                   b.get("value")),
    "/api/assemble":    lambda c, b: ops_mod.assemble(c, b["case"], b.get("goal")),
    "/api/answer":      lambda c, b: ops_mod.answer(c, b["case"], b["question"], b["value"]),
    "/api/turn":        lambda c, b: ops_mod.turn(c, b["case"], b.get("pipeline"), b.get("choice"),
                                                  b.get("value"), b.get("surface"),
                                                  b.get("actor", "human"), b.get("all", False)),
    "/api/search":      lambda c, b: ops_mod.search(c, b["case"], b["query"], b.get("top_k", 5)),
    "/api/query":       lambda c, b: ops_mod.query(c, b.get("case"), b["query"]),
    "/api/interview":   lambda c, b: ops_mod.interview(c, b["case"], b.get("answers"),
                                                       b.get("chooser", "script"), b.get("surface", "wizard"),
                                                       b.get("actor", "human"), b.get("max_turns", 20),
                                                       b.get("pipeline")),
    "/api/feedback":    lambda c, b: ops_mod.feedback_add(c, b["text"], b.get("case"),
                                                         b.get("screen", ""), b.get("author", "user"),
                                                         b.get("at", "")),
}

GET_ROUTES = {
    "/api/bundles": lambda c, q: ops_mod.bundles(c),
    "/api/cases":   lambda c, q: ops_mod.case_list(c),
    "/api/state":   lambda c, q: ops_mod.state(c, q["case"][0]),
    "/api/log":     lambda c, q: ops_mod.log(c, q["case"][0]),
    "/api/verdict": lambda c, q: ops_mod.verdict(c, q.get("case", [None])[0]),
    "/api/feedback": lambda c, q: ops_mod.feedback_list(c, q.get("case", [None])[0]),
    "/api/ops":     lambda c, q: {"post": POST_OPS, "get": GET_OPS},
}

POST_OPS = sorted(p[len("/api/"):] for p in POST_ROUTES)
GET_OPS = sorted([p[len("/api/"):] for p in GET_ROUTES] + ["watch"])


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

        # ── routing: one dispatch table per verb, zero logic ──
        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/api/watch":
                return self._watch(q["case"][0])
            fn = GET_ROUTES.get(u.path)
            if fn is None:
                return self._static(u.path)
            try:
                return self._json(fn(get_client(), q))
            except Exception as e:  # no tracebacks with locals over HTTP
                return self._json({"error": str(e)}, 500)

        def do_POST(self):
            u = urlparse(self.path)
            b = self._body()
            fn = POST_ROUTES.get(u.path)
            if fn is None:
                return self._json({"error": f"unknown op {u.path}"}, 404)
            try:
                return self._json(fn(get_client(), b))
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
                send("state", ops_mod.state(get_client(), case))
                seen = {c.get("identifier") for c in ops_mod.log(get_client(), case)["log"]}
                while True:
                    time.sleep(1.0)
                    log = ops_mod.log(get_client(), case)["log"]
                    fresh = [c for c in log if c.get("identifier") not in seen]
                    for c in fresh:
                        seen.add(c.get("identifier"))
                        send("commit", c)
                    if fresh:
                        send("state", ops_mod.state(get_client(), case))
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
            f = WEB_DIST / (path.lstrip("/") or "index.html")
            if not str(f.resolve()).startswith(str(WEB_DIST.resolve())) or not f.is_file():
                f = WEB_DIST / "index.html"
            ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                     ".svg": "image/svg+xml", ".json": "application/json"}.get(f.suffix, "application/octet-stream")
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return H


def serve(host: str = "127.0.0.1", port: int = 8080, client_factory=None):
    from .client import Client

    def get_client():
        return client_factory() if client_factory else Client()

    httpd = ThreadingHTTPServer((host, port), make_handler(get_client))
    print(f"facty serve on http://{host}:{port}  (UI: http://{host}:{port}/  API: /api/ops)",
          flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
