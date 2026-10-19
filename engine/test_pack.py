#!/usr/bin/env python3
# test_pack.py — the Pack Studio library (engine/pack.py): validate,
# test, diagnose, the scenario runner, and the draft staging policy.
# No LLM, no network: a fixture pack with a known dead rule + unraised
# hypothesis + unanswered question, exercised directly (like
# test_retry.py stubs the runner).
#
# The second half covers the Pack Studio LLM authoring ops (REQ-010…016)
# through the CLI functions with a STUBBED runner (the test_retry.py /
# test_cache.py pattern): no LLM, no network, no keys — the Strom
# client is stubbed for draft-questions (the judge's dry run). The
# response cache is pointed at a tempdir (FACTY_CACHE_DIR).
#
# Usage: python3 engine/test_pack.py   (exit 0 = pass)
#         ./facty test                  (selftest + this)

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import pack    # noqa: E402
import label   # noqa: E402  (the label sensor — the draft-questions judge)
import cli     # noqa: E402  (the CLI — the pack LLM ops, stubbed runner)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS" if ok else "FAIL") + f"  {name}"
          + (f" — {detail}" if detail and not ok else ""))


# ── The fixture pack ─────────────────────────────────────────────────
#
# A temp pack with:
#   R1 — fires on the fact set (derives d1, opens q1)
#   R2 — DEAD: never fires (its condition is never satisfied)
#   H1 — raised by R1
#   H2 — UNRAISED: no rule ever raises it
#   q1 — opened by R1, slot "threat-intel"; no fact speaks that slot
#        → the gap analysis must flag R2 (dead), H2 (unraised), q1
#        (unanswered)

FIXTURE_RULES = [
    {"id": "R1", "version": "1", "pack": None,  # filled per-fixture
     "when": [{"subject": "x", "predicate": "p", "value": True}],
     "then": [{"op": "raise", "hypotheses": ["H1", "H3"]},
              {"op": "derive",
               "fact": {"id": "d1", "type": "derived", "subject": "x",
                        "predicate": "q", "value": True, "confidence": 0.9,
                        "source": "rule:R1"}},
              {"op": "open",
               "question": {"id": "q1", "text": "Is the source known-bad?",
                            "slot": "threat-intel", "mandatory": True,
                            "priority": 1, "discriminates": ["H1"]}}]},
    {"id": "R2", "version": "1", "pack": None,
     "when": [{"subject": "x", "predicate": "never-true", "value": True}],
     "then": [{"op": "raise", "hypotheses": ["H1"]}]},
]

FIXTURE_HYPOTHESES = [
    {"id": "H1", "statement": "the thing happened", "status": "open",
     "prior": 0.5, "claims": [{"subject": "x", "predicate": "q", "value": True}]},
    {"id": "H2", "statement": "the other thing happened", "status": "open",
     "prior": 0.3, "claims": [{"subject": "x", "predicate": "never", "value": True}]},
    {"id": "H3", "statement": "the pruned thing happened", "status": "open",
     "prior": 0.2, "claims": [{"subject": "x", "predicate": "q", "value": True}]},
]

FIXTURE_CONSTRAINTS = [
    {"id": "C1", "type": "eliminate", "hypothesis": "H3",
     "when": [{"subject": "x", "predicate": "q", "value": True}],
     "reason": "q is true, so H3 is eliminated"},
]

FIXTURE_FACTS = [
    {"id": "f1", "type": "evidence", "subject": "x", "predicate": "p",
     "value": True, "confidence": 1.0, "source": "test:fixture"},
]


def write_fixture_pack(root, slug="gap-fixture", rules=None, hypotheses=None,
                       constraints=None, facts=None, expected=None,
                       set_pack_field=True):
    """Write a fixture pack under root/<slug>/. Returns the pack dir.
    The rules' `pack` field is set to the slug (the cross-artifact check
    requires it to match the directory name) unless set_pack_field=False."""
    pdir = Path(root) / slug
    (pdir / "pack").mkdir(parents=True, exist_ok=True)
    rules = rules if rules is not None else FIXTURE_RULES
    hypotheses = hypotheses if hypotheses is not None else FIXTURE_HYPOTHESES
    constraints = constraints if constraints is not None else FIXTURE_CONSTRAINTS
    # fill the pack field (deep-copy so the module-level fixtures stay clean)
    rules = json.loads(json.dumps(rules))
    if set_pack_field:
        for r in rules:
            r["pack"] = slug
    (pdir / "pack" / "rules.json").write_text(json.dumps(rules, indent=2))
    (pdir / "pack" / "hypotheses.json").write_text(json.dumps(hypotheses, indent=2))
    (pdir / "pack" / "constraints.json").write_text(json.dumps(constraints, indent=2))
    if facts is not None:
        (pdir / "tests").mkdir(parents=True, exist_ok=True)
        (pdir / "tests" / "facts-main.json").write_text(json.dumps(facts, indent=2))
        if expected is not None:
            (pdir / "tests" / "facts-main.expected.json").write_text(
                json.dumps(expected, indent=2))
    return pdir


# ── The LLM-op test rig (stubbed runner + stubbed Strom client) ─────

class StubUI:
    def __init__(self):
        self.lines = []

    def log(self, tag, msg):
        self.lines.append(f"[{tag}] {msg}")

    def step(self, tag, title):
        pass


def stub_runner(responses, calls, seen=None):
    """A runner stub: returns the canned responses in order (the last
    one repeats); records the staged prompts it was called with."""
    def runner(staged_path, stream):
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        if seen is not None:
            seen.append(Path(staged_path).read_text())
        if stream is not None:
            for line in responses[idx].splitlines():
                stream(line)
        return responses[idx]
    return runner


class StubClient:
    """A Strom client stub for the decision-question judge's dry run:
    well-shaped answers (choice probabilities sum to 1, matching the
    criteria keys; not degenerate — the top probability is 0.9)."""

    def __init__(self):
        self.calls = []

    def ask(self, state, questions):
        self.calls.append((state, questions))

        def answer(q):
            if q["type"] == "choice":
                crit = q["criteria"]
                first = next(iter(crit))
                return {"type": "choice", "choice": first, "confidence": 0.9,
                        "probabilities": {k: (0.9 if k == first else 0.05)
                                          for k in crit}}
            if q["type"] == "noul":
                return {"type": "noul", "noul": 0.9}
            return {"type": "score", "score": 1.0, "confidence": 0.8,
                    "legend": q["criteria"],
                    "probabilities": [0.1, 0.8, 0.1]}

        return {"model": "strom-1.0.7",
                "answers": {name: answer(q) for name, q in questions.items()},
                "usage": {}, "metadata": {}}


# The draft ops' fixtures: a CSV pile + classify config (suggest-labels
# + draft-questions), and the canned LLM responses.
OP_CSV = """alert_id,timestamp,src_ip,signature,severity,message
A-0001,2026-10-12T02:10:00,185.220.44.7,sql-injection,high,SQL injection attempt on /login blocked by WAF
A-0002,2026-10-12T02:10:23,185.220.44.7,credential-stuffing,high,Credential stuffing: 620 failed logins across 57 accounts
A-0003,2026-10-12T02:11:00,103.4.5.6,port-scan,medium,Port scan: 103.4.5.6 probed 40 ports on the firewall
A-0004,2026-10-12T02:12:00,10.2.3.4,backup,low,Scheduled backup job matched data exfiltration signature
"""

OP_CLASSIFY = {
    "file": "evidence/alerts.csv", "idColumn": "alert_id",
    "textColumn": "message", "sourceColumn": "src_ip",
    "timeColumn": "timestamp", "subject": "alerts",
    "labels": ["a targeted attack", "a probing scan",
               "a benign authorized activity"],
    "template": "This alert is {}.", "scoring": "margin", "threshold": 0.65,
    "model": "onnx-community/ModernBERT-base-nli-ONNX", "precision": "fp32",
    "prep": "none", "backend": "hybrid",
}

OP_RULES = [
    {"id": "R10", "version": "1", "pack": "draft-fixture",
     "when": [{"subject": "x", "predicate": "p", "value": True}],
     "then": [{"op": "raise", "hypotheses": ["H1"]},
              {"op": "derive",
               "fact": {"id": "d10", "type": "derived", "subject": "x",
                        "predicate": "q", "value": True, "confidence": 0.9,
                        "source": "rule:R10"}}]},
    {"id": "R11", "version": "1", "pack": "draft-fixture",
     "when": [{"subject": "x", "predicate": "never", "value": True}],
     "then": [{"op": "open",
               "question": {"id": "q10", "text": "Is it real?",
                            "slot": "s", "mandatory": False, "priority": 2,
                            "discriminates": ["H2"]}}]},
]

OP_HYPS = [{"id": "H10", "statement": "the thing happened", "status": "open",
            "prior": 0.5,
            "claims": [{"subject": "x", "predicate": "q", "value": True}]}]

OP_DECISIONS = {"model": "strom-1.0.7", "questions": {
    "classification": {"type": "choice",
                       "instructions": "Classify this alert row.",
                       "criteria": {l: f"when the row is {l}"
                                    for l in OP_CLASSIFY["labels"]}},
    "isExternalSource": {"type": "noul",
                         "instructions": "Is the source IP external?"},
    "urgency": {"type": "score", "instructions": "How urgent is the response?",
                "criteria": ["routine", "elevated", "high"]},
}}


def dir_digest(root):
    """{relative path: sha256} for every file under root — the
    byte-identical check (review never writes to the pack)."""
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def main():
    tmp = tempfile.mkdtemp(prefix="facty-test-pack-")

    # ── 1. validate_pack: accepts a clean pack ────────────────────────
    pdir = write_fixture_pack(tmp, facts=FIXTURE_FACTS,
                              expected={"verdict": "H1", "derived": ["d1"]})
    report = pack.validate_pack(pdir)
    check("validate_pack accepts a clean pack",
          report["ok"] and report["counts"]["rules"] == 2
          and report["counts"]["hypotheses"] == 3
          and report["counts"]["constraints"] == 1
          and report["counts"]["tests"] == 1,
          f"ok={report['ok']} counts={report['counts']}")

    # ── 2. validate_pack: rejects a schema violation ──────────────────
    bad_schema = write_fixture_pack(
        tmp, slug="bad-schema",
        rules=[{"id": "R1", "then": []}],  # missing required 'when'
        hypotheses=[], constraints=[])
    report = pack.validate_pack(bad_schema)
    check("validate_pack rejects a schema violation (names the file)",
          not report["ok"]
          and any("rules.json" in v["file"] for v in report["violations"]),
          f"violations={report['violations']}")

    # ── 3. validate_pack: rejects cross-artifact violations ───────────
    # 3a. constraint referencing a missing hypothesis
    bad_cons = write_fixture_pack(
        tmp, slug="bad-cons",
        constraints=[{"id": "C1", "type": "eliminate", "hypothesis": "H99",
                      "when": [], "reason": "test"}])
    report = pack.validate_pack(bad_cons)
    check("validate_pack rejects a constraint referencing a missing hypothesis",
          not report["ok"]
          and any("missing hypothesis" in v["message"]
                  for v in report["violations"]),
          f"violations={report['violations']}")

    # 3b. duplicate rule IDs
    bad_dup = write_fixture_pack(
        tmp, slug="bad-dup",
        rules=[{"id": "R1", "pack": "bad-dup", "when": [], "then": []},
               {"id": "R1", "pack": "bad-dup", "when": [], "then": []}])
    report = pack.validate_pack(bad_dup)
    check("validate_pack rejects duplicate rule IDs",
          not report["ok"]
          and any("duplicate rule id" in v["message"]
                  for v in report["violations"]),
          f"violations={report['violations']}")

    # 3c. rule whose raise target does not exist
    bad_raise = write_fixture_pack(
        tmp, slug="bad-raise",
        rules=[{"id": "R1", "pack": "bad-raise", "when": [],
                "then": [{"op": "raise", "hypotheses": ["H99"]}]}])
    report = pack.validate_pack(bad_raise)
    check("validate_pack rejects a rule raising a missing hypothesis",
          not report["ok"]
          and any("raises missing hypothesis" in v["message"]
                  for v in report["violations"]),
          f"violations={report['violations']}")

    # 3d. pack field mismatch (set_pack_field=False keeps the wrong value)
    bad_pack = write_fixture_pack(
        tmp, slug="bad-pack-field",
        rules=[{"id": "R1", "pack": "wrong-slug", "when": [], "then": []}],
        set_pack_field=False)
    report = pack.validate_pack(bad_pack)
    check("validate_pack rejects a pack/directory name mismatch",
          not report["ok"]
          and any("does not match the directory name" in v["message"]
                  for v in report["violations"]),
          f"violations={report['violations']}")

    # ── 4. run_pack_test: deterministic + byte-identical + < 1s ──────
    t0 = time.time()
    r1 = pack.run_pack_test(pdir, FIXTURE_FACTS)
    t1 = time.time()
    r2 = pack.run_pack_test(pdir, FIXTURE_FACTS)
    t2 = time.time()
    j1 = json.dumps(r1, sort_keys=True)
    j2 = json.dumps(r2, sort_keys=True)
    check("run_pack_test is deterministic (two runs byte-identical)",
          j1 == j2)
    check("run_pack_test completes in < 1s",
          (t1 - t0) < 1.0 and (t2 - t1) < 1.0,
          f"run1={t1-t0:.3f}s run2={t2-t1:.3f}s")
    check("run_pack_test returns verdict + trace + gaps",
          r1["verdict"] is not None and "trace" in r1 and "gaps" in r1
          and r1["verdict"]["id"] == "H1",
          f"verdict={r1['verdict']}")

    # ── 5. diagnose: flags the fixture's known gaps ──────────────────
    gaps = pack.diagnose(pdir, FIXTURE_FACTS)
    dead_ids = {r["id"] for r in gaps["dead_rules"]}
    unraised_ids = {h["id"] for h in gaps["unraised_hypotheses"]}
    unanswered_ids = {q["id"] for q in gaps["unanswered_questions"]}
    check("diagnose flags the known dead rule (R2)",
          "R2" in dead_ids and "R1" not in dead_ids,
          f"dead={dead_ids}")
    check("diagnose flags the unraised hypothesis (H2)",
          "H2" in unraised_ids and "H1" not in unraised_ids,
          f"unraised={unraised_ids}")
    check("diagnose flags the unanswered question (q1)",
          "q1" in unanswered_ids,
          f"unanswered={unanswered_ids}")
    check("diagnose reports the pruned hypothesis with its reason",
          any(p["id"] == "H3" and p["constraint"] == "C1"
              and "eliminated" in p["reason"]
              for p in gaps["pruned_hypotheses"]),
          f"pruned={gaps['pruned_hypotheses']}")

    # ── 6. run_scenarios: passes a matching scenario ─────────────────
    scen = pack.run_scenarios(pdir, pdir / "tests")
    check("run_scenarios passes a matching scenario",
          scen["ok"] and scen["found"] == 1
          and scen["scenarios"][0]["ok"],
          f"ok={scen['ok']} scenarios={scen['scenarios']}")

    # ── 7. run_scenarios: fails a mismatching one (named) ────────────
    bad_scen = write_fixture_pack(
        tmp, slug="bad-scen", facts=FIXTURE_FACTS,
        expected={"verdict": "H2"})  # wrong — the engine says H1
    scen = pack.run_scenarios(bad_scen, bad_scen / "tests")
    check("run_scenarios fails a mismatching scenario (named)",
          not scen["ok"]
          and scen["scenarios"][0]["name"] == "facts-main.json"
          and not scen["scenarios"][0]["ok"]
          and any("verdict" in m for m in scen["scenarios"][0]["mismatches"]),
          f"ok={scen['ok']} scenarios={scen['scenarios']}")

    # ── 8. stage_draft: writes .draft.json beside the target ─────────
    target = pdir / "pack" / "rules.json"
    original = target.read_text()
    staged = pack.stage_draft(pdir, "pack/rules.json",
                              [{"id": "R9", "when": [], "then": []}])
    check("stage_draft writes .draft.json beside the target; target untouched",
          staged.name == "rules.draft.json" and staged.exists()
          and target.read_text() == original,
          f"staged={staged.name} exists={staged.exists()}")

    # ── 9. accept_draft: replaces the target ─────────────────────────
    accepted = pack.accept_draft(pdir, "pack/rules.json")
    check("accept_draft replaces the target and consumes the draft",
          accepted == target and not staged.exists()
          and json.loads(target.read_text()) == [{"id": "R9", "when": [], "then": []}],
          f"accepted={accepted} staged_exists={staged.exists()}")

    # ── 10. load_facts_file: rejects invalid facts with a named error ─
    bad_facts = Path(tmp) / "bad-facts.json"
    bad_facts.write_text(json.dumps({"not": "an array"}))
    try:
        pack.load_facts_file(bad_facts)
        check("load_facts_file rejects non-array facts", False, "no exception")
    except pack.PackError as exc:
        check("load_facts_file rejects non-array facts (named error)",
              "expected a JSON array" in str(exc), str(exc))

    bad_facts2 = Path(tmp) / "bad-facts2.json"
    bad_facts2.write_text(json.dumps([{"id": "f1"}]))  # missing required keys
    try:
        pack.load_facts_file(bad_facts2)
        check("load_facts_file rejects schema-violating facts", False, "no exception")
    except pack.PackError as exc:
        check("load_facts_file rejects schema-violating facts (named error)",
              "missing required property" in str(exc), str(exc))

    # ── 11. resolve_pack: slug + path (against the temp packs dir) ───
    resolved = pack.resolve_pack("gap-fixture", packs_dir=tmp)
    check("resolve_pack resolves a slug under packs/",
          resolved.name == "gap-fixture",
          f"resolved={resolved}")
    try:
        pack.resolve_pack("does-not-exist", packs_dir=tmp)
        check("resolve_pack rejects a missing pack", False, "no exception")
    except pack.PackError as exc:
        check("resolve_pack rejects a missing pack (named error)",
              "does not exist" in str(exc), str(exc))

    # ── 12. list_packs: empty dir → [] ───────────────────────────────
    empty = Path(tmp) / "empty-packs"
    empty.mkdir()
    check("list_packs returns [] for an empty packs dir",
          pack.list_packs(empty) == [])

    # ── 13. the seeded pack: validate + scenarios pass ───────────────
    seeded = Path(__file__).resolve().parent.parent / "packs" / "triage-alert-flood"
    if seeded.is_dir():
        report = pack.validate_pack(seeded)
        check("the seeded pack (triage-alert-flood) validates clean",
              report["ok"], f"violations={report['violations']}")
        scen = pack.run_scenarios(seeded, seeded / "tests")
        check("the seeded pack's scenarios pass",
              scen["ok"] and scen["found"] >= 1,
              f"ok={scen['ok']} found={scen['found']}")
        # the seeded pack's gap analysis flags R3 (dead) + q1 (unanswered)
        facts = pack.load_facts_file(seeded / "tests" / "facts-initial.json")
        gaps = pack.diagnose(seeded, facts)
        dead_ids = {r["id"] for r in gaps["dead_rules"]}
        unanswered_ids = {q["id"] for q in gaps["unanswered_questions"]}
        check("the seeded pack's gaps flag R3 (dead) + q1 (unanswered)",
              "R3" in dead_ids and "q1" in unanswered_ids,
              f"dead={dead_ids} unanswered={unanswered_ids}")

    # ── 14. The LLM authoring ops (REQ-010…016) — stubbed runner ─────
    # No LLM, no network, no keys: the response cache is pointed at a
    # tempdir; the LLM runner (and the Strom client, for
    # draft-questions) is stubbed.
    os.environ["FACTY_CACHE_DIR"] = str(Path(tmp) / "cache")
    os.environ["FACTY_SENSE"] = "live"
    ui = StubUI()

    def unlink(path):
        path = Path(path)
        if path.exists():
            path.unlink()

    # ── draft-rules (REQ-010/015): stage, --write, judge, cache ──────
    pack_dir = write_fixture_pack(tmp, slug="draft-fixture",
                                  facts=FIXTURE_FACTS)
    target = pack_dir / "pack" / "rules.json"
    staged = pack_dir / "pack" / "rules.draft.json"
    before = target.read_text()
    good_rules = json.dumps(OP_RULES, indent=2)

    calls = {"n": 0}
    result = cli.pack_draft_rules(
        ui, pack_dir, "test domain: x is p",
        runner=stub_runner([good_rules], calls))
    check("draft-rules stages the draft and returns it",
          result is not None and result["doc"] == OP_RULES
          and not result["accepted"], f"result={result}")
    check("draft-rules stages pack/rules.draft.json; the target is untouched",
          staged.exists() and target.read_text() == before
          and json.loads(staged.read_text()) == OP_RULES,
          f"staged={staged.exists()} target_same={target.read_text() == before}")
    check("draft-rules accepted the draft on turn 1 (one LLM call)",
          calls["n"] == 1, f"calls={calls['n']}")
    check("draft-rules logs the staging summary + how to accept",
          any("draft staged" in l for l in ui.lines)
          and any("--write" in l for l in ui.lines),
          str(ui.lines[-4:]))

    # --write: the draft replaces the target, the staged file is consumed
    calls = {"n": 0}
    result = cli.pack_draft_rules(
        ui, pack_dir, "test domain: x is p", write=True,
        runner=stub_runner([good_rules], calls))
    check("draft-rules --write replaces the target and consumes the draft",
          result is not None and result["accepted"] and not staged.exists()
          and json.loads(target.read_text()) == OP_RULES,
          f"accepted={result and result['accepted']} "
          f"staged={staged.exists()}")

    # the judge (unit): duplicate ids / missing raise target / pack field
    judge = pack.rules_judge(pack_dir)
    errs = judge(OP_RULES + [dict(OP_RULES[0])])
    check("rules_judge rejects duplicate rule ids",
          any("duplicate rule id" in e for e in errs), str(errs))
    errs = judge([dict(OP_RULES[0],
                       then=[{"op": "raise", "hypotheses": ["H99"]}])])
    check("rules_judge rejects a missing raise target",
          any("H99" in e for e in errs), str(errs))
    errs = judge([dict(OP_RULES[0], pack="wrong-slug")])
    check("rules_judge rejects a pack-field mismatch",
          any("must be" in e for e in errs), str(errs))
    check("rules_judge accepts the valid draft", judge(OP_RULES) == [])

    # the prompt: the domain + the pack's ontology, never the engine's
    # conclusions (the anti-bias rule holds for authoring too)
    task = cli._draft_rules_task(pack_dir, "test domain: x is p")
    check("the draft-rules prompt carries the domain + the pack's ontology",
          "test domain: x is p" in task and "H1" in task
          and "predicates:" in task and "subjects:" in task,
          task[:200])
    check("the draft-rules prompt never carries the engine's conclusions",
          not any(w in task.lower()
                  for w in ("verdict", "ranking", "score", "claims_proven")),
          task[:200])

    # a judge-rejected draft is corrected (the capped correction loop)
    bad_rules = json.dumps(OP_RULES + [dict(OP_RULES[0])], indent=2)
    calls = {"n": 0}
    result = cli.pack_draft_rules(
        ui, pack_dir, "correction domain",
        runner=stub_runner([bad_rules, good_rules], calls))
    check("draft-rules: a judge-rejected draft is corrected on turn 2",
          result is not None and result["doc"] == OP_RULES and calls["n"] == 2,
          f"calls={calls['n']} result={result is not None}")

    # judge exhaustion → the op fails, nothing is staged
    unlink(staged)
    calls = {"n": 0}
    result = cli.pack_draft_rules(
        ui, pack_dir, "exhaustion domain",
        runner=stub_runner([bad_rules, bad_rules, bad_rules], calls))
    check("draft-rules: judge exhaustion fails the op (no draft staged)",
          result is None and calls["n"] == 3 and not staged.exists(),
          f"result={result} calls={calls['n']} staged={staged.exists()}")
    check("draft-rules: the failure is logged (the draft is the point)",
          any("LLM call failed" in l for l in ui.lines), str(ui.lines[-2:]))

    # an unreachable LLM → a clear failure, no silent fallback
    def dead_runner(staged_path, stream):
        raise RuntimeError("no credential reachable")

    result = cli.pack_draft_rules(ui, pack_dir, "unreachable domain",
                                  runner=dead_runner)
    check("draft-rules: an unreachable LLM fails the op (no fallback)",
          result is None, f"result={result}")

    # cache replay (REQ-016): byte-identical, no LLM call
    calls = {"n": 0}
    result = cli.pack_draft_rules(
        ui, pack_dir, "cache domain",
        runner=stub_runner([good_rules], calls))
    staged_bytes = staged.read_bytes()
    check("draft-rules (live) caches the raw response",
          result is not None and len(list(
              Path(os.environ["FACTY_CACHE_DIR"]).rglob("*.json"))) >= 1)
    unlink(staged)
    os.environ["FACTY_SENSE"] = "cache"
    calls = {"n": 0}
    result = cli.pack_draft_rules(ui, pack_dir, "cache domain",
                                  runner=dead_runner)
    check("FACTY_SENSE=cache replays the draft byte-identically, no LLM call",
          result is not None and staged.exists()
          and staged.read_bytes() == staged_bytes,
          f"result={result is not None} staged={staged.exists()}")
    check("cache mode never called the LLM",
          calls["n"] == 0, f"calls={calls['n']}")
    check("cache mode logs the replay (no LLM call)",
          any("response cache hit, no LLM call" in l for l in ui.lines),
          str(ui.lines[-3:]))
    os.environ["FACTY_SENSE"] = "live"

    # --offline forces the cache replay too
    unlink(staged)
    result = cli.pack_draft_rules(ui, pack_dir, "cache domain",
                                  runner=dead_runner, offline=True)
    check("--offline replays the cache (no LLM call)",
          result is not None and staged.exists()
          and staged.read_bytes() == staged_bytes, f"result={result}")
    check("--offline logs the offline mode",
          any("offline mode" in l for l in ui.lines), str(ui.lines[-3:]))

    # the CLI end-to-end (the parser + the session scope), cache mode:
    # no LLM, and the --json envelope is machine-readable. A dedicated
    # fixture pack — the earlier --write test mutated pack_dir's rules,
    # which changes the prompt (the term vocabulary) and orphans its
    # cache entry.
    e2e = write_fixture_pack(tmp, slug="e2e-fixture", facts=FIXTURE_FACTS)
    e2e_rules = [dict(r, pack="e2e-fixture") for r in OP_RULES]
    cli.pack_draft_rules(ui, e2e, "e2e domain",
                         runner=stub_runner(
                             [json.dumps(e2e_rules, indent=2)], {"n": 0}))
    e2e_staged = e2e / "pack" / "rules.draft.json"
    unlink(e2e_staged)
    os.environ["FACTY_SENSE"] = "cache"  # the end-to-end run replays, no LLM
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["pack", "draft-rules", str(e2e),
                       "--domain", "e2e domain"])
    check("the CLI end-to-end: pack draft-rules replays from the cache (exit 0)",
          rc == 0 and e2e_staged.exists()
          and json.loads(e2e_staged.read_text()) == e2e_rules,
          f"rc={rc} staged={e2e_staged.exists()}")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["pack", "draft-rules", str(e2e),
                       "--domain", "e2e domain", "--json"])
    payload = json.loads(buf.getvalue())
    check("pack draft-rules --json emits the machine-readable draft envelope",
          rc == 0 and payload["op"] == "draft-rules"
          and payload["draft"] == e2e_rules
          and payload["staged"].endswith("rules.draft.json")
          and payload["accepted"] is False,
          f"rc={rc} payload={payload}")
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), \
            contextlib.redirect_stderr(buf_err):
        rc = cli.main(["pack", "validate", "does-not-exist"])
    check("the CLI end-to-end: a missing pack exits 1 with a named error",
          rc == 1 and "does not exist" in buf_err.getvalue(),
          f"rc={rc} err={buf_err.getvalue()[:120]}")
    os.environ["FACTY_SENSE"] = "live"

    # ── suggest-labels (REQ-011) ─────────────────────────────────────
    pack_dir2 = write_fixture_pack(tmp, slug="labels-fixture",
                                   facts=FIXTURE_FACTS)
    (pack_dir2 / "evidence").mkdir()
    (pack_dir2 / "evidence" / "alerts.csv").write_text(OP_CSV)
    ev = pack_dir2 / "evidence" / "alerts.csv"
    staged_cfg = pack_dir2 / "classify.draft.json"
    good_cfg = json.dumps(OP_CLASSIFY, indent=2)

    calls = {"n": 0}
    result = cli.pack_suggest_labels(
        ui, pack_dir2, ev, runner=stub_runner([good_cfg], calls))
    check("suggest-labels stages classify.draft.json; no classify.json yet",
          result is not None and result["doc"] == OP_CLASSIFY
          and staged_cfg.exists()
          and not (pack_dir2 / "classify.json").exists()
          and json.loads(staged_cfg.read_text()) == OP_CLASSIFY,
          f"result={result is not None} staged={staged_cfg.exists()}")

    # --write on a not-yet-existing target: the draft creates it
    calls = {"n": 0}
    result = cli.pack_suggest_labels(
        ui, pack_dir2, ev, write=True, runner=stub_runner([good_cfg], calls))
    check("suggest-labels --write creates the target and consumes the draft",
          result is not None and result["accepted"] and not staged_cfg.exists()
          and json.loads((pack_dir2 / "classify.json").read_text())
          == OP_CLASSIFY,
          f"accepted={result and result['accepted']}")

    # the classify judge (unit): empty labels / threshold out of range
    check("classify_judge rejects empty labels",
          any("labels" in e for e in pack.classify_judge(
              {"file": "f", "textColumn": "t", "labels": []})),
          "no error")
    check("classify_judge rejects a threshold out of range",
          any("threshold" in e for e in pack.classify_judge(
              {"file": "f", "textColumn": "t", "labels": ["a"],
               "threshold": 1.5})),
          "no error")
    check("classify_judge accepts the valid config",
          pack.classify_judge(OP_CLASSIFY) == [])

    # op-level: an invalid config is corrected; a missing file is named
    bad_cfg = json.dumps(dict(OP_CLASSIFY, labels=[]), indent=2)
    calls = {"n": 0}
    result = cli.pack_suggest_labels(
        ui, pack_dir2, ev,
        runner=stub_runner([bad_cfg, good_cfg], calls))
    check("suggest-labels: a judge-rejected config is corrected on turn 2",
          result is not None and result["doc"] == OP_CLASSIFY
          and calls["n"] == 2, f"calls={calls['n']}")
    try:
        cli.pack_suggest_labels(ui, pack_dir2,
                                pack_dir2 / "evidence" / "nope.csv",
                                runner=stub_runner(["{}"], {"n": 0}))
        check("suggest-labels rejects a missing evidence file", False,
              "no exception")
    except pack.PackError as exc:
        check("suggest-labels rejects a missing evidence file (named error)",
              "does not exist" in str(exc), str(exc))

    # the prompt carries the sample evidence + the pack-relative path
    task = cli._suggest_labels_task(pack_dir2, ev)
    check("the suggest-labels prompt carries the sample evidence + rel path",
          "A-0001" in task and "evidence/alerts.csv" in task
          and "alert_id" in task, task[:200])

    # ── draft-hypotheses (REQ-012) ──────────────────────────────────
    target_h = pack_dir / "pack" / "hypotheses.json"
    staged_h = pack_dir / "pack" / "hypotheses.draft.json"
    before_h = target_h.read_text()
    good_hyps = json.dumps(OP_HYPS, indent=2)
    calls = {"n": 0}
    result = cli.pack_draft_hypotheses(
        ui, pack_dir, "hypothesis domain",
        runner=stub_runner([good_hyps], calls))
    check("draft-hypotheses stages pack/hypotheses.draft.json; target untouched",
          result is not None and staged_h.exists()
          and target_h.read_text() == before_h
          and json.loads(staged_h.read_text()) == OP_HYPS,
          f"staged={staged_h.exists()} "
          f"target_same={target_h.read_text() == before_h}")
    errs = pack.hypotheses_judge()(OP_HYPS + [dict(OP_HYPS[0])])
    check("hypotheses_judge rejects duplicate hypothesis ids",
          any("duplicate hypothesis id" in e for e in errs), str(errs))
    check("hypotheses_judge accepts the valid draft",
          pack.hypotheses_judge()(OP_HYPS) == [])

    # ── draft-questions (REQ-013) ───────────────────────────────────
    pack_dir3 = write_fixture_pack(tmp, slug="questions-fixture",
                                   facts=FIXTURE_FACTS)
    (pack_dir3 / "evidence").mkdir()
    (pack_dir3 / "evidence" / "alerts.csv").write_text(OP_CSV)
    (pack_dir3 / "classify.json").write_text(json.dumps(OP_CLASSIFY))
    staged_d = pack_dir3 / "sensor" / "decisions.draft.json"
    decide_resp = json.dumps(
        {"decisions_json": json.dumps(OP_DECISIONS)}, indent=2)

    calls = {"n": 0}
    client = StubClient()
    result = cli.pack_draft_questions(
        ui, pack_dir3, client=client,
        runner=stub_runner([decide_resp], calls))
    check("draft-questions stages sensor/decisions.draft.json (judge-accepted)",
          result is not None and result["doc"] == OP_DECISIONS
          and staged_d.exists()
          and not (pack_dir3 / "sensor" / "decisions.json").exists()
          and json.loads(staged_d.read_text()) == OP_DECISIONS,
          f"result={result is not None} staged={staged_d.exists()}")
    check("draft-questions passes the same judge as sense --op decide",
          label.check_decisions(OP_DECISIONS,
                                label.load_config(pack_dir3)) == [])
    check("the judge's dry run called the (stubbed) Strom client",
          len(client.calls) >= 1, f"calls={len(client.calls)}")
    check("draft-questions called the LLM once (accepted on turn 1)",
          calls["n"] == 1, f"calls={calls['n']}")

    # without a classify.json the op fails clearly (nothing staged)
    pack_dir4 = write_fixture_pack(tmp, slug="no-labels-fixture",
                                   facts=FIXTURE_FACTS)
    result = cli.pack_draft_questions(
        ui, pack_dir4, client=StubClient(),
        runner=stub_runner([decide_resp], {"n": 0}))
    check("draft-questions without a classify.json fails (no draft staged)",
          result is None and not (pack_dir4 / "sensor").exists(),
          f"result={result}")

    # cache replay: structure + label coverage, no LLM, no dry run
    os.environ["FACTY_SENSE"] = "cache"
    client2 = StubClient()
    result = cli.pack_draft_questions(
        ui, pack_dir3, client=client2, runner=dead_runner)
    check("draft-questions replays from the cache with no LLM call",
          result is not None and staged_d.exists()
          and json.loads(staged_d.read_text()) == OP_DECISIONS
          and len(client2.calls) == 0,
          f"result={result is not None} dry_run_calls={len(client2.calls)}")
    os.environ["FACTY_SENSE"] = "live"

    # ── review (REQ-014) ────────────────────────────────────────────
    digest_before = dir_digest(pack_dir)
    calls = {"n": 0}
    text = cli.pack_review(
        ui, pack_dir,
        runner=stub_runner(["## Review\n\nR2 is dead."], calls))
    check("review returns the LLM's prose",
          text == "## Review\n\nR2 is dead." and calls["n"] == 1,
          f"text={text!r} calls={calls['n']}")
    check("review leaves the pack directory byte-identical",
          dir_digest(pack_dir) == digest_before)
    check("the review prompt carries the pack's artifacts + the gap analysis",
          all(s in cli._pack_review_task(pack_dir3)
              for s in ("rules.json", "constraints.json", "hypotheses.json",
                        "classify.json", "GAP ANALYSIS",
                        "scenario facts-main.json", "dead rules", "R2",
                        "unanswered question")),
          "missing section")
    os.environ["FACTY_SENSE"] = "cache"
    text2 = cli.pack_review(ui, pack_dir, runner=dead_runner)
    check("review replays from the cache byte-identically, no LLM call",
          text2 == text, f"text2={text2!r}")
    check("review with no cache entry fails clearly (no LLM call made)",
          cli.pack_review(ui, pack_dir4, runner=dead_runner) is None)
    os.environ["FACTY_SENSE"] = "live"
    del os.environ["FACTY_SENSE"]
    del os.environ["FACTY_CACHE_DIR"]

    failed = RESULTS.count(False)
    print()
    print(f"{len(RESULTS) - failed}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
