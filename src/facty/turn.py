"""Turn dispatcher (ADR-0010 §3) — configurable determinism per turn.

Every step of a case's signed pipeline config carries a `mode`; this module is
the deterministic router that reads the next step and executes it:

  deterministic  rules engine / compiled plan over TDB state — no LLM call
  ranked         the engine produces the ranked, constrained option set; the
                 human/LLM picks within it; the pick is recorded in the Turn doc
  free           LLM sensing only; outputs are committed with confidence+source

Invariant (ADR-0003, unchanged): verdict-path turns are ALWAYS `deterministic`.
STEP_MODES encodes the allowed op→mode map and rejects anything else, so a
mis-signed pipeline config cannot put an LLM call in the verdict path.

The dispatcher is pure code over committed state: same branch + same choice →
same Turn doc. Replay = the branch + FACTY_SENSE=cache (free steps replay from
the sensing disk cache — no LLM call on replay).

Every executed turn commits a `Turn` doc:
  {id, case, pipeline, step, op, mode, surface, actor,
   inputCommit, options?, choice?, outputCommit}
"""

from __future__ import annotations

import json
from pathlib import Path

from . import engine, ingest

# op → allowed modes. Verdict-path ops (run/prove/assemble) are deterministic
# only; `ranked` only fills slots (answer); `free` only senses/ingests.
STEP_MODES = {
    "run": {"deterministic"},
    "prove": {"deterministic"},
    "assemble": {"deterministic"},
    "load-facts": {"deterministic"},
    "ingest": {"deterministic", "free"},
    "sense": {"free"},
    "answer": {"ranked"},
}

VERDICT_OPS = {"run", "prove", "assemble"}


def _docs_of(client, cls: str) -> list[dict]:
    return [d for d in client.get_all_docs() if d.get("@type") == cls]


def pipelines(client) -> list[dict]:
    return sorted(_docs_of(client, "Pipeline"), key=lambda d: d["id"])


def _head(client) -> str:
    log = client.commit_log()
    return log[0]["identifier"] if log else ""


def _params(step: dict) -> dict:
    raw = step.get("params")
    if not raw:
        return {}
    return json.loads(raw) if isinstance(raw, str) else raw


def _check_mode(step: dict) -> None:
    allowed = STEP_MODES.get(step["op"])
    if allowed is None:
        raise ValueError(f"step {step['id']}: unknown op {step['op']!r}")
    if step.get("mode") not in allowed:
        raise ValueError(
            f"step {step['id']} ({step['op']}): mode {step.get('mode')!r} not allowed — "
            f"allowed: {sorted(allowed)}"
            + (" — verdict-path turns are always deterministic (ADR-0003)"
               if step["op"] in VERDICT_OPS else ""))


def next_step(client, pipeline: dict) -> dict | None:
    """The first step (by order, id) with no Turn doc yet for this pipeline."""
    done = {t["step"] for t in _docs_of(client, "Turn") if t.get("pipeline") == pipeline["id"]}
    for s in sorted(pipeline.get("steps", []), key=lambda s: (s.get("order", 99), s["id"])):
        if s["id"] not in done:
            return s
    return None


def _sense_case(client, case: str) -> dict:
    """One free-mode sensing turn — the single implementation lives in
    ops.sense (LLM, disk-cached; FACTY_SENSE=cache replays with no LLM call)."""
    from . import ops
    return ops.sense(client, case)


def execute_step(client, case: str, step: dict, choice=None, value=None,
                 actor: str = "human") -> dict:
    """Execute one step per its op+mode. Returns {options?, choice?, result?}.
    `ranked` without a choice returns the option set and executes nothing."""
    _check_mode(step)
    op, mode = step["op"], step.get("mode", "deterministic")
    p = _params(step)
    if op == "run":
        r = engine.run_phase(client, case, p.get("phase", "1"))
        return {"result": {k: v for k, v in r.items() if k != "ranking"},
                "ranking": r["ranking"]}
    if op == "prove":
        goal = {"subject": p["subject"], "predicate": p["predicate"]}
        if "valueBool" in p: goal["valueBool"] = p["valueBool"]
        elif "valueNum" in p: goal["valueNum"] = p["valueNum"]
        elif "valueString" in p: goal["valueString"] = p["valueString"]
        tree = engine.prove(client, goal)
        return {"result": {"provable": tree is not None, "goal": goal,
                           **({"proof": tree} if tree else {})}}
    if op == "assemble":
        return {"result": engine.assemble(client, case, p.get("goal"))}
    if op == "load-facts":
        n = engine.load_facts(client, Path(p["path"]), p.get("message", "load facts (turn)"))
        return {"result": {"loaded": n}}
    if op == "ingest":
        s = ingest.ingest_dir(client, Path(p["dir"]), p.get("source", "pipeline"),
                              ocr=p.get("ocr", False), embed=not p.get("noEmbed", False))
        return {"result": s}
    if op == "sense":
        r = _sense_case(client, case)
        return {"result": {"sensed": r["sensed"], "facts": [d["id"] for d in r["facts"]]}}
    if op == "answer":
        ranking = engine.rank_hypotheses(client, {})
        alive = {r["hypothesis"] for r in ranking if r["status"] == "open"}
        options = [q["id"] for q in engine.rank_questions(client, alive)]
        if choice is None:
            return {"awaiting": "choice", "options": options}  # nothing executed/committed
        if choice not in options:
            raise ValueError(f"choice {choice!r} not in ranked options {options}")
        v = value if value is not None else p.get("value")
        if v is None:
            return {"awaiting": "value", "options": options, "choice": choice}
        doc = engine.answer_question(client, choice, v, actor=actor)
        return {"options": options, "choice": choice, "result": doc}
    raise ValueError(f"step {step['id']}: unknown op {op!r}")


def run_turn(client, case: str, pipeline_id: str | None = None, choice=None,
             value=None, surface: str | None = None, actor: str = "human",
             run_all: bool = False) -> dict:
    """Run the next un-executed step (or all remaining, until done or a ranked
    step awaits a choice). Commits one Turn doc per executed step."""
    pls = [p for p in pipelines(client) if pipeline_id is None or p["id"] == pipeline_id]
    if pipeline_id is None:
        pls = pls[:1]  # default: the first pipeline (by id) on the case branch
    if not pls:
        raise ValueError(f"no pipeline config on this ref"
                         + (f" (wanted {pipeline_id})" if pipeline_id else ""))
    turns = []
    while True:
        step = next((s for p in pls for s in [next_step(client, p)] if s), None)
        if step is None:
            return {"done": True, "turns": turns}
        pipeline = next(p for p in pls if any(s["id"] == step["id"] for s in p.get("steps", [])))
        input_commit = _head(client)
        out = execute_step(client, case, step, choice=choice, value=value, actor=actor)
        if "awaiting" in out:
            return {"done": False, "awaiting": out["awaiting"], "step": step["id"],
                    "op": step["op"], "options": out.get("options", []),
                    **({"choice": out["choice"]} if out.get("choice") else {}),
                    "turns": turns}
        seq = len([t for t in _docs_of(client, "Turn") if t.get("case") == case]) + 1
        turn = {"@type": "Turn", "id": f"turn-{case}-{seq}", "case": case,
                "pipeline": pipeline["id"], "step": step["id"], "op": step["op"],
                "mode": step.get("mode", "deterministic"),
                "surface": surface or step.get("surface") or "chat",
                "actor": actor,
                "inputCommit": input_commit,
                "outputCommit": _head(client)}
        if out.get("options"):
            turn["options"] = out["options"]
        if out.get("choice"):
            turn["choice"] = out["choice"]
        client.insert_docs([turn], message=f"turn {step['id']} ({turn['mode']}/{turn['surface']}) by {actor}")
        turns.append({"turn": turn["id"], "step": step["id"], "op": step["op"],
                      "mode": turn["mode"], "surface": turn["surface"],
                      **({"choice": turn["choice"]} if turn.get("choice") else {})})
        if not run_all:
            return {"done": False, "turn": turn, "result": out.get("result"),
                    "awaiting": None, "turns": turns}
        choice, value = None, None  # a choice fills exactly one ranked step
