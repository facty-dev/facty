#!/usr/bin/env python3
# test_strom.py — the Strom decision tier (engine/strom.py + the label
# sensor's backend dispatch + the decision-question judge/generator).
# No network, no key, no LLM: urlopen, the Strom client, the classifier
# and the LLM runner are stubbed (like test_label.py / test_retry.py).
#
# Usage: python3 engine/test_strom.py   (or: ./facty test / make dss-test)

import io
import json
import os
import sys
import tempfile
import urllib.error
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import label   # noqa: E402
import strom   # noqa: E402
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

LABELS = ["a targeted attack", "a probing scan",
          "a benign authorized activity"]

CLASSIFY = {
    "file": "evidence/alerts.csv",
    "idColumn": "alert_id",
    "textColumn": "message",
    "sourceColumn": "src_ip",
    "timeColumn": "timestamp",
    "subject": "alerts",
    "labels": LABELS,
    "template": "This alert is {}.",
    "threshold": 0.7,
    "model": "onnx-community/ModernBERT-base-nli-ONNX",
    "precision": "fp32",
    "prep": "none",
    "backend": "hybrid",
}


def make_case(tmp, classify=None):
    case = Path(tmp) / "triage-alert-flood"
    (case / "evidence").mkdir(parents=True, exist_ok=True)
    (case / "evidence" / "alerts.csv").write_text(CSV)
    (case / "classify.json").write_text(json.dumps(classify or CLASSIFY))
    return case


def default_answer(q):
    if q["type"] == "choice":
        crit = q["criteria"]
        first = next(iter(crit))
        return {"type": "choice", "choice": first, "confidence": 0.9,
                "probabilities": {k: (0.9 if k == first else 0.05)
                                  for k in crit}}
    if q["type"] == "noul":
        return {"type": "noul", "noul": 0.9}
    return {"type": "score", "score": 1.0, "confidence": 0.8,
            "legend": q["criteria"], "probabilities": [0.1, 0.8, 0.1]}


class StubClient:
    """A Strom client stub: fixed or per-question answers, or a failure."""

    def __init__(self, answers=None, fail=None):
        self.answers = answers or {}
        self.fail = fail
        self.calls = []

    def ask(self, state, questions):
        self.calls.append((state, questions))
        if self.fail is not None:
            raise self.fail
        return {"model": "strom-1.0.7",
                "answers": {name: self.answers.get(name, default_answer(q))
                            for name, q in questions.items()},
                "usage": {"input_tokens": 120, "output_tokens": 2,
                          "cached_input_tokens": 60, "cost": 0.000005,
                          "currency": "usd"},
                "metadata": {"server_processing_time_ms": 90}}


def attack_choice(top=0.9):
    """A choice answer favoring 'a targeted attack' at the given top prob."""
    rest = (1.0 - top) / (len(LABELS) - 1)
    return {"type": "choice", "choice": "a targeted attack",
            "confidence": top,
            "probabilities": {"a targeted attack": top,
                              "a probing scan": rest,
                              "a benign authorized activity": rest}}


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, body='{"detail": "nope"}'):
    return urllib.error.HTTPError("https://api.uprelic.com/v1/systemone",
                                  code, "err", {}, io.BytesIO(body.encode()))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        # ── the client (urlopen stubbed) ──────────────────────────────
        real_urlopen = strom.urllib.request.urlopen
        sleeps = []

        def fake_urlopen(req, timeout=None):
            raise AssertionError("urlopen not stubbed for this test")

        strom.urllib.request.urlopen = fake_urlopen
        try:
            # 429 → retried → success
            seq = {"n": 0}

            def rl_then_ok(req, timeout=None):
                seq["n"] += 1
                if seq["n"] == 1:
                    raise http_error(429)
                return FakeResp({"answers": {}, "usage": {}, "metadata": {}})

            strom.urllib.request.urlopen = rl_then_ok
            c = strom.Client("k", sleep=lambda s: sleeps.append(s))
            resp = c.ask({"text": "x"}, {"q": strom.noul("Is it bad?")})
            check("client: 429 is retried, then succeeds",
                  seq["n"] == 2 and resp["answers"] == {})

            # 401 → AuthError, no retry
            seq["n"] = 0

            def always_401(req, timeout=None):
                seq["n"] += 1
                raise http_error(401)

            strom.urllib.request.urlopen = always_401
            c = strom.Client("k-secret-401", sleep=lambda s: sleeps.append(s))
            try:
                c.ask("x", {"q": strom.noul("x")})
                check("client: 401 → AuthError (no retry)", False)
            except strom.AuthError as e:
                check("client: 401 → AuthError (no retry)",
                      seq["n"] == 1 and "k-secret-401" not in str(e))

            # 402 → BalanceError
            def always_402(req, timeout=None):
                raise http_error(402)

            strom.urllib.request.urlopen = always_402
            c = strom.Client("k", sleep=lambda s: sleeps.append(s))
            try:
                c.ask("x", {"q": strom.noul("x")})
                check("client: 402 → BalanceError", False)
            except strom.BalanceError:
                check("client: 402 → BalanceError", True)

            # 422 → InvalidRequest
            def always_422(req, timeout=None):
                raise http_error(422)

            strom.urllib.request.urlopen = always_422
            c = strom.Client("k", sleep=lambda s: sleeps.append(s))
            try:
                c.ask("x", {"q": strom.noul("x")})
                check("client: 422 → InvalidRequest", False)
            except strom.InvalidRequest:
                check("client: 422 → InvalidRequest", True)

            # 500 after retries → ServerError
            def always_500(req, timeout=None):
                raise http_error(500)

            strom.urllib.request.urlopen = always_500
            c = strom.Client("k", retries=2, sleep=lambda s: sleeps.append(s))
            try:
                c.ask("x", {"q": strom.noul("x")})
                check("client: 5xx after retries → ServerError", False)
            except strom.ServerError:
                check("client: 5xx after retries → ServerError", True)

            # connection failure after retries → Unreachable
            def always_down(req, timeout=None):
                raise urllib.error.URLError("dns")

            strom.urllib.request.urlopen = always_down
            c = strom.Client("k", retries=1, sleep=lambda s: sleeps.append(s))
            try:
                c.ask("x", {"q": strom.noul("x")})
                check("client: unreachable → Unreachable", False)
            except strom.Unreachable:
                check("client: unreachable → Unreachable", True)

            # the key never appears in errors
            strom.urllib.request.urlopen = always_401
            c = strom.Client("k-secret-value", sleep=lambda s: None)
            try:
                c.ask("x", {"q": strom.noul("x")})
            except strom.StromError as e:
                check("client: the key never appears in errors",
                      "k-secret-value" not in str(e))

            # the throttle paces request starts (the first goes immediately)
            c = strom.Client("k", rpm=480, sleep=lambda s: sleeps.append(s))
            before = len(sleeps)
            c._throttle()
            c._throttle()
            new = sleeps[before:]
            check("client: the throttle paces request starts",
                  len(new) == 1 and new[0] > 0.1, str(new))
        finally:
            strom.urllib.request.urlopen = real_urlopen

        # from_env without the key
        saved = os.environ.pop(strom.ENV_KEY, None)
        try:
            try:
                strom.from_env()
                check("from_env: no key → a clear posture error", False)
            except strom.StromError as e:
                check("from_env: no key → a clear posture error",
                      strom.ENV_KEY in str(e) and "never commit" in str(e))
        finally:
            if saved:
                os.environ[strom.ENV_KEY] = saved

        # the question helpers
        check("question helpers: choice/noul/score shapes",
              strom.choice("c", {"a": "x"})["type"] == "choice"
              and strom.noul("n")["type"] == "noul"
              and "criteria" not in strom.noul("n")
              and strom.score("s", ["lo", "hi"])["criteria"] == ["lo", "hi"])

        # ── config + the drafted decisions ────────────────────────────
        case = make_case(tmp)
        cfg = label.load_config(case)
        check("load_config: backend defaults to strom (when unset)",
              cfg["backend"] == "hybrid"  # the fixture pins hybrid
              and label.load_config(make_case(
                  tmp, {k: v for k, v in CLASSIFY.items()
                        if k != "backend"}))["backend"] == "strom")
        bad = dict(CLASSIFY, backend="everywhere")
        (case / "classify.json").write_text(json.dumps(bad))
        try:
            label.load_config(case)
            check("load_config: a bad backend is rejected", False)
        except label.LabelError:
            check("load_config: a bad backend is rejected", True)
        bad = dict(CLASSIFY, criteria={"not a label": "x"})
        (case / "classify.json").write_text(json.dumps(bad))
        try:
            label.load_config(case)
            check("load_config: criteria keys must be labels", False)
        except label.LabelError:
            check("load_config: criteria keys must be labels", True)
        (case / "classify.json").write_text(json.dumps(CLASSIFY))

        check("load_decisions: absent → None (the default question set)",
              label.load_decisions(case) is None)
        doc = {"model": "strom-1.0.7",
               "questions": {"class": strom.choice(
                   "Classify this alert.",
                   {lab: lab for lab in LABELS})}}
        (case / "sensor").mkdir(exist_ok=True)
        (case / "sensor" / "decisions.json").write_text(json.dumps(doc))
        check("load_decisions: a valid drafted doc loads",
              label.load_decisions(case) == doc)
        (case / "sensor" / "decisions.json").write_text("{oops")
        try:
            label.load_decisions(case)
            check("load_decisions: malformed JSON is rejected", False)
        except label.LabelError:
            check("load_decisions: malformed JSON is rejected", True)
        (case / "sensor" / "decisions.json").write_text(json.dumps(
            {"model": "strom-1.0.7", "questions": {"q": strom.noul("x")}}))
        try:
            label.load_decisions(case)
            check("load_decisions: no label coverage is rejected", False)
        except label.LabelError:
            check("load_decisions: no label coverage is rejected", True)
        (case / "sensor" / "decisions.json").unlink()

        qs, choice_name = label.decision_questions(cfg)
        check("decision_questions: the default choice question covers the labels",
              choice_name == "class" and set(qs["class"]["criteria"]) == set(LABELS))
        qs, choice_name = label.decision_questions(cfg, doc)
        check("decision_questions: the drafted doc's choice question is picked",
              choice_name == "class" and qs == doc["questions"])

        # ── the judge ─────────────────────────────────────────────────
        good = {"model": "strom-1.0.7",
                "questions": {"class": strom.choice(
                    "Classify this alert.", {lab: lab for lab in LABELS})}}
        check("check_decisions: a valid doc is accepted",
              label.check_decisions(good, cfg) == [])
        bad = {"model": "strom-1.0.7",
               "questions": {"class": strom.choice("c", {"only one": "x"})}}
        errs = label.check_decisions(bad, cfg)
        check("check_decisions: missing label coverage is flagged",
              any("covers the labels" in e for e in errs), str(errs))
        bad = {"model": "strom-1.0.7",
               "questions": {"class": strom.choice("c", {lab: lab for lab in LABELS}),
                             "bad": {"type": "essay", "instructions": "write"}}}
        errs = label.check_decisions(bad, cfg)
        check("check_decisions: a bad question type is flagged",
              any("type must be" in e for e in errs), str(errs))
        bad = {"model": "strom-1.0.7",
               "questions": {"class": strom.choice("c", {lab: lab for lab in LABELS}),
                             "s": strom.score("u", ["only one level"])}}
        errs = label.check_decisions(bad, cfg)
        check("check_decisions: a 1-level score rubric is flagged",
              any("≥2" in e for e in errs), str(errs))
        # dry run: probabilities must sum to 1
        rows = label.read_rows(case, cfg)
        stub = StubClient(answers={"class": {
            "type": "choice", "choice": "a targeted attack",
            "confidence": 0.9,
            "probabilities": {"a targeted attack": 0.9,
                              "a probing scan": 0.2,
                              "a benign authorized activity": 0.2}}})
        errs = label.check_decisions(good, cfg, client=stub, sample_rows=rows[:2])
        check("check_decisions: dry-run probabilities must sum to ~1",
              any("sum to" in e for e in errs), str(errs))
        # dry run: degenerate (every row the same choice at >0.95)
        stub = StubClient(answers={"class": attack_choice(0.99)})
        errs = label.check_decisions(good, cfg, client=stub,
                                     sample_rows=rows[:4])
        check("check_decisions: a degenerate dry run is flagged",
              any("degenerate" in e for e in errs), str(errs))
        # dry run: the client failing is an error
        stub = StubClient(fail=strom.Unreachable("dns"))
        errs = label.check_decisions(good, cfg, client=stub,
                                     sample_rows=rows[:2])
        check("check_decisions: a failing dry run is an error",
              any("dry run failed" in e for e in errs), str(errs))
        # dry run: clean → accepted
        stub = StubClient(answers={
            "class": attack_choice(0.8),
        })
        # vary the answer per row so the dry run is not degenerate
        n = {"i": 0}

        class VaryClient(StubClient):
            def ask(self, state, questions):
                n["i"] += 1
                lab = LABELS[n["i"] % len(LABELS)]
                probs = {l: (0.8 if l == lab else 0.1) for l in LABELS}
                return {"model": "strom-1.0.7",
                        "answers": {"class": {"type": "choice", "choice": lab,
                                               "confidence": 0.8,
                                               "probabilities": probs}},
                        "usage": {}, "metadata": {}}
        errs = label.check_decisions(good, cfg, client=VaryClient(),
                                     sample_rows=rows[:4])
        check("check_decisions: a clean dry run is accepted", errs == [],
              str(errs))

        # ── generate_questions (the stubbed LLM + client) ─────────────
        def runner_returning(texts):
            it = iter(texts)
            def runner(path, stream=None):
                return next(it)
            return runner

        ok_doc = {"model": "strom-1.0.7",
                  "questions": {"class": strom.choice(
                      "Classify this alert.", {lab: lab for lab in LABELS})}}
        wrapped = json.dumps({"decisions_json": json.dumps(ok_doc)})
        bad_doc = {"model": "strom-1.0.7", "questions": {"q": strom.noul("x")}}
        wrapped_bad = json.dumps({"decisions_json": json.dumps(bad_doc)})
        stub = VaryClient()
        notes = []
        out = label.generate_questions(case, cfg, runner=runner_returning(
            [wrapped_bad, wrapped]), client=stub, note=notes.append)
        check("generate_questions: broken → corrected → accepted (2 attempts)",
              out == ok_doc and len(notes) == 2
              and "rejected" in notes[0] and "accepted" in notes[1],
              str(notes))
        notes = []
        try:
            label.generate_questions(case, cfg, runner=runner_returning(
                [wrapped_bad, wrapped_bad, wrapped_bad]), client=stub,
                note=notes.append)
            check("generate_questions: exhaustion after 1+2 attempts", False)
        except ValueError as e:
            check("generate_questions: exhaustion after 1+2 attempts",
                  "after 3 attempts" in str(e) and len(notes) == 2, str(notes))

        def dead_runner(path, stream=None):
            raise RuntimeError("pi unreachable")

        try:
            label.generate_questions(case, cfg, runner=dead_runner, client=stub)
            check("generate_questions: an unreachable LLM fails fast", False)
        except RuntimeError as e:
            check("generate_questions: an unreachable LLM fails fast",
                  "unreachable" in str(e))
        local_cfg = dict(CLASSIFY, backend="local")
        (case / "classify.json").write_text(json.dumps(local_cfg))
        try:
            label.generate_questions(case, local_cfg, runner=runner_returning([wrapped]),
                                     client=stub)
            check("generate_questions: backend=local refuses to draft", False)
        except label.LabelError:
            check("generate_questions: backend=local refuses to draft", True)
        (case / "classify.json").write_text(json.dumps(CLASSIFY))

        # ── run_sensor: the backend dispatch ──────────────────────────
        def tier1_score(rs, labels, template):
            # rows 0,1 classified by tier 1; rows 2,3 gated (below 0.7)
            out = []
            for i, _r in enumerate(rs):
                if i < 2:
                    out.append([0.9, 0.05, 0.05])
                else:
                    out.append([0.5, 0.3, 0.2])
            return out

        cfg = label.load_config(case)
        # local: tier 1 only
        client = StubClient(answers={"class": attack_choice(0.95)})
        facts, src = label.run_sensor(case, dict(cfg, backend="local"),
                                      score_fn=tier1_score, client=client)
        check("run_sensor: backend=local runs tier 1 only",
              src == "classifier" and client.calls == []
              and sum(1 for f in facts if f["predicate"] == "classifiedAs"
                      and f["value"] == label.UNCLASSIFIED) == 2)
        # strom: every row scored by the decider tier
        cfg_s = dict(CLASSIFY, backend="strom")
        client = StubClient(answers={"class": attack_choice(0.95)})
        facts, src = label.run_sensor(case, cfg_s, score_fn=tier1_score,
                                      client=client)
        by_id = {f["id"]: f for f in facts}
        check("run_sensor: backend=strom scores every row (source: decider)",
              src == "decider" and len(client.calls) == 4
              and all(f["value"] == "a targeted attack"
                      for f in facts if f["predicate"] == "classifiedAs")
              and by_id["cl-A-0001"]["confidence"] == 0.95)
        check("run_sensor: decider facts validate against the schema",
              label.validate_facts(facts) == [])
        # strom + API failure → tier 1 fallback
        client = StubClient(fail=strom.Unreachable("dns"))
        facts, src = label.run_sensor(case, cfg_s, score_fn=tier1_score,
                                      client=client)
        check("run_sensor: strom failure → tier 1 fallback (logged in source)",
              src.startswith("classifier (decider failed:")
              and sum(1 for f in facts if f["predicate"] == "classifiedAs"
                      and f["value"] == label.UNCLASSIFIED) == 2, src)
        # hybrid: tier 1 bulk + the decider adjudicates the gated rows
        client = StubClient(answers={"class": attack_choice(0.95)})
        facts, src = label.run_sensor(case, cfg, score_fn=tier1_score,
                                      client=client)
        by_id = {f["id"]: f for f in facts}
        check("run_sensor: hybrid adjudicates only the gated rows",
              src == "classifier+decider" and len(client.calls) == 2
              and by_id["cl-A-0003"]["value"] == "a targeted attack"
              and by_id["cl-A-0003"]["confidence"] == 0.95
              and by_id["cl-A-0001"]["confidence"] == 0.9, src)
        # hybrid without a key → the gated rows stay unclassified
        os.environ.pop(strom.ENV_KEY, None)
        facts, src = label.run_sensor(case, cfg, score_fn=tier1_score)
        check("run_sensor: hybrid without a key degrades to tier 1",
              src.startswith("classifier (decider skipped:")
              and sum(1 for f in facts if f["predicate"] == "classifiedAs"
                      and f["value"] == label.UNCLASSIFIED) == 2, src)
        # hybrid + API failure → the gated rows stay unclassified
        client = StubClient(fail=strom.BalanceError("402"))
        facts, src = label.run_sensor(case, cfg, score_fn=tier1_score,
                                      client=client)
        check("run_sensor: hybrid + decider failure keeps the gate",
              src.startswith("classifier (decider skipped:")
              and sum(1 for f in facts if f["predicate"] == "classifiedAs"
                      and f["value"] == label.UNCLASSIFIED) == 2, src)
        # the decider tier's API usage accumulates for the op's log line
        client = StubClient(answers={"class": attack_choice(0.95)})
        usage = {}
        label.run_sensor(case, cfg, score_fn=tier1_score, client=client,
                         usage=usage)
        check("run_sensor: the decider usage accumulates (calls/tokens/"
              "cached/cost)",
              usage == {"calls": 2, "input_tokens": 240,
                        "cached_input_tokens": 120, "cost": 0.00001},
              str(usage))
        client = StubClient(answers={"class": attack_choice(0.95)})
        usage = {}
        label.run_sensor(case, dict(cfg, backend="local"), score_fn=tier1_score,
                         client=client, usage=usage)
        check("run_sensor: the local tier leaves the usage empty",
              usage == {} and len(client.calls) == 0)  # no decider calls
        # offline: every backend runs the local tier only
        client = StubClient(answers={"class": attack_choice(0.95)})
        facts, src = label.run_sensor(case, cfg, score_fn=tier1_score,
                                      client=client, offline=True)
        check("run_sensor: offline mode runs the local tier only",
              src == "classifier (offline: the decider tier is skipped)"
              and client.calls == [])
        client = StubClient(answers={"class": attack_choice(0.95)})
        facts, src = label.run_sensor(case, cfg_s, score_fn=tier1_score,
                                      client=client, offline=True)
        check("run_sensor: offline + backend=strom degrades to the local tier",
              src == "classifier (offline: the decider tier is skipped)"
              and client.calls == []
              and sum(1 for f in facts if f["predicate"] == "classifiedAs"
                      and f["value"] == label.UNCLASSIFIED) == 2, src)

        # ── extras: the drafted noul/score questions → decision facts ──
        doc = {"model": "strom-1.0.7",
               "questions": {
                   "class": strom.choice("Classify this alert.",
                                         {lab: lab for lab in LABELS}),
                   "isExternal": strom.noul("Is the source external?"),
                   "urgency": strom.score("How urgent?",
                                          ["Can wait", "This week", "Today"])}}
        client = StubClient(answers={
            "class": attack_choice(0.95),
            "isExternal": {"type": "noul", "noul": 0.87},
            "urgency": {"type": "score", "score": 1.6, "confidence": 0.8,
                        "legend": ["Can wait", "This week", "Today"],
                        "probabilities": [0.1, 0.5, 0.4]}})
        cfg_s = dict(CLASSIFY, backend="strom")
        facts, src = label.run_sensor(case, cfg_s, score_fn=tier1_score,
                                      client=client, decisions=doc)
        by_pred = {}
        for f in facts:
            by_pred.setdefault(f["predicate"], []).append(f)
        ext = by_pred.get("isExternal", [])
        urg = by_pred.get("urgency", [])
        check("extras: noul/score questions become per-row decision facts",
              len(ext) == 4 and len(urg) == 4
              and ext[0]["value"] == 0.87 and ext[0]["confidence"] == 1.0
              and ext[0]["source"] == "evidence/alerts.csv:row 1"
              and urg[0]["value"] == 1.6 and urg[0]["confidence"] == 0.8
              and urg[0]["id"] == "dq-urgency-A-0001",
              str(ext[:1] + urg[:1]))
        check("extras: the decision facts validate against the schema",
              label.validate_facts(facts) == [])

        # ── the CLI: ops, offline mode, sense_label's tier lines ─────
        ops = cli.sensing_ops(case)
        check("sensing_ops: the decide op appears for the strom backends",
              "decide" in ops and "decide" in cli.sensing_ops(
                  make_case(tmp, dict(CLASSIFY, backend="strom"))))
        local_case = make_case(tmp, dict(CLASSIFY, backend="local"))
        check("sensing_ops: no decide op for backend=local",
              "decide" not in cli.sensing_ops(local_case))

        # sense_one: offline forces cache mode for the LLM ops
        (case / "evidence-index.json").write_text("[]")
        (case / "entities.json").write_text("[]")
        (case / "facts.json").write_text("[]")
        seen = {}
        real_extract = cli.sense_extract
        real_label = cli.sense_label

        def stub_extract(ui, tag, label_, noun, schema_name, task, fallback,
                         **kw):
            seen["mode"] = kw.get("mode")
            return []

        def stub_label(ui, case_, files, **kw):
            seen["label_mode"] = kw.get("mode")
            seen["label_offline"] = kw.get("offline")
            return []

        cli.sense_extract = stub_extract
        cli.sense_label = stub_label
        try:
            ui = StubUI()
            cli.sense_one(ui, case, "entities", offline=True)
            check("sense_one: offline forces cache mode for the LLM ops",
                  seen["mode"] == "cache"
                  and any("offline mode" in ln for ln in ui.lines))
            ui = StubUI()
            cli.sense_one(ui, case, "label", offline=True)
            check("sense_one: offline runs the label op's local tier live",
                  seen["label_mode"] is None and seen["label_offline"] is True
                  and not any("offline mode" in ln for ln in ui.lines))
        finally:
            cli.sense_extract = real_extract
            cli.sense_label = real_label

        # sense_label: backend-aware lines + the cache key rides the backend
        os.environ["FACTY_CACHE_DIR"] = str(Path(tmp) / "cache")
        ui = StubUI()
        recorded = [{"id": "cl-A-0001", "type": "evidence", "subject": "A-0001",
                     "predicate": "classifiedAs", "value": "a targeted attack",
                     "confidence": 0.9, "source": "evidence/alerts.csv:row 1"}]
        (case / "facts.json").write_text(json.dumps(recorded))
        files = [case / "evidence" / "alerts.csv"]
        real_run_sensor = label.run_sensor

        def stub_run_sensor(case_dir, config=None, **kw):
            u = kw.get("usage")
            if u is not None:  # an empty dict is falsy — never `or {}`
                u.update({"calls": 2, "input_tokens": 240,
                          "cached_input_tokens": 120, "cost": 0.00001})
            return recorded, "classifier+decider"

        label.run_sensor = stub_run_sensor
        try:
            out = cli.sense_label(ui, case, files, mode="live")
            check("sense_label: hybrid logs both tiers (with the API usage) "
                  "and caches the output",
                  out == recorded
                  and any("tier 2" in ln and "2 calls" in ln
                          and "50% cached" in ln for ln in ui.lines)
                  and any("[decider · induction]" in ln for ln in ui.lines)
                  and any("sensor output cached" in ln for ln in ui.lines),
                  str(ui.lines))
            cache_files = list((Path(tmp) / "cache").rglob("*.json"))
            check("sense_label: the cache entry exists (replayable offline)",
                  len(cache_files) == 1)
            ui2 = StubUI()
            out2 = cli.sense_label(ui2, case, files, mode="cache")
            check("sense_label: cache mode replays without the models",
                  out2 == recorded
                  and any("cache hit" in ln for ln in ui2.lines))
        finally:
            label.run_sensor = real_run_sensor

    failed = len(RESULTS) - sum(RESULTS)
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
