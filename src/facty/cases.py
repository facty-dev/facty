"""Case lifecycle (M2): a case IS a TerminusDB branch — real, deletable.

  facty case init <id> --bundle <dir>     create branch case-<id>, verify+load the
                                          signed bundle onto it, register a Case doc
  facty case list                         Case registry docs on main
  facty case branch <id> <name>           branch off a case
  facty case show <id>                    case manifest + doc counts on its branch
  facty case delete <id>                  DELETE the branch + the registry doc.
                                          What remains: nothing in the DB; only an
                                          M7 attestation hash, if one was submitted.

The registry lives on `main` because v12 has no branch-listing endpoint
(GET /api/branch → 405, verified). Case ids are sanitized (no "/" — branch
names can't contain slashes).
"""

from __future__ import annotations

import datetime
import re

from . import bundle as bundle_mod
from .bundle import engine_version

CASE_PREFIX = "case-"


def _slug(case_id: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]", "-", case_id)
    return CASE_PREFIX + s


def _docs_of(client, cls: str) -> list[dict]:
    return [d for d in client.get_all_docs() if d.get("@type") == cls]


def case_init(client, case_id: str, bundle_dir: str, dev: bool = False,
              model: str | None = None) -> dict:
    """Create the case branch, load the (signed) bundle, register the Case doc."""
    branch = _slug(case_id)
    b = bundle_mod.Bundle.from_dir(bundle_dir, dev=dev)  # gate: verifies unless --dev
    main = client.ref
    client.ref = branch
    try:
        client.branch(branch, origin="main")
    except Exception:
        pass  # already exists
    counts = b.load_into(client, b.id, dev=dev)
    case_doc = {"@type": "Case", "id": case_id, "bundle": b.id,
                "bundleVersion": b.version, "fingerprint": b.fingerprint or "",
                "engineVersion": engine_version(),
                "created": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
                **({"model": model} if model else {})}
    client.insert_docs([case_doc], message=f"case init {case_id} (bundle {b.id}@{b.version})")
    client.ref = main
    # registry on main
    client.insert_docs([case_doc], message=f"register case {case_id}")
    return {"case": case_id, "branch": branch, "bundle": f"{b.id}@{b.version}",
            "fingerprint": b.fingerprint, "docs": counts}


def case_list(client) -> list[dict]:
    return sorted(_docs_of(client, "Case"), key=lambda d: d["id"])


def case_branch(client, case_id: str, name: str) -> str:
    src, dst = _slug(case_id), _slug(name)
    client.branch(dst, origin=src)
    return dst


def case_delete(client, case_id: str) -> dict:
    """Real deletion: branch DELETE + registry doc removal. Returns what remains."""
    branch = _slug(case_id)
    client.delete_branch(branch)
    main = client.ref
    client.ref = "main"
    remaining = [d for d in _docs_of(client, "Case") if d["id"] == case_id]
    if remaining:
        # Hash-keyed docs are addressed by their full @id (Case/<sha>), not the
        # logical id — v12 quirk, logged in docs/research/deps-log.md
        client.delete_doc(remaining[0]["@id"], message=f"unregister case {case_id}")
    client.ref = main
    # what remains after deletion: nothing in the DB. Only an M7 attestation
    # hash survives (submitted externally, content-free), if any.
    return {"deleted_branch": branch, "case": case_id,
            "remains_in_db": [], "note": "only an attestation hash (M7), if submitted, survives outside the DB"}


def case_show(client, case_id: str) -> dict:
    branch = _slug(case_id)
    main = client.ref
    client.ref = branch
    try:
        docs = client.get_all_docs()
    except Exception:
        client.ref = main
        return {"case": case_id, "error": f"no branch {branch}"}
    client.ref = main
    counts: dict[str, int] = {}
    for d in docs:
        counts[d.get("@type", "?")] = counts.get(d.get("@type", "?"), 0) + 1
    case_doc = next((d for d in _docs_of(client, "Case") if d["id"] == case_id), None)
    return {"case": case_id, "branch": branch, "manifest": case_doc, "docs": counts}
