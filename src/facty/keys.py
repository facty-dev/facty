"""Signing keys (M1 trust spine): Ed25519 keypairs for bundle signatures.

Keys live OUTSIDE the repo, in ~/.facty/keys/ (override: FACTY_KEYS_DIR) —
private keys are never committed, never logged. A key is identified by its
fingerprint: sha256(raw public key), hex, first 16 chars. The public key is
embedded in every bundle manifest, so `facty bundle verify` works anywhere
with no key material beyond the bundle itself.

  facty keys init [--name <label>]   generate a keypair, print the fingerprint
  facty keys list                    list fingerprints (+ label) with public keys

Signing is deterministic Ed25519 over canonical JSON (see bundle.py).
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

KEYS_DIR = Path(os.environ.get("FACTY_KEYS_DIR", "~/.facty/keys")).expanduser()


class KeyError_(RuntimeError):
    pass


def fingerprint_of_public_raw(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()[:16]


def _dir(keys_dir: Path | None) -> Path:
    return keys_dir if keys_dir is not None else KEYS_DIR


def init_key(name: str = "default", keys_dir: Path | None = None) -> tuple[str, Path]:
    """Generate an Ed25519 keypair. Returns (fingerprint, public key path).
    Private key: <fp>.key (PKCS8 PEM, mode 0600). Public: <fp>.pub (raw, b64)."""
    keys_dir = _dir(keys_dir)
    keys_dir.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    raw_pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    fp = fingerprint_of_public_raw(raw_pub)
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    key_path = keys_dir / f"{fp}.key"
    key_path.write_bytes(priv_pem)
    os.chmod(key_path, 0o600)
    pub_path = keys_dir / f"{fp}.pub"
    pub_path.write_text(base64.b64encode(raw_pub).decode() + "\n")
    label_path = keys_dir / f"{fp}.name"
    label_path.write_text(name + "\n")
    return fp, pub_path


def list_keys(keys_dir: Path | None = None) -> list[dict]:
    keys_dir = _dir(keys_dir)
    out = []
    if not keys_dir.is_dir():
        return out
    for pub in sorted(keys_dir.glob("*.pub")):
        fp = pub.stem
        label = (keys_dir / f"{fp}.name").read_text().strip() if (keys_dir / f"{fp}.name").exists() else ""
        out.append({"fingerprint": fp, "label": label, "has_private": (keys_dir / f"{fp}.key").exists()})
    return out


def load_private(fingerprint: str | None = None, keys_dir: Path | None = None) -> tuple[str, Ed25519PrivateKey]:
    """Load a private key by fingerprint; with None, use the sole private key
    (error if several — ambiguous)."""
    keys_dir = _dir(keys_dir)
    if fingerprint is None:
        keys = sorted(keys_dir.glob("*.key"))
        if len(keys) != 1:
            fps = [k.stem for k in keys] or [k["fingerprint"] for k in list_keys(keys_dir)]
            raise KeyError_(f"no --key given and {len(keys)} private keys present: {fps} — pass --key <fingerprint>")
        fingerprint = keys[0].stem
    path = keys_dir / f"{fingerprint}.key"
    if not path.exists():
        raise KeyError_(f"no private key for fingerprint {fingerprint} in {keys_dir}")
    priv = serialization.load_pem_private_key(path.read_bytes(), password=None)
    return fingerprint, priv  # type: ignore[return-value]


def load_public_raw(fingerprint: str, keys_dir: Path | None = None) -> bytes:
    keys_dir = _dir(keys_dir)
    path = keys_dir / f"{fingerprint}.pub"
    if not path.exists():
        raise KeyError_(f"no public key for fingerprint {fingerprint} in {keys_dir}")
    return base64.b64decode(path.read_text().strip())


def public_raw_from_b64(b64: str) -> bytes:
    return base64.b64decode(b64)


def sign(priv: Ed25519PrivateKey, data: bytes) -> bytes:
    return priv.sign(data)


def verify(pub_raw: bytes, data: bytes, signature: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(signature, data)
        return True
    except Exception:
        return False
