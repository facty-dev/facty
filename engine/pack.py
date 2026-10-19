#!/usr/bin/env python3
# pack.py — the Pack Studio library: validate, test, and diagnose
# knowledge packs (the authoring side of the detective DSS, PRD-007).
#
# A pack is a domain's costume: the rules, constraints, and hypotheses
# the engine wears (packs/<slug>/pack/), plus the optional sensor config
# (classify.json, sensor/decisions.json) and the test scenarios
# (tests/facts-*.json + tests/facts-*.expected.json). The layout mirrors
# a case's — engine.run_case(pack_dir, facts=...) works unchanged on it
# (PRD-007 Appendix B).
#
# This module is the DETERMINISTIC half of the authoring path: schema
# validation + cross-artifact checks (REQ-001/002), the test run with
# gap analysis (REQ-003/004/005), the scenario runner (REQ-006), and
# the draft staging policy (REQ-015). The LLM draft ops live in the CLI
# (engine/cli.py) — like the sensing ops they are induction only and
# never in the verdict path (ADR-0003 §1). stdlib only (ADR-0004): this
# module runs in the gondolin VM snapshot and CI.
#
# The gap analysis (diagnose, REQ-004) is deterministic — no
# heuristics:
#   dead rules           — a rule that never fires on the fact set (no
#                          entry in the trace's fired rules)
#   unraised hypotheses  — a hypothesis in the pack no rule ever raises
#   pruned hypotheses    — eliminated by a constraint, with its reason
#   unanswered questions — an open question whose slot the fact set
#                          never speaks: no fact (sensed or derived)
#                          carries the slot as its subject or predicate
#                          (the artifact model's "filled by the senses";
#                          the engine itself never flips a question's
#                          status, so this is the mechanical reading of
#                          "the fact set leaves the question unanswered")
#
# Library:
#   import pack
#   report = pack.validate_pack("packs/triage-alert-flood")
#   result = pack.run_pack_test("packs/triage-alert-flood", facts)
#   gaps = pack.diagnose("packs/triage-alert-flood", facts)
#   staged = pack.stage_draft("packs/triage-alert-flood", "pack/rules.json", rules)

import json
import shutil
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402

PACKS_DIR = ENGINE_DIR.parent / "packs"

# The pack layout (PRD-007 Appendix B): pack/{rules,constraints,hypotheses}.json
# are required; classify.json + sensor/decisions.json are optional.
PACK_ARTIFACTS = (("rules.json", "rule.schema.json"),
                  ("constraints.json", "constraint.schema.json"),
                  ("hypotheses.json", "hypothesis.schema.json"))

# classify.json's structural contract (mirrors label.load_config — kept
# inline so this module stays stdlib + engine only).
CLASSIFY_REQUIRED = ("file", "textColumn", "labels")
CLASSIFY_BACKENDS = ("local", "strom", "hybrid")
CLASSIFY_PREPS = ("none", "parser", "llm-filter")
CLASSIFY_PRECISIONS = ("fp32", "fp16", "int8")
CLASSIFY_SCORINGS = ("entail", "margin")

# sensor/decisions.json's structural contract (the Strom question set —
# mirrors label.DECISIONS_DOC_SCHEMA + the question shapes; the subset
# validator ignores minProperties, so the non-empty check is explicit).
DECISIONS_SCHEMA = {
    "type": "object",
    "required": ["model", "questions"],
    "properties": {
        "model": {"type": "string"},
        "questions": {"type": "object", "minProperties": 1},
    },
}

# The classify.json schema handed to the suggest-labels draft op (the
# judge checks the ranges + the non-empty labels the subset validator
# ignores).
CLASSIFY_SCHEMA = {
    "type": "object",
    "required": ["file", "textColumn", "labels"],
    "properties": {
        "file": {"type": "string",
                 "description": "the evidence file, relative to the pack "
                                "(e.g. evidence/alerts.csv)"},
        "idColumn": {"type": "string"},
        "textColumn": {"type": "string"},
        "sourceColumn": {"type": "string"},
        "timeColumn": {"type": "string"},
        "subject": {"type": "string"},
        "labels": {"type": "array", "items": {"type": "string"},
                   "description": "2-4 short, mutually exclusive noun phrases"},
        "template": {"type": "string",
                     "description": "one {} where the label goes"},
        "scoring": {"type": "string", "enum": ["entail", "margin"]},
        "threshold": {"type": "number",
                      "description": "the confidence gate, 0-1"},
        "model": {"type": "string"},
        "precision": {"type": "string", "enum": ["fp32", "fp16", "int8"]},
        "prep": {"type": "string", "enum": ["none", "parser", "llm-filter"]},
        "backend": {"type": "string", "enum": ["local", "strom", "hybrid"]},
    },
}

# The keys a scenario's expected outcome may assert (facts-<scenario>.expected.json).
EXPECTED_KEYS = ("verdict", "pruned", "derived", "recommended_test")


class PackError(Exception):
    """A named pack violation (the CLI turns it into exit 1)."""


# ── Pack resolution + listing (REQ-008/009) ─────────────────────────

def resolve_pack(arg, packs_dir=None):
    """A pack directory path, or a slug under packs/ (mirrors
    cli.resolve_case). Raises PackError when it does not exist."""
    base = Path(packs_dir) if packs_dir is not None else PACKS_DIR
    p = Path(arg)
    if p.is_dir() and (p / "pack" / "rules.json").exists():
        return p
    if (base / arg).is_dir() and ((base / arg) / "pack" / "rules.json").exists():
        return base / arg
    raise PackError(f"the pack directory does not exist: {arg} "
                    f"(packs live at {base}/<slug>/)")


def list_packs(packs_dir=None):
    """The packs under packs/ (REQ-008): [{slug, dir, counts, classify,
    decisions}] — the artifact counts. Tolerant: a pack with unreadable
    artifacts still lists (its counts read as 0 — validate names the
    violations)."""
    base = Path(packs_dir) if packs_dir is not None else PACKS_DIR
    out = []
    if not base.is_dir():
        return out
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d / "pack" / "rules.json").exists():
            out.append(pack_summary(d))
    return out


def pack_summary(pack_dir):
    """One pack's summary: the slug + the artifact counts."""
    pack_dir = Path(pack_dir)

    def count(name):
        try:
            data = json.loads((pack_dir / "pack" / name).read_text())
            return len(data) if isinstance(data, list) else 0
        except (ValueError, OSError):
            return 0

    tests = pack_dir / "tests"
    return {"slug": pack_dir.name, "dir": str(pack_dir),
            "counts": {"rules": count("rules.json"),
                       "hypotheses": count("hypotheses.json"),
                       "constraints": count("constraints.json"),
                       "tests": len(scenario_files(tests)) if tests.is_dir() else 0},
            "classify": (pack_dir / "classify.json").exists(),
            "decisions": (pack_dir / "sensor" / "decisions.json").exists()}


# ── Loading + validation (REQ-001/002/009) ──────────────────────────

def _read_json(path):
    return json.loads(Path(path).read_text())


def _load_artifact(pack_dir, name, schema_name):
    """Load a pack artifact (a JSON array), validating every element
    against its schema. Returns (items, violations) — violations are
    {"file", "message"} dicts (empty = valid)."""
    path = Path(pack_dir) / "pack" / name
    try:
        data = _read_json(path)
    except OSError as exc:
        return None, [{"file": str(path), "message": f"unreadable: {exc}"}]
    except ValueError as exc:
        return None, [{"file": str(path), "message": f"unparseable JSON: {exc}"}]
    if not isinstance(data, list):
        return None, [{"file": str(path), "message": "expected a JSON array"}]
    schema = engine.load_json(engine.SCHEMA_DIR / schema_name)
    errs = []
    for i, item in enumerate(data):
        for msg in engine.validate(item, schema, f"item {i}"):
            errs.append({"file": str(path), "message": msg})
    return data, errs


def load_pack(pack_dir):
    """Load + schema-validate the pack artifacts (REQ-009). Returns
    {"rules": [...], "constraints": [...], "hypotheses": [...],
    "classify": {...}|None, "decisions": {...}|None} — raises PackError
    on any violation (named, with the file)."""
    pack_dir = Path(pack_dir)
    if not pack_dir.is_dir() or not (pack_dir / "pack" / "rules.json").exists():
        raise PackError(f"the pack directory does not exist: {pack_dir} "
                        f"(no pack/rules.json — packs live at {PACKS_DIR}/<slug>/)")
    out = {}
    for name, schema_name in PACK_ARTIFACTS:
        items, errs = _load_artifact(pack_dir, name, schema_name)
        if errs:
            raise PackError("; ".join(f"{e['file']}: {e['message']}" for e in errs))
        out[name[:-5]] = items
    for key, rel in (("classify", "classify.json"),
                     ("decisions", "sensor/decisions.json")):
        path = pack_dir / rel
        if path.exists():
            try:
                out[key] = _read_json(path)
            except ValueError as exc:
                raise PackError(f"{path}: unparseable JSON: {exc}")
        else:
            out[key] = None
    return out


def _classify_violations(cfg, where="classify.json"):
    """The classify.json structural checks (REQ-001): required keys,
    non-empty labels, the threshold in range, the enum knobs."""
    errs = []
    if not isinstance(cfg, dict):
        return [f"{where}: expected a JSON object"]
    for key in CLASSIFY_REQUIRED:
        if key not in cfg:
            errs.append(f"{where}: missing required key {key!r}")
    labels = cfg.get("labels")
    if not isinstance(labels, list) or not labels:
        errs.append(f"{where}: labels must be a non-empty list")
    elif not all(isinstance(l, str) and l.strip() for l in labels):
        errs.append(f"{where}: labels must be non-empty strings")
    if "threshold" in cfg:
        t = cfg["threshold"]
        if (not isinstance(t, (int, float)) or isinstance(t, bool)
                or not 0 <= t <= 1):
            errs.append(f"{where}: threshold must be a number in [0, 1]")
    for key, allowed in (("backend", CLASSIFY_BACKENDS), ("prep", CLASSIFY_PREPS),
                         ("precision", CLASSIFY_PRECISIONS),
                         ("scoring", CLASSIFY_SCORINGS)):
        if key in cfg and cfg[key] not in allowed:
            errs.append(f"{where}: {key} must be one of {list(allowed)}")
    crit = cfg.get("criteria")
    if crit is not None:
        if not isinstance(crit, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in crit.items()):
            errs.append(f"{where}: criteria must map labels to description strings")
        elif isinstance(labels, list):
            unknown = set(crit) - set(labels)
            if unknown:
                errs.append(f"{where}: criteria keys must be labels "
                            f"(unknown: {sorted(unknown)})")
    return errs


def _decisions_violations(doc, where, labels=None):
    """The sensor/decisions.json structural checks (the Strom question
    set — mirrors label.check_decisions' structure half, plus the label
    coverage when classify.json is present)."""
    errs = list(engine.validate(doc, DECISIONS_SCHEMA, path=where))
    if errs:
        return errs
    qs = doc["questions"]
    if not isinstance(qs, dict) or not qs:
        return [f"{where}: questions must be a non-empty object"]
    for name, q in qs.items():
        if not isinstance(name, str) or not name:
            errs.append(f"{where}: question names must be non-empty strings")
            continue
        if not isinstance(q, dict):
            errs.append(f"{where}: question {name!r}: must be an object")
            continue
        t = q.get("type")
        if t not in ("noul", "choice", "score"):
            errs.append(f"{where}: question {name!r}: type must be "
                        "noul | choice | score")
            continue
        if not isinstance(q.get("instructions"), str) or not q["instructions"].strip():
            errs.append(f"{where}: question {name!r}: instructions must be "
                        "a non-empty string")
            continue
        if t == "choice":
            crit = q.get("criteria")
            if not isinstance(crit, dict) or not crit:
                errs.append(f"{where}: question {name!r}: choice needs a "
                            "non-empty criteria object")
            elif not all(isinstance(k, str) and isinstance(v, str) and v.strip()
                         for k, v in crit.items()):
                errs.append(f"{where}: question {name!r}: criteria values must "
                            "be non-empty descriptions")
        elif t == "score":
            crit = q.get("criteria")
            if (not isinstance(crit, list) or len(crit) < 2
                    or not all(isinstance(c, str) and c.strip() for c in crit)):
                errs.append(f"{where}: question {name!r}: score needs an "
                            "ordered criteria list of >=2 level descriptions")
    if labels:
        covered = any(
            isinstance(q, dict) and q.get("type") == "choice"
            and set(q.get("criteria") or {}) == set(labels)
            for q in qs.values())
        if not covered:
            errs.append(f"{where}: no choice question covers the labels "
                        "exactly: " + ", ".join(labels))
    return errs


def validate_pack(pack_dir):
    """REQ-001/002 — validate a pack: schema validation of the pack
    artifacts against engine/schemas/, the classify.json +
    decisions.json structural checks, and the cross-artifact checks
    (unique rule/hypothesis/constraint IDs; constraints reference
    existing hypotheses; rules' raise targets exist; the pack field
    matches the directory name). Returns the report:
    {"ok": bool, "pack": slug, "violations": [{"file", "message"}],
     "counts": {...}} — every violation is named with its file."""
    pack_dir = Path(pack_dir)
    if not pack_dir.is_dir() or not (pack_dir / "pack" / "rules.json").exists():
        raise PackError(f"the pack directory does not exist: {pack_dir} "
                        f"(packs live at {PACKS_DIR}/<slug>/)")
    violations = []
    counts = {"rules": 0, "hypotheses": 0, "constraints": 0, "tests": 0}

    def bad(path, message):
        violations.append({"file": str(path), "message": message})

    artifacts = {}
    for name, schema_name in PACK_ARTIFACTS:
        items, errs = _load_artifact(pack_dir, name, schema_name)
        violations.extend(errs)
        if items is not None:
            artifacts[name[:-5]] = items
    counts["rules"] = len(artifacts.get("rules") or [])
    counts["hypotheses"] = len(artifacts.get("hypotheses") or [])
    counts["constraints"] = len(artifacts.get("constraints") or [])
    tests = pack_dir / "tests"
    counts["tests"] = len(scenario_files(tests)) if tests.is_dir() else 0

    # classify.json (optional) — structural checks
    labels = None
    cfg_path = pack_dir / "classify.json"
    if cfg_path.exists():
        try:
            cfg = _read_json(cfg_path)
        except ValueError as exc:
            bad(cfg_path, f"unparseable JSON: {exc}")
            cfg = None
        if cfg is not None:
            for m in _classify_violations(cfg, str(cfg_path)):
                bad(cfg_path, m)
            if isinstance(cfg.get("labels"), list):
                labels = cfg["labels"]

    # sensor/decisions.json (optional) — structural checks
    dec_path = pack_dir / "sensor" / "decisions.json"
    if dec_path.exists():
        try:
            doc = _read_json(dec_path)
        except ValueError as exc:
            bad(dec_path, f"unparseable JSON: {exc}")
            doc = None
        if doc is not None:
            for m in _decisions_violations(doc, str(dec_path), labels):
                bad(dec_path, m)

    # ── cross-artifact checks (REQ-002) — only on a fully loaded pack
    if not violations:
        rules = artifacts.get("rules") or []
        hyps = artifacts.get("hypotheses") or []
        cons = artifacts.get("constraints") or []
        rules_path = pack_dir / "pack" / "rules.json"
        hyps_path = pack_dir / "pack" / "hypotheses.json"
        cons_path = pack_dir / "pack" / "constraints.json"
        hyp_ids = [h.get("id") for h in hyps]
        # unique IDs
        for path, kind, items in ((rules_path, "rule", rules),
                                  (hyps_path, "hypothesis", hyps),
                                  (cons_path, "constraint", cons)):
            ids = [it.get("id") for it in items]
            for dupe in sorted({i for i in ids if ids.count(i) > 1}):
                bad(path, f"duplicate {kind} id: {dupe!r}")
        # constraints reference existing hypotheses
        for c in cons:
            hid = c.get("hypothesis")
            if hid not in hyp_ids:
                bad(cons_path, f"constraint {c.get('id')!r} references "
                     f"missing hypothesis {hid!r}")
        # rules' raise targets exist
        for r in rules:
            for a in r.get("then", []):
                if a.get("op") == "raise":
                    for hid in a.get("hypotheses", []):
                        if hid not in hyp_ids:
                            bad(rules_path, f"rule {r.get('id')!r} raises "
                                 f"missing hypothesis {hid!r}")
        # the pack field matches the directory name
        for r in rules:
            if "pack" in r and r["pack"] != pack_dir.name:
                bad(rules_path, f"rule {r.get('id')!r}: pack field "
                     f"{r['pack']!r} does not match the directory name "
                     f"{pack_dir.name!r}")
    return {"ok": not violations, "pack": pack_dir.name,
            "violations": violations, "counts": counts}


# ── Facts + the test run (REQ-003/005) ──────────────────────────────

def load_facts_file(path):
    """Load + schema-validate a fact-set file (a scenario's facts-*.json
    or a --facts file). Raises PackError naming the file + violation."""
    path = Path(path)
    try:
        data = _read_json(path)
    except OSError as exc:
        raise PackError(f"{path}: unreadable: {exc}")
    except ValueError as exc:
        raise PackError(f"{path}: unparseable JSON: {exc}")
    if not isinstance(data, list):
        raise PackError(f"{path}: expected a JSON array of facts")
    schema = engine.load_json(engine.SCHEMA_DIR / "fact.schema.json")
    errs = []
    for i, item in enumerate(data):
        errs += engine.validate(item, schema, f"item {i}")
    if errs:
        raise PackError(f"{path}: " + "; ".join(errs))
    return data


def diagnose_result(pack_dir, facts, result):
    """REQ-004 — the gap analysis over an already-computed run
    (deterministic; no heuristics — see the module header)."""
    loaded = load_pack(pack_dir)
    rules, hyps = loaded["rules"], loaded["hypotheses"]
    fired = {e["rule"] for e in result["fired_rules"]}
    dead = [{"id": r["id"], "when": r.get("when", [])}
            for r in rules if r["id"] not in fired]
    raised = set(result["raised_hypotheses"])
    unraised = [{"id": h["id"], "statement": h.get("statement", "")}
                for h in hyps if h["id"] not in raised]
    pruned = [{"id": p["hypothesis"], "constraint": p["constraint"],
               "reason": p.get("reason", "")}
              for p in result["pruned"]]
    all_facts = list(facts) + list(result["derived_facts"])

    def slot_spoken(q):
        slot = q.get("slot")
        if not slot:
            return False
        return any(f.get("subject") == slot or f.get("predicate") == slot
                   for f in all_facts)

    unanswered = [{"id": q["id"], "slot": q.get("slot", ""),
                   "text": q.get("text", "")}
                  for q in result["opened_questions"]
                  if q.get("status", "open") == "open" and not slot_spoken(q)]
    return {"dead_rules": dead,
            "unraised_hypotheses": unraised,
            "pruned_hypotheses": pruned,
            "unanswered_questions": unanswered}


def diagnose(pack_dir, facts):
    """REQ-004 — run the pack on a fact set (a list of fact dicts) and
    report the gaps."""
    result = engine.run_case(pack_dir, facts=facts)
    return diagnose_result(pack_dir, facts, result)


def run_pack_test(pack_dir, facts):
    """REQ-003 — the pack test run: verdict + trace + gap analysis via
    the existing engine flow (run_case with the facts= override).
    Deterministic: the same pack + fact set → a byte-identical result
    (no LLM, no clock, no random source in the path)."""
    result = engine.run_case(pack_dir, facts=facts)
    return {"pack": Path(pack_dir).name,
            "verdict": result["verdict"],
            "trace": result,
            "gaps": diagnose_result(pack_dir, facts, result)}


# ── The scenario runner (REQ-006) ──────────────────────────────────

def scenario_files(tests_dir):
    """The scenario fact sets in a tests dir: every facts-*.json except
    the facts-*.expected.json assertion files."""
    tests_dir = Path(tests_dir)
    if not tests_dir.is_dir():
        return []
    return sorted(f for f in tests_dir.glob("facts-*.json")
                  if not f.name.endswith(".expected.json"))


def _assert_expected(expected, result):
    """Assert a scenario's expected outcome (facts-<scenario>.expected.json)
    against the run. Returns the mismatch list (empty = pass)."""
    mismatches = []
    v = result["verdict"]
    if "verdict" in expected:
        want, got = expected["verdict"], (v["id"] if v else None)
        if want != got:
            mismatches.append(f"verdict: expected {want!r}, got {got!r}")
    if "pruned" in expected:
        want = sorted(expected["pruned"])
        got = sorted(p["hypothesis"] for p in result["trace"]["pruned"])
        if want != got:
            mismatches.append(f"pruned: expected {want}, got {got}")
    if "derived" in expected:
        want = sorted(expected["derived"])
        got = sorted(f["id"] for f in result["trace"]["derived_facts"])
        if want != got:
            mismatches.append(f"derived: expected {want}, got {got}")
    if "recommended_test" in expected:
        q = result["trace"]["recommended_test"]
        want, got = expected["recommended_test"], (q["id"] if q else None)
        if want != got:
            mismatches.append(f"recommended_test: expected {want!r}, got {got!r}")
    unknown = set(expected) - set(EXPECTED_KEYS)
    if unknown:
        mismatches.append(f"unknown expected keys: {sorted(unknown)}")
    return mismatches


def run_scenarios(pack_dir, tests_dir):
    """REQ-006 — run every facts-*.json scenario in a tests dir and
    assert the expected outcome (facts-<scenario>.expected.json) when
    present. Returns {"ok": bool, "dir": ..., "scenarios": [{name, ok,
    mismatches, verdict, expected?}]} — a failing scenario is named."""
    tests_dir = Path(tests_dir)
    if not tests_dir.is_dir():
        raise PackError(f"the tests directory does not exist: {tests_dir}")
    scenarios = []
    for path in scenario_files(tests_dir):
        entry = {"name": path.name, "ok": True, "mismatches": [],
                 "verdict": None}
        try:
            facts = load_facts_file(path)
        except PackError as exc:
            entry.update(ok=False, mismatches=[str(exc)])
            scenarios.append(entry)
            continue
        result = run_pack_test(pack_dir, facts)
        entry["verdict"] = result["verdict"]["id"] if result["verdict"] else None
        expected_path = path.with_name(path.stem + ".expected.json")
        if expected_path.exists():
            try:
                expected = _read_json(expected_path)
            except ValueError as exc:
                entry.update(ok=False,
                             mismatches=[f"{expected_path}: unparseable JSON: {exc}"])
            else:
                entry["expected"] = expected
                entry["mismatches"] = _assert_expected(expected, result)
                entry["ok"] = not entry["mismatches"]
        scenarios.append(entry)
    return {"ok": all(s["ok"] for s in scenarios),
            "found": len(scenarios),
            "dir": str(tests_dir), "scenarios": scenarios}


# ── The draft write policy (REQ-015) ────────────────────────────────

def draft_path(pack_dir, rel_target):
    """The staged draft path for a target artifact (rules.json →
    rules.draft.json, beside the target)."""
    target = Path(pack_dir) / rel_target
    return target.with_suffix(".draft.json")


def stage_draft(pack_dir, rel_target, doc):
    """Stage a draft beside its target: the draft lands as
    <artifact>.draft.json and the target is untouched — the human
    accepts explicitly (accept_draft / --write). Returns the staged path."""
    staged = draft_path(pack_dir, rel_target)
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(json.dumps(doc, indent=2) + "\n")
    return staged


def accept_draft(pack_dir, rel_target):
    """Accept a staged draft (--write): the draft replaces the target
    and the staged file is consumed. Returns the target path."""
    target = Path(pack_dir) / rel_target
    staged = draft_path(pack_dir, rel_target)
    if not staged.exists():
        raise PackError(f"no staged draft at {staged} — run the draft op first")
    shutil.move(str(staged), str(target))
    return target


# ── The draft ops' schemas + judges (REQ-010/011/012) ───────────────

def array_schema(item_schema_name):
    """An array-of-<artifact> schema for the draft ops (the LLM drafts a
    whole artifact file — the full item schema inlined so the prompt
    carries it)."""
    return {"type": "array",
            "items": engine.load_json(engine.SCHEMA_DIR / item_schema_name)}


def classify_judge(cfg):
    """The suggest-labels judge: the classify.json structural checks
    (the ranges + the non-empty labels the subset validator ignores)."""
    return _classify_violations(cfg, "the draft")


def rules_judge(pack_dir):
    """The draft-rules judge: unique rule ids; the raise targets exist in
    the pack's hypotheses; the pack field matches the directory (the
    REQ-002 cross-checks the draft must pass)."""
    slug = Path(pack_dir).name
    try:
        hyp_ids = {h["id"] for h in load_pack(pack_dir)["hypotheses"]}
    except PackError:
        hyp_ids = set()

    def judge(rules):
        errs = []
        ids = [r.get("id") for r in rules]
        for dupe in sorted({i for i in ids if ids.count(i) > 1}):
            errs.append(f"duplicate rule id: {dupe!r}")
        for r in rules:
            if r.get("pack") not in (None, slug):
                errs.append(f"rule {r.get('id')!r}: pack field {r['pack']!r} "
                            f"must be {slug!r} (the directory name)")
            for a in r.get("then", []):
                if a.get("op") == "raise":
                    for hid in a.get("hypotheses", []):
                        if hid not in hyp_ids:
                            errs.append(f"rule {r.get('id')!r}: raise target "
                                        f"{hid!r} is not a hypothesis in this pack")
        return errs

    return judge


def hypotheses_judge():
    """The draft-hypotheses judge: unique hypothesis ids."""

    def judge(hyps):
        ids = [h.get("id") for h in hyps]
        return [f"duplicate hypothesis id: {d!r}"
                for d in sorted({i for i in ids if ids.count(i) > 1})]

    return judge
