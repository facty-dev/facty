"""Codemode (programmatic, not interactive): the LLM WRITES an extractor, the
sandbox RUNS it, and we validate its JSON output against a pydantic model.

This is the sensing-side answer to "LLM as parser/NLU engine under our control":
  1. pydantic-ai (typed output, tools=[]) asks the model to write a self-contained
     Python script that reads the evidence file (argv[1]) and prints JSON.
  2. sandbox.run_code executes it isolated (SmolVM when available, local --dev),
     with a hard timeout — never in an interactive chat, never in the verdict path.
  3. stdout JSON is validated against the target model (e.g. SensedFacts).

Determinism: the recorded facts + the LLM response cache are the deterministic
layer; codemode output is induction-only, same as any sensing op.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from . import sandbox, sensing

CODEGEN_INSTRUCTIONS = """You write ONE self-contained Python 3 script. Rules:
- It will be run as `python -I main.py <evidence-file>` in a sandbox with stdlib only.
- Read the evidence file from sys.argv[1]; print ONLY a JSON object to stdout
  matching this schema: {schema}
- No network, no file writes, no imports beyond the stdlib. Exit 0 on success.
- Do not editorialize; extract faithfully. If a field is unknown, use null.
"""


class CodegenScript(BaseModel):
    code: str
    notes: str = ""


def codemode_extract(file_path: str | Path, output_model: type[BaseModel],
                     timeout: float = 60.0, backend: str = "auto",
                     vocab: dict | None = None) -> tuple[BaseModel, dict]:
    """LLM writes an extractor for `file_path`; sandbox runs it; stdout is
    validated as `output_model`. Returns (parsed_output, sandbox_result).
    `vocab` = the bundle's exact subject/predicate strings the engine matches
    literally — pass it so the extractor emits engine-compatible facts."""
    file_path = Path(file_path)
    schema = json.dumps(output_model.model_json_schema(), indent=1)[:4000]
    data = file_path.read_bytes()
    if len(data) > 200_000:
        data = data[:200_000]  # cap the bytes we hand to the sandbox
    vocab_block = ""
    if vocab:
        vocab_block = ("\nCRITICAL: use ONLY these exact subject strings: "
                       + json.dumps(vocab.get("subjects", []))
                       + " and ONLY these exact predicate strings: "
                       + json.dumps(vocab.get("predicates", []))
                       + ". Do not paraphrase or invent terms — the symbolic engine "
                         "matches these strings literally.\n")
    prompt = (CODEGEN_INSTRUCTIONS.replace("{schema}", schema) + vocab_block
              + f"\n\nEVIDENCE FILE ({file_path.name}, {len(data)} bytes, text follows):\n"
              + data.decode("utf-8", errors="replace"))
    script = sensing.sense_json(prompt, CodegenScript)
    if hasattr(script, "model_dump"):
        script = script.model_dump()
    res = sandbox.run_code(script["code"], files={file_path.name: data},
                           timeout=timeout, backend=backend)
    if not res["ok"]:
        raise RuntimeError(f"codemode sandbox failed (exit {res['exit_code']}): {res['stderr'][:500]}")
    payload = json.loads(res["stdout"].strip().splitlines()[-1])
    return output_model.model_validate(payload), res
