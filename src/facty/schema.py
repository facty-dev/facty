"""The artifact model as a TerminusDB v12 schema (schema = ontology).

Pack files are authored directly in this shape (JSON-LD documents) — loading
them is a plain insert, and the DB enforces the shape at write time.

v12 syntax (live-verified against terminusdb-server v12.0.9 — see
docs/research/deps-log.md):
  scalar field          "xsd:string" / "xsd:decimal" / "xsd:boolean" / "xsd:integer" / "xsd:date"
  optional scalar       {"@type": "Optional", "@class": "xsd:string"}
  set of datatype       {"@type": "Set", "@class": "xsd:string"}   (optional by nature)
  set of subdocument    {"@type": "Set", "@class": "Condition"}     (class needs @subdocument + @key)
  key                   "@key": {"@type": "Hash", "@fields": ["id"]}

Polymorphic values are typed, not stringly-normalized: exactly one of
valueString / valueBool / valueNum (or `var` for a {"var": name} binding).
"""

from __future__ import annotations

OPT_STR = {"@type": "Optional", "@class": "xsd:string"}
STR_SET = {"@type": "Set", "@class": "xsd:string"}

# exactly one of these per Condition/FactTemplate/Constraint
VALUE_FIELDS = {
    "valueString": {"@type": "Optional", "@class": "xsd:string"},
    "valueBool": {"@type": "Optional", "@class": "xsd:boolean"},
    "valueNum": {"@type": "Optional", "@class": "xsd:decimal"},
    "var": {"@type": "Optional", "@class": "xsd:string"},  # presence = bind-any (existence)
}

# v12.1 (versioned search): the @context enables the VectorLink index
# (`store_indices`); classes with @metadata.embedding are auto-embedded on every
# commit, versioned per commit. Query = GraphQL over the doc (NO commas),
# template = Handlebars rendering to the embeddable text.
SCHEMA: list[dict] = [
    {"@type": "@context", "@base": "terminusdb:///data/", "@schema": "terminusdb:///schema#",
     "@metadata": {"terminusdb": {"options": ["store_indices"]}}},
    {"@type": "Class", "@id": "Condition", "@subdocument": [],
     "@key": {"@type": "Random"},
     "subject": "xsd:string", "predicate": "xsd:string", **VALUE_FIELDS},
    {"@type": "Class", "@id": "Fact",
     "id": "xsd:string", "type": "xsd:string",          # case | evidence | derived
     "subject": "xsd:string", "predicate": "xsd:string", **VALUE_FIELDS,
     "confidence": "xsd:decimal", "source": "xsd:string",
     "observedAt": {"@type": "Optional", "@class": "xsd:date"},
     # set at load time (BYO-key embeddings, disk-cached, stored content-addressed);
     # lets the deterministic engine flag semantic contradiction candidates (ADR-0009)
     "embeddingSha256": OPT_STR,
     "@key": {"@type": "Hash", "@fields": ["id"]},
     # native versioned embedding (12.1): lets the deterministic engine run
     # semantic-contradiction detection over facts from the commit-indexed
     # vectors — logged in ADR-0009, never an LLM call
     "@metadata": {"embedding": {
         "query": "query($id: ID){ Fact(id: $id) { _id subject predicate valueString valueBool valueNum source } }",
         "template": "Fact {{subject}} {{predicate}} = {{valueString}}{{valueBool}}{{valueNum}} (source: {{source}}). ID: {{_id}}."}}},
    # FactTemplate: the derived-fact blueprint inside a derive action. Must be
    # a @subdocument — if it were a Fact reference, TerminusDB would create a
    # real Fact node for it and the engine would see the conclusion as a premise.
    {"@type": "Class", "@id": "FactTemplate", "@subdocument": [],
     "@key": {"@type": "Random"},
     "id": "xsd:string", "type": "xsd:string",
     "subject": "xsd:string", "predicate": "xsd:string", **VALUE_FIELDS,
     "confidence": "xsd:decimal"},  # no `source`: Fact-only field is the class discriminator
    {"@type": "Class", "@id": "Question", "@subdocument": [],
     "@key": {"@type": "Random"},
     "id": "xsd:string", "text": "xsd:string", "slot": "xsd:string",
     "mandatory": "xsd:boolean", "priority": "xsd:integer", "status": "xsd:string",
     "raisedBy": OPT_STR, "discriminates": STR_SET},
    # OpenQuestion: a question opened at runtime by a rule's `open` action.
    # Top-level (Hash key) because subdocuments can't be inserted standalone.
    {"@type": "Class", "@id": "OpenQuestion",
     "id": "xsd:string", "text": "xsd:string", "slot": "xsd:string",
     "mandatory": "xsd:boolean", "priority": "xsd:integer", "status": "xsd:string",
     "raisedBy": OPT_STR, "discriminates": STR_SET,
     "@key": {"@type": "Hash", "@fields": ["id"]}},
    {"@type": "Class", "@id": "Action", "@subdocument": [],
     "@key": {"@type": "Random"},
     "op": "xsd:string",                                 # derive | raise | open
     "fact": {"@type": "Optional", "@class": "FactTemplate"},
     "hypotheses": STR_SET,
     "question": {"@type": "Optional", "@class": "Question"}},
    {"@type": "Class", "@id": "Rule",
     "id": "xsd:string", "version": "xsd:string", "pack": "xsd:string",
     "when": {"@type": "Set", "@class": "Condition"},
     "then": {"@type": "Set", "@class": "Action"},
     "@key": {"@type": "Hash", "@fields": ["id"]}},
    {"@type": "Class", "@id": "Hypothesis",
     "id": "xsd:string", "statement": "xsd:string", "status": "xsd:string",
     "prior": "xsd:decimal",
     "claims": {"@type": "Set", "@class": "Condition"},
     "killer": OPT_STR, "horse_fate": OPT_STR, "mechanism": OPT_STR,
     "evidenceFor": STR_SET, "evidenceAgainst": STR_SET, "discriminatingTests": STR_SET,
     "support": {"@type": "Optional", "@class": "xsd:decimal"},
     "prunedBy": OPT_STR,
     "@key": {"@type": "Hash", "@fields": ["id"]}},
    {"@type": "Class", "@id": "Constraint",
     "id": "xsd:string", "type": "xsd:string",           # eliminate | support
     "hypothesis": "xsd:string",
     "when": {"@type": "Set", "@class": "Condition"},
     "reason": OPT_STR, "field": OPT_STR, **VALUE_FIELDS,
     "@key": {"@type": "Hash", "@fields": ["id"]}},
    {"@type": "Class", "@id": "Derivation",
     "id": "xsd:string", "fact": "xsd:string", "rule": "xsd:string",
     "via": STR_SET,
     "@key": {"@type": "Hash", "@fields": ["id"]}},
    {"@type": "Class", "@id": "Ranking", "@subdocument": [],
     "@key": {"@type": "Random"},
     "hypothesis": "xsd:string", "score": "xsd:decimal", "claimsProven": "xsd:decimal",
     "support": "xsd:decimal", "prior": "xsd:decimal", "status": "xsd:string"},
    {"@type": "Class", "@id": "Verdict",
     "id": "xsd:string", "case": "xsd:string", "phase": "xsd:string",
     "winner": OPT_STR,
     "ranking": {"@type": "Set", "@class": "Ranking"},
     "questions": STR_SET,
     "recommendedTest": OPT_STR,
     "trace": STR_SET,
     "@key": {"@type": "Hash", "@fields": ["id"]}},
    # ── M2: case lifecycle + ingest contract ────────────────────────────────
    # Case: the registry entry on `main` (v12 has no branch-listing endpoint —
    # GET /api/branch is 405 — so cases are tracked as docs). The case itself
    # is the branch `case-<id>`; deleting the case deletes the branch and this
    # doc. What remains after deletion: nothing in the DB; only an M7
    # attestation hash, if one was submitted.
    {"@type": "Class", "@id": "Case",
     "id": "xsd:string", "bundle": "xsd:string", "bundleVersion": "xsd:string",
     "fingerprint": OPT_STR, "engineVersion": "xsd:string", "created": "xsd:string",
     "model": OPT_STR,
     "@key": {"@type": "Hash", "@fields": ["id"]}},
    # Original: a content-addressed evidence original. id = sha256 of the bytes.
    # The untouched bytes live in the local object store (.facty/objects/<sha>);
    # the DB holds only the hash + metadata + derived nodes.
    {"@type": "Class", "@id": "Original",
     "id": "xsd:string", "path": "xsd:string", "name": "xsd:string",
     "sha256": "xsd:string", "size": "xsd:integer", "mediaType": "xsd:string",
     "source": "xsd:string",
     "@key": {"@type": "Hash", "@fields": ["id"]}},
    # CustodyEvent: who/when/what-source touched an original.
    {"@type": "Class", "@id": "CustodyEvent",
     "id": "xsd:string", "original": "xsd:string", "actor": "xsd:string",
     "source": "xsd:string", "action": "xsd:string", "at": "xsd:string",
     "@key": {"@type": "Hash", "@fields": ["id"]}},
    # ExtractedText: derived node — parser output for an original (primary vs
    # derived is explicit: Original = sacred bytes, ExtractedText = derived).
    {"@type": "Class", "@id": "ExtractedText",
     "id": "xsd:string", "original": "xsd:string", "parser": "xsd:string",
     "text": "xsd:string", "textSha256": "xsd:string",
     "@key": {"@type": "Hash", "@fields": ["id"]},
     "@metadata": {"embedding": {
         "query": "query($id: ID){ ExtractedText(id: $id) { _id text parser } }",
         "template": "{{parser}}: {{text}} ID: {{_id}}."}}},
    # Quarantine: unknown file types are listed, never dropped, never guessed.
    {"@type": "Class", "@id": "Quarantine",
     "id": "xsd:string", "original": "xsd:string", "path": "xsd:string",
     "reason": "xsd:string",
     "@key": {"@type": "Hash", "@fields": ["id"]}},
    # EvidenceChunk: a chunk of an ExtractedText + its embedding (stored
    # content-addressed in the object store, referenced by embeddingSha256).
    # Sensing-side RAG only — never read by the verdict path.
    {"@type": "Class", "@id": "EvidenceChunk",
     "id": "xsd:string", "original": "xsd:string", "extracted": "xsd:string",
     "idx": "xsd:integer", "text": "xsd:string", "textSha256": "xsd:string",
     "embeddingSha256": "xsd:string", "embeddingModel": "xsd:string",
     "@key": {"@type": "Hash", "@fields": ["id"]}},
]
