"""M1 trust-spine tests: Ed25519 keys, bundle v2 sign/verify, the --dev gate,
and the encrypted file projection (same artifact, another serialization).

Run: uv run pytest tests/test_m1_bundle.py
Keys are generated into a tmp dir via FACTY_KEYS_DIR — nothing touches
~/.facty/keys and no key material is committed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from facty import bundle as bundle_mod
from facty import keys
from facty.bundle import Bundle, BundleError


@pytest.fixture()
def keys_dir(tmp_path, monkeypatch):
    d = tmp_path / "keys"
    monkeypatch.setenv("FACTY_KEYS_DIR", str(d))
    # keys.py reads KEYS_DIR at import time — point the module at tmp too
    monkeypatch.setattr(keys, "KEYS_DIR", d)
    monkeypatch.setattr(bundle_mod.keys, "KEYS_DIR", d)
    return d


@pytest.fixture()
def bundle_dir(tmp_path, keys_dir):
    d = tmp_path / "bundles" / "test-bundle"
    (d / "fixtures").mkdir(parents=True)
    (d / "bundle.json").write_text(json.dumps([
        {"@type": "Rule", "id": "r1", "version": "1", "pack": "test-bundle",
         "when": [{"@type": "Condition", "subject": "s", "predicate": "p", "valueBool": True}],
         "then": [{"@type": "Action", "op": "raise", "hypotheses": ["H1"]}]},
    ]))
    (d / "fixtures" / "case.json").write_text(json.dumps([{"@type": "Fact", "id": "f1"}]))
    return d


def make_signed(bundle_dir, keys_dir):
    fp, _ = keys.init_key("test", keys_dir=keys_dir)
    docs = json.loads((bundle_dir / "bundle.json").read_text())
    b = Bundle({"id": "test-bundle", "version": "2.0.0", "kind": "domain"}, docs, path=bundle_dir)
    b.sign(fp)
    return b, fp


def test_keys_init_and_fingerprint(keys_dir):
    fp, pub = keys.init_key("a", keys_dir=keys_dir)
    assert len(fp) == 16
    assert (keys_dir / f"{fp}.key").stat().st_mode & 0o777 == 0o600  # private key not world-readable
    assert (keys_dir / f"{fp}.pub").exists()
    listed = keys.list_keys(keys_dir)
    assert listed[0]["fingerprint"] == fp and listed[0]["has_private"]


def test_sign_verify_roundtrip(bundle_dir, keys_dir):
    b, fp = make_signed(bundle_dir, keys_dir)
    loaded = Bundle.from_dir(bundle_dir)  # no --dev: must verify against embedded pubkey
    assert loaded.fingerprint == fp
    loaded.verify_or_raise()


def test_unsigned_refused_without_dev(bundle_dir, keys_dir):
    docs = json.loads((bundle_dir / "bundle.json").read_text())
    Bundle({"id": "test-bundle", "version": "2.0.0", "kind": "domain"}, docs, path=bundle_dir)
    (bundle_dir / "manifest.json").write_text(json.dumps({"id": "test-bundle", "version": "2.0.0"}))
    with pytest.raises(BundleError, match="unsigned"):
        Bundle.from_dir(bundle_dir)
    # --dev escape hatch loads it
    b = Bundle.from_dir(bundle_dir, dev=True)
    assert b.id == "test-bundle"


def test_tampered_content_detected(bundle_dir, keys_dir):
    make_signed(bundle_dir, keys_dir)
    docs = json.loads((bundle_dir / "bundle.json").read_text())
    docs[0]["id"] = "r-evil"  # valid JSON, changed content
    (bundle_dir / "bundle.json").write_text(json.dumps(docs))
    with pytest.raises(BundleError, match="content hashes differ"):
        Bundle.from_dir(bundle_dir).verify_or_raise()


def test_tampered_signature_detected(bundle_dir, keys_dir):
    make_signed(bundle_dir, keys_dir)
    sig_path = bundle_dir / "bundle.sig"
    sig = json.loads(sig_path.read_text())
    sig["signature"] = "AAAA" + sig["signature"][4:]
    sig_path.write_text(json.dumps(sig))
    with pytest.raises(BundleError, match="signature verification FAILED"):
        Bundle.from_dir(bundle_dir).verify_or_raise()


def test_encrypted_file_projection_roundtrip(bundle_dir, keys_dir):
    b, fp = make_signed(bundle_dir, keys_dir)
    out = b.export(bundle_dir.parent / "export.factyenc", passphrase="hunter2")
    # ciphertext must not contain plaintext content
    assert b"r1" not in out.read_bytes() or b"Rule" not in out.read_bytes()
    loaded = Bundle.from_file(out, passphrase="hunter2")
    assert loaded.docs == b.docs and loaded.manifest["id"] == "test-bundle"
    with pytest.raises(BundleError, match="wrong passphrase"):
        Bundle.from_file(out, passphrase="wrong")


def test_legacy_v1_pack_refused_outside_dev(tmp_path):
    d = tmp_path / "legacy"
    d.mkdir()
    (d / "pack.json").write_text(json.dumps([{"@type": "Rule", "id": "r1"}]))
    with pytest.raises(BundleError, match="--dev"):
        Bundle.from_dir(d)
    assert Bundle.from_dir(d, dev=True).docs[0]["id"] == "r1"
