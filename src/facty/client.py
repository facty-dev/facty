"""Minimal TerminusDB REST client (stdlib only).

Endpoint shapes verified against terminusdb-server v12 docs + the official
python client (terminusdb-client-python, client/Client.py) — see
docs/research/deps-log.md. All paths concentrated here:
  POST /api/db/{org}/{db}
  POST /api/schema/{org}/{db}                      (schema graph)
  POST /api/document/{org}/{db}/local/branch/{b}   (?author&message&graph_type&create&raw_json)
  GET  /api/document/{org}/{db}/local/branch/{b}
  POST /api/woql/{org}/{db}/local/branch/{b}       (body = WOQL JSON)
  POST /api/branch/{org}/{db}/{b}                  (body {"origin": "{org}/{db}/local/branch/main"})
  POST /api/squash/{org}/{db}/{b}
  GET  /api/log/{org}/{db}
Time-travel: replace `local/branch/{b}` with `local/commit/{id}`.

Env:
  TERMINUSDB_URL   default http://127.0.0.1:6363
  TERMINUSDB_ORG   default admin
  TERMINUSDB_DB    default facty
  TERMINUSDB_USER  default admin   (v12 docker default password: root)
  TERMINUSDB_PASS  default root
  TERMINUSDB_REF   branch to work on (default main); "commit:<id>" for time-travel
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request


class TerminusError(RuntimeError):
    def __init__(self, op: str, status: int, body: str):
        super().__init__(f"terminusdb {op} failed: HTTP {status}: {body[:500]}")
        self.op, self.status, self.body = op, status, body


class Client:
    def __init__(
        self,
        url: str | None = None,
        org: str | None = None,
        db: str | None = None,
        user: str | None = None,
        password: str | None = None,
    ):
        self.url = (url or os.environ.get("TERMINUSDB_URL", "http://127.0.0.1:6363")).rstrip("/")
        self.org = org or os.environ.get("TERMINUSDB_ORG", "admin")
        self.db = db or os.environ.get("TERMINUSDB_DB", "facty")
        self.user = user or os.environ.get("TERMINUSDB_USER", "admin")
        self.password = password if password is not None else os.environ.get("TERMINUSDB_PASS", "root")
        # Working ref (branch or commit) for all document/query ops. The audit
        # trail is the commit log on this ref; set to a case branch to isolate
        # a run, "main" for the pack itself. "commit:<id>" pins a commit (time-travel).
        self.ref = os.environ.get("TERMINUSDB_REF", "main")

    def _ref_path(self) -> str:
        if self.ref.startswith("commit:"):
            return f"local/commit/{self.ref[len('commit:'):]}"
        return f"local/branch/{self.ref}"

    # -- low level ---------------------------------------------------------
    def _req(self, op: str, method: str, path: str, body=None, query: dict | None = None):
        url = f"{self.url}{path}"
        if query:
            from urllib.parse import urlencode

            url += "?" + urlencode(query)
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        token = base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            raise TerminusError(op, e.code, e.read().decode()) from e
        if not raw:
            return {}
        raw = raw.strip()
        if raw.startswith("["):
            return json.loads(raw)
        if raw.startswith("{"):
            # NDJSON (one JSON doc per line) or a single object — GET document
            # streams NDJSON; keep only object lines.
            lines = [l for l in raw.splitlines() if l.strip().startswith("{")]
            parsed = [json.loads(l) for l in lines]
            parsed = [p for p in parsed if isinstance(p, dict)]
            if len(parsed) == 1 and len(lines) == 1:
                return parsed[0]
            return parsed
        return json.loads(raw)

    def raw(self, op: str, method: str, path: str, body=None, query: dict | None = None) -> dict:
        """Escape hatch for endpoints not yet wrapped below."""
        return self._req(op, method, path, body, query)

    def _db_path(self, suffix: str = "") -> str:
        return f"/api/{suffix}{self.org}/{self.db}" if suffix else f"/api/{self.org}/{self.db}"

    def _ref_db_path(self, suffix: str) -> str:
        return f"/api/{suffix}{self.org}/{self.db}/{self._ref_path()}"

    # -- db lifecycle ------------------------------------------------------
    def create_db(self, label: str = "facty", comment: str = "") -> dict:
        # "schema": True creates the main schema graph — required before
        # POST /api/schema works (verified against terminusdb-client-python).
        return self._req("create_db", "POST", f"/api/db/{self.org}/{self.db}",
                         {"label": label, "comment": comment, "schema": True})

    def delete_db(self) -> dict:
        return self._req("delete_db", "DELETE", f"/api/db/{self.org}/{self.db}")

    def db_exists(self) -> bool:
        try:
            self._req("get_db", "GET", f"/api/db/{self.org}/{self.db}")
            return True
        except TerminusError as e:
            if e.status == 404:
                return False
            raise

    # -- schema ------------------------------------------------------------
    def install_schema(self, schema, author: str = "facty", message: str = "install schema") -> dict:
        # v12: the schema is written through the document endpoint with
        # graph_type=schema (POST /api/schema is a legacy 500). PUT-first so
        # re-running init-db on an existing db is idempotent. Verified live.
        q = {"author": author, "message": message, "graph_type": "schema"}
        try:
            return self._req("schema", "PUT", self._ref_db_path("document/"), schema, q)
        except TerminusError as e:
            if e.status == 404:
                return self._req("schema", "POST", self._ref_db_path("document/"), schema, q)
            raise

    # -- documents ---------------------------------------------------------
    def insert_docs(self, docs, author: str = "facty", message: str = "insert",
                    graph_type: str = "instance") -> dict:
        """Upsert documents (create or replace by @key).

        v12 semantics (verified live): POST errors on existing keys,
        PUT replaces but 404s on missing ones — so try PUT, fall back to POST.
        Generated @id is read-only and stripped; the server regenerates it.
        """
        body = docs if isinstance(docs, list) else [docs]
        body = [{k: v for k, v in d.items() if k != "@id"} if isinstance(d, dict) else d
                for d in body]
        q = {"author": author, "message": message, "graph_type": graph_type}
        # per-document upsert: batch PUT/POST are all-or-nothing per method in
        # v12, so loop — PUT (replace) and fall back to POST (create) on 404.
        out = []
        for d in body:
            try:
                out.append(self._req("replace", "PUT", self._ref_db_path("document/"), d, q))
            except TerminusError as e:
                if e.status == 404:
                    out.append(self._req("insert", "POST", self._ref_db_path("document/"), d, q))
                else:
                    raise
        return out

    def get_all_docs(self) -> list[dict]:
        """All instance documents on the current ref (as_list=true → one JSON array)."""
        out = self._req("get_docs", "GET", self._ref_db_path("document/"),
                        query={"graph_type": "instance", "as_list": "true"})
        return out if isinstance(out, list) else [out]

    def get_doc(self, doc_id: str) -> dict:
        """One document by id (e.g. a reference like 'Fact/<hash>')."""
        return self._req("get_doc", "GET", self._ref_db_path("document/"),
                         query={"graph_type": "instance", "id": doc_id})

    def query_docs(self, query: dict) -> dict:
        """Run a WOQL query on the current ref (branch, or commit:… for time-travel)."""
        return self._req("woql", "POST", self._ref_db_path("woql/"), query)

    # -- version control ---------------------------------------------------
    # v12: the branch name goes in the path as local/branch/<name> (verified
    # against terminusdb-client-js connectionConfig.branchURL). Slashes in
    # names are not allowed — sanitize refs at the CLI layer.
    def branch(self, name: str, origin: str = "main") -> dict:
        return self._req("branch", "POST",
                         f"/api/branch/{self.org}/{self.db}/local/branch/{name}",
                         {"origin": f"{self.org}/{self.db}/local/branch/{origin}"})

    def commit_log(self) -> dict:
        return self._req("log", "GET", f"/api/log/{self.org}/{self.db}/{self._ref_path()}")

    def squash(self) -> dict:
        return self._req("squash", "POST",
                         f"/api/squash/{self.org}/{self.db}/{self._ref_path()}")
