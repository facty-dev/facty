# ADR-0006 — bundles: the signed domain unit, and the trust spine (M1)

**Status:** accepted (v0.1 milestone M1, business-foundation build)
**Related:** [ADR-0005](0005-cleanroom-stack-replaces-poc.md) (stack), [ADR-0003](0003-detective-dss-neurosymbolic-core.md) (invariants)

## What problem are we solving?

The PoC called the domain unit a "pack" and stored it as loose JSON files with
no integrity or authenticity. For a commercial distribution (Apache-2.0 engine,
closed signed bundles) we need: one artifact kind with several serializations,
a signature gate at the single write choke point, and keys that never touch the
repo.

## Decision

The domain unit is renamed **bundle** ("pack" is retired — the bundle is the
costume). A bundle is ONE functional artifact with several serializations —
the manifest carries the characteristics, not the name:

| Projection | Shape | Used by |
|---|---|---|
| directory | `bundles/<id>/{manifest.json, bundle.json, bundle.sig, fixtures/, conformance/, evidence/…}` | version control, authoring |
| database | the bundle's JSON-LD documents inserted on a TerminusDB branch; schema enforced at every write | the engine (verdict path) |
| encrypted file | one Fernet-encrypted file (passphrase-derived key) | `facty export --signed --encrypt` / `facty replay` (M7) |

**Bundle format v2** — `manifest.json` = `{id, version, kind: domain|case,
engine:{name,version}, fingerprint, publicKey (b64 raw Ed25519), created,
contents: {relpath: sha256}}`; `bundle.json` = the JSON-LD document array;
`bundle.sig` = Ed25519 signature over the canonical manifest (which covers all
content hashes).

**Trust spine (M1):**

- `facty keys init` generates an Ed25519 keypair in `~/.facty/keys/`
  (override `FACTY_KEYS_DIR`); private key file mode 0600, **never committed**.
  Fingerprint = sha256(raw pubkey)[:16].
- `facty bundle sign <dir>` signs with a private key; `facty bundle verify`
  checks signature + content hashes using only the **public key embedded in the
  manifest** — verification works anywhere, signing only where the key lives.
- `facty bundle load` is the gate: signed v2 bundles verify before insert;
  unsigned or legacy v1 bundles are **refused** unless `--dev` / `FACTY_DEV=1`.
- Demo bundles in `bundles/` are signed (key `c50ed3ed27662dd3`, label `demo`);
  the private key exists only in the PO's `~/.facty/keys/`. CI/selftest verify
  with the embedded public key; `--dev` is the documented escape hatch.

## Consequences

- Positive: tamper-evidence on every bundle byte; one artifact model across
  disk/DB/encrypted export; the DB schema stays the single write choke point;
  zero key material in the repo (verified by tests using `FACTY_KEYS_DIR`).
- Costs accepted: Ed25519 via `cryptography` (boring, well-maintained) added as
  a dependency; legacy PoC `terminusdb/pack.json` dirs load only under `--dev`
  until the oracle is retired; manifests must be re-signed on any content edit
  (`bundle sign`), which is the intended friction.
- M6 metering and M7 attestation reuse the same keys (signed usage reports,
  Merkle roots).
