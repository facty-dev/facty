#!/usr/bin/env python3
# cli.py — the Facty CLI: the primary first-class interface to the detective DSS.
#
# Bare `./facty` opens the Textual workbench (the primary interface — a
# case picker and an interactive case board). The subcommands are the
# scriptable control plane: run cases, list them, sense evidence (the LLM
# half, streamed), walk a case step by step in a terminal, run the
# acceptance tests, emit the codegen projections.
#
# The engine core (engine/engine.py) and this control plane are
# dependency-free — they run anywhere, including the gondolin VM snapshot
# (no pip guarantees there) and CI (no TTY). Textual (the workbench) is
# the repo's one optional dependency, imported lazily with a graceful
# fallback. See docs/adr/0004-cli-primary-interface.md.
#
# Usage:
#   ./facty <command> [options]        (or: python3 engine/cli.py <command> ...)
#
# Keys (walkthrough): [Enter] next step · [a] auto-run · [t] log so far · [q] quit · [?] help

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine          # noqa: E402
import emit as emit_mod  # noqa: E402
import sensing         # noqa: E402
import label           # noqa: E402  (the label sensor — small classifier)
import procs           # noqa: E402  (subprocess registry — no dangling processes)

CASES_DIR = ENGINE_DIR / "cases"


def _cache_dir():
    """Where raw LLM responses are cached (machine-local, gitignored).
    FACTY_CACHE_DIR overrides — tests point it at a tempdir."""
    return Path(os.environ.get("FACTY_CACHE_DIR")
                or ENGINE_DIR.parent / ".agentic" / "cache" / "sensing")

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
    # the run-log vocabulary: tool · inference type
    "llm · induction": "\033[96m",               # bright cyan
    "classifier · induction": "\033[36m",        # cyan
    "fwd chain · deduction": "\033[34m",         # blue
    "constraint solver · deduction": "\033[33m", # yellow
    "bwd chain · deduction": "\033[35m",         # magenta
}

HELP = ("  [Enter] next step · [a] auto-run the rest · [t] show the log so far · "
        "[q] quit · [?] this help")

DEBUG = False  # set from --debug / FACTY_DEBUG=1 in the command handlers

EXAMPLES = """\
examples:
  ./facty                            the workbench (Textual TUI — the primary interface)
  ./facty tui phantom-invoice        the workbench, straight into a case
  ./facty cases                      the demo cases (type · pack · phase-2 drop)
  ./facty run phantom-invoice        phase 1 (unique slug match)
  ./facty run three-am-outage --add-facts engine/cases/causation-three-am-outage/facts-postmortem.json
  ./facty run silver-blaze --json    machine-readable verdict + trace
  ./facty selftest                   acceptance test — every case, asserted
  ./facty test                       all tests (selftest + retry loop + the TUI, headless)
  ./facty walkthrough silver-blaze --auto   terminal step-through (VMs, no-TTY)
  ./facty explain silver-blaze         LLM commentary on the verdict (out-of-band)
  ./facty sense alert-flood --op label     the label sensor (small classifier, CPU-only)
  ./facty sense alert-flood --op parser    generate the case's extract parser (LLM, judged)
  ./facty completion bash >> ~/.bash_completion
"""


# ── Color kit (auto-off when not a TTY / NO_COLOR) ───────────────────

def _c(code, s):
    return f"\033[{code}m{s}{NC}" if USE_COLOR else s


def bold(s):
    return _c("1", s)


def dim(s):
    return _c("2", s)


def red(s):
    return _c("31", s)


def green(s):
    return _c("32", s)


def yellow(s):
    return _c("33", s)


def blue(s):
    return _c("34", s)


def magenta(s):
    return _c("35", s)


def cyan(s):
    return _c("36", s)


# ── Case helpers ─────────────────────────────────────────────────────

def list_cases():
    return sorted(c for c in CASES_DIR.iterdir() if (c / "pack" / "rules.json").exists())


def case_type(case):
    """The investigation family — the case dir's type prefix.
    See docs/INVESTIGATION-TYPES.md."""
    return Path(case).name.split("-", 1)[0]


def drop_file(case):
    """The phase-2 facts drop (facts-<drop>.json), if the case has one."""
    drops = sorted(Path(case).glob("facts-*.json"))
    return drops[0] if drops else None


def drop_source_names(case):
    """The evidence files the phase-2 drop was sensed from — derived from
    the drop facts' source spans (no per-case config needed)."""
    drop = drop_file(case)
    if not drop:
        return set()
    facts = engine.load_array(drop, "fact.schema.json")
    return {Path(str(f.get("source", "")).split(":")[0]).name for f in facts}


def sensor_source_names(case):
    """The evidence files the label sensor senses (from classify.json).
    Sensor-sourced evidence is sensed by the sensor; the LLM reads the rest."""
    cfg_path = Path(case) / "classify.json"
    if not cfg_path.exists():
        return set()
    try:
        return {Path(json.loads(cfg_path.read_text())["file"]).name}
    except (ValueError, KeyError):
        return set()


def phase1_evidence(case):
    """Phase-1 evidence: every file except the phase-2 drop's sources and
    the label sensor's source (sensor-sourced evidence is sensed by the
    sensor — the LLM never sees the pile)."""
    ev = sorted((Path(case) / "evidence").iterdir())
    drop_srcs = drop_source_names(case)
    sensor_srcs = sensor_source_names(case)
    return [f for f in ev if f.name not in drop_srcs
            and f.name not in sensor_srcs]


def resolve_case(arg):
    """A case dir path, an exact case name, or a unique slug (e.g. 'phantom-invoice')."""
    p = Path(arg)
    if p.is_dir() and (p / "pack" / "rules.json").exists():
        return p
    if (CASES_DIR / arg).is_dir():
        return CASES_DIR / arg
    matches = [c for c in list_cases()
               if arg == c.name or c.name.endswith("-" + arg) or arg in c.name]
    if len(matches) == 1:
        return matches[0]
    avail = ", ".join(c.name for c in list_cases())
    raise SystemExit(f"facty: unknown case {arg!r} (available: {avail})")


# ── UI (the terminal walkthrough) ─────────────────────────────────────

class UI:
    def __init__(self, auto=False, quiet=False):
        self.auto = auto
        self.quiet = quiet
        self.log_lines = []

    def _prefix(self, tag):
        color = TAGS.get(tag, "")
        return f"{color}[{tag}]{NC}" if USE_COLOR else f"[{tag}]"

    def log(self, tag, msg):
        prefix = self._prefix(tag)
        for line in str(msg).splitlines() or [""]:
            text = f"{prefix} {line}"
            if not self.quiet:
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

def _source_exists(case, fname):
    """A fact's source file, resolved tolerantly: as given (relative to
    the case), or by its bare name inside the case's evidence dir (the
    recorded convention cites evidence/<file>; a bare name still names
    a real file)."""
    p = Path(fname)
    return (case / p).exists() or (case / "evidence" / p.name).exists()


def make_facts_judge(case_dir):
    """The judge layer for fact extraction: schema validation (inside
    extract_structured) plus compute checks on the structured objects —
    unique fact ids, source files that actually exist, and a value
    normalization: the models often emit booleans as the STRINGS
    "true"/"false", while the pack's rules bind real booleans — coerce
    them (in place) so a paraphrased type cannot silence a rule."""
    case = Path(case_dir)

    def judge(facts):
        errs = []
        ids = [f.get("id") for f in facts]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            errs.append(f"duplicate fact ids: {', '.join(dupes)}")
        for f in facts:
            v = f.get("value")
            if isinstance(v, str) and v.strip().lower() in ("true", "false"):
                f["value"] = v.strip().lower() == "true"
            fname = str(f.get("source", "")).split(":")[0]
            if fname and not _source_exists(case, fname):
                errs.append(f"{f.get('id')}: source file not found: {fname}")
        return errs

    return judge


# The sensing/commentary prompt-template version — part of every cache
# key. Bump it when the prompt templates change (the task builders, the
# vocabulary/context blocks, the sensing-prompt.md files): stale cached
# responses must orphan, never replay under a new prompt.
PROMPT_VERSION = "6"


def _cache_file(cache_ns, label, schema_name=None, files=None, task=None,
                context=None):
    """The response-cache file for one sensing call. Keyed by the case,
    the op label, the schema, and a content hash of the input evidence
    files — a changed case or evidence means a fresh key, never a stale
    response, and the key is stable across runs (the embedded
    evidence-index/entities are LLM context, not part of the key).
    `task` (the full prompt) is the fallback key for direct callers.
    `context` (the engine context a call depends on — e.g. the drop
    sensing's open questions) is hashed too: a changed context means a
    fresh key."""
    h = hashlib.sha256()
    h.update(f"{cache_ns}|{label}|{schema_name}|v{PROMPT_VERSION}".encode())
    if files:
        for f in sorted(files, key=lambda p: p.name):
            h.update(f.name.encode())
            h.update(Path(f).read_bytes())
    elif task is not None:
        h.update(task.encode())
    if context is not None:
        h.update(json.dumps(context, sort_keys=True, default=str).encode())
    return _cache_dir() / cache_ns / f"{label}-{h.hexdigest()[:16]}.json"


def sense_extract(ui, tag, label, noun, schema_name, task, fallback, judge=None,
                  stream=None, on_response=None, cache_ns=None, runner=None,
                  evidence_files=None, mode=None, context=None):
    """One sensing operation: schema + messy input → validated object,
    with the LLM response streamed live (stream callback; default: stdout)
    and a capped correction loop (errors fed back to the LLM, max 3 turns).

    Response cache (FACTY_SENSE, or the `mode` param): `live` (default)
    calls the LLM and caches the raw response; `cache` never calls the
    LLM — it replays the cached response (parsed + judged
    deterministically) or falls back to the recorded sensing. So the
    deterministic side runs offline, and demos replay reproducibly.
    Live mode falls back: cache → recorded sensing (logged, never
    silent). on_response(text, source) carries the raw response + its
    source (live|cache|recorded) to the caller."""
    mode = mode or os.environ.get("FACTY_SENSE", "live")
    cache_file = (_cache_file(cache_ns, label, schema_name,
                              files=evidence_files, task=task, context=context)
                  if cache_ns else None)
    arrow = f"{TAGS['llm']}▸{NC} " if USE_COLOR else "▸ "
    staged = sensing.staged_prompt_path(label.replace(" ", "-"))
    if DEBUG:
        ui.log(tag, f"debug: prompt staged at {staged}")
        ui.log(tag, "debug: pi command: " + " ".join(sensing.pi_command())
                + "  (the staged assignment is sent inline as the prompt)")

    def on_stream(line):
        if stream is not None:
            stream(line)
        else:
            sys.stdout.write(f"  {arrow}{line}\n")
            sys.stdout.flush()

    def on_note(msg):
        ui.log(tag, msg)

    result = None
    raw = None
    source = None
    if mode == "cache":
        # cache mode never calls the LLM: replay the cached response, or
        # fall back to the recorded sensing (logged, never silent).
        if cache_file is not None and cache_file.exists():
            raw = json.loads(cache_file.read_text())["response"]
            source = "cache"
            ui.log(tag, f"{label} — response cache hit, no LLM call ({cache_file.name})")
        else:
            ui.log(tag, f"{label} — no cached response, using the recorded sensing "
                        "(see SENSING.md); run live to populate the cache")
            result = fallback
            source = "recorded"
    else:
        ui.log(tag, f"{label} — calling Mistral Large 4 (mistral-subscription), streaming …")
        try:
            holder = []
            result = sensing.extract_structured(
                ENGINE_DIR / "schemas" / schema_name, task,
                stream=on_stream, label=label.replace(" ", "-"),
                judge=judge, note=on_note, debug=DEBUG, on_response=holder.append,
                runner=runner)
            raw = holder[0] if holder else None
            source = "live"
        except Exception as exc:  # unreachable LLM, or retries exhausted
            ui.log(tag, f"LLM call failed ({exc})")
            if DEBUG:
                ui.log(tag, f"debug: no fallback in debug mode — staged prompt: {staged}")
                raise SystemExit(2)
            if cache_file is not None and cache_file.exists():
                raw = json.loads(cache_file.read_text())["response"]
                source = "cache"
                ui.log(tag, f"falling back to the response cache ({cache_file.name})")
            else:
                ui.log(tag, "falling back to the recorded sensing (see SENSING.md) — "
                            "run this CLI from your own terminal to stream live")
                result = fallback
                source = "recorded"
    if source == "live" and raw is not None and cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            "case": cache_ns, "op": label, "model": sensing.MODEL,
            "response": raw, "cached_at": time.time()}, indent=2))
        ui.log(tag, f"response cached ({cache_file.name}) — "
                    "FACTY_SENSE=cache replays it without the LLM")
    if source == "cache":
        schema_dict = json.loads((ENGINE_DIR / "schemas" / schema_name).read_text())
        result = sensing.parse_and_validate(raw, schema_dict)
    if judge and result is not None:
        errs = judge(result)
        if errs:
            ui.log(tag, f"WARNING: judge flagged the result — {'; '.join(errs[:3])}")
    if on_response is not None:
        on_response(raw if raw is not None else json.dumps(result, indent=2),
                    source or "recorded")
    ui.log(tag, f"judge layer accepted ✓ ({sensing.describe(result, noun)})")
    return result


def _recorded_label_facts(case, cfg):
    """The recorded classifier facts: facts.json filtered to the sensor's
    source file (the recorded sensing is the fallback)."""
    path = Path(case) / "facts.json"
    if not path.exists():
        return None
    prefix = cfg["file"] + ":"
    facts = engine.load_validated(path, "facts.schema.json")
    out = [f for f in facts if str(f.get("source", "")).startswith(prefix)]
    return out or None


def sense_label(ui, case, files, on_response=None, mode=None):
    """The label sensor (small zero-shot classifier, CPU-only): evidence
    rows → labeled facts + aggregates. The same contract as sense_extract:
    live runs the model and caches the facts; FACTY_SENSE=cache replays the
    cache (never calls the model); fallbacks: cache → the recorded facts
    (the classifier facts already in facts.json, filtered by source)."""
    mode = mode or os.environ.get("FACTY_SENSE", "live")
    cfg = label.load_config(case)
    lbl = f"label the {Path(cfg['file']).stem} pile"
    cache_file = _cache_file(case.name, lbl, "facts.schema.json", files=files)
    recorded = _recorded_label_facts(case, cfg)
    tag = "classifier · induction"
    judge = make_facts_judge(case)

    def replay(entry, source):
        facts = entry["facts"]
        errs = label.validate_facts(facts)
        if errs:
            raise ValueError(f"{source} entry failed schema validation: "
                             + "; ".join(errs[:3]))
        return facts

    facts, source = None, None
    if mode == "cache":
        if cache_file.exists():
            facts = replay(json.loads(cache_file.read_text()), "cache")
            source = "cache"
            ui.log(tag, f"{lbl} — sensor cache hit, no model call "
                        f"({cache_file.name})")
        else:
            ui.log(tag, f"{lbl} — no cached sensor output, using the recorded "
                        "facts; run live to populate the cache")
    else:
        ui.log(tag, f"{lbl} — the label sensor (a small local classifier, "
                    "no LLM tokens)")
        ui.log(tag, f"scoring the pile with {label.short_model(cfg['model'])} "
                    f"({cfg['precision']}, CPU-only), threshold "
                    f"{cfg['threshold']}")
        try:
            facts, src_tag = label.run_sensor(case, cfg)
            source = "live"
            if src_tag != "classifier":
                ui.log(tag, f"fallback path: {src_tag} (the classifier could "
                            "not run — the raw text was classified as-is)")
        except (RuntimeError, label.LabelError) as exc:
            ui.log(tag, f"sensor call failed ({exc})")
            if DEBUG:
                raise SystemExit(2)
    if facts is None:
        if cache_file.exists():
            facts = replay(json.loads(cache_file.read_text()), "cache")
            source = "cache"
            ui.log(tag, f"falling back to the sensor cache ({cache_file.name})")
        elif recorded:
            facts, source = recorded, "recorded"
            ui.log(tag, "falling back to the recorded label facts "
                        "(see SENSING.md)")
    if facts is None:
        raise SystemExit("facty: no label-sensor output — install the sensor "
                         "deps (make deps-sensors), run live, or record the facts")
    if source == "live":
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            "case": case.name, "op": lbl, "model": cfg["model"],
            "precision": cfg["precision"], "facts": facts,
            "cached_at": time.time()}, indent=2))
        ui.log(tag, f"sensor output cached ({cache_file.name}) — "
                    "FACTY_SENSE=cache replays it without the model")
    if on_response is not None:
        on_response(json.dumps(facts, indent=2), source or "recorded")
    counts = {}
    for f in facts:
        if f["predicate"] == "classifiedAs":
            counts[f["value"]] = counts.get(f["value"], 0) + 1
    n_aggs = sum(1 for f in facts if f["id"].startswith("ag-"))
    gated = counts.pop(label.UNCLASSIFIED, 0)
    if counts:
        breakdown = ", ".join(f"{v} {k}" for k, v in sorted(counts.items()))
        ui.log(tag, f"{sum(counts.values())} rows labeled ({breakdown}); "
                    f"{gated} below the {cfg['threshold']} gate → unclassified "
                    "(the LLM fallback set); "
                    f"{n_aggs} aggregate facts")
    errs = judge(facts)
    if errs:
        ui.log(tag, f"WARNING: judge flagged the result — {'; '.join(errs[:3])}")
    ui.log(tag, f"judge layer accepted ✓ ({sensing.describe(facts, 'facts')})")
    return facts


def _write_and_report(ui, case, raw):
    obj = sensing.parse_and_validate(raw, label.PARSER_SCHEMA)
    label.write_parser(case, obj)
    errs = label.check_parser_contract(obj["extract_py"])
    ui.log("llm · induction", "parser written (sensor/extract.py + "
                              "extract_test.py) — contract "
                              + ("holds ✓" if not errs
                                 else "VIOLATIONS: " + "; ".join(errs[:3])))
    return obj


def sense_parser(ui, case, files, stream=None, on_response=None, mode=None):
    """The parser-generation op: the LLM writes sensor/extract.py +
    extract_test.py (judged by the code judge in a capped correction loop,
    1 initial + 2 revisions), and the files are written for commit. Cached
    like the sensing calls; the recorded parser (sensor/extract.py) is the
    fallback."""
    mode = mode or os.environ.get("FACTY_SENSE", "live")
    cfg = label.load_config(case)
    lbl = "generate the extract parser"
    cache_file = _cache_file(case.name, lbl, files=files)
    tag = "llm · induction"
    recorded = (Path(case) / "sensor" / "extract.py").exists()
    if mode == "cache":
        if cache_file.exists():
            raw = json.loads(cache_file.read_text())["response"]
            ui.log(tag, f"{lbl} — response cache hit, no LLM call "
                        f"({cache_file.name})")
            return _write_and_report(ui, case, raw)
        ui.log(tag, f"{lbl} — no cached response, using the recorded parser")
        if recorded:
            return None
        raise SystemExit("facty: no parser — run live to generate it")
    ui.log(tag, f"{lbl} — calling Mistral Large 4 (mistral-subscription), "
                "streaming …")
    try:
        obj = label.generate_parser(case, cfg, stream=stream)
        raw = json.dumps(obj, indent=2)
    except Exception as exc:
        ui.log(tag, f"parser generation failed ({exc})")
        if DEBUG:
            raise SystemExit(2)
        if recorded:
            ui.log(tag, "falling back to the recorded parser "
                        "(sensor/extract.py)")
            return None
        raise SystemExit("facty: parser generation failed and no recorded "
                         "parser exists")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        "case": case.name, "op": lbl, "model": sensing.MODEL,
        "response": raw, "cached_at": time.time()}, indent=2))
    ui.log(tag, f"response cached ({cache_file.name}) — FACTY_SENSE=cache "
                "replays it without the LLM")
    if on_response is not None:
        on_response(raw, "live")
    return _write_and_report(ui, case, raw)


def evidence_refs(files):
    """The evidence files, INLINED (a path header + the content) — the
    model reads them in one shot, in the assignment itself. (@refs are
    not expanded inside a prompt message: the model would have to read
    every file through the read tool — an agentic loop of LLM round
    trips per file, which is what made the sensing calls slow.) The
    header carries the case-relative path (evidence/<file>) — the exact
    form a fact's source span cites."""
    return "\n\n".join(f"── evidence/{f.name} ──\n{f.read_text()}" for f in files)


def _terms(node, key):
    """Every literal string under `key` in a JSON structure (recursive).
    Variable patterns ({"var": name}) are dicts, not strings — skipped."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key and isinstance(v, str):
                yield v
            else:
                yield from _terms(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from _terms(v, key)


def pack_vocabulary(case_dir):
    """The pack's term vocabulary — (predicates, subjects): every
    predicate the rules, constraints, and hypotheses speak (conditions,
    claims, derived facts) and every subject they reference. The facts
    task carries it so a fresh extraction speaks the pack's ontology:
    without it the model invents its own terms (its own entity names,
    its own paraphrases) and no rule can fire — the recorded sensing
    was authored against these exact terms. This is domain knowledge
    (the ontology), not the engine's conclusions — the model still
    reads the evidence and reports only what it shows."""
    case = Path(case_dir)
    preds, subs = set(), set()
    for name, schema in (("rules.json", "rule.schema.json"),
                         ("constraints.json", "constraint.schema.json"),
                         ("hypotheses.json", "hypothesis.schema.json")):
        for item in engine.load_array(case / "pack" / name, schema):
            preds.update(_terms(item, "predicate"))
            subs.update(_terms(item, "subject"))
    return sorted(preds), sorted(subs)


def build_facts_task(case_dir, files, evidence_index=None, entities=None,
                     engine_context=None):
    template = (case_dir / "sensing-prompt.md").read_text()
    task = (template
            .replace("{{EVIDENCE}}", evidence_refs(files))
            .replace("{{SCHEMA}}", str((ENGINE_DIR / "schemas" / "fact.schema.json").resolve()))
            .replace("{{EVIDENCE_INDEX}}", json.dumps(evidence_index or [], indent=2))
            .replace("{{ENTITIES}}", json.dumps(entities or [], indent=2)))
    preds, subs = pack_vocabulary(case_dir)
    if preds or subs:
        task += ("\n\n## The pack's term vocabulary (the ontology)\n\n"
                 "The engine's rules, constraints, and hypotheses speak "
                 "exactly these terms. When a fact matches one of them, use "
                 "THAT predicate and THAT subject label, verbatim; invent "
                 "new terms only when the evidence states something the "
                 "pack does not cover. Values: quote the evidence's exact "
                 "terms (singular/plural as written); booleans as the JSON "
                 "literals true/false — never the strings \"true\"/\"false\""
                 ".\n\n"
                 "Subjects the pack references:\n"
                 + (", ".join(subs) if subs else "(none)") + "\n\n"
                 "Predicates the pack references:\n"
                 + (", ".join(preds) if preds else "(none)") + "\n")
    if engine_context is not None:
        task += ("\n\n## The engine's context (phase 1)\n\n"
                 + engine_context_block(engine_context))
    return task


def engine_context_block(r):
    """The engine's phase-1 context for sensing the recommended test's
    evidence: its OPEN QUESTIONS (where to look) and the hypothesis space
    (statements only, in a neutral id order — never scores, rankings,
    derived facts, or pruning verdicts). Feeding the engine's conclusions
    back into the senses would bias the reading toward the current
    verdict (confirmation / echo); the questions carry no conclusions —
    they tell the senses where to look, never what to find."""
    lines = ["The deterministic engine has already solved the case on the "
             "initial evidence. It opened these questions — the checks that "
             "best discriminate the surviving explanations — and this is the "
             "hypothesis space it is working with (statements only, in no "
             "particular order):", ""]
    open_q = [q for q in (r.get("opened_questions") or [])
              if q.get("status") == "open"]
    if open_q:
        lines.append("Open questions:")
        for q in open_q:
            disc = ", ".join(q.get("discriminates") or [])
            lines.append(f"- {q['id']}: {q['text']}"
                         + (f" (discriminates: {disc})" if disc else ""))
        lines.append("")
    ranking = sorted(r.get("ranking") or [], key=lambda x: x["id"])
    if ranking:
        lines.append("Hypotheses still in play (statements only):")
        for rk in ranking:
            lines.append(f"- {rk['id']}: {rk['statement']}")
        lines.append("")
    lines += ["Sense the evidence below into facts (the schema follows). "
              "Prioritize evidence that bears on the open questions. Report "
              "ONLY what the evidence shows, with source spans — do not "
              "evaluate the hypotheses, do not tailor facts to the questions, "
              "and do not restate the initial evidence's facts (the engine "
              "already holds them). The questions tell you where to look, "
              "never what to find."]
    return "\n".join(lines)


def sensing_ops(case):
    """The sensing operations for a case: {op: (label, schema_name, files)}.
    The files are the op's input evidence (phase-1 files, or the drop's
    files) — they key the response cache. Shared by sense_one and the
    cache-readiness check (the labels must match exactly)."""
    case = Path(case)
    evidence = sorted((case / "evidence").iterdir())
    phase1 = phase1_evidence(case)
    ops = {
        "classify": ("classify the evidence pile", "evidence-index.schema.json", phase1),
        "entities": ("extract the case entities", "entities.schema.json", phase1),
        "facts": ("extract the facts", "facts.schema.json", phase1),
    }
    drop = drop_file(case)
    if drop is not None:
        drop_names = drop_source_names(case)
        drop_files = [f for f in evidence if f.name in drop_names]
        ops["drop"] = (f"extract the {drop.stem.replace('facts-', '')} facts",
                       "facts.schema.json", drop_files)
    if (case / "classify.json").exists():
        cfg = label.load_config(case)
        pile = Path(cfg["file"]).stem
        ops["label"] = (f"label the {pile} pile", "facts.schema.json",
                        [case / cfg["file"]])
        if cfg["prep"] == "parser":
            ops["parser"] = ("generate the extract parser", None,
                             [case / cfg["file"]])
    return ops


def _offline_facts(case):
    """The facts an offline (cache-mode) run would use: the cached facts
    response (the live pipeline's), else the recorded sensing."""
    case = Path(case)
    label, schema, files = sensing_ops(case)["facts"]
    cache_file = _cache_file(case.name, label, schema, files=files)
    if cache_file.exists():
        try:
            return json.loads(json.loads(cache_file.read_text())["response"])
        except (ValueError, KeyError):
            pass
    return engine.load_array(case / "facts.json", "fact.schema.json")


def context_key(r):
    """The cache-key projection of the engine context a sensing call
    depends on: the open questions + the hypothesis statements — the
    part that shapes the prompt."""
    return {
        "questions": sorted(
            ({k: q.get(k) for k in ("id", "text", "discriminates", "status")}
             for q in (r.get("opened_questions") or [])),
            key=lambda q: q["id"]),
        "hypotheses": sorted(
            ({k: h.get(k) for k in ("id", "statement")}
             for h in (r.get("ranking") or [])),
            key=lambda h: h["id"]),
    }


def cache_state(case):
    """(ready, total) — how many of the case's sensing steps have a
    cached response. The workbench shows this next to its offline
    checkbox. The drop's key carries the engine context an offline run
    would sense with (the phase-1 solve on the cached facts, else the
    recorded sensing), so the count answers: would offline replay
    work?"""
    case = Path(case)
    ops = sensing_ops(case)
    drop_key = None
    if "drop" in ops:
        drop_key = context_key(engine.run_case(case, facts=_offline_facts(case)))
    ready = 0
    for op, (label, schema, files) in ops.items():
        context = drop_key if op == "drop" else None
        if _cache_file(case.name, label, schema, files=files,
                       context=context).exists():
            ready += 1
    return ready, len(ops)


def cache_ready(case):
    """True when the response cache has an entry for every sensing step
    of the case."""
    ready, total = cache_state(case)
    return ready == total


def sense_one(ui, case, op, evidence_index=None, entities=None, stream=None,
              on_response=None, mode=None, runner=None, engine_context=None):
    """Run a single sensing operation (classify | entities | facts | drop |
    label | parser). Live LLM/classifier when reachable (FACTY_SENSE=cache,
    or mode='cache', replays the response cache instead), recorded sensing
    otherwise. The phase-1 / phase-2 split is derived from the case: the
    drop's facts name their source files; everything else is phase 1.
    The label/parser ops exist only for cases with a classify.json.

    The drop op senses the recommended test's evidence WITH the engine's
    phase-1 context (engine_context: the open questions + the hypothesis
    space — statements only, never the engine's conclusions). Callers
    that hold a live phase-1 solve pass it; otherwise the recorded
    phase-1 solve is computed on the spot (cheap — the engine is
    deterministic)."""
    case = Path(case)
    ops = sensing_ops(case)
    if op not in ops:
        raise SystemExit(f"unknown op: {op} (expected {', '.join(ops)})")
    label, schema_name, files = ops[op]
    evidence = sorted((case / "evidence").iterdir())
    phase1 = phase1_evidence(case)
    recorded_index = engine.load_validated(case / "evidence-index.json",
                                           "evidence-index.schema.json")
    recorded_entities = engine.load_validated(case / "entities.json",
                                              "entities.schema.json")
    recorded_facts = engine.load_validated(case / "facts.json", "facts.schema.json")
    drop = drop_file(case)
    recorded_drop = engine.load_validated(drop, "facts.schema.json") if drop else None
    judge = make_facts_judge(case)
    index = evidence_index if evidence_index is not None else recorded_index
    ents = entities if entities is not None else recorded_entities
    if op == "classify":
        task = sensing.CLASSIFY_TASK.replace("{{FILES}}", evidence_refs(phase1))
        return sense_extract(ui, "llm · induction", label, "evidence items",
                             schema_name, task, recorded_index, stream=stream,
                             on_response=on_response, cache_ns=case.name,
                             runner=runner, evidence_files=files, mode=mode)
    if op == "entities":
        task = sensing.ENTITIES_TASK.replace("{{FILES}}", evidence_refs(phase1))
        return sense_extract(ui, "llm · induction", label, "entities",
                             schema_name, task, recorded_entities, stream=stream,
                             on_response=on_response, cache_ns=case.name,
                             runner=runner, evidence_files=files, mode=mode)
    if op == "facts":
        return sense_extract(ui, "llm · induction", label, "facts",
                             schema_name,
                             build_facts_task(case, phase1, index, ents),
                             recorded_facts, judge=judge, stream=stream,
                             on_response=on_response, cache_ns=case.name,
                             runner=runner, evidence_files=files, mode=mode)
    if op == "label":
        return sense_label(ui, case, files, on_response=on_response, mode=mode)
    if op == "parser":
        return sense_parser(ui, case, files, stream=stream,
                            on_response=on_response, mode=mode)
    # drop — the recommended test's evidence, sensed with the earlier
    # context (the evidence index + entities, for consistent entity ids)
    # and the engine's phase-1 context (its open questions + the
    # hypothesis space — never its conclusions).
    if recorded_drop is None:
        raise SystemExit(f"facty: case {case.name} has no phase-2 drop")
    drop_names = drop_source_names(case)
    drop_evidence = [f for f in evidence if f.name in drop_names]
    if engine_context is None:
        # the recorded phase-1 solve — on the facts an offline run would
        # use (the cached facts, else the recorded sensing), so the cache
        # key matches what cache_state checks
        engine_context = engine.run_case(case, facts=_offline_facts(case))
    return sense_extract(ui, "llm · induction", label, "facts",
                         schema_name,
                         build_facts_task(case, drop_evidence, index, ents,
                                          engine_context=engine_context),
                         recorded_drop, judge=judge, stream=stream,
                         on_response=on_response, cache_ns=case.name,
                         runner=runner, evidence_files=files, mode=mode,
                         context=context_key(engine_context))


# ── Out-of-band commentary (the LLM as explainer, never as decider) ──

def _label_tier(case):
    """The label sensor's tier as the case pins it (classify.json
    `backend`): strom (the default — the Strom decider tier scores every
    row, the local classifier is the automatic fallback), hybrid (the
    classifier scores the bulk, the decider adjudicates the gated rows),
    local (the offline-only classifier). The explainer describes the tier
    the case actually runs — not a hardcoded one."""
    backend = "strom"
    try:
        backend = json.loads((Path(case) / "classify.json").read_text()).get(
            "backend", "strom")
    except (ValueError, OSError):
        pass
    try:
        import strom  # the decider tier's client (stdlib-only)
        hosted = f"the Strom decider tier (Uprelic {strom.DEFAULT_MODEL}, EU/Paris)"
    except Exception:
        hosted = "the Strom decider tier (Uprelic, EU/Paris)"
    tier = {
        "strom": f"{hosted} scores every row; the local classifier is "
                 "the automatic fallback",
        "hybrid": f"the local classifier (tier 1) scores the bulk; "
                  f"{hosted} adjudicates the rows below the confidence gate",
        "local": "a small local classifier (tier 1, CPU-only, no LLM "
                 "tokens) scores every row",
    }.get(backend, f"the label sensor ({backend} backend)")
    short = {
        "strom": hosted,
        "hybrid": f"the local classifier + {hosted}",
        "local": "the local classifier (CPU-only)",
    }.get(backend, f"the label sensor ({backend})")
    return backend, tier, short


def sensing_block(case, result, entities):
    """The induction half of the run, as the commentary sees it: the
    models behind it and the steps the senses performed (classify →
    entities → facts → the label sensor's tier → the test evidence),
    with their outputs — so the explainer can walk the WHOLE run
    (induction + deduction), not just the engine's half. The facts are
    compact triples (the judge layer already checked them: schema +
    compute)."""
    case = Path(case)
    index = engine.load_validated(case / "evidence-index.json",
                                  "evidence-index.schema.json")
    facts = engine.load_array(case / "facts.json", "fact.schema.json")
    steps = [
        {"step": "classify the evidence pile (messy input → typed evidence)",
         "items": [{k: e.get(k) for k in ("file", "evidenceClass", "summary")}
                   for e in index]},
        {"step": "extract the entities (extraction is sensing, not reasoning)",
         "count": len(entities or [])},
        {"step": "sense the evidence → facts (a judge layer checks the "
                 "schema + the compute)",
         "count": len(facts),
         "facts": [{k: f.get(k) for k in ("id", "subject", "predicate", "value")}
                   for f in facts]},
    ]
    models = {"reading — classify · entities · facts":
              f"{sensing.PROVIDER} / {sensing.MODEL} (the LLM reads "
              "the evidence)"}
    sensor_srcs = sensor_source_names(case)
    if sensor_srcs:
        n = sum(1 for f in facts
                if Path(str(f.get("source", "")).split(":")[0]).name in sensor_srcs)
        backend, tier, short = _label_tier(case)
        models["label sensor"] = f"{backend} backend — {short}"
        steps.append({"step": f"label the evidence pile — {tier}",
                      "files": sorted(sensor_srcs),
                      "facts_contributed": n})
    drop = drop_file(case)
    if drop is not None and "recommended test" in str(result.get("phase", "")):
        steps.append({"step": "sense the recommended test's evidence (with "
                              "the engine's open questions as context — "
                              "never its conclusions)",
                      "count": len(engine.load_array(drop, "fact.schema.json"))})
    return {"models": models, "steps": steps}


def explain_task(target, result, entities, sensing=None):
    """The commentary prompt: a plain-language explanation of the whole
    run — the senses (induction) and the engine (deduction). Presentation
    only — the verdict is deterministic and never depends on this call
    (ADR-0003: the LLM is never in the verdict path); this is the LLM as
    explainer, fed the run's artifacts (unlike the senses, which never
    see the engine's conclusions).

    The summary carries the WHOLE candidate story, in the order the
    engine performed it — the forward chain's fired rules + derived
    facts + opened questions + raised candidates, the pruned records
    (constraint + reason + the pruned hypothesis's own statement), and
    the ranking — so the commentary can reconcile the counts ("three
    were raised, one was eliminated, two ranked") and walk the steps.
    With `sensing`, the prompt opens with the induction half (the steps
    the senses performed + their outputs), so the step-by-step covers
    the whole run, not just the engine's half."""
    summary = {
        "phase": result.get("phase"),
        "fired_rules": [{"rule": e.get("rule"), "round": e.get("round"),
                         "op": ("derived" if "derived" in e
                                else "opened" if "opened" in e else "raised"),
                         "target": (e.get("derived") or e.get("opened")
                                    or e.get("raised")),
                         "from": e.get("sources", [])}
                        for e in result.get("fired_rules", [])],
        "derived_facts": [{k: f.get(k) for k in ("id", "subject", "predicate", "value")}
                          for f in result.get("derived_facts", [])],
        "opened_questions": [{k: q.get(k) for k in ("id", "text", "discriminates")}
                             for q in result.get("opened_questions", [])],
        "raised": list(result.get("raised_hypotheses", [])),
        "pruned": [{k: p.get(k) for k in ("hypothesis", "constraint",
                                          "reason", "statement")}
                   if isinstance(p, dict) else p
                   for p in result.get("pruned", [])],
        "ranking": [{k: rk[k] for k in ("id", "statement", "score",
                                        "claims_proven", "claims_total",
                                        "support", "prior")}
                    for rk in result.get("ranking", [])],
        "verdict": (result.get("verdict") or {}).get("id"),
        "recommended_test": result.get("recommended_test"),
    }
    ents = [{k: e.get(k) for k in ("id", "name", "kind", "role")}
            for e in (entities or [])]
    if target == "entities":
        ask = ("Summarize the extracted entities for a human reader: group "
               "them by kind, one line each, and name the key players.")
    elif target == "ranking":
        ask = ("Explain the ranking for a human reader: why each hypothesis "
               "scored where it did (claims proven, support, prior) — and "
               "what the scores mean in plain language. Also name the "
               "candidates that were eliminated before ranking and why, so "
               "the ranking is not mistaken for the full candidate set.")
    else:
        ask = ("Explain the whole run for a human reader, in plain "
               "language — the conclusion first, the details after. "
               "(1) Open with an ELI5 executive summary of at most three "
               "sentences: what the case was about, what the engine "
               "concluded (the verdict), and what should happen next — a "
               "reader who stops there already has the answer. (2) Then "
               "the step-by-step details, in the order the run performed "
               "them: first the senses (induction — the evidence "
               "classified, the entities extracted, the facts sensed and "
               "judge-checked, any sensor labels, and for a phase-2 run "
               "the test evidence sensed with the engine's open "
               "questions); then the engine (deduction — the forward "
               "chain's fired rules, derived facts, opened questions and "
               "raised candidates; the constraint layer's eliminations "
               "and the reason each; the backward chain's claim proofs "
               "and ranking; the verdict and the reasoning behind it); "
               "and finally the recommended next check — what would "
               "change the conclusion. Short sections, no jargon.")
    head = ("You are explaining a deterministic detective engine's run — "
            "the senses (induction) and the engine (deduction) — to a "
            "human. Everything below is verbatim: the run's sensing, the "
            "engine's output. Explain it, do not re-derive it. Plain "
            "language, short sections, no jargon, no speculation beyond "
            "what the output says. This is commentary for a human reader; "
            "the engine's verdict stands on its own.\n\n"
            f"{ask}\n\n")
    senses = ""
    if sensing:
        senses = ("THE SENSES (induction — the reading model + the label "
                  "sensor read the evidence; probabilistic, never in the "
                  "verdict path):\n"
                  f"{json.dumps(sensing, indent=2)}\n\n"
                  "Entities extracted (the case's people, animals, places, "
                  f"objects):\n{json.dumps(ents, indent=2)}\n\n")
    return (head + senses
            + "THE ENGINE (deduction — deterministic; it alone decides "
              "the verdict; its output, verbatim):\n"
              f"{json.dumps(summary, indent=2)}\n\n"
              "Write the commentary in plain language (markdown is fine).")


def explain(ui, case, result, entities, target="verdict", stream=None,
            on_response=None, mode=None, runner=None):
    """Out-of-band LLM commentary: a plain-language explanation of the
    whole run — the senses (induction) and the engine's result
    (entities | ranking | verdict). Presentation only — the verdict is
    deterministic and never depends on this call. The commentary is
    cached like the sensing responses (keyed by the full prompt, so a
    changed result means a fresh key) and replayed in cache mode; with
    no cache entry it degrades to None (logged, never silent).
    on_response(text, source) carries the raw commentary + its source
    (live | cache) to the caller."""
    mode = mode or os.environ.get("FACTY_SENSE", "live")
    tag = "llm · commentary"
    label = f"explain the {target}"
    # the prune records carry the constraint + reason; add the pruned
    # hypothesis's own statement (from the pack) so the commentary can
    # say what the eliminated candidate claimed before why it fell
    result = dict(result or {})
    hyps = engine.load_array(Path(case) / "pack" / "hypotheses.json",
                             "hypothesis.schema.json")
    stmt = {h["id"]: h.get("statement") for h in hyps}
    result["pruned"] = [dict(p, statement=stmt.get(p.get("hypothesis")))
                        if isinstance(p, dict) else p
                        for p in result.get("pruned", [])]
    task = explain_task(target, result, entities,
                        sensing=sensing_block(case, result, entities))
    cache_file = _cache_file(Path(case).name, label, task=task)

    def on_stream(line):
        if stream is not None:
            stream(line)

    if mode == "cache":
        if cache_file.exists():
            raw = json.loads(cache_file.read_text())["response"]
            ui.log(tag, f"{label} — response cache hit, no LLM call ({cache_file.name})")
            if on_response:
                on_response(raw, "cache")
            return raw
        ui.log(tag, f"{label} — no cached commentary, run live to cache it")
        return None
    ui.log(tag, f"calling Mistral Large 4 ({sensing.PROVIDER}), streaming …")
    source = "live"
    try:
        raw = sensing.llm_text(task, stream=on_stream,
                               label=label.replace(" ", "-"), runner=runner)
    except Exception as exc:  # unreachable LLM, or the call failed
        ui.log(tag, f"commentary call failed ({exc})")
        if cache_file.exists():
            raw = json.loads(cache_file.read_text())["response"]
            source = "cache"
            ui.log(tag, f"falling back to the cached commentary ({cache_file.name})")
        else:
            return None
    if on_response:
        on_response(raw, source)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        "case": Path(case).name, "target": target, "model": sensing.MODEL,
        "response": raw, "cached_at": time.time()}, indent=2))
    ui.log(tag, f"commentary cached ({cache_file.name})")
    return raw


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


# ── The run log: tools and inference types ───────────────────────────
#
# Every line in a run log (walkthrough, workbench) is tagged with the
# tool that produced it and whether the inference was a deduction (the
# engine) or an induction (the LLM senses). Facts are triples:
# subject / predicate = value.

TOOL_TAG = {
    "derive": "fwd chain · deduction",
    "raise": "fwd chain · deduction",
    "open": "fwd chain · deduction",
    "eliminate": "constraint solver · deduction",
    "support": "constraint solver · deduction",
    "claim": "bwd chain · deduction",
    "proof": "bwd chain · deduction",
}


def fmt_event(e):
    """Format one engine event (derive/raise/open/eliminate/support/
    claim/proof) as a run-log line — facts expressed as triples."""
    if e["op"] == "derive":
        return fmt_derive(e)
    if e["op"] == "raise":
        return fmt_raise(e)
    if e["op"] == "open":
        return fmt_open(e)
    if e["op"] == "eliminate":
        return fmt_eliminate(e)
    if e["op"] == "support":
        return fmt_support(e)
    if e["op"] == "claim":
        return fmt_claim(e)
    if e["op"] == "proof":
        return fmt_proof(e)
    return str(e)


# ── Pretty rendering (the control plane's human output) ──────────────

def table(headers, rows):
    cols = list(zip(*([list(headers)] + [list(r) for r in rows]))) if rows \
        else [[h] for h in headers]
    widths = [max(len(str(c)) for c in col) for col in cols]

    def fmt(row):
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row))

    lines = [fmt(headers), fmt(["─" * w for w in widths])]
    lines += [fmt(r) for r in rows]
    return "\n".join(lines)


def render_report(r):
    a = []
    add = a.append
    add(bold(f"Facty · {r['case']}") + dim(f"  ({r['phase']})"))
    add(f"{r['facts_sensed']} sensed facts · {r['rules']} rules · "
        f"{r['hypotheses_total']} hypotheses")
    add("")
    add(bold("Forward chain") + dim(f" — {len(r['derived_facts'])} derived facts"))
    for f in r["derived_facts"]:
        add(f"  ▸ {cyan(f['id'])}: {f['subject']} / {f['predicate']} = {f['value']!r}"
            f"  {dim('← ' + f['source'])}")
    if not r["derived_facts"]:
        add("  (no rules fired)")
    add("")
    add(bold("Questions opened") + dim(f" — {len(r['opened_questions'])} (the awareness loop)"))
    for q in r["opened_questions"]:
        add(f"  ▸ {magenta(q['id'])} [{q['slot']}] {q['text']}")
    add("")
    if r["pruned"]:
        add(bold("Constraints") + dim(f" — {len(r['pruned'])} pruned"))
        for p in r["pruned"]:
            add(f"  ✗ {red(p['hypothesis'])} — {p['reason']}  {dim('(' + p['constraint'] + ')')}")
        add("")
    add(bold("Ranking") + dim(" — backward chain + score"))
    rows = [[rk["id"], f"{rk['claims_proven']}/{rk['claims_total']}", str(rk["support"]),
             f"{rk['prior']:.2f}", f"{rk['score']:.4f}"] for rk in r["ranking"]]
    add(table(["ID", "CLAIMS", "SUPPORT", "PRIOR", "SCORE"], rows))
    add("")
    if r["recommended_test"]:
        q = r["recommended_test"]
        add(bold("Recommended test") + f": {green(q['id'])} — {q['text']}")
        add("")
    v = r["verdict"]
    if v:
        add(bold(green(f"VERDICT: {v['id']}")) + f" — {v['statement']}"
            + bold(f"  (score {v['score']:.4f})"))
        extras = [f"{k}: {v[k]}" for k in ("killer", "horse_fate") if v.get(k)]
        note = engine.confidence_note(v, r["opened_questions"])
        add("  " + (" · ".join(extras) + " · " if extras else "") + f"confidence: {note}")
    return "\n".join(a)


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
        line = f"  VERDICT: {verdict['id']} ({verdict['score']:.4f})"
        extras = [f"{k}: {verdict[k]}" for k in ("killer", "horse_fate") if verdict.get(k)]
        if extras:
            line += f" — {' · '.join(extras)}"
        ui.log("trace", line)


# ── The walkthrough (terminal step-through; VMs, no-TTY) ─────────────

def walkthrough(case, auto=False):
    case = Path(case)
    ui = UI(auto=auto)
    drop = drop_file(case)
    drop_label = drop.stem.replace("facts-", "") if drop else "phase-2"

    print()
    ui.log("case", "Facty — interactive case walkthrough (terminal UI; the workbench is `./facty`)")
    ui.log("case", f"case: {case.name} · type: {case_type(case)} · "
                   f"engine: deterministic · LLM: Mistral Large 4 (sensing only)")

    # ── Step 1: load the case ──────────────────────────────────────
    ui.step("case", "Load the case")
    for f in sorted((case / "evidence").iterdir()):
        ui.log("case", f"evidence: {f.name} ({f.stat().st_size} bytes)")
    recorded = engine.load_validated(case / "facts.json", "facts.schema.json")
    rules = engine.load_array(case / "pack" / "rules.json", "rule.schema.json")
    hypotheses = engine.load_array(case / "pack" / "hypotheses.json", "hypothesis.schema.json")
    constraints = engine.load_array(case / "pack" / "constraints.json", "constraint.schema.json")
    ui.log("case", f"pack: {len(rules)} rules · {len(constraints)} constraints · "
                   f"{len(hypotheses)} hypotheses (all schema-validated ✓)")
    ui.log("case", f"recorded sensing: {len(recorded)} facts (see SENSING.md)")

    # one pi session for this case run — the provider's prompt
    # cache hits across the calls; a new run starts fresh
    with sensing.session_scope() as sess:
        # ── Step 2: the sensing motion (the LLM half, streamed) ────────
        ui.step("llm · induction", "Classify the evidence pile — messy input → typed evidence")
        evidence_index = sense_one(ui, case, "classify")
        for item in evidence_index:
            ui.log("llm · induction", f"  {item['file']} → {item['evidenceClass']} ({item['confidence']})")

        ui.step("llm · induction", "Extract the entities — extraction is sensing, not reasoning")
        entities = sense_one(ui, case, "entities")
        ui.log("llm · induction", f"entities: {', '.join(e['name'] for e in entities)}")

        ui.step("llm · induction", "Sense the evidence → facts (judge: schema + compute checks)")
        facts = sense_one(ui, case, "facts", evidence_index, entities)
        if (case / "classify.json").exists():
            ui.step("classifier · induction", "The label sensor — the evidence pile, "
                                            "labeled (small classifier, CPU-only)")
            label_facts = sense_one(ui, case, "label")
            facts = facts + label_facts
            ui.log("classifier · induction", f"the pile is labeled — "
                    f"{len(label_facts)} facts enter the case")

        # ── Step 3: forward chain ──────────────────────────────────────
        ui.step("fwd chain · deduction", "Forward chain — watch the rules fire")

        def chain_emit(e):
            if e["op"] == "derive":
                ui.log("fwd chain · deduction", fmt_derive(e))
            elif e["op"] == "raise":
                ui.log("fwd chain · deduction", fmt_raise(e))
            elif e["op"] == "open":
                ui.log("fwd chain · deduction", fmt_open(e))

        derived, fired, questions, raised = engine.forward_chain(facts, rules, emit=chain_emit)
        ui.log("fwd chain · deduction", f"fixpoint: {len(derived)} derived facts · "
                                       f"{len(questions)} questions opened · {len(raised)} hypotheses raised")

        # ── Step 4: the awareness loop ─────────────────────────────────
        ui.step("fwd chain · deduction", "The awareness loop — what the engine still wants to know")
        active = [h for h in hypotheses if h["id"] in raised] if raised else hypotheses
        survivors0, _ = engine.apply_constraints(active, facts + derived, constraints)
        verdict_tmp = engine.combine(survivors0, facts + derived, questions)
        for q in engine.rank_questions(questions, [r["id"] for r in verdict_tmp["ranking"]]):
            ui.log("fwd chain · deduction", f"{q['id']} [{q['slot']}] discriminates "
                                           f"{', '.join(q.get('discriminates', []))}: {q['text']}")
        if verdict_tmp["recommended_test"]:
            rec = verdict_tmp["recommended_test"]
            ui.log("fwd chain · deduction", f"recommended test: {rec['id']} — {rec['text']}")

        # ── Step 5: constraints ────────────────────────────────────────
        ui.step("constraint solver · deduction", "Constraint layer — prune and support")
        survivors, pruned = engine.apply_constraints(
            active, facts + derived, constraints,
            emit=lambda e: ui.log("constraint solver · deduction",
                                  fmt_eliminate(e) if e["op"] == "eliminate"
                                  else fmt_support(e)))
        ui.log("constraint solver · deduction", f"{len(pruned)} pruned · {len(survivors)} survive")

        # ── Step 6: backward chain + ranking ───────────────────────────
        ui.step("bwd chain · deduction", "Backward chain — prove the claims, rank the survivors")

        def combine_emit(e):
            if e["op"] == "claim":
                ui.log("bwd chain · deduction", "  " + fmt_claim(e))
            elif e["op"] == "proof":
                ui.log("bwd chain · deduction", fmt_proof(e))

        verdict1 = engine.combine(survivors, facts + derived, questions, emit=combine_emit)

        # ── Step 7: verdict (initial evidence) ─────────────────────────
        ui.step("verdict", "Verdict — on the initial evidence")
        v1 = verdict1["ranking"][0] if verdict1["ranking"] else None
        if v1:
            ui.log("verdict", f"{v1['id']} — {v1['statement']}  (score {v1['score']:.4f})")
            extras = [f"{k}: {v1[k]}" for k in ("killer", "horse_fate") if v1.get(k)]
            prefix = " · ".join(extras)
            ui.log("verdict", f"{prefix + ' · ' if prefix else ''}"
                              f"confidence: {engine.confidence_note(v1, questions)}")
        ui.log("verdict", "not final — the recommended test is still open")

        # ── Step 8: trace (phase 1) ────────────────────────────────────
        ui.step("trace", "The red yarn — phase 1 trace")
        render_trace(ui, "phase 1", facts, derived, fired, pruned,
                     verdict1["ranking"], v1)

        if drop is None:
            ui.log("verdict", "this case has no phase-2 drop — the case closes here")
            print()
            return 0

        # ── The recommended test runs ───────────────────────────────────
        ui.step("test", f"Run the recommended test — sense the {drop_label} evidence "
                        f"(the LLM half, streamed)")
        drop_facts = sense_one(ui, case, "drop", evidence_index, entities,
                               engine_context={"opened_questions": questions,
                                               "ranking": verdict1["ranking"]})
        facts2 = facts + drop_facts
        ui.log("llm · induction", f"the recommended test is answered — the {drop_label} "
                                 f"evidence enters the case")
        summary = sess.summary()
        if summary:
            ui.log("llm · induction", summary)

    ui.step("fwd chain · deduction", "Forward chain — the new facts")
    derived2, fired2, questions2, raised2 = engine.forward_chain(facts2, rules, emit=chain_emit)
    ui.log("fwd chain · deduction", f"fixpoint: {len(derived2)} derived facts (was {len(derived)})")

    ui.step("constraint solver · deduction", "Constraint layer — re-applied")
    survivors2, pruned2 = engine.apply_constraints(
        active, facts2 + derived2, constraints,
        emit=lambda e: ui.log("constraint solver · deduction",
                              fmt_eliminate(e) if e["op"] == "eliminate"
                              else fmt_support(e)))

    ui.step("bwd chain · deduction", "Backward chain — prove the claims")
    verdict2 = engine.combine(survivors2, facts2 + derived2, questions2, emit=combine_emit)

    ui.step("verdict", "Verdict — with the recommended test's evidence")
    v2 = verdict2["ranking"][0] if verdict2["ranking"] else None
    if v2:
        ui.log("verdict", f"{v2['id']} — {v2['statement']}  (score {v2['score']:.4f})")
        extras = [f"{k}: {v2[k]}" for k in ("killer", "horse_fate") if v2.get(k)]
        prefix = " · ".join(extras)
        ui.log("verdict", f"{prefix + ' · ' if prefix else ''}"
                          f"confidence: {engine.confidence_note(v2, questions2)}")
    ui.log("verdict", "the case is closed — and every step above replays deterministically "
                      f"(./facty run {case.name} --add-facts {drop} --json)")

    ui.step("trace", "The red yarn — final trace")
    render_trace(ui, "final", facts2, derived2, fired2, pruned2,
                 verdict2["ranking"], v2)
    print()
    return 0


# ── Subcommands (the control plane) ──────────────────────────────────

def cmd_run(args):
    case = resolve_case(args.case)
    add = Path(args.add_facts) if args.add_facts else None
    r = engine.run_case(case, add_facts=add)
    if args.json:
        print(json.dumps(r, indent=2, sort_keys=True))
    else:
        print(render_report(r))
    return 0


def cmd_cases(args):
    rows = []
    for case in list_cases():
        rules = engine.load_array(case / "pack" / "rules.json", "rule.schema.json")
        hyps = engine.load_array(case / "pack" / "hypotheses.json", "hypothesis.schema.json")
        cons = engine.load_array(case / "pack" / "constraints.json", "constraint.schema.json")
        drop = drop_file(case)
        n_ev = len(list((case / "evidence").iterdir()))
        rows.append([case.name, case_type(case), str(len(rules)), str(len(hyps)),
                     str(len(cons)), drop.name if drop else "—", str(n_ev)])
    if args.json:
        keys = ["case", "type", "rules", "hypotheses", "constraints", "drop", "evidence"]
        print(json.dumps([dict(zip(keys, r)) for r in rows], indent=2))
        return 0
    print(table(["CASE", "TYPE", "RULES", "HYPS", "CONSTR", "TEST EVIDENCE", "EVIDENCE"], rows))
    return 0


def cmd_selftest(args):
    return engine.cmd_selftest(args)


def cmd_test(args):
    rc = engine.cmd_selftest(args)
    if rc:
        return rc
    for script in ("test_retry.py", "test_tui.py", "test_cache.py",
                   "test_auth.py", "test_explain.py", "test_label.py",
                   "test_session.py"):
        r = subprocess.run([sys.executable, str(ENGINE_DIR / script)])
        if r.returncode:
            return r.returncode
    return 0


def cmd_sense(args):
    global DEBUG
    DEBUG = args.debug or os.environ.get("FACTY_DEBUG") == "1"
    case = resolve_case(args.case)
    ui = UI(auto=True, quiet=getattr(args, "json", False))
    result = sense_one(ui, case, args.op)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_explain(args):
    """Out-of-band LLM commentary on a solved case (presentation only —
    the verdict is deterministic and never depends on this call)."""
    case = resolve_case(args.case)
    add = Path(args.add_facts) if args.add_facts else None
    r = engine.run_case(case, add_facts=add)
    entities = engine.load_validated(case / "entities.json", "entities.schema.json")
    ui = UI(auto=True)
    text = explain(ui, case, r, entities, args.target)
    if text:
        print(text)
    return 0


def cmd_walkthrough(args):
    global DEBUG
    DEBUG = args.debug or os.environ.get("FACTY_DEBUG") == "1"
    case = resolve_case(args.case)
    return walkthrough(case, auto=args.auto)


def cmd_emit(args):
    emit_mod.main()
    return 0


def cmd_tui(args):
    if not sys.stdout.isatty():
        print("facty: the workbench is a full-screen TUI — it needs a terminal.", file=sys.stderr)
        print("       the control plane works anywhere: "
              "./facty cases · run <case> · selftest · walkthrough <case>", file=sys.stderr)
        return 1
    case = resolve_case(args.case) if args.case else None
    try:
        import tui
    except ImportError:
        print("facty: the workbench needs Textual (latest):", file=sys.stderr)
        print("       make deps                 # uv venv + uv pip install -r requirements.txt",
              file=sys.stderr)
        print("       or: uv pip install -U textual", file=sys.stderr)
        print("       the control plane works without it: "
              "./facty cases · ./facty run <case> · ./facty selftest", file=sys.stderr)
        return 1
    return tui.run(case, auto=getattr(args, "auto", False))


def cmd_completion(args):
    print(COMPLETIONS[args.shell])
    return 0


def cmd_version(args):
    print(f"facty {engine.__version__}")
    return 0


def cmd_doctor(args):
    """`facty doctor` — the self-check: is everything where it should
    be? (python, textual, env, the loaded workbench's keys, the response
    cache per case, any running workbench processes)."""
    print("facty doctor — is everything where it should be?")
    print(f"  python:     {sys.version.split()[0]} ({sys.executable})")
    print(f"  engine:     {ENGINE_DIR}")
    try:
        import textual
        print(f"  textual:    {textual.__version__} (the workbench layer)")
    except ImportError:
        print("  textual:    NOT INSTALLED — the workbench needs it (`make deps`)")
    for var in ("TERM", "NO_COLOR", "FACTY_SENSE", "FACTY_CACHE_DIR",
                "FACTY_PROVIDER", "FACTY_MODEL", "FACTY_THINKING",
                "GONDOLIN_PI", "PI_SNAPSHOT"):
        print(f"  {var.lower()}:  {os.environ.get(var) or '(unset)'}")
    gondolin_dir = ENGINE_DIR.parent / "gondolin"
    snap = gondolin_dir / "snapshots" / "pi-sandbox.qcow2"
    if (gondolin_dir / "gondolin-pi.sh").exists():
        state = ("snapshot built" if snap.exists()
                 else "snapshot missing — `make vm-image`")
        print(f"  gondolin:   {gondolin_dir.name}/ (vendored image config — {state})")
    else:
        print("  gondolin:   not vendored in this repo")
    try:
        import tui
        keys = sorted({(b.key if hasattr(b, "key") else b[0])
                       for b in tui.CaseScreen.BINDINGS})
        print(f"  workbench:  loaded — keys: {', '.join(keys)}")
    except ImportError:
        print("  workbench:  not importable (no textual)")
    for case in list_cases():
        ready, total = cache_state(case)
        state = "offline-ready" if ready == total else "run live once to populate"
        print(f"  cache:      {case.name}: {ready}/{total} steps ({state})")
    r = subprocess.run(["pgrep", "-af", "engine/cli.py"], capture_output=True, text=True)
    lines = []
    for l in r.stdout.splitlines():
        if not l.strip():
            continue
        try:
            pid = int(l.split()[0])
        except ValueError:
            continue
        if pid != os.getpid():  # not this doctor process
            lines.append(l.strip()[:100])
    print(f"  processes:  {len(lines)} other workbench process(es) running")
    for line in lines:
        print(f"              {line}")
    return 0


# ── Shell completion ─────────────────────────────────────────────────

COMPLETIONS = {
    "bash": """\
# bash completion for facty — source it:  . <(./facty completion bash)
_facty() {
    local cur prev
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    local commands="run cases selftest test sense walkthrough tui emit completion version"
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=($(compgen -W "$commands" -- "$cur"))
        return 0
    fi
    if [ "$prev" = "--op" ]; then
        COMPREPLY=($(compgen -W "classify entities facts drop label parser" -- "$cur"))
        return 0
    fi
    case "$prev" in
        run|walkthrough|tui|sense)
            local cases
            cases=$(ls engine/cases 2>/dev/null)
            COMPREPLY=($(compgen -W "$cases" -- "$cur"))
            return 0
            ;;
        completion)
            COMPREPLY=($(compgen -W "bash zsh fish" -- "$cur"))
            return 0
            ;;
    esac
    case "$cur" in
        --*)
            COMPREPLY=($(compgen -W "--json --add-facts --auto --debug --op" -- "$cur"))
            return 0
            ;;
    esac
}
complete -F _facty facty
""",
    "zsh": """\
#compdef facty
# zsh completion for facty — drop in $fpath as _facty
_facty() {
    local -a commands
    commands=(
        'run:run a case end-to-end'
        'cases:list the demo cases'
        'selftest:acceptance test — every case, asserted'
        'test:all tests (selftest + retry loop + the TUI, headless)'
        'sense:one sensing op, standalone (LLM, streamed)'
        'walkthrough:interactive step-through (terminal UI)'
        'tui:the Textual workbench (the primary interface)'
        'emit:codegen projections'
        'completion:print a shell completion script'
        'version:print the version'
    )
    if (( CURRENT == 2 )); then
        _describe -t commands 'facty command' commands
        return
    fi
    case "$words[2]" in
        run|walkthrough|tui|sense)
            local -a cases
            cases=(${(f)"$(ls engine/cases 2>/dev/null)"})
            _describe -t cases 'case' cases
            ;;
        sense)
            if [[ "$prev" == "--op" ]]; then
                _values 'op' classify entities facts drop label parser
            fi
            ;;
        completion)
            _values 'shell' bash zsh fish
            ;;
    esac
}
_facty "$@"
""",
    "fish": """\
# fish completion for facty — drop in ~/.config/fish/completions/facty.fish
complete -c facty -f -a 'run cases selftest test sense walkthrough tui emit completion version'
complete -c facty -f -n '__fish_seen_subcommand_from run walkthrough tui sense' -a '(ls engine/cases 2>/dev/null)' -d 'case'
complete -c facty -f -n '__fish_seen_subcommand_from sense' -l op -a 'classify entities facts drop label parser'
complete -c facty -f -n '__fish_seen_subcommand_from run' -l add-facts -d 'phase-2 facts drop'
complete -c facty -f -n '__fish_seen_subcommand_from run cases' -l json -d 'machine-readable output'
complete -c facty -f -n '__fish_seen_subcommand_from walkthrough tui' -l auto -d 'no prompting'
""",
}


# ── CLI ──────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="facty",
        description="Facty — the detective DSS. Bare `facty` opens the Textual "
                    "workbench (the primary interface); the subcommands are the "
                    "scriptable control plane.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"facty {engine.__version__}")
    sub = ap.add_subparsers(dest="command", metavar="command")

    p = sub.add_parser("run", help="run a case end-to-end (phase 1, or phase 2 with --add-facts)")
    p.add_argument("case", help="case name, unique slug (e.g. phantom-invoice), or path")
    p.add_argument("--add-facts", metavar="FILE",
                   help="phase-2 facts drop to apply (e.g. facts-trail.json)")
    p.add_argument("--json", action="store_true", help="machine-readable verdict + trace")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("cases", help="list the demo cases (type · pack · phase-2 drop)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_cases)

    p = sub.add_parser("selftest", help="acceptance test — every case, asserted")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("test", help="all tests: selftest + sensing retry loop + the TUI (headless)")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("sense", help="run one sensing op, standalone (the LLM half, streamed; "
                                    "the classifier/parser sensors for classify.json cases)")
    p.add_argument("case", help="case name, unique slug, or path")
    p.add_argument("--op", required=True,
                   choices=["classify", "entities", "facts", "drop", "label", "parser"],
                   help="the sensing operation")
    p.add_argument("--json", action="store_true",
                   help="machine-readable output only (logs suppressed)")
    p.add_argument("--debug", action="store_true",
                   help="debug mode: loud failures (no fallback), prompt path + pi command")
    p.set_defaults(func=cmd_sense)

    p = sub.add_parser("explain", help="out-of-band LLM commentary: explain a case's "
                                       "result in plain language (never the verdict path)")
    p.add_argument("case", help="case slug (e.g. silver-blaze)")
    p.add_argument("--target", choices=("entities", "ranking", "verdict"),
                   default="verdict", help="what to explain (default: verdict)")
    p.add_argument("--add-facts", help="a phase-2 facts drop (facts-<drop>.json)")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("walkthrough", help="interactive step-through of a case (terminal UI)")
    p.add_argument("case", help="case name, unique slug, or path")
    p.add_argument("--auto", action="store_true", help="run all steps without prompting")
    p.add_argument("--debug", action="store_true", help="debug mode: loud failures")
    p.set_defaults(func=cmd_walkthrough)

    p = sub.add_parser("tui", help="the Textual workbench (the primary interface; needs `make deps`)")
    p.add_argument("case", nargs="?", help="open this case directly (default: the case picker)")
    p.add_argument("--auto", action="store_true", help="run phase 1 on mount")
    p.set_defaults(func=cmd_tui)

    p = sub.add_parser("emit", help="codegen projections (TS types + Datalog per case)")
    p.set_defaults(func=cmd_emit)

    p = sub.add_parser("completion", help="print a shell completion script")
    p.add_argument("shell", choices=["bash", "zsh", "fish"])
    p.set_defaults(func=cmd_completion)

    p = sub.add_parser("version", help="print the version")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("doctor", help="self-check: python, textual, env, cache, processes")
    p.set_defaults(func=cmd_doctor)

    args = ap.parse_args(argv)
    try:
        if args.command is None:
            # bare `facty` → the primary interface: the Textual workbench
            return cmd_tui(argparse.Namespace(case=None, auto=False))
        return args.func(args)
    finally:
        # quitting (q / ctrl+c / ctrl+q) leaves no LLM/auth subprocess behind
        procs.kill_all()


if __name__ == "__main__":
    raise SystemExit(main())
