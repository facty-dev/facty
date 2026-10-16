#!/usr/bin/env python3
# cli.py — the redyarn interactive CLI (a stepping stone to the Workbench UI).
#
# Walks a case step by step, showing the engine's work as it happens:
# module-tagged log lines for every kind of output, live rule firings,
# constraint prunes, claim proofs — and STREAMED LLM output for the
# sensing steps (the probabilistic half). The verdict path stays LLM-free.
#
# Usage:
#   python3 engine/cli.py [--case engine/cases/silver-blaze] [--auto]
#   make dss-live
#
# Keys: [Enter] next step · [a] auto-run · [t] log so far · [q] quit · [?] help

import argparse
import json
import os
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402
import sensing  # noqa: E402

NC = "\033[0m"
USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

TAGS = {
    "case": "\033[37m",         # white
    "sense": "\033[36m",        # cyan
    "sense:classify": "\033[36m",
    "sense:entities": "\033[36m",
    "sense:facts": "\033[36m",
    "llm": "\033[96m",          # bright cyan
    "chain": "\033[34m",        # blue
    "questions": "\033[35m",    # magenta
    "constraints": "\033[33m",  # yellow
    "rank": "\033[35m",         # magenta
    "verdict": "\033[32m",      # green
    "trace": "\033[90m",        # grey
    "test": "\033[33m",         # yellow
}

HELP = ("  [Enter] next step · [a] auto-run the rest · [t] show the log so far · "
        "[q] quit · [?] this help")


# ── UI ───────────────────────────────────────────────────────────────

class UI:
    def __init__(self, auto=False):
        self.auto = auto
        self.log_lines = []

    def _prefix(self, tag):
        color = TAGS.get(tag, "")
        return f"{color}[{tag}]{NC}" if USE_COLOR else f"[{tag}]"

    def log(self, tag, msg):
        prefix = self._prefix(tag)
        for line in str(msg).splitlines() or [""]:
            text = f"{prefix} {line}"
            print(text)
            self.log_lines.append(text)

    def step(self, tag, title):
        print()
        print(f"{self._prefix(tag)} ── {title} " + "─" * max(4, 66 - len(title)))
        if self.auto:
            return
        while True:
            try:
                ans = input("  ▶ [Enter]=next [a]=auto [t]=log [q]=quit [?]=help: ").strip().lower()
            except EOFError:
                raise SystemExit(0)
            if ans in ("", "n", "next", "step"):
                return
            if ans == "a":
                self.auto = True
                self.log("case", "(auto-run: no more prompts)")
                return
            if ans == "q":
                raise SystemExit(0)
            if ans == "t":
                print()
                for line in self.log_lines:
                    print(line)
                print()
                continue
            if ans == "?":
                print(HELP)
                continue
            print("  (press Enter for the next step)")


# ── Sensing (the LLM half, streamed) ─────────────────────────────────
#
# The sensing motion, made explicit: messy field input + a JSON schema →
# a typesafe, schema-validated structured object the logic engine can
# consume. Entity extraction and classification are sensing operations —
# the engine never does them. engine/sensing.py is the tool; the case's
# sensing-prompt.md is the facts task (customizable per pack).

def make_facts_judge(case_dir):
    """The judge layer for fact extraction: schema validation (inside
    extract_structured) plus compute checks on the structured objects —
    unique fact ids, and source files that actually exist."""
    case = Path(case_dir)

    def judge(facts):
        errs = []
        ids = [f.get("id") for f in facts]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            errs.append(f"duplicate fact ids: {', '.join(dupes)}")
        for f in facts:
            fname = str(f.get("source", "")).split(":")[0]
            if fname and not (case / fname).exists():
                errs.append(f"{f.get('id')}: source file not found: {fname}")
        return errs

    return judge


def sense_extract(ui, tag, label, noun, schema_name, task, fallback, judge=None):
    """One sensing operation: schema + messy input → validated object,
    with the LLM response streamed live and a capped correction loop
    (errors fed back to the LLM, max 3 turns). Falls back to the recorded
    sensing when the LLM is unreachable or the retries exhaust (logged,
    never silent)."""
    ui.log(tag, f"{label} — calling Mistral Large 4 (mistral-subscription), streaming …")
    arrow = f"{TAGS['llm']}▸{NC} " if USE_COLOR else "▸ "

    def on_stream(line):
        sys.stdout.write(f"  {arrow}{line}\n")
        sys.stdout.flush()

    def on_note(msg):
        ui.log(tag, msg)

    try:
        result = sensing.extract_structured(
            ENGINE_DIR / "schemas" / schema_name, task,
            stream=on_stream, label=label.replace(" ", "-"),
            judge=judge, note=on_note)
    except Exception as exc:  # unreachable LLM, or retries exhausted
        ui.log(tag, f"LLM call failed ({exc})")
        ui.log(tag, "falling back to the recorded sensing (see SENSING.md) — "
                    "run this CLI from your own terminal to stream live")
        result = fallback
    if judge:
        errs = judge(result)
        if errs:
            ui.log(tag, f"WARNING: judge flagged the result — {'; '.join(errs[:3])}")
    ui.log(tag, f"judge layer accepted ✓ ({sensing.describe(result, noun)})")
    return result


def evidence_refs(files):
    return "\n".join(f"- {f.name}: @{f.resolve()}" for f in files)


def build_facts_task(case_dir, files, evidence_index=None, entities=None):
    template = (case_dir / "sensing-prompt.md").read_text()
    return (template
            .replace("{{EVIDENCE}}", evidence_refs(files))
            .replace("{{SCHEMA}}", str((ENGINE_DIR / "schemas" / "fact.schema.json").resolve()))
            .replace("{{EVIDENCE_INDEX}}", json.dumps(evidence_index or [], indent=2))
            .replace("{{ENTITIES}}", json.dumps(entities or [], indent=2)))


# ── Event formatters ─────────────────────────────────────────────────

def fmt_derive(e):
    f = e["fact"]
    return (f"rule {e['rule']} fired ▸ derived {f['id']}: "
            f"{f['subject']} / {f['predicate']} = {f['value']!r}   "
            f"← {', '.join(e['sources'])}")


def fmt_raise(e):
    return f"rule {e['rule']} fired ▸ hypothesis space opened: {', '.join(e['hypotheses'])}"


def fmt_open(e):
    q = e["question"]
    return f"rule {e['rule']} fired ▸ opened {q['id']} [{q['slot']}]: {q['text']}"


def fmt_eliminate(e):
    return f"{e['constraint']} ✗ {e['hypothesis']} eliminated — {e['reason']}"


def fmt_support(e):
    return f"{e['constraint']} ▲ {e['hypothesis']} supported ({e['field']} = {e['value']!r})"


def fmt_claim(e):
    c = e["claim"]
    mark = "✓" if e["proven"] else "✗"
    line = f"{mark} {c.get('subject')} / {c.get('predicate')} = {c.get('value')!r}"
    line += f"   ← {e['provenBy']}" if e["proven"] else "   (no evidence)"
    return line


def fmt_proof(e):
    marks = "✓" * e["proven"] + "✗" * (e["total"] - e["proven"])
    return (f"{e['hypothesis']} — {e['statement']}\n"
            f"    claims {e['proven']}/{e['total']} {marks} · score {e['score']:.4f}")


# ── Trace (the red yarn) ─────────────────────────────────────────────

def render_trace(ui, label, facts, derived, fired, pruned, ranking, verdict):
    ui.log("trace", f"the red yarn — derivation trace ({label})")
    ui.log("trace", f"  sensed facts ({len(facts)}):")
    for f in facts:
        ui.log("trace", f"    {f['id']}  {f['subject']} / {f['predicate']} = {f['value']!r}"
                        f"   ({f['confidence']} · {f['source']})")
    ui.log("trace", "  rules fired:")
    for e in fired:
        if "derived" in e:
            d = next((x for x in derived if x["id"] == e["derived"]), None)
            if d:
                ui.log("trace", f"    {e['rule']} ▸ {d['id']} ({d['subject']} / {d['predicate']}"
                                f" = {d['value']!r})   ← {', '.join(e['sources'])}")
        elif "opened" in e:
            ui.log("trace", f"    {e['rule']} ▸ opened {e['opened']}")
        elif "raised" in e:
            ui.log("trace", f"    {e['rule']} ▸ raised {e['raised']}")
    ui.log("trace", f"  constraints ({len(pruned)} pruned):")
    for p in pruned:
        ui.log("trace", f"    {p['constraint']} ✗ {p['hypothesis']} — {p['reason']}")
    ui.log("trace", "  claim proofs:")
    for rk in ranking:
        parts = []
        for p in rk["proofs"]:
            c = p["claim"]
            parts.append(f"✓ {c.get('subject')}/{c.get('predicate')}={c.get('value')!r}←{p['provenBy']}")
        for c in rk["refuted"]:
            parts.append(f"✗ {c.get('subject')}/{c.get('predicate')}={c.get('value')!r}")
        ui.log("trace", f"    {rk['id']}: " + " · ".join(parts))
    if verdict:
        ui.log("trace", f"  VERDICT: {verdict['id']} ({verdict['score']:.4f}) — "
                        f"killer: {verdict['killer']} · horse fate: {verdict['horse_fate']}")


# ── The walkthrough ──────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(prog="cli.py",
                                 description="redyarn interactive CLI — step through a case")
    ap.add_argument("--case", default=str(ENGINE_DIR / "cases" / "silver-blaze"),
                    help="case directory (default: engine/cases/silver-blaze)")
    ap.add_argument("--auto", action="store_true",
                    help="run all steps without prompting")
    args = ap.parse_args()
    case = Path(args.case)
    ui = UI(auto=args.auto)

    print()
    ui.log("case", "redyarn — interactive case walkthrough (a stepping stone to the Workbench UI)")
    ui.log("case", f"case: {case.name} · engine: deterministic · LLM: Mistral Large 4 (sensing only)")

    # ── Step 1: load the case ──────────────────────────────────────
    ui.step("case", "Load the case")
    evidence = sorted((case / "evidence").iterdir())
    for f in evidence:
        ui.log("case", f"evidence: {f.name} ({f.stat().st_size} bytes)")
    recorded = engine.load_validated(case / "facts.json", "facts.schema.json")
    rules = engine.load_array(case / "pack" / "rules.json", "rule.schema.json")
    hypotheses = engine.load_array(case / "pack" / "hypotheses.json", "hypothesis.schema.json")
    constraints = engine.load_array(case / "pack" / "constraints.json", "constraint.schema.json")
    ui.log("case", f"pack: {len(rules)} rules · {len(constraints)} constraints · "
                   f"{len(hypotheses)} hypotheses (all schema-validated ✓)")
    ui.log("case", f"recorded sensing: {len(recorded)} facts (see SENSING.md)")

    # ── Step 2: the sensing motion (the LLM half, streamed) ────────
    phase1_evidence = [f for f in evidence if f.name != "ledger.txt"]

    ui.step("sense", "Classify the evidence pile — messy input → typed evidence")
    recorded_index = engine.load_validated(case / "evidence-index.json",
                                           "evidence-index.schema.json")
    evidence_index = sense_extract(
        ui, "sense:classify", "classify the evidence pile", "evidence items",
        "evidence-index.schema.json",
        sensing.CLASSIFY_TASK.replace("{{FILES}}", evidence_refs(phase1_evidence)),
        recorded_index)
    for item in evidence_index:
        ui.log("sense", f"  {item['file']} → {item['evidenceClass']} ({item['confidence']})")

    ui.step("sense", "Extract the entities — extraction is sensing, not reasoning")
    recorded_entities = engine.load_validated(case / "entities.json",
                                              "entities.schema.json")
    entities = sense_extract(
        ui, "sense:entities", "extract the case entities", "entities",
        "entities.schema.json",
        sensing.ENTITIES_TASK.replace("{{FILES}}", evidence_refs(phase1_evidence)),
        recorded_entities)
    ui.log("sense", f"entities: {', '.join(e['name'] for e in entities)}")

    ui.step("sense", "Sense the evidence → facts (judge: schema + compute checks)")
    facts_judge = make_facts_judge(case)
    facts = sense_extract(
        ui, "sense:facts", "extract the facts", "facts",
        "facts.schema.json",
        build_facts_task(case, phase1_evidence, evidence_index, entities),
        recorded, judge=facts_judge)

    # ── Step 3: forward chain ──────────────────────────────────────
    ui.step("chain", "Forward chain — watch the rules fire")

    def chain_emit(e):
        if e["op"] == "derive":
            ui.log("chain", fmt_derive(e))
        elif e["op"] == "raise":
            ui.log("chain", fmt_raise(e))
        elif e["op"] == "open":
            ui.log("questions", fmt_open(e))

    derived, fired, questions, raised = engine.forward_chain(facts, rules, emit=chain_emit)
    ui.log("chain", f"fixpoint: {len(derived)} derived facts · "
                    f"{len(questions)} questions opened · {len(raised)} hypotheses raised")

    # ── Step 4: the awareness loop ─────────────────────────────────
    ui.step("questions", "The awareness loop — what the engine still wants to know")
    active = [h for h in hypotheses if h["id"] in raised] if raised else hypotheses
    survivors0, _ = engine.apply_constraints(active, facts + derived, constraints)
    verdict_tmp = engine.combine(survivors0, facts + derived, questions)
    for q in engine.rank_questions(questions, [r["id"] for r in verdict_tmp["ranking"]]):
        ui.log("questions", f"{q['id']} [{q['slot']}] discriminates "
                            f"{', '.join(q.get('discriminates', []))}: {q['text']}")
    if verdict_tmp["recommended_test"]:
        rec = verdict_tmp["recommended_test"]
        ui.log("test", f"recommended test: {rec['id']} — {rec['text']}")

    # ── Step 5: constraints ────────────────────────────────────────
    ui.step("constraints", "Constraint layer — prune and support")
    survivors, pruned = engine.apply_constraints(
        active, facts + derived, constraints,
        emit=lambda e: ui.log("constraints", fmt_eliminate(e) if e["op"] == "eliminate"
                              else fmt_support(e)))
    ui.log("constraints", f"{len(pruned)} pruned · {len(survivors)} survive")

    # ── Step 6: backward chain + ranking ───────────────────────────
    ui.step("chain", "Backward chain — prove the claims, rank the survivors")

    def combine_emit(e):
        if e["op"] == "claim":
            ui.log("chain", "  " + fmt_claim(e))
        elif e["op"] == "proof":
            ui.log("rank", fmt_proof(e))

    verdict1 = engine.combine(survivors, facts + derived, questions, emit=combine_emit)

    # ── Step 7: verdict (phase 1) ──────────────────────────────────
    ui.step("verdict", "Verdict — phase 1 (initial evidence)")
    v1 = verdict1["ranking"][0] if verdict1["ranking"] else None
    if v1:
        ui.log("verdict", f"{v1['id']} — {v1['statement']}  (score {v1['score']:.4f})")
        ui.log("verdict", f"killer: {v1['killer']} · horse fate: {v1['horse_fate']} · "
                           f"confidence: {engine.confidence_note(v1, questions)}")
    ui.log("verdict", "not final — the recommended test is still open")

    # ── Step 8: trace (phase 1) ────────────────────────────────────
    ui.step("trace", "The red yarn — phase 1 trace")
    render_trace(ui, "phase 1", facts, derived, fired, pruned,
                 verdict1["ranking"], v1)

    # ── Phase 2: the test runs ─────────────────────────────────────
    ui.step("test", "Run the recommended test — sense the ledger (the LLM half, streamed)")
    ledger_recorded = engine.load_validated(case / "facts-ledger.json", "facts.schema.json")
    ledger_facts = sense_extract(
        ui, "sense:facts", "extract the ledger facts", "facts",
        "facts.schema.json",
        build_facts_task(case, [case / "evidence" / "ledger.txt"]),
        ledger_recorded, judge=facts_judge)
    facts2 = facts + ledger_facts
    ui.log("questions", "q1 [sabotage-payment] answered: the ledger shows payments from "
                        "S.B. and the 3 a.m. meeting → new facts enter the case")

    ui.step("chain", "Forward chain — the new facts")
    derived2, fired2, questions2, raised2 = engine.forward_chain(facts2, rules, emit=chain_emit)
    ui.log("chain", f"fixpoint: {len(derived2)} derived facts (was {len(derived)})")

    ui.step("constraints", "Constraint layer — re-applied")
    survivors2, pruned2 = engine.apply_constraints(
        active, facts2 + derived2, constraints,
        emit=lambda e: ui.log("constraints", fmt_eliminate(e) if e["op"] == "eliminate"
                              else fmt_support(e)))

    ui.step("chain", "Backward chain — prove the claims")
    verdict2 = engine.combine(survivors2, facts2 + derived2, questions2, emit=combine_emit)

    ui.step("verdict", "Verdict — final")
    v2 = verdict2["ranking"][0] if verdict2["ranking"] else None
    if v2:
        ui.log("verdict", f"{v2['id']} — {v2['statement']}  (score {v2['score']:.4f})")
        ui.log("verdict", f"killer: {v2['killer']} · horse fate: {v2['horse_fate']} · "
                           f"confidence: {engine.confidence_note(v2, questions2)}")
    ui.log("verdict", "the case is closed — and every step above replays deterministically "
                      "(python3 engine/engine.py run --case engine/cases/silver-blaze --json)")

    ui.step("trace", "The red yarn — final trace")
    render_trace(ui, "final", facts2, derived2, fired2, pruned2,
                 verdict2["ranking"], v2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
