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

        # the candidate story: raised → pruned (with reasons) → ranked —
        # the commentary must be able to reconcile the counts, not just
        # echo the ranking (the manual-test report: "only 2 hypotheses,
        # but three were raised")
        pr = phase1["pruned"]
        esc = lambda s: json.dumps(s)[1:-1]  # the prompt is JSON — non-ASCII escapes
        check("the commentary prompt carries the pruned candidates + their reasons",
              len(seen) == 1 and pr
              and all(p["hypothesis"] in seen[0] and p["constraint"] in seen[0]
                      and esc(p["reason"]) in seen[0] for p in pr),
              str([p["hypothesis"] for p in pr]))
        hyps = engine.load_array(case / "pack" / "hypotheses.json",
                                 "hypothesis.schema.json")
        stmt = {h["id"]: h["statement"] for h in hyps}
        check("the commentary prompt carries the pruned hypotheses' statements",
              len(seen) == 1 and all(esc(stmt[p["hypothesis"]]) in seen[0]
                                     for p in pr))
        check("the commentary prompt carries the raised candidate set",
              len(seen) == 1 and '"raised"' in seen[0]
              and all(h in seen[0] for h in phase1["raised_hypotheses"]))
        check("the commentary asks for the eliminated candidates and their reasons",
              len(seen) == 1 and "the constraint layer's eliminations" in seen[0]
              and "the reason each" in seen[0])
        check("the commentary asks for the conclusion first (an ELI5 summary), "
              "then the step-by-step details",
              len(seen) == 1 and "conclusion first" in seen[0]
              and "executive summary" in seen[0]
              and "at most three sentences" in seen[0]
              and "step-by-step" in seen[0]
              and "in the order the run performed them" in seen[0])
        check("the commentary prompt carries the forward chain's fired rules "
              "(the steps performed)",
              len(seen) == 1 and '"fired_rules"' in seen[0]
              and all(f'"{e["rule"]}"' in seen[0]
                      for e in phase1["fired_rules"][:3]))

        # the induction half: the senses' steps + outputs (the whole run,
        # not just the engine's half)
        check("the commentary prompt carries the senses (induction) section",
              len(seen) == 1 and "THE SENSES" in seen[0]
              and "THE ENGINE" in seen[0])
        check("the senses section lists the classify step (the typed evidence)",
              len(seen) == 1 and "classify the evidence pile" in seen[0]
              and '"evidenceClass"' in seen[0])
        check("the senses section lists the sensed facts (so the fired rules' "
              "source fact-ids are decodable)",
              len(seen) == 1 and "sense the evidence" in seen[0]
              and '"facts"' in seen[0]
              and all(f'"{f["id"]}"' in seen[0]
                      for f in engine.load_array(
                          case / "facts.json", "fact.schema.json")[:5]))
        check("the senses section lists the entity extraction step",
              len(seen) == 1 and "extract the entities" in seen[0])
        check("the engine summary carries the phase (1 vs 2)",
              len(seen) == 1 and '"phase"' in seen[0]
              and phase1["phase"] in seen[0])
        check("a phase-1 result does not claim a second sensing wave",
              len(seen) == 1
              and "sense the recommended test's evidence" not in seen[0])

        # a phase-2 result: the test evidence was sensed in a second wave
        phase2 = engine.run_case(case, add_facts=cli.drop_file(case))
        seen_p2, calls_p2 = [], {"n": 0}
        cli.explain(ui, case, phase2, entities, "verdict",
                    runner=stub_runner(["phase-2 commentary"], calls_p2,
                                       seen=seen_p2))
        check("a phase-2 result's commentary carries the second sensing wave",
              len(seen_p2) == 1 and "sense the recommended test's evidence"
              in seen_p2[0] and phase2["phase"] in seen_p2[0],
              seen_p2[0][:200] if seen_p2 else "no prompt seen")

        # the reported scenario: the triage case prunes H3 — the prompt
        # must carry what H3 claimed and why it fell (constraint C1)
        triage = ENGINE_DIR / "cases" / "triage-alert-flood"
        r_triage = engine.run_case(triage)
        seen_t, calls_t = [], {"n": 0}
        cli.explain(ui, triage, r_triage, [], "verdict",
                    runner=stub_runner(["commentary"], calls_t, seen=seen_t))
        # expectations derived from the case's own artifacts (the triage
        # case is being reworked in a parallel session — don't hardcode)
        h3s = [p for p in r_triage["pruned"] if p["hypothesis"] == "H3"]
        stmt_t = {h["id"]: h["statement"] for h in engine.load_array(
            triage / "pack" / "hypotheses.json", "hypothesis.schema.json")}
        pile = sorted(cli.sensor_source_names(triage))
        check("the triage commentary prompt carries pruned H3 + its reason + statement",
              len(seen_t) == 1 and calls_t["n"] == 1 and h3s
              and esc(h3s[0]["reason"]) in seen_t[0] and "C1" in seen_t[0]
              and esc(stmt_t["H3"]) in seen_t[0],
              seen_t[0][:200] if seen_t else "no prompt seen")
        check("the triage commentary prompt carries the classifier step "
              "(the label sensor — no LLM tokens)",
              len(seen_t) == 1 and "label the evidence pile" in seen_t[0]
              and "no LLM tokens" in seen_t[0]
              and all(p in seen_t[0] for p in pile))
        check("the triage commentary prompt carries the classifier's "
              "sensed facts (the sensor's contribution)",
              len(seen_t) == 1 and '"facts_contributed"' in seen_t[0]
              and any(f'"{f["id"]}"' in seen_t[0]
                      for f in engine.load_array(
                          triage / "facts.json", "fact.schema.json")
                      if Path(str(f.get("source", "")).split(":")[0]).name in pile))

        # explainer coverage on another demo case: the RCA (causation) case
        # — phase 2 flips the verdict (H1 → H3) and prunes H1 (C5), so the
        # commentary must walk both phases' whole runs (senses + engine)
        rca = ENGINE_DIR / "cases" / "causation-three-am-outage"
        rca_ents = engine.load_validated(rca / "entities.json",
                                         "entities.schema.json")
        rca1 = engine.run_case(rca)
        rca2 = engine.run_case(rca, add_facts=cli.drop_file(rca))
        seen_r, calls_r = [], {"n": 0}
        cli.explain(ui, rca, rca1, rca_ents, "verdict",
                    runner=stub_runner(["rca phase 1"], calls_r, seen=seen_r))
        check("the RCA case (phase 1): the prompt walks the whole run — "
              "senses + engine, fired rules + pruned + raised",
              len(seen_r) == 1 and "THE SENSES" in seen_r[0]
              and "THE ENGINE" in seen_r[0]
              and all(f'"{e["rule"]}"' in seen_r[0]
                      for e in rca1["fired_rules"][:3])
              and all(p["hypothesis"] in seen_r[0] and esc(p["reason"]) in seen_r[0]
                      for p in rca1["pruned"])
              and all(h in seen_r[0] for h in rca1["raised_hypotheses"]))
        check("the RCA case (phase 1): the senses section carries this case's "
              "evidence + facts, and no second wave yet",
              len(seen_r) == 1 and "classify the evidence pile" in seen_r[0]
              and all(f'"{f["id"]}"' in seen_r[0]
                      for f in engine.load_array(
                          rca / "facts.json", "fact.schema.json")[:5])
              and "sense the recommended test's evidence" not in seen_r[0])
        seen_r2, calls_r2 = [], {"n": 0}
        cli.explain(ui, rca, rca2, rca_ents, "verdict",
                    runner=stub_runner(["rca phase 2"], calls_r2, seen=seen_r2))
        stmt_r = {h["id"]: h["statement"] for h in engine.load_array(
            rca / "pack" / "hypotheses.json", "hypothesis.schema.json")}
        check("the RCA case (phase 2): the second sensing wave + the flipped "
              "verdict + the new prunes are in the prompt",
              len(seen_r2) == 1
              and "sense the recommended test's evidence" in seen_r2[0]
              and rca2["phase"] in seen_r2[0]
              and all(p["hypothesis"] in seen_r2[0] and esc(p["reason"]) in seen_r2[0]
                      and esc(stmt_r[p["hypothesis"]]) in seen_r2[0]
                      for p in rca2["pruned"])
              and all(f'"{f["id"]}"' in seen_r2[0] for f in rca2["derived_facts"])
              and f'"{rca2["verdict"]["id"]}"' in seen_r2[0],
              seen_r2[0][:200] if seen_r2 else "no prompt seen")

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
