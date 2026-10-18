#!/usr/bin/env python3
# label.py — the label sensor: a small CPU-only zero-shot classifier that
# turns evidence rows into labeled facts.
#
# The numeric sense for categorical evidence. A case declares its labeling
# task in classify.json (labels, threshold, model, prep mode); the sensor
# scores every row against the labels with a small NLI model — zero-shot:
# premise = the row text, hypothesis = the template with the label, and the
# entailment probability becomes the label's score. It emits one fact per row
# plus aggregate facts, and gates on the threshold: below it the fact says
# "unclassified" and the LLM picks the row up (the confidence-gated
# handoff). The sensor never touches the verdict path — it emits facts, the
# engine decides (ADR-0003 §1).
#
# Prep modes (how rows are extracted from the evidence):
#   none        — structured evidence (CSV): read the columns directly;
#                 the LLM never sees the pile (the token-saving case)
#   parser      — semi-structured mess: a generated, committed, tested,
#                 stdlib-only parser (sensor/extract.py) extracts the rows
#   llm-filter  — the LLM reads the messy evidence and emits candidate rows
# The parser is generated once per evidence format by an LLM (a capped
# correction loop with a code judge: contract + execution + tests +
# completeness + schema), then committed and reviewed like any artifact.
#
# Fallback ladder (logged, never silent):
#   rows → classifier → facts
#   prep/classifier failed → raw chunks (classify the messy text as-is,
#   threshold-gated) → facts
#   everything failed → the op falls back to the response cache, then the
#   recorded facts (cli.sense_label).
#
# Library:
#   from label import load_config, run_sensor, build_facts, score_rows
#   config = load_config(Path("engine/cases/triage-alert-flood"))
#   facts, source = run_sensor(Path("engine/cases/triage-alert-flood"))
#
# Deps (optional, lazily imported — the engine core + CLI stay
# dependency-free and run in the gondolin VM snapshot, which has no pypi
# egress):
#   make deps-sensors    # uv venv + uv pip install -r requirements-sensors.txt
#
# Knobs (classify.json): model (an ONNX repo, default
# onnx-community/ModernBERT-base-nli-ONNX), precision (fp32 | int8),
# threshold (default 0.7).

import ast
import csv
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import engine  # noqa: E402  (schema validation — $ref support)
import procs  # noqa: E402  (subprocess registry — no dangling processes)

DEFAULT_MODEL = "onnx-community/ModernBERT-base-nli-ONNX"
DEFAULT_THRESHOLD = 0.7
PRECISION_FILES = {"fp32": "onnx/model.onnx", "fp16": "onnx/model_fp16.onnx",
                   "int8": "onnx/model_int8.onnx"}
UNCLASSIFIED = "unclassified"
ROW_BATCH = 32
ROW_MAXLEN = 64
PARSER_TIMEOUT_S = 30

# The parser contract: stdlib-only, pure function, no I/O, no network.
# The import allowlist keeps generated parsers deterministic and side-
# effect-free; the isolated runtime + review are the backstop (the contract
# is the first line, not the only one).
ALLOWED_IMPORTS = {"re", "json", "csv", "datetime", "collections", "itertools",
                   "math", "string", "statistics", "html", "unicodedata",
                   "textwrap", "difflib", "functools", "operator", "heapq",
                   "bisect", "copy", "pprint", "uuid", "hashlib", "base64",
                   "binascii", "struct", "array", "decimal", "fractions",
                   "time", "enum", "dataclasses", "pathlib", "shlex", "os"}
DENIED_BUILTINS = {"eval", "exec", "compile", "__import__", "open", "input",
                   "breakpoint"}


class LabelError(ValueError):
    """A malformed labeling task or evidence — a sensing-input error."""


# ── Config ────────────────────────────────────────────────────────────

def load_config(case_dir):
    """Load + validate classify.json. Required keys: file, textColumn,
    labels. Everything else has a default (see the module docstring)."""
    case = Path(case_dir)
    path = case / "classify.json"
    if not path.exists():
        raise LabelError(f"{case.name}: no classify.json — this case has no "
                         "label-sensor task")
    try:
        cfg = json.loads(path.read_text())
    except ValueError as exc:
        raise LabelError(f"classify.json: unparseable JSON: {exc}")
    for key in ("file", "textColumn", "labels"):
        if key not in cfg:
            raise LabelError(f"classify.json: missing required key {key!r}")
    if not isinstance(cfg["labels"], list) or not cfg["labels"]:
        raise LabelError("classify.json: labels must be a non-empty list")
    cfg.setdefault("idColumn", "id")
    cfg.setdefault("sourceColumn", None)
    cfg.setdefault("timeColumn", None)
    cfg.setdefault("subject", Path(cfg["file"]).stem)
    cfg.setdefault("template", "This example is {}.")
    cfg.setdefault("threshold", DEFAULT_THRESHOLD)
    cfg.setdefault("model", DEFAULT_MODEL)
    cfg.setdefault("precision", "fp32")
    cfg.setdefault("prep", "none")
    cfg.setdefault("scoring", "margin")
    cfg.setdefault("backend", "strom")
    if cfg["precision"] not in PRECISION_FILES:
        raise LabelError(f"classify.json: precision must be one of "
                         f"{sorted(PRECISION_FILES)}")
    if cfg["prep"] not in ("none", "parser", "llm-filter"):
        raise LabelError("classify.json: prep must be one of "
                         "none | parser | llm-filter")
    if cfg["scoring"] not in ("entail", "margin"):
        raise LabelError("classify.json: scoring must be one of "
                         "entail | margin")
    if cfg["backend"] not in ("local", "strom", "hybrid"):
        raise LabelError("classify.json: backend must be one of "
                         "local | strom | hybrid")
    crit = cfg.get("criteria")
    if crit is not None:
        if not isinstance(crit, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in crit.items()):
            raise LabelError("classify.json: criteria must map labels to "
                             "description strings")
        unknown = set(crit) - set(cfg["labels"])
        if unknown:
            raise LabelError("classify.json: criteria keys must be labels "
                             f"(unknown: {sorted(unknown)})")
    return cfg


def short_model(model):
    """'onnx-community/ModernBERT-base-nli-ONNX' → 'ModernBERT-base-nli'."""
    name = model.split("/")[-1]
    return name[:-5] if name.endswith("-ONNX") else name


# ── The decider tier (Strom) ─────────────────────────────────────────

def load_decisions(case_dir):
    """Load the drafted decision questions (sensor/decisions.json) — the
    committed artifact from `./facty sense <case> --op decide`. Returns
    None when absent (the sensor then builds the default question set
    from classify.json)."""
    path = Path(case_dir) / "sensor" / "decisions.json"
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text())
    except ValueError as exc:
        raise LabelError(f"sensor/decisions.json: unparseable JSON: {exc}")
    errs = check_decisions(doc, load_config(case_dir))
    if errs:
        raise LabelError("sensor/decisions.json: " + "; ".join(errs[:3]))
    return doc


def choice_question(cfg):
    """The default choice question for the label task, built from
    classify.json (used when no decisions.json is drafted): the labels as
    options, the criteria descriptions when configured (the model goes by
    the name alone otherwise — Strom's docs)."""
    import strom
    crit = {lab: (cfg.get("criteria") or {}).get(lab, lab)
            for lab in cfg["labels"]}
    return strom.choice(f"Classify this {cfg['subject']}.", crit)


def decision_questions(cfg, decisions=None):
    """The Strom question set for the label task + the name of the choice
    question that drives classifiedAs. Uses the drafted decisions.json when
    given, else the default choice question. Raises LabelError when no
    choice question covers the labels exactly."""
    qs = decisions["questions"] if decisions else {"class": choice_question(cfg)}
    for name, q in qs.items():
        if (q.get("type") == "choice"
                and set(q.get("criteria") or {}) == set(cfg["labels"])):
            return qs, name
    raise LabelError("no choice question covers the classify.json labels "
                     "exactly — draft one: ./facty sense <case> --op decide")


def _slug(label):
    """'a targeted attack' → 'targetedAttack' — the aggregate-predicate stem."""
    text = label.strip().lower()
    for art in ("a ", "an ", "the "):
        if text.startswith(art):
            text = text[len(art):]
            break
    parts = [p for p in re.split(r"[^a-z0-9]+", text) if p]
    return parts[0] + "".join(p.capitalize() for p in parts[1:]) if parts else "label"


# ── Prep: rows from evidence ──────────────────────────────────────────

def read_rows(case_dir, cfg):
    """prep=none: read the structured evidence (CSV) directly — the LLM
    never sees it. Returns row dicts with the configured columns."""
    case = Path(case_dir)
    path = case / cfg["file"]
    if not path.exists():
        raise LabelError(f"{cfg['file']}: not found")
    with path.open(newline="") as fh:
        rows = [r for r in csv.reader(fh) if r and any(c.strip() for c in r)]
    if not rows:
        raise LabelError(f"{cfg['file']}: empty")
    header = [c.strip() for c in rows[0]]
    wanted = [cfg["textColumn"], cfg["idColumn"]]
    wanted += [c for c in (cfg["sourceColumn"], cfg["timeColumn"]) if c]
    for col in wanted:
        if col not in header:
            raise LabelError(f"{cfg['file']}: missing column {col!r}")
    out = []
    for n, row in enumerate(rows[1:], start=1):
        if len(row) != len(header):
            raise LabelError(f"{cfg['file']}: row {n} has {len(row)} fields, "
                             f"expected {len(header)}")
        rec = dict(zip(header, (c.strip() for c in row)))
        out.append({
            "id": rec.get(cfg["idColumn"]) or f"row-{n}",
            "text": rec[cfg["textColumn"]],
            "source": rec.get(cfg["sourceColumn"]) if cfg["sourceColumn"] else None,
            "time": rec.get(cfg["timeColumn"]) if cfg["timeColumn"] else None,
            "row": n,
        })
    return out


def run_parser(case_dir, cfg, text=None):
    """prep=parser: run the committed generated parser (sensor/extract.py)
    in a subprocess (timeout, stdlib-only contract) over the evidence text.
    Returns row dicts. Raises RuntimeError on any failure."""
    case = Path(case_dir)
    parser = case / "sensor" / "extract.py"
    if not parser.exists():
        raise RuntimeError(f"{case.name}: no sensor/extract.py — generate it: "
                           f"./facty sense {case.name} --op parser")
    if text is None:
        text = (case / cfg["file"]).read_text()
    code = ("import json, sys\n"
            f"sys.path.insert(0, {str(parser.parent)!r})\n"
            "import extract\n"
            "print(json.dumps(extract.parse(sys.stdin.read())))")
    proc = subprocess.Popen([sys.executable, "-c", code],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    procs.register(proc)
    try:
        out, err = proc.communicate(input=text, timeout=PARSER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"{parser.name}: timed out after {PARSER_TIMEOUT_S}s")
    finally:
        procs.unregister(proc)
    if proc.returncode != 0:
        raise RuntimeError(f"{parser.name} failed: {err.strip()[:300]}")
    try:
        rows = json.loads(out)
    except ValueError:
        raise RuntimeError(f"{parser.name}: did not print JSON rows")
    if not isinstance(rows, list):
        raise RuntimeError(f"{parser.name}: parse() must return a list of rows")
    return [_row_from_parser(r, cfg, i) for i, r in enumerate(rows, start=1)]


def _row_from_parser(rec, cfg, n):
    """Normalize one parser record into a row dict. Records without the text
    column are the unparsed bucket (counted, never silently dropped)."""
    if not isinstance(rec, dict):
        raise RuntimeError(f"extract.py: entry {n} is not an object")
    if "unparsed" in rec:
        return {"id": f"unparsed-{n}", "text": None,
                "unparsed": str(rec["unparsed"]),
                "source": None, "time": None, "row": n}
    if cfg["textColumn"] not in rec:
        raise RuntimeError(f"extract.py: entry {n} missing field "
                           f"{cfg['textColumn']!r}")
    return {
        "id": str(rec.get(cfg["idColumn"]) or f"row-{n}"),
        "text": str(rec[cfg["textColumn"]]),
        "source": (str(rec[cfg["sourceColumn"]])
                   if cfg["sourceColumn"] and cfg["sourceColumn"] in rec else None),
        "time": (str(rec[cfg["timeColumn"]])
                 if cfg["timeColumn"] and cfg["timeColumn"] in rec else None),
        "row": n,
    }


def prep_llm_filter(case_dir, cfg, stream=None, runner=None):
    """prep=llm-filter: the LLM reads the messy evidence and emits the
    candidate rows (its judgment strength: relevance). Schema-guided via
    sensing.extract_structured; the classifier labels the rows locally."""
    import sensing
    case = Path(case_dir)
    path = case / cfg["file"]
    if not path.exists():
        raise LabelError(f"{cfg['file']}: not found")
    fields = {cfg["idColumn"]: "string", cfg["textColumn"]: "string"}
    for col in (cfg["sourceColumn"], cfg["timeColumn"]):
        if col:
            fields[col] = "string"
    schema = {"type": "array",
              "items": {"type": "object", "required": [cfg["textColumn"]],
                        "properties": fields}}
    task = (f"Extract the {cfg['subject']} records from this evidence file. "
            "For each record, emit one object with the fields: "
            f"{', '.join(fields)}. Skip boilerplate, headers, and noise — emit "
            f"only the records. Evidence: @{path.resolve()}")
    rows = sensing.extract_structured(schema, task, stream=stream,
                                      label=f"{case.name}-llm-filter",
                                      runner=runner)
    return [_row_from_parser(r, cfg, i) for i, r in enumerate(rows, start=1)]


def raw_chunks(case_dir, cfg, max_lines=20):
    """The fallback rows: the raw evidence text, chunked by line groups.
    The classifier scores the chunks as-is (no prep) — lower quality,
    threshold-gated, and fully deterministic."""
    case = Path(case_dir)
    text = (case / cfg["file"]).read_text()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    chunks = []
    for i in range(0, len(lines), max_lines):
        group = lines[i:i + max_lines]
        chunks.append({"id": f"chunk-{i // max_lines + 1}",
                       "text": "\n".join(group),
                       "source": None, "time": None,
                       "row": i + 1, "lines": (i + 1, i + len(group))})
    return chunks


def _prep_rows(case, cfg, stream=None, runner=None):
    if cfg["prep"] == "parser":
        return run_parser(case, cfg)
    if cfg["prep"] == "llm-filter":
        return prep_llm_filter(case, cfg, stream=stream, runner=runner)
    return read_rows(case, cfg)


# ── The classifier ────────────────────────────────────────────────────

def load_classifier(model=None, precision="fp32"):
    """Load the zero-shot NLI model (lazy import — the optional sensor deps).
    Returns (session, tokenizer, input_names, entailment_index,
    contradiction_index). The contradiction index is None for binary
    entailment / not-entailment models (the zeroshot-v2.0 recipe) — margin
    scoring degrades to entail-only for those. Raises RuntimeError with
    the install hint when the deps are missing: a missing dep cannot be
    corrected by a retry, so callers fail fast."""
    model = model or DEFAULT_MODEL
    try:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "the label sensor needs onnxruntime + transformers (CPU-only; "
            f"missing: {exc.name}). Install the optional sensor deps: "
            "make deps-sensors   — or —   uv pip install -r requirements-sensors.txt")
    onnx_file = PRECISION_FILES[precision]
    local = hf_hub_download(model, onnx_file)
    cfg_path = hf_hub_download(model, "config.json")
    cfg = json.loads(open(cfg_path).read())
    id2label = {int(k): v for k, v in cfg["id2label"].items()}
    ent = con = None
    for i, lab in id2label.items():
        low = str(lab).lower()
        if "entail" in low and ent is None:
            ent = i
        elif "contrad" in low and con is None:
            con = i
    if ent is None:
        raise LabelError(f"{model}: no entailment label in config")
    tok = AutoTokenizer.from_pretrained(model)
    if tok.pad_token is None:
        for cand in ("eos_token", "unk_token", "sep_token", "cls_token"):
            if getattr(tok, cand):
                tok.pad_token = getattr(tok, cand)
                break
    so = ort.SessionOptions()
    so.intra_op_num_threads = 4
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(local, so, providers=["CPUExecutionProvider"])
    return sess, tok, [i.name for i in sess.get_inputs()], ent, con


def softmax(xs):
    m = max(xs)
    ex = [math.exp(x - m) for x in xs]
    s = sum(ex)
    return [e / s for e in ex]


def score_rows(classifier, rows, labels, template, scoring="margin"):
    """Zero-shot score every row against every label: premise = row text,
    hypothesis = template.format(label). scoring="entail" softmaxes the
    labels' entailment logits; scoring="margin" (the default) softmaxes
    entailment − contradiction per label — measured to calibrate the
    confidences far better for threshold gating on out-of-domain text.
    Returns per-row probability vectors."""
    import numpy as np
    sess, tok, input_names, ent, con = classifier
    pairs = [(r["text"], template.format(lab)) for r in rows for lab in labels]
    scores = []
    for i in range(0, len(pairs), ROW_BATCH):
        batch = pairs[i:i + ROW_BATCH]
        enc = tok([p for p, _ in batch], [h for _, h in batch], padding=True,
                  truncation=True, max_length=ROW_MAXLEN, return_tensors="np")
        feeds = {n: enc[n].astype(np.int64) for n in input_names if n in enc}
        for row in sess.run(None, feeds)[0]:
            e = float(row[ent])
            if scoring == "margin" and con is not None:
                scores.append(e - float(row[con]))
            else:
                scores.append(e)
    return [softmax(scores[i * len(labels):(i + 1) * len(labels)])
            for i in range(len(rows))]


def _score(cfg, rows, classifier, score_fn):
    """Score the rows (only rows with text), re-aligning the probability
    vectors to the full row list (rows without text get a zero vector —
    they flow through build_facts as unclassified)."""
    scored = [r for r in rows if r.get("text") is not None]
    if not scored:
        raise RuntimeError("no rows with text to classify")
    if score_fn is not None:
        probs = score_fn(scored, cfg["labels"], cfg["template"])
    else:
        if classifier is None:
            classifier = load_classifier(cfg["model"], cfg["precision"])
        probs = score_rows(classifier, scored, cfg["labels"], cfg["template"],
                           scoring=cfg["scoring"])
    out, i = [], 0
    for r in rows:
        if r.get("text") is not None:
            out.append(probs[i])
            i += 1
        else:
            out.append([0.0] * len(cfg["labels"]))
    return out


# ── Facts ─────────────────────────────────────────────────────────────

def build_facts(cfg, rows, probs, case_dir):
    """Rows + probability vectors → Facts: one labeled fact per row (below
    the threshold: classifiedAs = unclassified), plus aggregate facts over
    the labeled rows. Pure — no model, no I/O."""
    src = cfg["file"]
    facts = []
    for row, prob in zip(rows, probs):
        best = max(range(len(cfg["labels"])), key=lambda i: prob[i])
        value = (cfg["labels"][best]
                 if prob[best] >= cfg["threshold"] else UNCLASSIFIED)
        span = (f":lines {row['lines'][0]}-{row['lines'][1]}"
                if row.get("lines") else f":row {row['row']}")
        facts.append({
            "id": f"cl-{row['id']}",
            "type": "evidence",
            "subject": str(row["id"]),
            "predicate": "classifiedAs",
            "value": value,
            "confidence": round(prob[best], 4),
            "source": f"{src}{span}",
        })
    facts += _aggregates(cfg, rows, probs, src)
    return facts


def _aggregates(cfg, rows, probs, src):
    """Aggregate facts over the labeled rows: counts + mean confidence per
    label, source concentration, and the window of each label. Only the
    aggregates whose inputs exist (source/time columns) are emitted."""
    subject = cfg["subject"]
    labels = list(cfg["labels"]) + [UNCLASSIFIED]
    stems = [_slug(l) for l in cfg["labels"]] + ["unclassified"]
    labeled = []
    for row, prob in zip(rows, probs):
        best = max(range(len(cfg["labels"])), key=lambda i: prob[i])
        li = best if prob[best] >= cfg["threshold"] else len(cfg["labels"])
        labeled.append((row, li, prob[best]))
    out = [{
        "id": "ag-classifiedcount", "type": "evidence", "subject": subject,
        "predicate": "classifiedCount", "value": len(rows),
        "confidence": 1.0, "source": f"{src}:rows 1-{len(rows)}",
    }]
    for li in range(len(labels)):
        members = [t for t in labeled if t[1] == li]
        if not members:
            continue
        stem = stems[li]
        out.append({
            "id": f"ag-{stem.lower()}count", "type": "evidence", "subject": subject,
            "predicate": f"{stem}Count", "value": len(members),
            "confidence": 1.0, "source": f"{src}:rows 1-{len(rows)}",
        })
        out.append({
            "id": f"ag-{stem.lower()}meanconfidence", "type": "evidence",
            "subject": subject, "predicate": f"{stem}MeanConfidence",
            "value": round(sum(t[2] for t in members) / len(members), 4),
            "confidence": 1.0, "source": f"{src}:rows 1-{len(rows)}",
        })
        if cfg["sourceColumn"]:
            srcs = [t[0]["source"] for t in members if t[0]["source"]]
            if srcs:
                counts = Counter(srcs)
                top, top_n = counts.most_common(1)[0]
                out.append({
                    "id": f"ag-{stem.lower()}topsource", "type": "evidence",
                    "subject": subject, "predicate": f"{stem}TopSource",
                    "value": top, "confidence": 1.0,
                    "source": f"{src}:rows 1-{len(rows)}",
                })
                out.append({
                    "id": f"ag-{stem.lower()}topsourcecount", "type": "evidence",
                    "subject": subject, "predicate": f"{stem}TopSourceCount",
                    "value": top_n, "confidence": 1.0,
                    "source": f"{src}:rows 1-{len(rows)}",
                })
                out.append({
                    "id": f"ag-{stem.lower()}distinctsources", "type": "evidence",
                    "subject": subject, "predicate": f"{stem}DistinctSources",
                    "value": len(counts), "confidence": 1.0,
                    "source": f"{src}:rows 1-{len(rows)}",
                })
        if cfg["timeColumn"]:
            times = [t[0]["time"] for t in members if t[0]["time"]]
            if times:
                out.append({
                    "id": f"ag-{stem.lower()}window", "type": "evidence",
                    "subject": subject, "predicate": f"{stem}Window",
                    "value": [min(times), max(times)], "confidence": 1.0,
                    "source": f"{src}:rows 1-{len(rows)}",
                })
    if cfg["sourceColumn"]:
        all_srcs = [r["source"] for r in rows if r["source"]]
        if all_srcs:
            counts = Counter(all_srcs)
            top, top_n = counts.most_common(1)[0]
            for pred, val in (("topSource", top), ("topSourceCount", top_n),
                              ("distinctSources", len(counts))):
                out.append({
                    "id": f"ag-{pred.lower()}", "type": "evidence",
                    "subject": subject, "predicate": pred, "value": val,
                    "confidence": 1.0, "source": f"{src}:rows 1-{len(rows)}",
                })
    return out


def validate_facts(facts):
    """Validate the facts list against schemas/facts.schema.json (the array
    schema $refs fact.schema.json per item). Returns the error list."""
    schema = engine.load_json(engine.SCHEMA_DIR / "facts.schema.json")
    return engine.validate(facts, schema)


# ── The sensor pipeline ───────────────────────────────────────────────

def _strom_score(cfg, rows, client, decisions=None, usage=None):
    """The decider tier: score the rows with Strom (one request per row —
    the state is the row's fields; the questions are the decision set;
    many questions per request and byte-identical states, so Strom's
    prompt cache reuses what it can — replays come back faster).
    Returns (probs aligned to cfg["labels"], extras) where extras are the
    non-choice answers as (row_index, question_name, answer) tuples.
    Rows without text are skipped (they stay unclassified). When `usage`
    is a dict it accumulates {calls, input_tokens, cached_input_tokens,
    cost} — the response's usage, for the op's log line."""
    import strom
    client = client or strom.from_env()
    questions, choice_name = decision_questions(cfg, decisions)
    probs = [[0.0] * len(cfg["labels"]) for _ in rows]
    extras = []
    for i, row in enumerate(rows):
        if row.get("text") is None:
            continue
        state = {k: v for k, v in row.items() if k not in ("row", "lines")}
        resp = client.ask(state, questions)
        if usage is not None:
            u = resp.get("usage") or {}
            usage["calls"] = usage.get("calls", 0) + 1
            usage["input_tokens"] = (usage.get("input_tokens", 0)
                                     + u.get("input_tokens", 0))
            usage["cached_input_tokens"] = (
                usage.get("cached_input_tokens", 0)
                + u.get("cached_input_tokens", 0))
            usage["cost"] = usage.get("cost", 0.0) + u.get("cost", 0.0)
        answers = resp["answers"]
        ch = answers[choice_name]
        probs[i] = [float(ch["probabilities"].get(lab, 0.0))
                    for lab in cfg["labels"]]
        for qname in questions:
            if qname != choice_name:
                extras.append((i, qname, answers[qname]))
    return probs, extras


def _extras_facts(cfg, rows, extras):
    """The non-choice decision answers (noul/score) → per-row facts: the
    question name is the predicate (camelCase, stable — packs reference
    it), the value is the answer (the noul probability / the score), the
    confidence is the answer's confidence (noul answers carry none — the
    probability is the value)."""
    out = []
    for i, qname, a in extras:
        row = rows[i]
        if a.get("type") == "noul":
            value, conf = round(float(a["noul"]), 4), 1.0
        else:
            value = round(float(a["score"]), 4)
            conf = round(float(a.get("confidence", 1.0)), 4)
        out.append({
            "id": f"dq-{qname}-{row['id']}",
            "type": "evidence",
            "subject": str(row["id"]),
            "predicate": qname,
            "value": value,
            "confidence": conf,
            "source": f"{cfg['file']}:row {row['row']}",
        })
    return out


def run_sensor(case_dir, config=None, classifier=None, score_fn=None,
               stream=None, runner=None, client=None, decisions=None,
               offline=None, usage=None):
    """Run the label sensor over a case. The backend (classify.json)
    selects the tiers:
      strom (default) — the Strom decider tier scores every row
        (calibrated decision model, the first-class path); the local
        classifier is the automatic fallback when the API is
        unreachable / the key is missing / the balance is empty;
      hybrid — the local classifier (tier 1) scores the bulk; Strom
        adjudicates the rows tier 1 gated (the confidence-gated
        handoff, calibrated);
      local — tier 1 only.
    Offline (FACTY_OFFLINE=1 / --offline) runs the local tier only,
    whatever the backend (no network, no decider). The prep fallback
    ladder is unchanged: prep rows → classifier; prep or classifier
    failure → raw chunks → classifier. `classifier`/`score_fn`/`client`/
    `decisions`/`usage` are injectable (tests stub them; `usage` is a
    dict the decider tier accumulates its API usage into). Returns
    (facts, source)."""
    case = Path(case_dir)
    cfg = config or load_config(case)
    if decisions is None:
        decisions = load_decisions(case)
    backend = cfg.get("backend", "strom")
    if offline is None:
        offline = os.environ.get("FACTY_OFFLINE") == "1"
    # ── the prep ladder (shared): prep rows → classifier → raw chunks ──
    ladder = []
    try:
        ladder.append((_prep_rows(case, cfg, stream=stream, runner=runner),
                       "classifier"))
    except Exception:
        ladder.append((None, "classifier"))
    ladder.append((raw_chunks(case, cfg), "raw-chunks"))

    def tier1():
        """The local tier: the prep → classifier → raw-chunks ladder.
        Returns (rows, probs, source-tag) or raises RuntimeError."""
        last_err = None
        for r, tag in ladder:
            if r is None:
                continue
            try:
                return r, _score(cfg, r, classifier, score_fn), tag
            except Exception as exc:
                last_err = exc
        raise RuntimeError(f"label sensor failed on every path: {last_err}")

    extras = []
    if offline:
        # offline mode: the local tier only (no network, no decider)
        rows, probs, t1 = tier1()
        source = f"{t1} (offline: the decider tier is skipped)"
    elif backend == "strom":
        # the decider tier is primary; tier 1 is the fallback
        rows = ladder[0][0] if ladder[0][0] is not None else ladder[1][0]
        if rows is None:
            raise RuntimeError("label sensor: the evidence could not be "
                               f"read ({cfg['file']}) — nothing to score")
        try:
            probs, extras = _strom_score(cfg, rows, client, decisions,
                                         usage=usage)
            source = "decider"
        except Exception as exc:
            err = _short(exc)
            try:
                rows, probs, t1 = tier1()
                source = f"{t1} (decider failed: {err})"
            except RuntimeError as exc2:
                raise RuntimeError(f"the decider tier failed ({err}) and "
                                   "the local classifier is unavailable "
                                   f"({exc2})") from exc2
    elif backend == "hybrid":
        # tier 1 scores the bulk; the decider tier adjudicates the gated
        rows, probs, t1 = tier1()
        gated = [i for i, p in enumerate(probs)
                 if rows[i].get("text") is not None
                 and max(p) < cfg["threshold"]]
        if gated:
            try:
                sub = [rows[i] for i in gated]
                sub_probs, sub_extras = _strom_score(cfg, sub, client,
                                                     decisions, usage=usage)
                for k, i in enumerate(gated):
                    probs[i] = sub_probs[k]
                extras = [(gated[k], qname, a)
                          for k, qname, a in sub_extras]
                source = "classifier+decider"
            except Exception as exc:
                source = f"{t1} (decider skipped: {_short(exc)})"
        else:
            source = "classifier+decider (tier 1 gated nothing)"
    else:  # local
        rows, probs, t1 = tier1()
        source = t1
    facts = build_facts(cfg, rows, probs, case)
    facts += _extras_facts(cfg, rows, extras)
    errs = validate_facts(facts)
    if errs:
        raise ValueError("label-sensor facts failed schema validation: "
                         + "; ".join(errs[:5]))
    return facts, source


def _short(exc):
    text = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
    return text[:120]


# ── The parser generator (the LLM writes the code; the judge judges it) ─

PARSER_SCHEMA = {
    "type": "object",
    "required": ["extract_py", "extract_test_py"],
    "properties": {
        "extract_py": {"type": "string"},
        "extract_test_py": {"type": "string"},
    },
}

PARSER_TASK = """Write a deterministic log parser for this evidence format, as
two Python files returned as a JSON object with the keys "extract_py" and
"extract_test_py".

extract_py — the parser, following this contract EXACTLY:
- stdlib only (re, json, csv, datetime, collections, itertools, math, ...)
- one top-level function: def parse(text: str) -> list[dict]
- pure: no file I/O, no network, no randomness, no global state
- every input line is accounted for: each returned dict is either a record
  (with the field "{textColumn}") or an unparsed line ({"unparsed": line}) —
  the header line goes in the unparsed bucket
- no silent drops: len(records) + len(unparsed) == number of non-blank lines

The records must have these fields: {fields}.

extract_test_py — a unittest test module for the parser with at least 3 test
methods built from the sample lines below (round-trip: parse the sample,
assert the records and the unparsed bucket).

Sample lines from the evidence (the file's first lines):
{{SAMPLE}}
"""


def check_parser_contract(source):
    """The static half of the code judge: stdlib-only imports (allowlist),
    no dangerous builtins, and a top-level parse(text) function. Returns a
    list of violations (empty = the contract holds)."""
    errs = []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"syntax error: {exc}"]
    has_parse = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                root = (alias.name or "").split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    errs.append(f"import not in the stdlib allowlist: "
                                f"{alias.name}")
        elif isinstance(node, ast.Name) and node.id in DENIED_BUILTINS:
            errs.append(f"forbidden builtin: {node.id}")
        elif isinstance(node, ast.FunctionDef) and node.name == "parse":
            has_parse = True
    if not has_parse:
        errs.append("no top-level parse(text) function")
    return errs


def _try_run_parser_source(source, cfg, sample_text):
    """The dynamic half of the code judge on a candidate parser: run it in
    a subprocess over the sample, check completeness + the record schema.
    Returns (rows, errors)."""
    import tempfile
    errs = []
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "extract.py").write_text(source)
        code = ("import json, sys\n"
                f"sys.path.insert(0, {tmp!r})\n"
                "import extract\n"
                "print(json.dumps(extract.parse(sys.stdin.read())))")
        proc = subprocess.Popen([sys.executable, "-c", code],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True,
                                start_new_session=True)
        try:
            out, err = proc.communicate(input=sample_text,
                                        timeout=PARSER_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            return None, ["extract.py: timed out"]
        if proc.returncode != 0:
            return None, [f"extract.py failed to run: {err.strip()[:300]}"]
        try:
            rows = json.loads(out)
        except ValueError:
            return None, ["extract.py did not print JSON rows"]
        if not isinstance(rows, list):
            return None, ["extract.py: parse() must return a list"]
        n_lines = len([ln for ln in sample_text.splitlines() if ln.strip()])
        if len(rows) != n_lines:
            errs.append(f"completeness: parse() returned {len(rows)} entries "
                        f"for {n_lines} non-blank input lines (silent drop?)")
        for i, rec in enumerate(rows):
            if (isinstance(rec, dict) and "unparsed" not in rec
                    and cfg["textColumn"] not in rec):
                errs.append(f"entry {i}: missing field {cfg['textColumn']!r}")
        return rows, errs


def _run_parser_tests(test_source, extract_source):
    """Run the candidate's extract_test.py (with extract.py beside it) in a
    subprocess. Returns a list of errors (empty = tests pass)."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "extract.py").write_text(extract_source)
        test = Path(tmp) / "extract_test.py"
        test.write_text(test_source)
        try:
            proc = subprocess.run([sys.executable, str(test)],
                                  capture_output=True, text=True,
                                  timeout=PARSER_TIMEOUT_S, cwd=tmp)
        except subprocess.TimeoutExpired:
            return ["extract_test.py: timed out"]
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-6:]
            return ["extract_test.py failed: " + " | ".join(tail)]
    return []


def generate_parser(case_dir, config=None, runner=None, stream=None,
                    max_attempts=3, note=None):
    """Generate the case's parser (sensor/extract.py + extract_test.py) with
    an LLM, judged by the code judge in a capped correction loop (1 initial
    + max_attempts-1 revisions — the sensing.py pattern; an unreachable LLM
    fails fast). Returns the accepted {"extract_py", "extract_test_py"}
    object. The caller writes and commits the files."""
    import sensing
    case = Path(case_dir)
    cfg = config or load_config(case)
    if cfg["prep"] != "parser":
        raise LabelError(f"{case.name}: classify.json prep is {cfg['prep']!r}, "
                         "not 'parser'")
    sample = "\n".join((case / cfg["file"]).read_text().splitlines()[:25])
    fields = [cfg["idColumn"], cfg["textColumn"]]
    fields += [c for c in (cfg["sourceColumn"], cfg["timeColumn"]) if c]
    task = (PARSER_TASK
            .replace("{{SAMPLE}}", sample)
            .replace("{textColumn}", cfg["textColumn"])
            .replace("{fields}", ", ".join(fields)))
    runner = runner or sensing._pi_runner
    label = f"{case.name}-parser"
    staged = sensing.staged_prompt_path(label)
    staged.parent.mkdir(parents=True, exist_ok=True)
    prompt = (f"{task}\n\n"
              "Respond with ONLY a JSON object with the keys extract_py and "
              "extract_test_py — no prose, no markdown fences:\n\n"
              + json.dumps(PARSER_SCHEMA))
    for attempt in range(1, max_attempts + 1):
        staged.write_text(prompt)
        text = runner(str(staged), stream)  # RuntimeError = unreachable, fail fast
        try:
            obj = sensing.parse_and_validate(text, PARSER_SCHEMA)
            errs = list(check_parser_contract(obj["extract_py"]))
            if not errs:
                _rows, run_errs = _try_run_parser_source(obj["extract_py"],
                                                         cfg, sample)
                errs += run_errs
            if not errs:
                errs = _run_parser_tests(obj["extract_test_py"],
                                         obj["extract_py"])
        except ValueError as exc:
            errs = [str(exc)]
            obj = None
        if not errs:
            if note:
                note(f"attempt {attempt}/{max_attempts} accepted by the code judge")
            return obj
        if attempt < max_attempts:
            detail = "; ".join(errs[:5])
            if note:
                note(f"attempt {attempt}/{max_attempts} rejected — {detail}; "
                     "correcting")
            prev = (obj or {}).get("extract_py", text[:2000]) if obj else text[:2000]
            prompt = (f"{prompt}\n\nYour previous parser was rejected by the "
                      "code judge:\n\n"
                      + "\n".join(f"- {e}" for e in errs[:8])
                      + f"\n\nPrevious extract_py:\n{prev[:2000]}\n\n"
                      "Fix it. Respond with ONLY the JSON object again.")
            continue
        raise ValueError(f"code judge rejected the parser after {max_attempts} "
                         f"attempts: {'; '.join(errs[:5])}")
    raise ValueError("unreachable")  # pragma: no cover


def write_parser(case_dir, obj):
    """Write the generated parser + its tests into the case's sensor/ dir
    (the artifact is meant to be committed and reviewed)."""
    case = Path(case_dir)
    sensor = case / "sensor"
    sensor.mkdir(parents=True, exist_ok=True)
    (sensor / "extract.py").write_text(obj["extract_py"])
    (sensor / "extract_test.py").write_text(obj["extract_test_py"])
    return sensor


# ── The decision-question generator (the LLM drafts the questions) ────

DECISIONS_SCHEMA = {
    "type": "object",
    "required": ["decisions_json"],
    "properties": {"decisions_json": {"type": "string"}},
}

DECISIONS_DOC_SCHEMA = {
    "type": "object",
    "required": ["model", "questions"],
    "properties": {
        "model": {"type": "string"},
        "questions": {"type": "object", "minProperties": 1},
    },
}

DECISIONS_TASK = """Draft the decision questions for this case's label sensor, as a
JSON document (a string) under the key "decisions_json".

Strom is a decision model: it never writes text — it answers typed
questions about the state (one evidence row) with probabilities over the
options YOU define. Question types:
- {"type": "choice", "instructions": "...", "criteria": {"<option>": "<when it applies>", ...}}
  — exactly one of the named options. The criteria descriptions say when
  each option applies; be concrete (what distinguishes them).
- {"type": "noul", "instructions": "..."} — the probability that the
  statement holds (yes/no).
- {"type": "score", "instructions": "...", "criteria": ["<level 0>", "<level 1>", ...]}
  — a position on the ordered rubric (the first level is 0).

The document:
{{
  "model": "strom-1.0.7",
  "questions": {{
    "<name>": <question>, ...
  }}
}}

REQUIRED: one "choice" question whose criteria keys are EXACTLY these
labels (the classification axis): {labels}

The instructions read as a plain question about one row ("Classify this
alert.", "Is this row a targeted attack?").

OPTIONAL: extra noul/score questions that add decision facts per row
(e.g. urgency on a rubric, "is this row from an external source?"). The
question name becomes the fact predicate — keep names camelCase and
stable (packs reference them).

Sample rows from the evidence (the file's first lines):
{{SAMPLE}}
"""


def check_decisions(doc, cfg, client=None, sample_rows=None):
    """The decision-question judge: structure (schema), label coverage (a
    choice question whose criteria keys are exactly the labels), and —
    when a client + sample rows are given — a dry run against the API
    (answers well-shaped, probabilities sane, not degenerate). Returns
    the error list (empty = accepted)."""
    errs = list(engine.validate(doc, DECISIONS_DOC_SCHEMA))
    if errs:
        return errs
    qs = doc["questions"]
    for name, q in qs.items():
        if not isinstance(name, str) or not name:
            errs.append("question names must be non-empty strings")
            continue
        if not isinstance(q, dict):
            errs.append(f"question {name!r}: must be an object")
            continue
        t = q.get("type")
        if t not in ("noul", "choice", "score"):
            errs.append(f"question {name!r}: type must be noul | choice | score")
            continue
        if not isinstance(q.get("instructions"), str) or not q["instructions"].strip():
            errs.append(f"question {name!r}: instructions must be a non-empty "
                        "string")
            continue
        if t == "choice":
            crit = q.get("criteria")
            if not isinstance(crit, dict) or not crit:
                errs.append(f"question {name!r}: choice needs a non-empty "
                            "criteria object")
            elif not all(isinstance(k, str) and isinstance(v, str)
                         and v.strip() for k, v in crit.items()):
                errs.append(f"question {name!r}: criteria values must be "
                            "non-empty descriptions")
        elif t == "score":
            crit = q.get("criteria")
            if (not isinstance(crit, list) or len(crit) < 2
                    or not all(isinstance(c, str) and c.strip() for c in crit)):
                errs.append(f"question {name!r}: score needs an ordered "
                            "criteria list of ≥2 level descriptions")
    covered = any(
        isinstance(q, dict) and q.get("type") == "choice"
        and set(q.get("criteria") or {}) == set(cfg["labels"])
        for q in qs.values())
    if not covered:
        errs.append("no choice question covers the labels exactly: "
                    + ", ".join(cfg["labels"]))
    if errs or client is None or not sample_rows:
        return errs
    # ── the dry run: every question answered, well-shaped, sane ──
    choice_answers = []
    try:
        for r in sample_rows:
            state = {k: v for k, v in r.items() if k not in ("row", "lines")}
            answers = client.ask(state, qs)["answers"]
            if set(answers) != set(qs):
                errs.append(f"dry run: answers missing for "
                            f"{sorted(set(qs) - set(answers))}")
                return errs
            for name, a in answers.items():
                if a.get("type") != qs[name]["type"]:
                    errs.append(f"dry run: answer {name!r} has type "
                                f"{a.get('type')!r}, expected "
                                f"{qs[name]['type']!r}")
                if qs[name]["type"] == "choice":
                    probs = a.get("probabilities") or {}
                    if set(probs) != set(qs[name]["criteria"]):
                        errs.append(f"dry run: choice {name!r} probabilities "
                                    "don't match the criteria")
                    elif abs(sum(probs.values()) - 1.0) > 0.05:
                        errs.append(f"dry run: choice {name!r} probabilities "
                                    f"sum to {sum(probs.values()):.3f}")
                    choice_answers.append(a)
    except Exception as exc:
        errs.append(f"dry run failed: {_short(exc)}")
        return errs
    # non-degeneracy: not every sampled row the same choice at >0.95
    if len(choice_answers) >= 3:
        picks = {a.get("choice") for a in choice_answers}
        tops = [max((a.get("probabilities") or {"": 0}).values())
                for a in choice_answers]
        if len(picks) == 1 and min(tops) > 0.95:
            errs.append("dry run is degenerate: every sampled row got the "
                        f"same choice ({picks.pop()!r}) at >0.95 — the "
                        "criteria don't distinguish the labels")
    return errs


def generate_questions(case_dir, config=None, runner=None, client=None,
                       stream=None, max_attempts=3, note=None):
    """Draft the case's Strom decision questions (sensor/decisions.json)
    with an LLM, judged by the decision-question judge in a capped
    correction loop (1 initial + max_attempts-1 revisions — the
    sensing.py pattern; an unreachable LLM fails fast). The judge's dry
    run needs a Strom client (the API is called on a row sample — a few
    thousandths of a cent). Returns the accepted decisions doc. The
    caller writes and commits the file."""
    import sensing
    case = Path(case_dir)
    cfg = config or load_config(case)
    if cfg.get("backend", "strom") == "local":
        raise LabelError(f"{case.name}: classify.json backend is 'local' — "
                         "decision questions are for the Strom tier")
    rows = _prep_rows(case, cfg, stream=stream, runner=runner)
    scored = [r for r in rows if r.get("text") is not None]
    sample_rows = scored[::max(1, len(scored) // 6)][:6] if scored else []
    sample = "\n".join(
        json.dumps({k: v for k, v in r.items() if k not in ("row", "lines")},
                   ensure_ascii=False)
        for r in sample_rows)
    task = (DECISIONS_TASK
            .replace("{{SAMPLE}}", sample)
            .replace("{labels}", json.dumps(cfg["labels"])))
    runner = runner or sensing._pi_runner
    label = f"{case.name}-decide"
    staged = sensing.staged_prompt_path(label)
    staged.parent.mkdir(parents=True, exist_ok=True)
    prompt = (f"{task}\n\n"
              "Respond with ONLY a JSON object with the key decisions_json "
              "— no prose, no markdown fences:\n\n"
              + json.dumps(DECISIONS_SCHEMA))
    for attempt in range(1, max_attempts + 1):
        staged.write_text(prompt)
        text = runner(str(staged), stream)  # RuntimeError = unreachable, fail fast
        try:
            obj = sensing.parse_and_validate(text, DECISIONS_SCHEMA)
            doc = json.loads(obj["decisions_json"])
            errs = check_decisions(doc, cfg, client=client,
                                   sample_rows=sample_rows)
        except ValueError as exc:
            errs, doc = [str(exc)], None
        if not errs:
            if note:
                note(f"attempt {attempt}/{max_attempts} accepted by the "
                     "decision-question judge")
            return doc
        if attempt < max_attempts:
            detail = "; ".join(errs[:5])
            if note:
                note(f"attempt {attempt}/{max_attempts} rejected — {detail}; "
                     "correcting")
            prev = (json.dumps(doc, indent=2)[:2000] if doc
                    else text[:2000])
            prompt = (f"{prompt}\n\nYour previous decision questions were "
                      "rejected by the judge:\n\n"
                      + "\n".join(f"- {e}" for e in errs[:8])
                      + f"\n\nPrevious decisions_json:\n{prev}\n\n"
                      "Fix it. Respond with ONLY the JSON object again.")
            continue
        raise ValueError(f"decision-question judge rejected the questions "
                         f"after {max_attempts} attempts: "
                         + "; ".join(errs[:5]))
    raise ValueError("unreachable")  # pragma: no cover


def write_decisions(case_dir, doc):
    """Write the drafted decision questions into the case's sensor/ dir
    (the artifact is meant to be committed and reviewed)."""
    case = Path(case_dir)
    sensor = case / "sensor"
    sensor.mkdir(parents=True, exist_ok=True)
    (sensor / "decisions.json").write_text(json.dumps(doc, indent=2) + "\n")
    return sensor
