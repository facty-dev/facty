#!/usr/bin/env python3
# test_label.py — the label sensor (engine/label.py): config, prep, the
# classifier math, facts + aggregates, the fallback ladder, the parser
# contract, the parser generator's correction loop, and the CLI op's
# cache/fallback flow. No model, no LLM, no network: the classifier and
# the LLM runner are stubbed (like test_retry.py stubs the runner).
#
# Usage: python3 engine/test_label.py   (or: ./facty test / make dss-test)

import json
import os
import sys
import tempfile
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import label   # noqa: E402
import cli     # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS" if ok else "FAIL") + f"  {name}"
          + (f" — {detail}" if detail and not ok else ""))


class StubUI:
    def __init__(self):
        self.lines = []

    def log(self, tag, msg):
        self.lines.append(f"[{tag}] {msg}")

    def step(self, tag, title):
        pass


CSV = """alert_id,timestamp,src_ip,signature,severity,message
A-0001,2026-10-12T02:10:01,185.220.44.7,sql-injection,high,SQL injection attempt on /login from 185.220.44.7
A-0002,2026-10-12T02:10:05,185.220.44.7,credential-stuffing,high,Credential stuffing: 412 failed logins from 3 IPs
A-0003,2026-10-12T02:11:00,103.4.5.6,port-scan,medium,Port scan: 103.4.5.6 probed 40 ports on the firewall
A-0004,2026-10-12T02:12:00,10.2.3.4,backup,low,Scheduled backup job matched data exfiltration signature
"""

CLASSIFY = {
    "file": "evidence/alerts.csv",
    "idColumn": "alert_id",
    "textColumn": "message",
    "sourceColumn": "src_ip",
    "timeColumn": "timestamp",
    "subject": "alerts",
    "labels": ["a targeted attack", "a background scan",
               "a benign authorized activity"],
    "template": "This alert is {}.",
    "threshold": 0.7,
    "model": "onnx-community/ModernBERT-base-nli-ONNX",
    "precision": "fp32",
    "prep": "none",
    "backend": "local",  # these tests exercise the classifier tier
}

LOG = """2026-10-12T02:10:01Z ALERT A-0001 src=185.220.44.7 sql injection attempt on /login
2026-10-12T02:10:05Z ALERT A-0002 src=185.220.44.7 credential stuffing against vpn
garbage line that is not an alert
2026-10-12T02:11:00Z ALERT A-0003 src=103.4.5.6 port scan of 40 ports
"""

CLEAN_PARSER = '''import re

def parse(text):
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = re.match(r"(\\S+)\\s+ALERT\\s+(\\S+)\\s+src=(\\S+)\\s+(.*)", line)
        if m:
            rows.append({"timestamp": m.group(1), "alert_id": m.group(2),
                         "src_ip": m.group(3), "message": m.group(4)})
        else:
            rows.append({"unparsed": line})
    return rows
'''

CLEAN_TESTS = '''import unittest
import extract

class TestParse(unittest.TestCase):
    def test_records_and_unparsed(self):
        rows = extract.parse("2026-10-12T02:10:01Z ALERT A-0001 src=185.220.44.7 sql injection\\nnoise line\\n")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["alert_id"], "A-0001")
        self.assertIn("unparsed", rows[1])

    def test_empty(self):
        self.assertEqual(extract.parse(""), [])

    def test_all_lines_accounted(self):
        self.assertEqual(len(extract.parse("a\\nb\\nc\\n")), 3)

if __name__ == "__main__":
    unittest.main()
'''

BROKEN_PARSER = "import socket\n\ndef parse(text):\n    return []\n"


def make_case(tmp, csv_text=CSV, classify=None, facts=None, with_parser=False,
              log_text=None):
    case = Path(tmp) / "triage-alert-flood"
    (case / "evidence").mkdir(parents=True)
    (case / "evidence" / "alerts.csv").write_text(csv_text)
    (case / "classify.json").write_text(json.dumps(classify or CLASSIFY))
    if facts is not None:
        (case / "facts.json").write_text(json.dumps(facts))
    if with_parser:
        (case / "sensor").mkdir(parents=True, exist_ok=True)
        (case / "sensor" / "extract.py").write_text(CLEAN_PARSER)
    if log_text is not None:
        (case / "evidence" / "alerts.log").write_text(log_text)
    return case


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # ── config ────────────────────────────────────────────────────
        case = make_case(tmp)
        cfg = label.load_config(case)
        check("load_config: defaults applied",
              cfg["threshold"] == 0.7 and cfg["precision"] == "fp32"
              and cfg["prep"] == "none" and cfg["subject"] == "alerts")
        bad = make_case(Path(tmp) / "bad1")
        (bad / "classify.json").write_text(json.dumps({"file": "evidence/alerts.csv"}))
        try:
            label.load_config(bad)
            check("load_config: missing keys rejected", False)
        except label.LabelError:
            check("load_config: missing keys rejected", True)
        bad2 = make_case(Path(tmp) / "bad2")
        cfg2 = dict(CLASSIFY, precision="fp8")
        (bad2 / "classify.json").write_text(json.dumps(cfg2))
        try:
            label.load_config(bad2)
            check("load_config: bad precision rejected", False)
        except label.LabelError:
            check("load_config: bad precision rejected", True)

        # ── slug + read_rows ──────────────────────────────────────────
        check("_slug: article-ful label → camelCase stem",
              label._slug("a targeted attack") == "targetedAttack"
              and label._slug("a benign authorized activity") == "benignAuthorizedActivity")
        rows = label.read_rows(case, cfg)
        check("read_rows: parses the CSV, keeps the configured columns",
              len(rows) == 4 and rows[0]["id"] == "A-0001"
              and rows[0]["source"] == "185.220.44.7"
              and rows[0]["time"] == "2026-10-12T02:10:01"
              and rows[0]["row"] == 1)
        badcsv = make_case(Path(tmp) / "badcsv",
                           csv_text="alert_id,message\nA-1,hello\n")
        try:
            label.read_rows(badcsv, label.load_config(badcsv))
            check("read_rows: missing column rejected", False)
        except label.LabelError:
            check("read_rows: missing column rejected", True)

        # ── softmax ───────────────────────────────────────────────────
        p = label.softmax([2.0, 1.0, 0.0])
        check("softmax: normalizes, argmax preserved",
              abs(sum(p) - 1.0) < 1e-9 and max(range(3), key=lambda i: p[i]) == 0)

        # ── build_facts: labels, gating, aggregates ───────────────────
        probs = [[0.9, 0.05, 0.05], [0.8, 0.1, 0.1],
                 [0.1, 0.85, 0.05], [0.4, 0.35, 0.25]]
        facts = label.build_facts(cfg, rows, probs, case)
        by_id = {f["id"]: f for f in facts}
        check("build_facts: per-item labels + source rows",
              by_id["cl-A-0001"]["value"] == "a targeted attack"
              and by_id["cl-A-0003"]["value"] == "a background scan"
              and by_id["cl-A-0001"]["source"] == "evidence/alerts.csv:row 1"
              and by_id["cl-A-0001"]["confidence"] == 0.9)
        check("build_facts: below threshold → unclassified",
              by_id["cl-A-0004"]["value"] == "unclassified")
        check("build_facts: aggregates (counts, confidence, sources, window)",
              by_id["ag-classifiedcount"]["value"] == 4
              and by_id["ag-targetedattackcount"]["value"] == 2
              and by_id["ag-targetedattackmeanconfidence"]["value"] == 0.85
              and by_id["ag-targetedattacktopsource"]["value"] == "185.220.44.7"
              and by_id["ag-targetedattacktopsourcecount"]["value"] == 2
              and by_id["ag-targetedattackdistinctsources"]["value"] == 1
              and by_id["ag-targetedattackwindow"]["value"]
              == ["2026-10-12T02:10:01", "2026-10-12T02:10:05"]
              and by_id["ag-backgroundscancount"]["value"] == 1
              and by_id["ag-unclassifiedcount"]["value"] == 1
              and by_id["ag-topsource"]["value"] == "185.220.44.7"
              and by_id["ag-distinctsources"]["value"] == 3)
        check("build_facts: facts validate against the facts schema",
              label.validate_facts(facts) == [])

        # ── run_sensor with a stubbed classifier ──────────────────────
        def stub_score(rs, labels, template):
            return [[0.9, 0.05, 0.05] for _ in rs]

        facts2, src = label.run_sensor(case, cfg, score_fn=stub_score)
        check("run_sensor: prep=none reads the pile, classifier labels it",
              src == "classifier" and len(facts2) == 4 + len(
                  [f for f in facts2 if f["id"].startswith("ag-")])
              and all(f["value"] == "a targeted attack"
                      for f in facts2 if f["predicate"] == "classifiedAs"))

        # fallback ladder: the classifier fails on prep rows → raw chunks
        calls = {"n": 0}

        def flaky_score(rs, labels, template):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("model exploded")
            return [[0.9, 0.05, 0.05] for _ in rs]

        facts3, src3 = label.run_sensor(case, cfg, score_fn=flaky_score)
        check("run_sensor: classifier failure → raw-chunks fallback",
              src3 == "raw-chunks" and calls["n"] == 2
              and any(f["source"].startswith("evidence/alerts.csv:lines")
                      for f in facts3 if f["predicate"] == "classifiedAs"))

        def dead_score(rs, labels, template):
            raise RuntimeError("model exploded")

        try:
            label.run_sensor(case, cfg, score_fn=dead_score)
            check("run_sensor: total failure raises (the op falls back)", False)
        except RuntimeError:
            check("run_sensor: total failure raises (the op falls back)", True)

        # ── parser contract + execution ───────────────────────────────
        check("check_parser_contract: clean parser passes",
              label.check_parser_contract(CLEAN_PARSER) == [])
        check("check_parser_contract: network import rejected",
              any("socket" in e
                  for e in label.check_parser_contract(BROKEN_PARSER)))
        check("check_parser_contract: eval rejected",
              any("eval" in e for e in label.check_parser_contract(
                  "def parse(text):\n    return eval(text)\n")))
        check("check_parser_contract: missing parse() rejected",
              any("parse" in e for e in label.check_parser_contract(
                  "x = 1\n")))
        check("check_parser_contract: syntax error rejected",
              label.check_parser_contract("def parse(:\n") != [])

        pcase = make_case(Path(tmp) / "parsercase", with_parser=True,
                          log_text=LOG,
                          classify=dict(CLASSIFY, prep="parser",
                                        file="evidence/alerts.log"))
        pcfg = label.load_config(pcase)
        prows = label.run_parser(pcase, pcfg)
        check("run_parser: committed parser extracts rows + unparsed bucket",
              len(prows) == 4 and prows[0]["id"] == "A-0001"
              and prows[0]["text"].startswith("sql injection")
              and prows[2]["text"] is None and prows[2]["unparsed"] ==
              "garbage line that is not an alert")
        broken = make_case(Path(tmp) / "brokenparser", with_parser=True,
                           log_text=LOG,
                           classify=dict(CLASSIFY, prep="parser",
                                         file="evidence/alerts.log"))
        (broken / "sensor" / "extract.py").write_text(
            "def parse(text):\n    raise ValueError('boom')\n")
        try:
            label.run_parser(broken, label.load_config(broken))
            check("run_parser: crashing parser raises", False)
        except RuntimeError:
            check("run_parser: crashing parser raises", True)
        nongen = make_case(Path(tmp) / "nogen", log_text=LOG, classify=dict(
            CLASSIFY, prep="parser", file="evidence/alerts.log"))
        try:
            label.run_parser(nongen, label.load_config(nongen))
            check("run_parser: missing parser raises (generate it first)", False)
        except RuntimeError:
            check("run_parser: missing parser raises (generate it first)", True)

        # ── generate_parser: the correction loop (stubbed LLM) ────────
        def parser_obj(src_py, src_test):
            return json.dumps({"extract_py": src_py, "extract_test_py": src_test})

        attempts = {"n": 0}

        def fixing_runner(staged, stream):
            attempts["n"] += 1
            return parser_obj(BROKEN_PARSER if attempts["n"] == 1
                              else CLEAN_PARSER, CLEAN_TESTS)

        notes = []
        obj = label.generate_parser(pcase, pcfg, runner=fixing_runner,
                                    note=notes.append)
        check("generate_parser: broken → corrected → accepted (2 attempts)",
              attempts["n"] == 2 and obj["extract_py"] == CLEAN_PARSER
              and any("rejected" in n for n in notes))

        attempts2 = {"n": 0}

        def stuck_runner(staged, stream):
            attempts2["n"] += 1
            return parser_obj(BROKEN_PARSER, CLEAN_TESTS)

        try:
            label.generate_parser(pcase, pcfg, runner=stuck_runner)
            check("generate_parser: exhaustion fails after 1+2 attempts", False)
        except ValueError:
            check("generate_parser: exhaustion fails after 1+2 attempts",
                  attempts2["n"] == 3)

        attempts3 = {"n": 0}

        def dead_runner(staged, stream):
            attempts3["n"] += 1
            raise RuntimeError("LLM unreachable")

        try:
            label.generate_parser(pcase, pcfg, runner=dead_runner)
            check("generate_parser: unreachable LLM fails fast (no retry)", False)
        except RuntimeError:
            check("generate_parser: unreachable LLM fails fast (no retry)",
                  attempts3["n"] == 1)

        # ── CLI: ops, phase-1 exclusion, the op's cache/fallback flow ──
        ops = cli.sensing_ops(case)
        check("sensing_ops: the label op appears for classify.json cases",
              "label" in ops and ops["label"][1] == "facts.schema.json"
              and ops["label"][2] == [case / "evidence" / "alerts.csv"])
        check("sensing_ops: the parser op appears only for prep=parser",
              "parser" not in ops and "parser" in cli.sensing_ops(pcase))
        phase1 = {f.name for f in cli.phase1_evidence(case)}
        (case / "evidence" / "narrative.txt").write_text("prose\n")
        phase1 = {f.name for f in cli.phase1_evidence(case)}
        check("phase1_evidence: the sensor's pile is excluded (the LLM never sees it)",
              phase1 == {"narrative.txt"})

        # sense_label: live → cache → replay; failure → recorded
        os.environ["FACTY_CACHE_DIR"] = str(Path(tmp) / "cache")
        ui = StubUI()
        recorded = [
            {"id": "f1", "type": "case", "subject": "flood", "predicate": "note",
             "value": "prose fact", "confidence": 0.9,
             "source": "evidence/narrative.txt:1"},
            {"id": "cl-A-0001", "type": "evidence", "subject": "A-0001",
             "predicate": "classifiedAs", "value": "a targeted attack",
             "confidence": 0.9, "source": "evidence/alerts.csv:row 1"},
        ]
        (case / "facts.json").write_text(json.dumps(recorded))
        files = [case / "evidence" / "alerts.csv"]
        stub_facts = [dict(recorded[1], id="cl-stub")]

        real_run_sensor = label.run_sensor
        calls4 = {"n": 0}

        def stub_run_sensor(case_dir, config=None, **kw):
            calls4["n"] += 1
            return stub_facts, "classifier"

        label.run_sensor = stub_run_sensor
        try:
            out = cli.sense_label(ui, case, files, mode="live")
            check("sense_label: live run caches the sensor output",
                  out == stub_facts and calls4["n"] == 1
                  and any("sensor output cached" in ln for ln in ui.lines))
            ui2 = StubUI()
            out2 = cli.sense_label(ui2, case, files, mode="cache")
            check("sense_label: cache mode replays without the model",
                  out2 == stub_facts and calls4["n"] == 1
                  and any("cache hit" in ln for ln in ui2.lines))

            def dead_run_sensor(case_dir, config=None, **kw):
                raise RuntimeError("deps missing")

            label.run_sensor = dead_run_sensor
            import shutil
            shutil.rmtree(Path(tmp) / "cache")
            ui3 = StubUI()
            out3 = cli.sense_label(ui3, case, files, mode="live")
            check("sense_label: failure + no cache → recorded facts (by source)",
                  out3 == [recorded[1]]
                  and any("recorded label facts" in ln for ln in ui3.lines))
        finally:
            label.run_sensor = real_run_sensor

    failed = len(RESULTS) - sum(RESULTS)
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
