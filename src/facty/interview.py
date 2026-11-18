"""The interview loop as a pydantic-graph — the questionnaire state machine.

Correspondence (framework rule, 2026-11-17): asking the user questions IS a
state machine — engine gap analysis → ask → slot-fill answer → engine run →
done — and pydantic-graph executes it as a typed graph. Allowed by the rule:
no ReAct loop, no LLM-as-judge; the LLM may appear only in the designated
`AskQuestion` chooser node, and its output is gated through ops and committed
as a Turn doc. The verdict path is untouched: engine nodes are `deterministic`.

Invariant: every mutating node commits via turn.execute_one_turn → the case
branch remains the system of record (pydantic-graph's in-process run history
is a cache/visualization only; Mermaid rendering for docs/UI via Graph.render()).
Replay = branch + FACTY_SENSE=cache, same as the linear dispatcher.

Optional layer: imports pydantic_graph (bundled with pydantic-ai) lazily —
the engine core stays stdlib-only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from . import cases as cases_mod
from . import engine, turn

try:
    from pydantic_graph import BaseNode, End, GraphBuilder, GraphRunContext
    from pydantic import BaseModel
    _HAS_GRAPH = True
except ImportError:  # engine core must run without the optional layer
    _HAS_GRAPH = False
    BaseNode = object  # type: ignore


@dataclass
class InterviewState:
    case: str
    surface: str = "wizard"
    actor: str = "human"
    answers: dict = field(default_factory=dict)   # question id → value ("*" = any)
    use_llm_chooser: bool = False
    question: str | None = None
    question_text: str = ""
    phase: int = 1
    turns: list = field(default_factory=list)
    max_turns: int = 20
    log: list = field(default_factory=list)


@dataclass
class InterviewDeps:
    client: Any
    pipeline: dict


def _client_for(deps: InterviewDeps, case: str):
    deps.client.ref = cases_mod._slug(case)
    return deps.client


def _step(sid: str, op: str, mode: str, params: dict | None = None) -> dict:
    return {"@type": "Step", "id": sid, "op": op, "mode": mode,
            "order": 0, "params": json.dumps(params or {})}


class _Base(BaseNode):
    pass


class RunPhase(_Base):
    """Deterministic engine turn (verdict path — never an LLM node)."""

    async def run(self, ctx: GraphRunContext) -> "GapAnalysis":
        st, deps = ctx.state, ctx.deps
        step = _step(f"interview-run-{st.phase}", "run", "deterministic", {"phase": str(st.phase)})
        out = turn.execute_one_turn(_client_for(deps, st.case), st.case, deps.pipeline, step,
                                    surface=st.surface, actor=st.actor)
        st.turns.append(out["turn"]); st.log.append(f"run phase {st.phase}")
        st.phase += 1
        return GapAnalysis()


class GapAnalysis(_Base):
    """Engine gap analysis: rank the open questions over alive hypotheses."""

    async def run(self, ctx: GraphRunContext) -> "AskQuestion | Assemble":
        st, deps = ctx.state, ctx.deps
        c = _client_for(deps, st.case)
        ranking = engine.rank_hypotheses(c, {})
        alive = {r["hypothesis"] for r in ranking if r["status"] == "open"}
        qs = engine.rank_questions(c, alive)
        if not qs or len(st.turns) >= st.max_turns:
            st.log.append("no open questions — assemble")
            return Assemble()
        q = qs[0]
        st.question, st.question_text = q["id"], q["text"]
        st.log.append(f"ask {q['id']}")
        return AskQuestion()


class SlotPick(BaseModel):
    value: str | bool | int | float
    why: str = ""


class AskQuestion(_Base):
    """Present the question; pick the answer from the scripted answers, or the
    LLM chooser (designated node — output still gated + committed below)."""

    async def run(self, ctx: GraphRunContext) -> "CommitAnswer | End[dict]":
        st, deps = ctx.state, ctx.deps
        qid = st.question
        value = st.answers.get(qid, st.answers.get("*"))
        if value is None and st.use_llm_chooser:
            from . import sensing
            prompt = (f"Answer this case question for the operator. Question: {st.question_text!r} "
                      f"(slot {qid}). Reply with a JSON object {{\"value\": <string|bool|number>, "
                      f"\"why\": <one line>}} — the value must be of the slot's type. "
                      f"Pick the most defensible value given the case context.")
            o = sensing.sense_json(prompt, SlotPick)
            value = o.value if hasattr(o, "value") else o["value"]
            st.log.append(f"llm chose {value!r} for {qid}")
        if value is None:
            # human must answer via the UI (same OpenQuestion doc) — stop the graph
            return End({"awaiting": qid, "question": st.question_text, "turns": st.turns})
        return CommitAnswer(value=value)


@dataclass
class CommitAnswer(_Base):
    """Slot filling (ranked turn): the pick is recorded in the Turn doc."""

    value: object = None

    async def run(self, ctx: GraphRunContext) -> "RunPhase":
        st, deps = ctx.state, ctx.deps
        step = _step(f"interview-answer-{st.question}", "answer", "ranked", {})
        out = turn.execute_one_turn(_client_for(deps, st.case), st.case, deps.pipeline, step,
                                    choice=st.question, value=self.value,
                                    surface=st.surface, actor=st.actor)
        st.turns.append(out["turn"]); st.log.append(f"answered {st.question}={self.value!r}")
        return RunPhase()


class Assemble(_Base):
    """Deterministic assembly (verdict path)."""

    async def run(self, ctx: GraphRunContext) -> "End[dict]":
        st, deps = ctx.state, ctx.deps
        step = _step("interview-assemble", "assemble", "deterministic", {})
        out = turn.execute_one_turn(_client_for(deps, st.case), st.case, deps.pipeline, step,
                                    surface=st.surface, actor=st.actor)
        st.turns.append(out["turn"])
        return End({"done": True, "turns": [t["id"] for t in st.turns],
                    "modes": [t["mode"] for t in st.turns], "log": st.log})


def build_graph():
    if not _HAS_GRAPH:
        raise RuntimeError("interview loop needs the optional pydantic-ai layer "
                           "(pydantic_graph) — baked into the SmolVM image at build time")
    b = GraphBuilder(state_type=InterviewState, deps_type=InterviewDeps, output_type=dict)
    b.add(b.node(RunPhase), b.node(GapAnalysis), b.node(AskQuestion),
          b.node(CommitAnswer), b.node(Assemble),
          b.edge_from(b.start_node).to(RunPhase))
    return b.build()


def run_interview(client, case: str, answers: dict | None = None, chooser: str = "script",
                  surface: str = "wizard", actor: str = "human", max_turns: int = 20,
                  pipeline_id: str | None = None) -> dict:
    """Run the questionnaire loop for a case to completion (or until a question
    awaits a human). Every turn is committed to the case branch."""
    client.ref = cases_mod._slug(case)
    pls = turn.pipelines(client)
    pipeline = next((p for p in pls if p["id"] == pipeline_id), pls[0] if pls else {"id": "interview"})
    state = InterviewState(case=case, surface=surface, actor=actor,
                           answers=answers or {}, use_llm_chooser=(chooser == "llm"),
                           max_turns=max_turns)
    graph = build_graph()
    out = graph.run_sync(state=state, deps=InterviewDeps(client=client, pipeline=pipeline),
                         inputs=RunPhase())
    return out if isinstance(out, dict) else {"done": True, "output": out,
                                               "turns": [t["id"] for t in state.turns],
                                               "log": state.log}
