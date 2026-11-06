"""Ingest contract (M2): content-addressed originals + custody + version conflicts.

  facty ingest <dir> --source "<label>" [--case <id>]

- Originals are sacred: untouched bytes go to the content-addressed object
  store (<data-dir>/objects/<sha256>, default ./.facty/objects, gitignored).
  TerminusDB holds only hashes, metadata, and derived nodes (ExtractedText).
- Idempotent: re-ingesting the same bytes is a no-op (same sha → same Original
  id → upsert is a no-op).
- A changed file at the same path+source is a **version conflict**, recorded
  as an adjudication Fact (the engine can reason about it) — not an error.
- Custody manifest: every ingest writes CustodyEvent docs (who/when/source/path).
- Parsers (parsers.py) produce ExtractedText; unknown files are quarantined
  (listed, never dropped); images go to the BYO-key OCR path with --ocr.

Determinism note: ingest is NOT the verdict path — timestamps here are fine;
the verdict path never reads them.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import shutil
from pathlib import Path

from . import parsers

DATA_DIR = Path(os.environ.get("FACTY_DATA_DIR", ".facty")).resolve()
ACTOR = os.environ.get("FACTY_ACTOR", os.environ.get("USER", "unknown"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _docs_of(client, cls: str) -> list[dict]:
    return [d for d in client.get_all_docs() if d.get("@type") == cls]


def ingest_dir(client, src: Path, source: str, ocr: bool = False) -> dict:
    """Ingest a directory onto the client's current ref. Returns a summary."""
    src = Path(src)
    objects = DATA_DIR / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    summary = {"added": [], "skipped": [], "conflicts": [], "quarantined": [], "extracted": [], "ocr": []}
    existing_originals = {d["id"]: d for d in _docs_of(client, "Original")}
    by_path = {}
    for d in existing_originals.values():
        by_path.setdefault((d["path"], d["source"]), d)

    files = sorted(p for p in src.rglob("*") if p.is_file())
    new_docs: list[dict] = []
    for f in files:
        rel = str(f.relative_to(src))
        data = f.read_bytes()
        sha = _sha256(data)
        obj = objects / sha
        now = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")

        if sha in existing_originals:
            summary["skipped"].append(rel)
            continue
        # store the original bytes (content-addressed, write-once)
        if not obj.exists():
            tmp = objects / (sha + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, obj)
        orig = {"@type": "Original", "id": sha, "path": rel, "name": f.name,
                "sha256": sha, "size": len(data),
                "mediaType": parsers.media_type(f), "source": source}
        cust = {"@type": "CustodyEvent",
                "id": "cust-" + _sha256(f"{sha}|{source}|{rel}|ingest".encode())[:16],
                "original": sha, "actor": ACTOR, "source": source,
                "action": "ingest", "at": now}
        new_docs += [orig, cust]

        # version conflict: same path+source, different bytes
        prev = by_path.get((rel, source))
        if prev and prev["sha256"] != sha:
            vc_id = f"vc-{_sha256(prev['sha256'].encode())[:8]}-{_sha256(sha.encode())[:8]}"
            new_docs.append({"@type": "Fact", "id": vc_id, "type": "case",
                             "subject": rel, "predicate": "versionConflict",
                             "valueString": f"{prev['sha256'][:12]} -> {sha[:12]}",
                             "confidence": 1.0, "source": f"ingest:{source}"})
            summary["conflicts"].append(rel)
        by_path[(rel, source)] = {"sha256": sha}

        # parse → derived ExtractedText (or quarantine / OCR)
        try:
            text = parsers.parse(f)
            ext_id = "ext-" + _sha256(f"{sha}|{parsers.parser_name(f)}".encode())[:12]
            new_docs.append({"@type": "ExtractedText", "id": ext_id, "original": sha,
                             "parser": parsers.parser_name(f), "text": text,
                             "textSha256": _sha256(text.encode())})
            summary["extracted"].append(rel)
        except parsers.NeedsOCR:
            if ocr:
                summary["ocr"].append(rel)  # OCR runs on the BYO-key path at sense time
            else:
                new_docs.append({"@type": "Quarantine", "id": "q-" + sha[:12],
                                 "original": sha, "path": rel,
                                 "reason": "image — needs the BYO-key OCR path (--ocr)"})
                summary["quarantined"].append(rel)
        except parsers.UnknownFormat as e:
            new_docs.append({"@type": "Quarantine", "id": "q-" + sha[:12],
                             "original": sha, "path": rel,
                             "reason": f"unknown format: {e}"})
            summary["quarantined"].append(rel)
        summary["added"].append(rel)

    if new_docs:
        client.insert_docs(new_docs, message=f"ingest {source}: {len(files)} files "
                                              f"({len(summary['added'])} new, {len(summary['skipped'])} unchanged)")
    return summary


def verify_originals(client, data_dir: Path | None = None) -> dict:
    """Re-hash every stored object and compare to its Original doc — originals
    must verify unchanged by hash."""
    data_dir = data_dir or DATA_DIR
    objects = data_dir / "objects"
    bad = []
    checked = 0
    for d in _docs_of(client, "Original"):
        obj = objects / d["sha256"]
        if not obj.exists() or _sha256(obj.read_bytes()) != d["sha256"]:
            bad.append(d["path"])
        checked += 1
    return {"checked": checked, "mismatches": bad}
