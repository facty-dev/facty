"""Bundles (M1): the signed, versioned domain unit — and the one artifact kind
with several serializations.

A bundle is a manifest + contents + an Ed25519 signature over the canonical
manifest. The SAME functional artifact, three projections:

  directory   bundles/<id>/{manifest.json, bundle.json, bundle.sig, ...}
              (plain text, version-controlled)
  database    the bundle's JSON-LD documents inserted on a TerminusDB branch
              (the engine instantiates it there; schema enforced at write time)
  file        an encrypted single-file export (Fernet, passphrase) for
              `facty export --signed --encrypt` / `facty replay` (M7)

v2 directory layout:
  manifest.json   {id, version, kind: "domain"|"case", engine:{name,version},
                   fingerprint, publicKey (b64 raw), created,
                   contents: {relpath: sha256}}   — everything except the sig
  bundle.json     the JSON-LD document array (ontology/rules/hypotheses/
                  constraints/questions as schema classes) + optional sections
  bundle.sig      {"fingerprint": ..., "signature": b64}
  fixtures/ conformance/ ...   any extra files, covered by manifest.contents

Legacy v1 dirs (a bare pack.json, e.g. the PoC oracle cases under engine/cases)
are readable in --dev mode only: unsigned bundles are refused otherwise.

Env: FACTY_DEV=1 is the global escape hatch; --dev on the CLI commands.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization

from . import keys

MANIFEST = "manifest.json"
DOCS = "bundle.json"
SIG = "bundle.sig"


class BundleError(RuntimeError):
    pass


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dev_mode(flag: bool = False) -> bool:
    return flag or os.environ.get("FACTY_DEV", "") == "1"


def engine_version() -> str:
    try:
        from importlib.metadata import version
        return version("facty")
    except Exception:
        return "0.0.0+unknown"


class Bundle:
    """One artifact, multiple serializations: dir ↔ db docs ↔ encrypted file."""

    def __init__(self, manifest: dict, docs: list[dict], path: Path | None = None):
        self.manifest = manifest
        self.docs = docs
        self.path = path

    @property
    def id(self) -> str:
        return self.manifest["id"]

    @property
    def version(self) -> str:
        return self.manifest["version"]

    @property
    def fingerprint(self) -> str | None:
        return self.manifest.get("fingerprint")

    # ── directory projection ────────────────────────────────────────────────

    @classmethod
    def from_dir(cls, path: str | Path, dev: bool = False) -> "Bundle":
        """Load a bundle directory. v2 (manifest+bundle.json) requires a valid
        signature unless dev. v1 legacy (bare pack.json / terminusdb/pack.json)
        is dev-only."""
        path = Path(path)
        if (path / MANIFEST).exists():
            b = cls._from_dir_v2(path)
            if not dev_mode(dev):
                b.verify_or_raise()
            return b
        for legacy in (path / "pack.json", path / "terminusdb" / "pack.json"):
            if legacy.exists():
                if not dev_mode(dev):
                    raise BundleError(
                        f"{path}: unsigned legacy bundle (v1) refused — re-sign as v2 "
                        f"(`facty bundle sign`) or pass --dev / FACTY_DEV=1")
                docs = json.loads(legacy.read_text())
                return cls({"id": path.name, "version": "1.0.0", "kind": "domain",
                            "legacy": True}, docs, path)
        raise BundleError(f"{path}: not a bundle (no {MANIFEST} or pack.json)")

    @classmethod
    def _from_dir_v2(cls, path: Path) -> "Bundle":
        manifest = json.loads((path / MANIFEST).read_text())
        if not (path / DOCS).exists():
            raise BundleError(f"{path}: manifest without {DOCS}")
        docs = json.loads((path / DOCS).read_text())
        if isinstance(docs, dict) and "documents" in docs:
            docs = docs["documents"]
        return cls(manifest, docs, path)

    def contents_map(self, path: Path) -> dict[str, str]:
        out = {}
        for f in sorted(path.rglob("*")):
            if f.is_file() and f.name not in (MANIFEST, SIG):
                out[str(f.relative_to(path))] = sha256_file(f)
        return out

    def verify_or_raise(self) -> None:
        if self.path is None:
            raise BundleError("cannot verify: bundle not loaded from a directory")
        m = self.manifest
        if not (self.path / SIG).exists():
            raise BundleError(f"{self.path}: unsigned bundle (no {SIG}) — refused outside --dev")
        sig = json.loads((self.path / SIG).read_text())
        if sig.get("fingerprint") != m.get("fingerprint"):
            raise BundleError(f"{self.path}: signature fingerprint does not match manifest")
        actual = self.contents_map(self.path)
        if actual != m.get("contents"):
            raise BundleError(f"{self.path}: content hashes differ from manifest (tampered or stale)")
        pub_raw = keys.public_raw_from_b64(m["publicKey"])
        ok = keys.verify(pub_raw, canonical(m), base64.b64decode(sig["signature"]))
        if not ok:
            raise BundleError(f"{self.path}: signature verification FAILED")

    def sign(self, key_fingerprint: str | None = None) -> str:
        """(Re)write manifest fingerprint/publicKey/contents and bundle.sig.
        Returns the fingerprint used. Requires the private key (never leaves
        ~/.facty/keys)."""
        if self.path is None:
            raise BundleError("cannot sign: bundle not loaded from a directory")
        fp, priv = keys.load_private(key_fingerprint)
        raw_pub = priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        m = dict(self.manifest)
        m["fingerprint"] = fp
        m["publicKey"] = base64.b64encode(raw_pub).decode()
        m["contents"] = self.contents_map(self.path)
        m.setdefault("engine", {"name": "facty", "version": engine_version()})
        import datetime
        m["created"] = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
        (self.path / MANIFEST).write_text(json.dumps(m, indent=2, sort_keys=True) + "\n")
        self.manifest = m
        sig = base64.b64encode(keys.sign(priv, canonical(m))).decode()
        (self.path / SIG).write_text(json.dumps({"fingerprint": fp, "signature": sig}, indent=2) + "\n")
        return fp

    # ── database projection ─────────────────────────────────────────────────

    @classmethod
    def from_db(cls, client, name: str) -> "Bundle":
        """Instantiate the bundle layer from a TerminusDB ref: all pack-level
        docs on the ref (Facts/Verdicts/Derivations/OpenQuestions excluded)."""
        docs = [d for d in client.get_all_docs()
                if d.get("@type") in ("Rule", "Hypothesis", "Constraint", "Question")]
        return cls({"id": name, "version": "db", "kind": "domain", "source": "terminusdb"}, docs)

    def load_into(self, client, name: str | None = None, dev: bool = False) -> dict:
        """The trust gate: verify (unless --dev), then insert into the current
        ref as schema-validated documents — the single write choke point."""
        if (self.path is not None) and (self.path / MANIFEST).exists() and not dev_mode(dev):
            self.verify_or_raise()
        name = name or self.id
        client.insert_docs(self.docs, message=f"load bundle {name}@{self.version}")
        return {k: sum(1 for d in self.docs if d.get("@type") == k)
                for k in ("Rule", "Hypothesis", "Constraint", "Question")}

    # ── encrypted file projection (M7 export/replay) ────────────────────────

    def export(self, out_path: str | Path, passphrase: str) -> Path:
        """Serialize the whole bundle (manifest + docs + sig) as one encrypted
        file. Fernet key derived from the passphrase (sha256, urlsafe b64)."""
        out_path = Path(out_path)
        payload = canonical({
            "manifest": self.manifest,
            "docs": self.docs,
            "sig": json.loads((self.path / SIG).read_text()) if (self.path and (self.path / SIG).exists()) else None,
        })
        key = base64.urlsafe_b64encode(hashlib.sha256(passphrase.encode()).digest())
        out_path.write_bytes(Fernet(key).encrypt(payload))
        return out_path

    @classmethod
    def from_file(cls, path: str | Path, passphrase: str) -> "Bundle":
        path = Path(path)
        key = base64.urlsafe_b64encode(hashlib.sha256(passphrase.encode()).digest())
        try:
            payload = json.loads(Fernet(key).decrypt(path.read_bytes()))
        except InvalidToken:
            raise BundleError(f"{path}: wrong passphrase or not an encrypted bundle")
        b = cls(payload["manifest"], payload["docs"])
        b._sig = payload.get("sig")
        return b
