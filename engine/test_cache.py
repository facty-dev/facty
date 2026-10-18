#!/usr/bin/env python3
# test_cache.py — the LLM response cache (no LLM needed: the runner is
# stubbed, like test_retry.py).
#
# The cache stores the raw LLM responses for the demo examples so the
# e2e pipeline can run without live LLM calls (FACTY_SENSE=cache) —
# reproducible demos, and the deterministic side stays testable offline.
# Live mode (the default) calls the LLM and caches the response; on
# failure it falls back cache → recorded sensing (logged, never silent).
#
# Usage: python3 engine/test_cache.py   (or: ./facty test / make dss-test)

import json
import os
import sys
import tempfile
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import cli     # noqa: E402

FACT = {"id": "f1", "type": "case", "subject": "s", "predicate": "p",
        "value": True, "confidence": 0.9, "source": "evidence/x.txt:1"}
RESPONSES = [json.dumps([FACT, dict(FACT, id="f2")])]

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f" — {detail}" if detail and not ok else ""))


class StubUI:
    def __init__(self):
        self.lines = []

    def log(self, tag, msg):
        self.lines.append(f"[{tag}] {msg}")

    def step(self, tag, title):
        pass


def stub_runner(responses, calls):
    def runner(staged_path, stream):
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return responses[idx]
    return runner


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["FACTY_CACHE_DIR"] = str(Path(tmp) / "cache")
        ui = StubUI()

        # live mode: the stubbed LLM answers; the raw response is cached
        os.environ["FACTY_SENSE"] = "live"
        calls = {"n": 0}
        result = cli.sense_extract(ui, "llm · induction", "extract the things", "things",
                                   "facts.schema.json", "produce things", [],
                                   runner=stub_runner(RESPONSES, calls),
                                   cache_ns="test-case")
        check("live mode returns the LLM's response",
              [r["id"] for r in result] == ["f1", "f2"], str(result))
        check("live mode called the LLM once", calls["n"] == 1, str(calls["n"]))
        cache_files = list(Path(os.environ["FACTY_CACHE_DIR"]).rglob("*.json"))
        check("live mode caches the raw LLM response", len(cache_files) == 1,
              str(cache_files))

        # cache mode: no LLM call; the cached response is replayed
        os.environ["FACTY_SENSE"] = "cache"
        calls2 = {"n": 0}
        result2 = cli.sense_extract(ui, "llm · induction", "extract the things", "things",
                                    "facts.schema.json", "produce things", [],
                                    runner=stub_runner(RESPONSES, calls2),
                                    cache_ns="test-case")
        check("cache mode replays the cached response",
              [r["id"] for r in result2] == ["f1", "f2"], str(result2))
        check("cache mode never calls the LLM", calls2["n"] == 0, str(calls2["n"]))

        # cache miss in cache mode → the recorded sensing, still no LLM
        result3 = cli.sense_extract(ui, "llm · induction", "extract the things", "things",
                                    "facts.schema.json", "produce DIFFERENT things",
                                    [{"id": "rec", "type": "case", "subject": "s",
                                      "predicate": "p", "value": 1, "confidence": 1.0,
                                      "source": "evidence/r.txt:1"}],
                                    runner=stub_runner(RESPONSES, calls2),
                                    cache_ns="test-case")
        check("cache mode with no cache falls back to the recorded sensing",
              [r["id"] for r in result3] == ["rec"], str(result3))
        check("the fallback still never called the LLM", calls2["n"] == 0,
              str(calls2["n"]))

        # on_response carries the raw response + its source
        captured = []
        os.environ["FACTY_SENSE"] = "live"
        calls3 = {"n": 0}
        cli.sense_extract(ui, "llm · induction", "extract the things", "things",
                          "facts.schema.json", "produce things", [],
                          runner=stub_runner(RESPONSES, calls3),
                          cache_ns="test-case",
                          on_response=lambda text, source: captured.append((text, source)))
        check("on_response carries the raw response + source (live)",
              captured and captured[0][1] == "live" and "f1" in captured[0][0],
              str(captured))
        captured2 = []
        os.environ["FACTY_SENSE"] = "cache"
        cli.sense_extract(ui, "llm · induction", "extract the things", "things",
                          "facts.schema.json", "produce things", [],
                          runner=stub_runner(RESPONSES, calls3),
                          cache_ns="test-case",
                          on_response=lambda text, source: captured2.append((text, source)))
        check("on_response reports the cache as the source",
              captured2 and captured2[0][1] == "cache", str(captured2))

        # cache_ready — the workbench's offline checkbox needs this:
        # false with an empty cache, true once every sensing step is cached
        case = ENGINE_DIR / "cases" / "adjudication-phantom-invoice"
        os.environ["FACTY_CACHE_DIR"] = str(Path(tmp) / "cache2")
        check("cache_ready is false with an empty cache",
              cli.cache_ready(case) is False)
        recorded = {
            "classify": json.dumps(engine.load_validated(
                case / "evidence-index.json", "evidence-index.schema.json")),
            "entities": json.dumps(engine.load_validated(
                case / "entities.json", "entities.schema.json")),
            "facts": json.dumps(engine.load_validated(
                case / "facts.json", "facts.schema.json")),
            "drop": json.dumps(engine.load_array(
                cli.drop_file(case), "fact.schema.json")),
        }
        os.environ["FACTY_SENSE"] = "live"  # populate: live writes the cache
        for op, response in recorded.items():
            calls = {"n": 0}
            cli.sense_one(ui, case, op, runner=stub_runner([response], calls))
        check("cache_ready is true once every sensing step is cached",
              cli.cache_ready(case) is True)
        # the cache key is content-hashed: stable across index/entities
        # differences, fresh when the evidence changes
        ops = cli.sensing_ops(case)
        before = cli._cache_file(case.name, *ops["facts"][:2], files=ops["facts"][2])
        check("the cache key is content-hashed and stable",
              before.exists() and before == cli._cache_file(
                  case.name, *ops["facts"][:2], files=ops["facts"][2]))

    print("")
    failed = len(RESULTS) - sum(RESULTS)
    print(f"{sum(RESULTS)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
