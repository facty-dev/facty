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
import shutil
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
import strom           # noqa: E402  (the Strom decision tier — stdlib client)
import dotenv          # noqa: E402  (the dotenv setup — machine-local secrets)
import procs           # noqa: E402  (subprocess registry — no dangling processes)
import pack            # noqa: E402  (the Pack Studio library — packs/<slug>/)

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
    # the Pack Studio (the authoring half — packs/<slug>/)
    "pack · list": "\033[36m",       # cyan
    "pack · validate": "\033[35m",   # magenta
    "pack · test": "\033[36m",       # cyan
    # the Pack Studio LLM ops (the authoring pair programmer — induction only)
    "pack · draft-rules": "\033[36m",       # cyan
    "pack · suggest-labels": "\033[36m",    # cyan
    "pack · draft-hypotheses": "\033[36m",  # cyan
    "pack · draft-questions": "\033[36m",   # cyan
    "pack · review": "\033[96m",            # bright cyan (prose)
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
  ./facty sense alert-flood --op label     the label sensor (classifier bulk + Strom adjudication)
  ./facty sense alert-flood --op parser    generate the case's extract parser (LLM, judged)
  ./facty sense alert-flood --op decide    draft the Strom decision questions (LLM, judged)
  ./facty sense alert-flood --op facts --offline   offline mode (cache replay + local tier only)
  ./facty pack list                   the packs under packs/ (artifact counts)
  ./facty pack validate triage-alert-flood   validate a pack (schema + cross-artifact)
  ./facty pack test triage-alert-flood --facts packs/triage-alert-flood/tests/facts-initial.json
  ./facty pack test triage-alert-flood --tests packs/triage-alert-flood/tests
  ./facty pack test triage-alert-flood --facts <file> --json    machine-readable verdict + trace + gaps
  ./facty pack draft-rules triage-alert-flood --domain "invoice fraud: duplicates, round amounts"
  ./facty pack draft-rules triage-alert-flood --domain "..." --write    accept the staged draft
  ./facty pack suggest-labels triage-alert-flood --evidence packs/triage-alert-flood/evidence/alerts.csv
  ./facty pack draft-hypotheses triage-alert-flood --domain "invoice fraud"
  ./facty pack draft-questions triage-alert-flood    draft the Strom decision questions (LLM, judged)
  ./facty pack review triage-alert-flood              advisory gap review (prose, never written)
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


def sense_label(ui, case, files, on_response=None, mode=None, offline=None):
    """The label sensor: evidence rows → labeled facts + aggregates. The
    local classifier (tier 1, CPU-only) scores the bulk; the Strom
    decision tier (tier 2) adjudicates the gated rows when the backend
    is 'hybrid'/'strom' and a key is set. The same contract as
    sense_extract: live runs the models and caches the facts;
    FACTY_SENSE=cache replays the cache (never calls a model);
    fallbacks: cache → the recorded facts (the classifier facts already
    in facts.json, filtered by source). Offline mode (--offline /
    FACTY_OFFLINE=1) runs the local tier only."""
    mode = mode or os.environ.get("FACTY_SENSE", "live")
    if offline is None:
        offline = os.environ.get("FACTY_OFFLINE") == "1"
    cfg = label.load_config(case)
    backend = cfg.get("backend", "hybrid")
    lbl = f"label the {Path(cfg['file']).stem} pile"
    cache_file = _cache_file(case.name, lbl, f"facts.schema.json:{backend}",
                             files=files)
    recorded = _recorded_label_facts(case, cfg)
    tag = "classifier · induction"
    dtag = "decider · induction"
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
        if backend == "strom":
            ui.log(dtag, f"{lbl} — the decision tier (Strom "
                         f"{strom.DEFAULT_MODEL}: a hosted decision model, "
                         "calibrated probabilities, EU-hosted; no LLM tokens)")
        elif backend == "hybrid":
            ui.log(tag, f"{lbl} — tier 1: the local classifier (bulk, "
                        "no LLM tokens)")
            ui.log(tag, f"scoring the pile with "
                        f"{label.short_model(cfg['model'])} "
                        f"({cfg['precision']}, CPU-only), threshold "
                        f"{cfg['threshold']}")
            ui.log(dtag, "tier 2: Strom adjudicates the gated rows "
                         "(calibrated probabilities)")
        else:
            ui.log(tag, f"{lbl} — the label sensor (a small local "
                        "classifier, no LLM tokens)")
            ui.log(tag, f"scoring the pile with "
                        f"{label.short_model(cfg['model'])} "
                        f"({cfg['precision']}, CPU-only), threshold "
                        f"{cfg['threshold']}")
        if offline:
            ui.log("offline", "offline mode — the decider tier is skipped")
        usage = {}
        try:
            facts, src_tag = label.run_sensor(case, cfg, offline=offline,
                                              usage=usage)
            source = "live"
            note = _usage_note(usage)
            if src_tag == "classifier+decider":
                ui.log(dtag, "tier 2 done — the gated rows are adjudicated "
                             f"(threshold {cfg['threshold']}, calibrated"
                             + note + ")")
            elif src_tag == "decider":
                ui.log(dtag, "every row scored by the decision tier" + note)
            elif src_tag.startswith("classifier+decider"):
                ui.log(dtag, src_tag.split("(", 1)[1].rstrip(")"))
            elif src_tag.startswith("classifier ("):
                ui.log(dtag, f"decider tier: {src_tag.split('(', 1)[1].rstrip(')')}")
            elif src_tag != "classifier":
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


def _usage_note(usage):
    """The decider tier's API usage as a log suffix (empty when the
    decider tier did not run). Strom's prompt cache shows up as the
    cached share — replays come back faster; billed tokens are the
    payload size either way."""
    if not usage or not usage.get("calls"):
        return ""
    total = usage.get("input_tokens", 0)
    cached = usage.get("cached_input_tokens", 0)
    pct = f", {round(100 * cached / total)}% cached" if total else ""
    return (f"; {usage['calls']} calls, {total:,} input tokens{pct}, "
            f"${usage.get('cost', 0.0):.4f}")


def sense_decide(ui, case, files, stream=None, on_response=None, mode=None):
    """The decision-question op: the LLM drafts sensor/decisions.json (the
    Strom question set for the case), judged by the decision-question
    judge in a capped correction loop (1 initial + 2 revisions) whose dry
    run calls the API on a row sample; the file is written for commit.
    Cached like the sensing calls."""
    mode = mode or os.environ.get("FACTY_SENSE", "live")
    cfg = label.load_config(case)
    lbl = "draft the decision questions"
    cache_file = _cache_file(case.name, lbl, files=files)
    tag = "llm · induction"
    if mode == "cache":
        if cache_file.exists():
            raw = json.loads(cache_file.read_text())["response"]
            ui.log(tag, f"{lbl} — response cache hit, no LLM call "
                        f"({cache_file.name})")
            return _write_decisions_and_report(ui, case, raw)
        raise SystemExit("facty: no cached decision questions — the decide "
                         "op drafts a new artifact, run it live")
    ui.log(tag, f"{lbl} — calling Mistral Large 4 (mistral-subscription), "
                "streaming …")
    ui.log("decider · induction",
           f"the judge dry-runs the drafted questions against Strom "
           f"({strom.DEFAULT_MODEL}) on a row sample")
    try:
        client = strom.from_env()
        doc = label.generate_questions(case, cfg, stream=stream, client=client)
        raw = json.dumps(doc, indent=2)
    except Exception as exc:
        ui.log(tag, f"decision-question drafting failed ({exc})")
        if DEBUG:
            raise SystemExit(2)
        raise SystemExit("facty: decision-question drafting failed — the "
                         "judge dry-runs against the Strom API: set "
                         f"{strom.ENV_KEY} and retry")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        "case": case.name, "op": lbl, "model": sensing.MODEL,
        "response": raw, "cached_at": time.time()}, indent=2))
    ui.log(tag, f"response cached ({cache_file.name}) — FACTY_SENSE=cache "
                "replays it without the LLM")
    if on_response is not None:
        on_response(raw, "live")
    return _write_decisions_and_report(ui, case, raw)


def _write_decisions_and_report(ui, case, raw):
    doc = sensing.parse_and_validate(raw, label.DECISIONS_DOC_SCHEMA)
    label.write_decisions(case, doc)
    errs = label.check_decisions(doc, label.load_config(case))
    verdict = ("judge ✓" if not errs
               else "judge flagged: " + "; ".join(errs[:3]))
    ui.log("decider · induction", "decision questions written "
                                  "(sensor/decisions.json) — " + verdict)
    return doc


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
        if cfg.get("backend", "strom") != "local":
            ops["decide"] = ("draft the decision questions", None,
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
              on_response=None, mode=None, runner=None, engine_context=None,
              offline=None):
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
    if offline is None:
        offline = os.environ.get("FACTY_OFFLINE") == "1"
    if offline and mode != "cache" and op != "label":
        # offline = no network, no LLM: the extract/parser/decide ops replay
        # the response cache; the label op runs its local tier live (below)
        ui.log("offline", "offline mode — LLM ops replay the response cache; "
                          "the label sensor runs the local tier only")
        mode = "cache"
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
        return sense_label(ui, case, files, on_response=on_response, mode=mode,
                           offline=offline)
    if op == "parser":
        return sense_parser(ui, case, files, stream=stream,
                            on_response=on_response, mode=mode)
    if op == "decide":
        return sense_decide(ui, case, files, stream=stream,
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
            backend = label.load_config(case).get("backend", "hybrid")
            stage = {
                "local": "The label sensor — the evidence pile, labeled "
                         "(small local classifier, CPU-only)",
                "strom": "The decision tier — the evidence pile, labeled "
                         "(Strom decision model, calibrated probabilities)",
                "hybrid": "The label sensor — the pile, labeled (tier 1: the "
                          "local classifier; tier 2: Strom adjudicates the "
                          "gated rows)",
            }[backend]
            ui.step("classifier · induction", stage)
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


# ── Pack Studio (the authoring half — packs/<slug>/) ─────────────────

def cmd_pack_list(args):
    """`pack list` — the packs under packs/ with artifact counts (REQ-008)."""
    packs = pack.list_packs()
    if args.json:
        print(json.dumps(packs, indent=2, sort_keys=True))
        return 0
    if not packs:
        print("no packs yet — create one at packs/<slug>/ "
              "(see docs/prd/PRD-007-pack-studio.md)")
        return 0
    rows = []
    for p in packs:
        c = p["counts"]
        rows.append([p["slug"], str(c["rules"]), str(c["hypotheses"]),
                     str(c["constraints"]), str(c["tests"]),
                     "yes" if p["classify"] else "—",
                     "yes" if p["decisions"] else "—"])
    print(table(["PACK", "RULES", "HYPS", "CONSTR", "TESTS", "CLASSIFY", "DECISIONS"],
                rows))
    return 0


def cmd_pack_validate(args):
    """`pack validate <pack>` — schema + cross-artifact validation
    (REQ-001/002): exit 0 with a clean report, exit 1 naming each
    violation (file + message)."""
    try:
        pack_dir = pack.resolve_pack(args.pack)
    except pack.PackError as exc:
        print(f"facty: {exc}", file=sys.stderr)
        return 1
    report = pack.validate_pack(pack_dir)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1
    ui = UI(auto=True)
    tag = "pack · validate"
    c = report["counts"]
    ui.log(tag, f"pack: {report['pack']} — {c['rules']} rules · "
                f"{c['hypotheses']} hypotheses · {c['constraints']} constraints · "
                f"{c['tests']} tests")
    if report["ok"]:
        ui.log(tag, "valid ✓ (schema + cross-artifact checks pass)")
        return 0
    ui.log(tag, f"INVALID — {len(report['violations'])} violation(s):")
    for v in report["violations"]:
        ui.log(tag, f"  ✗ {v['file']}: {v['message']}")
    return 1


def _render_gaps(ui, gaps):
    """The gap analysis (REQ-004) as run-log lines."""
    tag = "pack · test"
    ui.log(tag, "gap analysis:")
    if gaps["dead_rules"]:
        for r in gaps["dead_rules"]:
            ui.log(tag, f"  dead rule (never fires): {r['id']}")
    else:
        ui.log(tag, "  dead rules: (none)")
    if gaps["unraised_hypotheses"]:
        for h in gaps["unraised_hypotheses"]:
            ui.log(tag, f"  unraised hypothesis (no rule raises it): {h['id']} — "
                        f"{h['statement'][:80]}")
    else:
        ui.log(tag, "  unraised hypotheses: (none)")
    if gaps["pruned_hypotheses"]:
        for p in gaps["pruned_hypotheses"]:
            ui.log(tag, f"  pruned: {p['id']} — {p['constraint']}: {p['reason']}")
    else:
        ui.log(tag, "  pruned hypotheses: (none)")
    if gaps["unanswered_questions"]:
        for q in gaps["unanswered_questions"]:
            ui.log(tag, f"  unanswered question: {q['id']} [{q['slot']}] — {q['text'][:80]}")
    else:
        ui.log(tag, "  unanswered questions: (none)")


def cmd_pack_test(args):
    """`pack test <pack> --facts <file>` (REQ-003/004/005) — run the
    pack on a fact set: verdict + trace + gap analysis. Deterministic.
    `pack test <pack> --tests <dir>` (REQ-006) — run every scenario;
    exit 1 and name the failing scenario on mismatch."""
    try:
        pack_dir = pack.resolve_pack(args.pack)
    except pack.PackError as exc:
        print(f"facty: {exc}", file=sys.stderr)
        return 1
    if not args.facts and not args.tests:
        print("facty: pack test needs --facts <file> or --tests <dir>",
              file=sys.stderr)
        return 1
    ui = UI(auto=True, quiet=args.json)
    tag = "pack · test"

    if args.facts:
        try:
            facts = pack.load_facts_file(args.facts)
        except pack.PackError as exc:
            print(f"facty: {exc}", file=sys.stderr)
            return 1
        result = pack.run_pack_test(pack_dir, facts)
        if args.json:
            print(json.dumps({"verdict": result["verdict"],
                              "trace": result["trace"],
                              "gaps": result["gaps"]},
                             indent=2, sort_keys=True))
            return 0
        ui.log(tag, f"pack: {result['pack']} · {len(facts)} facts · "
                    "deterministic run (no LLM)")
        print(render_report(result["trace"]))
        print()
        _render_gaps(ui, result["gaps"])
        return 0

    # --tests: run every scenario
    try:
        report = pack.run_scenarios(pack_dir, args.tests)
    except pack.PackError as exc:
        print(f"facty: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1
    ui.log(tag, f"scenarios: {report['found']} in {report['dir']}")
    for s in report["scenarios"]:
        status = "✓ pass" if s["ok"] else "✗ FAIL"
        verdict = s["verdict"] or "(no verdict)"
        ui.log(tag, f"  {status} {s['name']} — verdict {verdict}")
        if not s["ok"]:
            for m in s["mismatches"]:
                ui.log(tag, f"    mismatch: {m}")
    if not report["ok"]:
        failing = [s["name"] for s in report["scenarios"] if not s["ok"]]
        ui.log(tag, f"FAILED: {', '.join(failing)}")
        return 1
    ui.log(tag, f"all {report['found']} scenario(s) pass ✓")
    return 0


# ── Pack Studio — the LLM authoring ops (REQ-010…016) ────────────────
#
# The one-shot draft ops — the "pair programmer" half of the MVP: the
# LLM drafts an artifact (schema-guided, judged, streamed), the draft
# is staged beside its target, and the HUMAN accepts it (--write). Like
# the sensing ops they are induction only — never in the verdict path
# (ADR-0003 §1). The prompts carry the author's domain description and
# the pack's ontology (its hypotheses + term vocabulary) — never the
# engine's conclusions (the anti-bias rule holds for authoring too; the
# review op is the exception: it is advisory commentary ABOUT the pack,
# fed the gap analysis because finding the gaps is its point).
#
# The plumbing (REQ-016): streamed output, the response cache
# (.agentic/cache/sensing/, keyed by the pack + the prompt), replay
# without the LLM via FACTY_SENSE=cache / --offline, and one pi session
# per `pack` command (main() wraps the command in
# sensing.session_scope() — the correction turns share the session, so
# the provider's prompt cache hits across them). Fallback: none — when
# the LLM is unreachable or the judge rejects, the op logs the failure
# and exits with a clear error (the draft is the point; the human
# re-runs when the LLM is back).

def _pack_llm_mode(ui, offline):
    """The pack LLM ops' mode (REQ-016) + the offline log line:
    --offline / FACTY_OFFLINE=1 forces the response-cache replay (no
    LLM call); FACTY_SENSE=cache too; live (the default) calls the LLM
    and caches the raw response."""
    if offline or os.environ.get("FACTY_OFFLINE") == "1":
        ui.log("offline", "offline mode — the LLM op replays the response "
                          "cache, no LLM call")
        return "cache"
    return os.environ.get("FACTY_SENSE", "live")


def _llm_stream():
    """The live LLM stream writer (the sense ops' `  ▸ line` output —
    the LLM's response streams live, like `sense`)."""
    arrow = f"{TAGS['llm']}▸{NC} " if USE_COLOR else "▸ "

    def stream(line):
        sys.stdout.write(f"  {arrow}{line}\n")
        sys.stdout.flush()

    return stream


def _cache_summary(ui, tag):
    """The run's provider-cache summary (one line at the end of a pack
    LLM op — like the walkthrough's sensing summary; empty when the run
    made fewer than 2 LLM calls, e.g. a cache replay)."""
    sess = sensing.current_session()
    if sess is None:
        return
    summary = sess.summary()
    if summary:
        ui.log(tag, summary)


def _load_pack_array_tolerant(pack_dir, name, schema_name):
    """Load a pack artifact tolerantly: a missing or unparseable
    artifact reads as [] (a pack mid-authoring still gets its draft
    op). engine.load_array raises SystemExit on a schema violation,
    which `except Exception` would not catch — hence the explicit
    tuple."""
    path = Path(pack_dir) / "pack" / name
    try:
        return engine.load_array(path, schema_name)
    except (SystemExit, ValueError, OSError):
        return []


def _pack_terms(pack_dir):
    """The pack's term vocabulary — (predicates, subjects): every
    predicate and subject the pack's rules, constraints, and
    hypotheses speak (the same idea as pack_vocabulary for the facts
    task, tolerant so a pack mid-authoring still drafts)."""
    preds, subs = set(), set()
    for name, schema in (("rules.json", "rule.schema.json"),
                         ("constraints.json", "constraint.schema.json"),
                         ("hypotheses.json", "hypothesis.schema.json")):
        for item in _load_pack_array_tolerant(pack_dir, name, schema):
            preds.update(_terms(item, "predicate"))
            subs.update(_terms(item, "subject"))
    return sorted(preds), sorted(subs)


def _draft_summary(doc, noun):
    """One line: what the draft holds (the ids for an array; the label
    set + threshold for a classify config; the question names for a
    decisions doc)."""
    if isinstance(doc, list):
        ids = ", ".join(str(i.get("id", "?")) for i in doc)
        return f"{len(doc)} {noun}: {ids}"
    if isinstance(doc, dict) and "labels" in doc:
        return (f"the label-sensor config — {len(doc['labels'])} labels "
                f"({', '.join(str(l) for l in doc['labels'])}), threshold "
                f"{doc.get('threshold', '?')}, file {doc.get('file', '?')}")
    if isinstance(doc, dict) and "questions" in doc:
        return (f"the decision questions — {len(doc['questions'])} "
                f"questions ({', '.join(doc['questions'])})")
    return sensing.describe(doc, noun)


def _stage_pack_draft(ui, tag, pack_dir, rel_target, doc, write, noun):
    """Stage the draft beside its target and print the summary (REQ-015):
    the default stages <artifact>.draft.json and leaves the target
    untouched; --write accepts (the draft replaces the target, the
    staged file is consumed). The human always accepts — the LLM never
    writes the pack. Returns the result dict."""
    staged = pack.stage_draft(pack_dir, rel_target, doc)
    target = Path(pack_dir) / rel_target
    accepted = False
    ui.log(tag, f"judge layer accepted ✓ ({_draft_summary(doc, noun)})")
    if write:
        pack.accept_draft(pack_dir, rel_target)
        accepted = True
        ui.log(tag, f"draft accepted — {target} (--write; the staged draft "
                    "is consumed)")
    else:
        ui.log(tag, f"draft staged — {staged}")
        ui.log(tag, f"target untouched — {target}")
        ui.log(tag, "accept with --write (the human always accepts; the LLM "
                    "never writes the pack)")
    return {"doc": doc, "staged": staged, "target": target,
            "accepted": accepted}


def _pack_extract_draft(ui, tag, pack_dir, op_label, rel_target, schema,
                        task, judge, write, runner=None, stream=None,
                        offline=False, noun="rules", cache_files=None,
                        cache_context=None):
    """The shared extract-structured draft op (REQ-010/011/012 + the
    REQ-015/016 plumbing): the LLM drafts the artifact (schema-guided,
    judged, streamed), the draft is staged beside its target, and
    --write accepts it. Returns the result dict, or None on failure (a
    clear error is logged — no fallback: the draft is the point)."""
    mode = _pack_llm_mode(ui, offline)
    cache_file = _cache_file(f"pack-{pack_dir.name}", op_label,
                             files=cache_files, task=None if cache_files else task,
                             context=cache_context)
    if mode == "cache":
        if not cache_file.exists():
            ui.log(tag, f"{op_label} — no cached response ({cache_file.name}); "
                        "run live to populate the cache")
            return None
        raw = json.loads(cache_file.read_text())["response"]
        ui.log(tag, f"{op_label} — response cache hit, no LLM call "
                    f"({cache_file.name})")
        try:
            doc = sensing.parse_and_validate(raw, schema)
        except ValueError as exc:
            ui.log(tag, f"{op_label} — the cached response failed "
                        f"validation ({exc})")
            return None
        errs = judge(doc) if judge else []
        if errs:
            ui.log(tag, f"{op_label} — the cached response failed the judge: "
                        + "; ".join(errs[:3]))
            return None
    else:
        ui.log(tag, f"{op_label} — calling Mistral Large 4 "
                    f"({sensing.PROVIDER}), streaming …")
        holder = []
        try:
            doc = sensing.extract_structured(
                schema, task, stream=stream,
                label=op_label.replace(" ", "-"), judge=judge,
                note=lambda m: ui.log(tag, m), debug=DEBUG,
                on_response=holder.append, runner=runner)
        except Exception as exc:  # unreachable LLM (fail fast), or the judge exhausted its turns
            ui.log(tag, f"{op_label} — LLM call failed ({exc})")
            if DEBUG:
                raise SystemExit(2)
            return None
        raw = holder[0] if holder else None
        if raw is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({
                "pack": pack_dir.name, "op": op_label,
                "model": sensing.MODEL, "response": raw,
                "cached_at": time.time()}, indent=2))
            ui.log(tag, f"response cached ({cache_file.name}) — "
                        "FACTY_SENSE=cache replays it without the LLM")
    result = _stage_pack_draft(ui, tag, pack_dir, rel_target, doc, write, noun)
    _cache_summary(ui, tag)
    return result


def _draft_rules_task(pack_dir, domain):
    """The draft-rules prompt (REQ-010): the author's plain-language
    domain + the pack's existing hypotheses (the valid raise targets)
    + the pack's term vocabulary. The rule schema rides with the prompt
    (extract_structured appends it)."""
    pack_dir = Path(pack_dir)
    hyps = _load_pack_array_tolerant(pack_dir, "hypotheses.json",
                                     "hypothesis.schema.json")
    if hyps:
        hyp_block = ("The pack's existing hypotheses — rules may raise "
                     "THESE ids (verbatim; do not invent new hypothesis ids):\n"
                     + "\n".join(f"- {h.get('id')}: {h.get('statement', '')}"
                                 for h in hyps))
    else:
        hyp_block = ("The pack has no hypotheses yet — rules may derive "
                     "facts and open questions, but cannot raise "
                     "hypotheses (run `pack draft-hypotheses` first).")
    preds, subs = _pack_terms(pack_dir)
    return f"""Draft the forward-chaining rules for this knowledge pack, as a
JSON array of rule objects.

The domain (plain language, from the pack's author):
{domain}

The pack's slug (set every rule's "pack" field to exactly this): {pack_dir.name}

{hyp_block}

The pack's term vocabulary — the predicates and subjects its rules,
constraints, and hypotheses already speak. Prefer these terms in
conditions and derived facts so the rules chain with the rest of the
pack; invent new terms only when the domain demands it:
subjects: {", ".join(subs) if subs else "(none)"}
predicates: {", ".join(preds) if preds else "(none)"}

The engine's contract:
- "when": conditions over facts — subject / predicate / value triples
  (literals match exactly; every condition must hold).
- "then": actions — derive a fact (a full fact object: id, type
  "derived", subject, predicate, value, confidence, source
  "rule:<rule id>"), raise hypotheses (existing ids only), open a
  question (id, text, slot, mandatory, priority, discriminates).
- every rule: a unique id (R1, R2, …), "version": "1", and the "pack"
  field set to the slug above.

Draft 3-8 rules that carry the domain: what the evidence shows → what
it implies (derived facts), which hypotheses it raises, and which
question it opens when more evidence is needed. A rule that can never
fire is dead weight — every condition must be satisfiable.

Respond with ONLY the JSON array of rules."""


def pack_draft_rules(ui, pack_dir, domain, write=False, runner=None,
                     stream=None, offline=False):
    """REQ-010 — `pack draft-rules`: the LLM drafts pack/rules.json
    from a plain-language domain description (schema-guided, judged by
    the pack's cross-artifact checks, streamed); the draft is staged
    (--write accepts)."""
    return _pack_extract_draft(
        ui, "pack · draft-rules", pack_dir,
        f"draft the rules for {pack_dir.name}", "pack/rules.json",
        pack.array_schema("rule.schema.json"),
        _draft_rules_task(pack_dir, domain),
        pack.rules_judge(pack_dir), write, runner=runner, stream=stream,
        offline=offline, noun="rules")


def _suggest_labels_task(pack_dir, evidence):
    """The suggest-labels prompt (REQ-011): the sample evidence (the
    file's header + first 50 rows) + the pack-relative path. The
    classify.json schema rides with the prompt (extract_structured
    appends it). The classifier is never run — the op drafts the
    config only."""
    evidence = Path(evidence)
    if not evidence.is_file():
        raise pack.PackError(f"the evidence file does not exist: {evidence}")
    lines = evidence.read_text().splitlines()
    header = lines[0] if lines else ""
    sample = "\n".join(lines[:51])  # the header + the first 50 rows
    try:
        rel = str(evidence.resolve().relative_to(Path(pack_dir).resolve()))
    except ValueError:
        rel = str(evidence)  # outside the pack — cite it as given
    return f"""Draft the label-sensor config (classify.json) for this knowledge
pack from the sample evidence below. The sensor scores every evidence
row against the label set — one fact per row, confidence-gated.

The pack: {Path(pack_dir).name}
The evidence file (pack-relative): {rel}
Columns (the header row): {header}

Sample evidence (the header + the first 50 rows):
{sample}

The config:
- "file": the pack-relative evidence path ("{rel}")
- "textColumn": the column whose text gets classified
- "idColumn" / "sourceColumn" / "timeColumn": the identifying columns
  (omit the ones the file lacks)
- "labels": 2-4 short, mutually exclusive noun phrases — the
  classification axis (the pack's rules and hypotheses reference
  these labels)
- "template": one {{}} where the label goes (a hypothesis sentence)
- "threshold": the confidence gate, 0-1 (0.6-0.8 typical)
- "scoring": "margin" (calibrated confidences) or "entail"
- "model" / "precision" / "prep" / "backend": the sensor-ladder knobs
  (sensible defaults)

Respond with ONLY the JSON object."""


def pack_suggest_labels(ui, pack_dir, evidence, write=False, runner=None,
                        stream=None, offline=False):
    """REQ-011 — `pack suggest-labels`: the LLM drafts classify.json
    (labels, columns, threshold, template) from sample evidence
    (schema-guided, judged by the classify structural checks,
    streamed); the draft is staged (--write accepts)."""
    task = _suggest_labels_task(pack_dir, evidence)
    return _pack_extract_draft(
        ui, "pack · suggest-labels", pack_dir,
        f"suggest the labels for {pack_dir.name}", "classify.json",
        pack.CLASSIFY_SCHEMA, task, pack.classify_judge, write,
        runner=runner, stream=stream, offline=offline,
        noun="label-sensor config",
        cache_files=[Path(evidence)],
        cache_context={"file": str(Path(evidence).resolve())})


def _draft_hypotheses_task(pack_dir, domain):
    """The draft-hypotheses prompt (REQ-012): the author's
    plain-language domain + the pack's term vocabulary (the claims
    must speak it so the backward chain can prove them). The
    hypothesis schema rides with the prompt."""
    pack_dir = Path(pack_dir)
    preds, subs = _pack_terms(pack_dir)
    return f"""Draft the hypothesis space for this knowledge pack, as a JSON
array of hypothesis objects.

The domain (plain language, from the pack's author):
{domain}

The pack's slug: {pack_dir.name}

The pack's term vocabulary — the predicates and subjects its rules and
constraints speak. The hypotheses' claims must use these terms so the
backward chain can prove them:
subjects: {", ".join(subs) if subs else "(none)"}
predicates: {", ".join(preds) if preds else "(none)"}

Each hypothesis: a unique id (H1, H2, …), a one-sentence statement
(the explanation), "status": "open", a "prior" (0-1 — the plausibility
before evidence; the smallest term in the engine's score), and
"claims": the fact triples (subject / predicate / value) that must be
provable for the hypothesis to stand.

Draft 3-6 hypotheses covering the plausible explanations of the
domain — including the boring one (benign activity / noise / false
positives): the constraint layer needs rivals to prune.

Respond with ONLY the JSON array of hypotheses."""


def pack_draft_hypotheses(ui, pack_dir, domain, write=False, runner=None,
                          stream=None, offline=False):
    """REQ-012 — `pack draft-hypotheses`: the LLM drafts
    pack/hypotheses.json (statements, priors, claims) from a
    plain-language domain description (schema-guided, judged for
    unique ids, streamed); the draft is staged (--write accepts)."""
    return _pack_extract_draft(
        ui, "pack · draft-hypotheses", pack_dir,
        f"draft the hypotheses for {pack_dir.name}", "pack/hypotheses.json",
        pack.array_schema("hypothesis.schema.json"),
        _draft_hypotheses_task(pack_dir, domain),
        pack.hypotheses_judge(), write, runner=runner, stream=stream,
        offline=offline, noun="hypotheses")


def pack_draft_questions(ui, pack_dir, write=False, runner=None, client=None,
                         stream=None, offline=False):
    """REQ-013 — `pack draft-questions`: the LLM drafts the pack's
    Strom decision questions (sensor/decisions.json), mirroring
    `sense --op decide`: the decision-question judge checks the draft
    (schema + label coverage + a dry run against Strom on a row
    sample). The draft is staged (--write accepts). The pack needs a
    classify.json — the questions classify the label sensor's pile."""
    tag = "pack · draft-questions"
    pack_dir = Path(pack_dir)
    mode = _pack_llm_mode(ui, offline)
    op_label = f"draft the decision questions for {pack_dir.name}"
    try:
        cfg = label.load_config(pack_dir)
    except label.LabelError as exc:
        ui.log(tag, f"no label-sensor task ({exc}) — the decision questions "
                    "classify the label sensor's pile; run `pack suggest-labels` "
                    "first")
        return None
    evidence = pack_dir / cfg["file"]
    cache_file = _cache_file(f"pack-{pack_dir.name}", op_label,
                             files=[evidence],
                             context={"labels": cfg["labels"]})
    if mode == "cache":
        if not cache_file.exists():
            ui.log(tag, f"{op_label} — no cached response ({cache_file.name}); "
                        "run live to populate the cache")
            return None
        raw = json.loads(cache_file.read_text())["response"]
        ui.log(tag, f"{op_label} — response cache hit, no LLM call "
                    f"({cache_file.name})")
        try:
            doc = sensing.parse_and_validate(raw, label.DECISIONS_DOC_SCHEMA)
        except ValueError as exc:
            ui.log(tag, f"{op_label} — the cached response failed "
                        f"validation ({exc})")
            return None
        # structure + label coverage (the dry run needs the API — skipped on replay)
        errs = label.check_decisions(doc, cfg)
        if errs:
            ui.log(tag, f"{op_label} — the cached response failed the judge: "
                        + "; ".join(errs[:3]))
            return None
    else:
        ui.log(tag, f"{op_label} — calling Mistral Large 4 "
                    f"({sensing.PROVIDER}), streaming …")
        ui.log("decider · induction",
               f"the judge dry-runs the drafted questions against Strom "
               f"({strom.DEFAULT_MODEL}) on a row sample")
        try:
            if client is None:
                client = strom.from_env()
            doc = label.generate_questions(
                pack_dir, cfg, runner=runner, client=client, stream=stream,
                note=lambda m: ui.log(tag, m))
        except (label.LabelError, strom.StromError, RuntimeError,
                ValueError) as exc:
            ui.log(tag, f"{op_label} — drafting failed ({exc})")
            if DEBUG:
                raise SystemExit(2)
            return None
        raw = json.dumps(doc, indent=2)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            "pack": pack_dir.name, "op": op_label, "model": sensing.MODEL,
            "response": raw, "cached_at": time.time()}, indent=2))
        ui.log(tag, f"response cached ({cache_file.name}) — FACTY_SENSE=cache "
                    "replays it without the LLM")
    result = _stage_pack_draft(ui, tag, pack_dir, "sensor/decisions.json",
                               doc, write, "decision questions")
    _cache_summary(ui, tag)
    return result


def _pack_gap_blocks(pack_dir):
    """The gap analysis (REQ-004) over the pack's test scenarios, as
    prompt blocks — one per scenario (the deterministic engine run on
    its fact set). No scenarios → a note (the gap analysis needs a fact
    set)."""
    pack_dir = Path(pack_dir)
    tests = pack_dir / "tests"
    files = pack.scenario_files(tests) if tests.is_dir() else []
    if not files:
        return ["(no test scenarios — add tests/facts-*.json fact sets; "
                "the gap analysis needs one)"]
    blocks = []
    for path in files:
        try:
            facts = pack.load_facts_file(path)
            gaps = pack.diagnose(pack_dir, facts)
        except pack.PackError as exc:
            blocks.append(f"scenario {path.name}: unreadable — {exc}")
            continue
        lines = [f"scenario {path.name} ({len(facts)} facts):"]
        if gaps["dead_rules"]:
            lines.append("  dead rules (never fire): "
                         + ", ".join(r["id"] for r in gaps["dead_rules"]))
        else:
            lines.append("  dead rules: (none)")
        if gaps["unraised_hypotheses"]:
            lines.append("  unraised hypotheses: "
                         + ", ".join(h["id"]
                                     for h in gaps["unraised_hypotheses"]))
        else:
            lines.append("  unraised hypotheses: (none)")
        for p in gaps["pruned_hypotheses"]:
            lines.append(f"  pruned: {p['id']} — {p['constraint']}: "
                         f"{p['reason']}")
        for q in gaps["unanswered_questions"]:
            lines.append(f"  unanswered question: {q['id']} [{q['slot']}] — "
                         f"{q['text']}")
        blocks.append("\n".join(lines))
    return blocks


def _pack_review_task(pack_dir):
    """The review prompt (REQ-014): the pack's artifacts + the gap
    analysis over its test scenarios (deterministic, via pack.diagnose).
    The review is advisory commentary about the pack (like `explain` is
    about a run) — it is fed the engine's gap analysis because finding
    the gaps is the point."""
    pack_dir = Path(pack_dir)

    def dump(rel):
        path = pack_dir / rel
        if not path.exists():
            return "(absent)"
        try:
            return json.dumps(json.loads(path.read_text()), indent=2)
        except ValueError:
            return f"(unparseable: {path})"

    return f"""Review this knowledge pack for gaps — you are the pack author's
pair programmer. The pack's artifacts and the engine's gap analysis
follow. Read them, then write an advisory review in prose (markdown is
fine).

Look for:
- dead rules — never fire on the test scenarios
- unraised hypotheses — no rule ever raises them (unreachable
  explanations)
- missing constraints — rival hypotheses that should be prunable but
  are not
- unanswered questions — the test fact sets leave them open
- sensor gaps — a missing classify.json (the label sensor) or
  sensor/decisions.json (the Strom question set)
- schema smells — empty when/then blocks, priors at the extremes,
  duplicate ids

Be concrete (name the rule / hypothesis / question ids), rank the
findings most-important-first, and suggest the next authoring step for
each (which `pack` op to run). Advisory only — do not rewrite the
artifacts; the human decides.

THE PACK ({pack_dir.name}):
rules.json:
{dump("pack/rules.json")}

constraints.json:
{dump("pack/constraints.json")}

hypotheses.json:
{dump("pack/hypotheses.json")}

classify.json:
{dump("classify.json")}

sensor/decisions.json:
{dump("sensor/decisions.json")}

GAP ANALYSIS (the deterministic engine, run on each test scenario):
{chr(10).join(_pack_gap_blocks(pack_dir))}"""


def pack_review(ui, pack_dir, runner=None, stream=None, offline=False):
    """REQ-014 — `pack review`: the LLM reads the pack's artifacts +
    the gap analysis over its test scenarios and returns a prose
    review. Advisory only — the pack directory is byte-identical before
    and after (the op never writes to it). Returns the prose, or None
    on failure (a clear error is logged — no fallback)."""
    tag = "pack · review"
    pack_dir = Path(pack_dir)
    mode = _pack_llm_mode(ui, offline)
    op_label = f"review the pack {pack_dir.name}"
    task = _pack_review_task(pack_dir)
    cache_file = _cache_file(f"pack-{pack_dir.name}", op_label, task=task)
    if mode == "cache":
        if not cache_file.exists():
            ui.log(tag, f"{op_label} — no cached response ({cache_file.name}); "
                        "run live to populate the cache")
            return None
        raw = json.loads(cache_file.read_text())["response"]
        ui.log(tag, f"{op_label} — response cache hit, no LLM call "
                    f"({cache_file.name})")
    else:
        ui.log(tag, f"{op_label} — calling Mistral Large 4 "
                    f"({sensing.PROVIDER}), streaming …")
        try:
            raw = sensing.llm_text(task, stream=stream,
                                   label=op_label.replace(" ", "-"),
                                   runner=runner)
        except Exception as exc:  # unreachable LLM — fail fast, no fallback
            ui.log(tag, f"{op_label} — LLM call failed ({exc})")
            if DEBUG:
                raise SystemExit(2)
            return None
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            "pack": pack_dir.name, "op": op_label, "model": sensing.MODEL,
            "response": raw, "cached_at": time.time()}, indent=2))
        ui.log(tag, f"response cached ({cache_file.name}) — FACTY_SENSE=cache "
                    "replays it without the LLM")
    _cache_summary(ui, tag)
    return raw


def _resolve_pack_arg(args):
    """Resolve the pack arg (a slug or a path); prints the error and
    returns None when the pack does not exist (the pack cmds' style)."""
    try:
        return pack.resolve_pack(args.pack)
    except pack.PackError as exc:
        print(f"facty: {exc}", file=sys.stderr)
        return None


def _pack_draft_exit(op, result):
    """The draft ops' failure exit: the op logged the reason; this adds
    the one-line stderr error. (The draft is the point — no silent
    fallback to recorded artifacts.)"""
    if result is None:
        print(f"facty: pack {op} failed — no draft staged (the LLM call or "
              "the judge rejected; re-run when the LLM is back)",
              file=sys.stderr)
        return 1
    return None


def cmd_pack_draft_rules(args):
    """`pack draft-rules <pack> --domain "<text>" [--write]` (REQ-010)."""
    global DEBUG
    DEBUG = args.debug or os.environ.get("FACTY_DEBUG") == "1"
    pack_dir = _resolve_pack_arg(args)
    if pack_dir is None:
        return 1
    ui = UI(auto=True, quiet=args.json)
    result = pack_draft_rules(ui, pack_dir, args.domain, write=args.write,
                              stream=None if args.json else _llm_stream(),
                              offline=args.offline)
    failed = _pack_draft_exit("draft-rules", result)
    if failed:
        return failed
    if args.json:
        print(json.dumps({"pack": pack_dir.name, "op": "draft-rules",
                          "staged": str(result["staged"]),
                          "target": str(result["target"]),
                          "accepted": result["accepted"],
                          "draft": result["doc"]},
                         indent=2, sort_keys=True))
    return 0


def cmd_pack_suggest_labels(args):
    """`pack suggest-labels <pack> --evidence <file> [--write]` (REQ-011)."""
    global DEBUG
    DEBUG = args.debug or os.environ.get("FACTY_DEBUG") == "1"
    pack_dir = _resolve_pack_arg(args)
    if pack_dir is None:
        return 1
    ui = UI(auto=True, quiet=args.json)
    try:
        result = pack_suggest_labels(ui, pack_dir, args.evidence,
                                     write=args.write,
                                     stream=None if args.json else _llm_stream(),
                                     offline=args.offline)
    except pack.PackError as exc:
        print(f"facty: {exc}", file=sys.stderr)
        return 1
    failed = _pack_draft_exit("suggest-labels", result)
    if failed:
        return failed
    if args.json:
        print(json.dumps({"pack": pack_dir.name, "op": "suggest-labels",
                          "staged": str(result["staged"]),
                          "target": str(result["target"]),
                          "accepted": result["accepted"],
                          "draft": result["doc"]},
                         indent=2, sort_keys=True))
    return 0


def cmd_pack_draft_hypotheses(args):
    """`pack draft-hypotheses <pack> --domain "<text>" [--write]` (REQ-012)."""
    global DEBUG
    DEBUG = args.debug or os.environ.get("FACTY_DEBUG") == "1"
    pack_dir = _resolve_pack_arg(args)
    if pack_dir is None:
        return 1
    ui = UI(auto=True, quiet=args.json)
    result = pack_draft_hypotheses(ui, pack_dir, args.domain,
                                   write=args.write,
                                   stream=None if args.json else _llm_stream(),
                                   offline=args.offline)
    failed = _pack_draft_exit("draft-hypotheses", result)
    if failed:
        return failed
    if args.json:
        print(json.dumps({"pack": pack_dir.name, "op": "draft-hypotheses",
                          "staged": str(result["staged"]),
                          "target": str(result["target"]),
                          "accepted": result["accepted"],
                          "draft": result["doc"]},
                         indent=2, sort_keys=True))
    return 0


def cmd_pack_draft_questions(args):
    """`pack draft-questions <pack> [--write]` (REQ-013)."""
    global DEBUG
    DEBUG = args.debug or os.environ.get("FACTY_DEBUG") == "1"
    pack_dir = _resolve_pack_arg(args)
    if pack_dir is None:
        return 1
    ui = UI(auto=True, quiet=args.json)
    result = pack_draft_questions(ui, pack_dir, write=args.write,
                                  stream=None if args.json else _llm_stream(),
                                  offline=args.offline)
    failed = _pack_draft_exit("draft-questions", result)
    if failed:
        return failed
    if args.json:
        print(json.dumps({"pack": pack_dir.name, "op": "draft-questions",
                          "staged": str(result["staged"]),
                          "target": str(result["target"]),
                          "accepted": result["accepted"],
                          "draft": result["doc"]},
                         indent=2, sort_keys=True))
    return 0


def cmd_pack_review(args):
    """`pack review <pack>` (REQ-014) — advisory prose, never written."""
    global DEBUG
    DEBUG = args.debug or os.environ.get("FACTY_DEBUG") == "1"
    pack_dir = _resolve_pack_arg(args)
    if pack_dir is None:
        return 1
    ui = UI(auto=True)
    text = pack_review(ui, pack_dir, stream=_llm_stream(),
                       offline=args.offline)
    if text is None:
        print("facty: pack review failed — no review (the LLM call failed; "
              "re-run when the LLM is back)", file=sys.stderr)
        return 1
    print()
    print(text)
    return 0


def cmd_selftest(args):
    return engine.cmd_selftest(args)


def cmd_test(args):
    rc = engine.cmd_selftest(args)
    if rc:
        return rc
    for script in ("test_retry.py", "test_tui.py", "test_cache.py",
                   "test_auth.py", "test_explain.py", "test_label.py",
                   "test_strom.py", "test_dotenv.py", "test_session.py",
                   "test_pack.py"):
        r = subprocess.run([sys.executable, str(ENGINE_DIR / script)])
        if r.returncode:
            return r.returncode
    return 0


def cmd_sense(args):
    global DEBUG
    DEBUG = args.debug or os.environ.get("FACTY_DEBUG") == "1"
    if getattr(args, "offline", False):
        os.environ["FACTY_OFFLINE"] = "1"
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


def cmd_env(args):
    """`facty env` — the secrets status: which keys are set and where
    they come from (never values). `--exports` prints `export KEY=...`
    lines for `eval "$(./facty env --exports)"` — hoisting the keys into
    the launching shell (the gondolin VMs read them host-side via
    --host-secret; the guest only ever sees placeholders)."""
    if args.exports:
        print(dotenv.exports())
        return 0
    print("facty env — the secrets status (values are never printed)")
    for key, origin in dotenv.status():
        print(f"  {key:18s} {origin or '(unset)'}")
    for w in dotenv.warnings():
        print(f"  ! WARNING: {w}")
    print("  real keys live in ~/.facty/.env (machine-local, never committed);")
    print("  the project .env is mounted into the VMs — keep real keys out of it")
    return 0


def cmd_doctor(args):
    """`facty doctor` — the self-check: is everything where it should
    be? (python, textual, env, the secrets, the loaded workbench's keys,
    the response cache per case, any running workbench processes)."""
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
    for key, origin in dotenv.status():
        print(f"  {key.lower()}:  {origin or '(unset)'}")
    for w in dotenv.warnings():
        print(f"  ! WARNING: {w}")
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
    local commands="run cases selftest test sense walkthrough tui emit pack completion version"
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=($(compgen -W "$commands" -- "$cur"))
        return 0
    fi
    if [ "$prev" = "--op" ]; then
        COMPREPLY=($(compgen -W "classify entities facts drop label parser decide" -- "$cur"))
        return 0
    fi
    case "$prev" in
        run|walkthrough|tui|sense)
            local cases
            cases=$(ls engine/cases 2>/dev/null)
            COMPREPLY=($(compgen -W "$cases" -- "$cur"))
            return 0
            ;;
        pack)
            if [ "$COMP_CWORD" -eq 2 ]; then
                COMPREPLY=($(compgen -W "list validate test draft-rules suggest-labels draft-hypotheses draft-questions review" -- "$cur"))
            else
                local packs
                packs=$(ls packs 2>/dev/null)
                COMPREPLY=($(compgen -W "$packs" -- "$cur"))
            fi
            return 0
            ;;
        completion)
            COMPREPLY=($(compgen -W "bash zsh fish" -- "$cur"))
            return 0
            ;;
    esac
    case "$cur" in
        --*)
            COMPREPLY=($(compgen -W "--json --add-facts --auto --debug --op --offline --write --domain --evidence --facts --tests" -- "$cur"))
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
        'pack:the Pack Studio (validate, test, author packs)'
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
        pack)
            if (( CURRENT == 3 )); then
                local -a ops
                ops=('list:list the packs' 'validate:validate a pack' 'test:run a pack test' 'draft-rules:draft rules.json from a domain description (LLM)' 'suggest-labels:draft classify.json from sample evidence (LLM)' 'draft-hypotheses:draft hypotheses.json (LLM)' 'draft-questions:draft the Strom decision questions (LLM)' 'review:advisory gap review (LLM, prose)')
                _describe -t ops 'pack op' ops
            else
                local -a packs
                packs=(${(f)"$(ls packs 2>/dev/null)"})
                _describe -t packs 'pack' packs
            fi
            ;;
        sense)
            if [[ "$prev" == "--op" ]]; then
                _values 'op' classify entities facts drop label parser decide
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
complete -c facty -f -a 'run cases selftest test sense walkthrough tui emit pack completion version'
complete -c facty -f -n '__fish_seen_subcommand_from run walkthrough tui sense' -a '(ls engine/cases 2>/dev/null)' -d 'case'
complete -c facty -f -n '__fish_seen_subcommand_from sense' -l op -a 'classify entities facts drop label parser'
complete -c facty -f -n '__fish_seen_subcommand_from run' -l add-facts -d 'phase-2 facts drop'
complete -c facty -f -n '__fish_seen_subcommand_from run cases' -l json -d 'machine-readable output'
complete -c facty -f -n '__fish_seen_subcommand_from walkthrough tui' -l auto -d 'no prompting'
complete -c facty -f -n '__fish_seen_subcommand_from pack' -a 'list validate test draft-rules suggest-labels draft-hypotheses draft-questions review' -d 'pack op'
complete -c facty -f -n '__fish_seen_subcommand_from pack' -a '(ls packs 2>/dev/null)' -d 'pack'
complete -c facty -f -n '__fish_seen_subcommand_from pack' -l facts -d 'fact set file'
complete -c facty -f -n '__fish_seen_subcommand_from pack' -l tests -d 'tests directory'
complete -c facty -f -n '__fish_seen_subcommand_from pack' -l json -d 'machine-readable output'
complete -c facty -f -n '__fish_seen_subcommand_from pack' -l domain -d 'domain description (draft-rules/draft-hypotheses)'
complete -c facty -f -n '__fish_seen_subcommand_from pack' -l evidence -d 'sample evidence file (suggest-labels)'
complete -c facty -f -n '__fish_seen_subcommand_from pack' -l write -d 'accept the staged draft'
complete -c facty -f -n '__fish_seen_subcommand_from pack' -l offline -d 'replay the response cache, no LLM call'
complete -c facty -f -n '__fish_seen_subcommand_from pack' -l debug -d 'loud failures'
""",
}


# ── CLI ──────────────────────────────────────────────────────────────

def main(argv=None):
    dotenv.load()  # the dotenv setup: ~/.facty/.env + ./.env (setdefault —
    # the real environment wins; a missing file is fine)
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

    p = sub.add_parser("pack", help="the Pack Studio: validate, test, and author "
                                     "knowledge packs (packs/<slug>/)",
                       description="The Pack Studio (PRD-007): validate, test, and "
                                   "author the knowledge packs under packs/<slug>/. "
                                   "The draft ops (draft-rules, suggest-labels, "
                                   "draft-hypotheses, draft-questions) stage "
                                   "<artifact>.draft.json beside the target and print "
                                   "a summary — the human accepts with --write; the "
                                   "LLM never writes the pack. review prints advisory "
                                   "prose and never writes.")
    pack_sub = p.add_subparsers(dest="pack_op", metavar="op")

    p_list = pack_sub.add_parser("list", help="list the packs under packs/ (artifact counts)")
    p_list.add_argument("--json", action="store_true", help="machine-readable output")
    p_list.set_defaults(func=cmd_pack_list)

    p_val = pack_sub.add_parser("validate", help="validate a pack (schema + cross-artifact checks)")
    p_val.add_argument("pack", help="pack slug (e.g. triage-alert-flood) or path")
    p_val.add_argument("--json", action="store_true", help="machine-readable output")
    p_val.set_defaults(func=cmd_pack_validate)

    p_test = pack_sub.add_parser("test", help="run a pack on a fact set (--facts) "
                                              "or every scenario (--tests)")
    p_test.add_argument("pack", help="pack slug or path")
    p_test.add_argument("--facts", metavar="FILE",
                        help="a fact set file to run the pack on")
    p_test.add_argument("--tests", metavar="DIR",
                        help="a tests directory (every facts-*.json scenario, "
                             "asserted against facts-*.expected.json)")
    p_test.add_argument("--json", action="store_true",
                        help="machine-readable output (verdict + trace + gaps)")
    p_test.set_defaults(func=cmd_pack_test)

    def add_draft_op(name, help_text, with_domain=False, with_evidence=False,
                     with_json=True):
        """One LLM draft-op sub-subparser (the REQ-015/016 plumbing is
        identical across the ops: --write accepts the staged draft,
        --offline replays the response cache, --json is machine-readable)."""
        sp = pack_sub.add_parser(name, help=help_text)
        sp.add_argument("pack", help="pack slug or path")
        if with_domain:
            sp.add_argument("--domain", required=True,
                            help="the domain in plain language")
        if with_evidence:
            sp.add_argument("--evidence", required=True, metavar="FILE",
                            help="a sample evidence file (e.g. a CSV pile)")
        sp.add_argument("--write", action="store_true",
                        help="accept the staged draft (overwrite the target)")
        if with_json:
            sp.add_argument("--json", action="store_true",
                            help="machine-readable output (the staged draft)")
        sp.add_argument("--offline", action="store_true",
                        help="offline mode: replay the response cache, no LLM call")
        sp.add_argument("--debug", action="store_true",
                        help="debug mode: loud failures (no fallback)")
        return sp

    add_draft_op(
        "draft-rules",
        "draft pack/rules.json from a plain-language domain description "
        "(LLM, judged, staged — accept with --write)",
        with_domain=True).set_defaults(func=cmd_pack_draft_rules)
    add_draft_op(
        "suggest-labels",
        "draft classify.json (labels, columns, threshold, template) from "
        "sample evidence (LLM, judged, staged — accept with --write)",
        with_evidence=True).set_defaults(func=cmd_pack_suggest_labels)
    add_draft_op(
        "draft-hypotheses",
        "draft pack/hypotheses.json (statements, priors, claims) from a "
        "plain-language domain description (LLM, judged, staged — accept "
        "with --write)",
        with_domain=True).set_defaults(func=cmd_pack_draft_hypotheses)
    add_draft_op(
        "draft-questions",
        "draft sensor/decisions.json (the Strom question set) for the "
        "pack's label sensor (LLM, judged, staged — accept with --write)"
    ).set_defaults(func=cmd_pack_draft_questions)

    p_rev = pack_sub.add_parser(
        "review", help="advisory LLM review of the pack for gaps (dead "
                       "rules, unproven hypotheses, missing constraints) — "
                       "prose, never written to the pack")
    p_rev.add_argument("pack", help="pack slug or path")
    p_rev.add_argument("--offline", action="store_true",
                       help="offline mode: replay the response cache, no LLM call")
    p_rev.add_argument("--debug", action="store_true",
                       help="debug mode: loud failures (no fallback)")
    p_rev.set_defaults(func=cmd_pack_review)

    p = sub.add_parser("selftest", help="acceptance test — every case, asserted")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("test", help="all tests: selftest + sensing retry loop + the TUI (headless)")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("sense", help="run one sensing op, standalone (the LLM half, streamed; "
                                    "the classifier/parser sensors for classify.json cases)")
    p.add_argument("case", help="case name, unique slug, or path")
    p.add_argument("--op", required=True,
                   choices=["classify", "entities", "facts", "drop", "label",
                            "parser", "decide"],
                   help="the sensing operation")
    p.add_argument("--json", action="store_true",
                   help="machine-readable output only (logs suppressed)")
    p.add_argument("--offline", action="store_true",
                   help="offline mode: LLM ops replay the response cache; the "
                        "label sensor runs the local tier only (also "
                        "FACTY_OFFLINE=1)")
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

    p = sub.add_parser("env", help="the secrets status (never values); "
                                   "--exports for eval-hoisting into VMs")
    p.add_argument("--exports", action="store_true",
                   help="print `export KEY=...` lines (secrets — your terminal "
                        "only) for `eval \"$(./facty env --exports)\"`")
    p.set_defaults(func=cmd_env)
    p = sub.add_parser("version", help="print the version")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("doctor", help="self-check: python, textual, env, cache, processes")
    p.set_defaults(func=cmd_doctor)

    args = ap.parse_args(argv)
    try:
        if args.command is None:
            # bare `facty` → the primary interface: the Textual workbench
            return cmd_tui(argparse.Namespace(case=None, auto=False))
        if args.command == "pack":
            # REQ-016: one pi session for the whole pack command — the LLM
            # ops (and their correction turns) share one process and one
            # conversation prefix, so the provider's prompt cache hits
            # across them. The deterministic ops spawn nothing.
            with sensing.session_scope():
                return args.func(args)
        return args.func(args)
    finally:
        # quitting (q / ctrl+c / ctrl+q) leaves no LLM/auth subprocess behind
        procs.kill_all()


if __name__ == "__main__":
    raise SystemExit(main())
