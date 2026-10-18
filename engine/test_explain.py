#!/usr/bin/env python3
# test_explain.py — the engine context in the drop sensing + the
# out-of-band LLM commentary (no LLM needed: the runner is stubbed, like
# test_cache.py / test_retry.py).
#
# Two things are asserted here:
#
# 1. The drop sensing gets the engine's phase-1 context — its OPEN
#    QUESTIONS and the hypothesis space (statements only). Never the
#    engine's conclusions (scores, rankings, derived facts, pruning
#    verdicts): feeding those back into the senses would bias the
#    reading toward the current verdict (confirmation / echo).
#
# 2. The out-of-band commentary (explain) — the LLM as explainer, fed the
#    engine's conclusions, never in the verdict path. Cached like the
#    sensing responses; cache mode replays it without an LLM call.
#
# Usage: python3 engine/test_explain.py   (or: ./facty test)

import json
import os
import sys
import tempfile
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import cli     # noqa: E402

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


def stub_runner(responses, calls, seen=None):
    """A runner stub: returns the canned responses in order; records the
    staged prompts it was called with (to assert on the task text)."""
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


def main():
    case = ENGINE_DIR / "cases" / "adjudication-phantom-invoice"
    phase1 = engine.run_case(case)  # the recorded phase-1 solve
    ui = StubUI()

    # ── the engine context block (the bias guard) ──────────────────
    block = cli.engine_context_block(phase1)
    check("the context block carries the engine's open questions",
          "Open questions:" in block
          and all(q["id"] in block for q in phase1["opened_questions"]
                  if q.get("status") == "open"),
          block[:200])
    check("the context block carries the hypothesis statements",
          "Hypotheses still in play (statements only):" in block
          and all(rk["statement"] in block for rk in phase1["ranking"]))
    check("the context block never leaks the engine's conclusions",
          not any(f"{rk['score']:.4f}" in block for rk in phase1["ranking"])
          and "derived" not in block.lower().replace("already holds", "")
          and "pruned" not in block.lower(),
          block[:300])
    check("the context block states the guard (where to look, never what to find)",
          "never what to find" in block and "do not tailor facts" in block)
    check("the hypothesis statements come in a neutral (id) order, not score order",
          block.index("h1-") < block.index("h2-") if "h1-" in block and "h2-" in block
          else True)

    # ── the drop sensing task gets the context ─────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["FACTY_CACHE_DIR"] = str(Path(tmp) / "cache")
        os.environ["FACTY_SENSE"] = "live"
        recorded_drop = json.dumps(engine.load_array(
            cli.drop_file(case), "fact.schema.json"))
        seen, calls = [], {"n": 0}
        cli.sense_one(ui, case, "drop", stream=lambda line: None,
                      runner=stub_runner([recorded_drop], calls, seen=seen))
        check("the drop sensing ran (the stubbed LLM answered)", calls["n"] == 1)
        check("the drop's staged prompt carries the engine's open questions",
              len(seen) == 1 and "Open questions:" in seen[0]
              and "Hypotheses still in play" in seen[0],
              seen[0][:200] if seen else "no prompt seen")
        check("the drop's staged prompt carries the earlier index + entities",
              len(seen) == 1 and '"file"' in seen[0] and '"kind"' in seen[0])
        check("the drop's staged prompt states the bias guard",
              len(seen) == 1 and "never what to find" in seen[0])

        # the pack's term vocabulary (the ontology a fresh extraction must
        # speak — otherwise no rule can fire on the live path)
        preds, subs = cli.pack_vocabulary(case)
        check("the drop's staged prompt carries the pack's term vocabulary",
              len(seen) == 1 and "term vocabulary" in seen[0]
              and all(p in seen[0] for p in preds[:5])
              and all(s in seen[0] for s in subs[:5]),
              f"{len(preds)} predicates, {len(subs)} subjects") if seen else None

        # the drop's cache key carries the context: a changed question
        # set means a fresh key (never a stale response under new
        # questions)
        ops = cli.sensing_ops(case)
        label, schema, files = ops["drop"]
        key = cli._cache_file(case.name, label, schema, files=files,
                              context=cli.context_key(phase1))
        check("the drop's cache entry is keyed with the engine context",
              key.exists())
        other = dict(phase1)
        other["opened_questions"] = [dict(q, text="a different question")
                                     for q in phase1["opened_questions"]]
        check("a changed question set means a fresh cache key",
              cli._cache_file(case.name, label, schema, files=files,
                              context=cli.context_key(other)) != key)

        # cache_state answers for the offline replay: with every step
        # cached (the facts step included), the drop is counted ready
        for op, resp in (("classify", json.dumps(engine.load_validated(
                case / "evidence-index.json", "evidence-index.schema.json"))),
                ("entities", json.dumps(engine.load_validated(
                    case / "entities.json", "entities.schema.json"))),
                ("facts", json.dumps(engine.load_validated(
                    case / "facts.json", "facts.schema.json")))):
            cli.sense_one(ui, case, op, stream=lambda line: None,
                          runner=stub_runner([resp], {"n": 0}))
        ready, total = cli.cache_state(case)
        check("cache_state counts the context-keyed drop as ready",
              ready == total, f"{ready}/{total}")

    # ── the out-of-band commentary (explain) ───────────────────────
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["FACTY_CACHE_DIR"] = str(Path(tmp) / "cache2")
        entities = engine.load_validated(case / "entities.json",
                                         "entities.schema.json")
        os.environ["FACTY_SENSE"] = "live"
        seen, calls = [], {"n": 0}
        text = cli.explain(ui, case, phase1, entities, "verdict",
                           runner=stub_runner(["The clerk was exonerated."], calls,
                                              seen=seen))
        check("explain returns the commentary (live)",
              text == "The clerk was exonerated." and calls["n"] == 1)
        check("the commentary prompt embeds the engine's result + entities",
              len(seen) == 1 and '"ranking"' in seen[0]
              and '"derived_facts"' in seen[0] and '"kind"' in seen[0])
        check("the commentary prompt is labelled presentation-only",
              len(seen) == 1 and "the engine's verdict stands on its own" in seen[0])
        check("explain caches the commentary",
              any(p.name.startswith("explain the verdict-")
                  for p in (Path(os.environ["FACTY_CACHE_DIR"]) / case.name).iterdir()))

        os.environ["FACTY_SENSE"] = "cache"
        calls2 = {"n": 0}
        text2 = cli.explain(ui, case, phase1, entities, "verdict",
                            runner=stub_runner(["SHOULD NOT BE CALLED"], calls2))
        check("explain replays the cache without an LLM call (offline mode)",
              text2 == "The clerk was exonerated." and calls2["n"] == 0)

        # a changed result means a fresh key: no stale commentary
        os.environ["FACTY_SENSE"] = "live"
        other = dict(phase1)
        other["ranking"] = [dict(rk, score=0.1234) for rk in phase1["ranking"]]
        calls3 = {"n": 0}
        text3 = cli.explain(ui, case, other, entities, "verdict",
                            runner=stub_runner(["fresh commentary"], calls3))
        check("a changed result means a fresh commentary (no stale replay)",
              text3 == "fresh commentary" and calls3["n"] == 1)

        # no cache entry + cache mode → None (logged, never silent)
        with tempfile.TemporaryDirectory() as tmp2:
            os.environ["FACTY_CACHE_DIR"] = str(Path(tmp2) / "cache3")
            os.environ["FACTY_SENSE"] = "cache"
            text4 = cli.explain(ui, case, phase1, entities, "entities",
                                runner=stub_runner(["x"], {"n": 0}))
            check("no cached commentary + offline → None (logged)",
                  text4 is None
                  and any("no cached commentary" in l for l in ui.lines))

    print("")
    n = len(RESULTS)
    print(f"{sum(RESULTS)}/{n} checks passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
