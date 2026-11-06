# ADR-0007 — case lifecycle, ingest contract, and the codemode sandbox (M2)

**Status:** accepted (v0.1 milestone M2)
**Related:** [ADR-0005](0005-cleanroom-stack-replaces-poc.md), [ADR-0006](0006-bundle-trust-spine.md)

## Decisions

1. **A case is a TerminusDB branch — real and deletable.** `facty case init <id>
   --bundle <dir>` creates branch `case-<id>`, verifies + loads the signed bundle
   onto it (the M1 gate), and registers a `Case` manifest doc (bundle id/version,
   key fingerprint, engine version, model) — on `main`, because v12 has no
   branch-listing endpoint (GET /api/branch → 405, verified). `case delete`
   issues a real branch DELETE plus registry-doc removal; what remains in the DB
   is nothing — only an M7 attestation hash, if one was ever submitted.
2. **Ingest contract.** `facty ingest <dir> --source <label> --case <id>`:
   originals are sacred — untouched bytes go to a content-addressed object store
   (`.facty/objects/<sha256>`, gitignored; `FACTY_DATA_DIR` override); TerminusDB
   holds only hashes + metadata (`Original`) + derived nodes (`ExtractedText`).
   Re-ingest is idempotent (same sha → no-op). A changed file at the same
   path+source is a **version conflict recorded as an adjudication Fact**
   (`predicate: versionConflict`), not an error. Every ingest writes `CustodyEvent`
   docs (actor/when/source). `ingest` re-hashes all stored objects at the end and
   fails on any mismatch.
3. **Parsers** (`parsers.py`): pdf (pypdf), docx (python-docx), xlsx/xls
   (openpyxl), csv/json/text/markdown, eml/msg/mbox (stdlib email/mailbox +
   extract-msg). Images have no local parser → the BYO-key OCR path (`--ocr`),
   never guessed. Unknown formats are **quarantined** (listed in a `Quarantine`
   doc, never dropped). Deps are the boring standard ones, added via uv.
4. **Codemode under programmatic control** (`codemode.py` + `sandbox.py`): for NLU /
   structured extraction / messy files, pydantic-ai (typed output, `tools=[]`)
   makes the LLM **write** a self-contained extractor script; `sandbox.run_code`
   executes it isolated — SmolVM micro-VM when the binary + `facty` machine exist
   (code+files travel over stdin as a JSON payload to a tiny in-VM bootstrap),
   otherwise a local `python -I` subprocess with a hard timeout (dev only —
   NOT network-isolated; SmolVM is the zero-data-trust path). stdout JSON is
   validated against the pydantic model (`SensedFacts`). This is induction-only:
   never an interactive chat session, never in the verdict path. Live-verified:
   mistral-large-4 wrote a regex extractor (42s), the sandbox ran it (0.06s),
   3 correctly-vocabularied facts out of `police-report.txt`.
5. **CLI framework:** Typer (see deps-log) — all of the above hangs off
   `facty case|ingest|sense|extract`.

## Consequences

- Positive: the demo loop runs headless end-to-end (`scripts/demo.sh`, live LLM
  sensing → deterministic verdict); evidence bytes never leave the machine except
  to the BYO-key LLM; originals are tamper-evident by hash; deletion semantics
  are real and documented.
- Costs accepted: ingest timestamps are wall-clock (fine — not the verdict path);
  the local sandbox backend is not network-isolated (documented; SmolVM is the
  production isolation, still an open ADR-0005 item); four boring parser deps.
- v12 quirks found live and logged in deps-log.md: bodyless DELETE needs
  `Content-Length: 0`; doc DELETE needs author/message and the full Hash-keyed
  `@id`; no branch listing.
