#!/usr/bin/env python3
# test_retry.py — tests for the sensing correction loop (no LLM needed:
# the runner is stubbed). The judge layer's capped retry pattern:
# parse/validate/judge rejections feed back to the LLM for a correction
# turn (max_attempts); an unreachable LLM fails fast (never retried).
#
# Usage: python3 engine/test_retry.py   (exit 0 = pass)
#         make dss-test                  (selftest + this)

import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import sensing  # noqa: E402

SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["id", "name"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
        },
    },
}

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f" — {detail}" if detail and not ok else ""))


def run_stub(responses, **kwargs):
    """Run extract_structured with a stubbed runner returning the canned
    responses in order (the last one repeats). Returns (obj, calls)."""
    calls = {"n": 0}

    def runner(staged_path, stream):
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return responses[idx]

    obj = sensing.extract_structured(SCHEMA, "produce the things",
                                     runner=runner, **kwargs)
    return obj, calls["n"]


def main():
    # 1. unparseable → corrected on turn 2
    obj, n = run_stub([
        "sorry, I cannot help with that",
        '[{"id": "a", "name": "A"}]',
    ])
    check("parse error corrected on turn 2",
          obj == [{"id": "a", "name": "A"}] and n == 2, f"n={n}")

    # 2. schema violation → corrected on turn 2
    obj, n = run_stub([
        '[{"id": "a"}]',
        '[{"id": "a", "name": "A"}]',
    ])
    check("schema violation corrected on turn 2",
          obj == [{"id": "a", "name": "A"}] and n == 2, f"n={n}")

    # 3. judge (compute) rejection → corrected on turn 2
    def judge_no_a(objs):
        return ["id 'a' is reserved"] if any(o["id"] == "a" for o in objs) else []

    obj, n = run_stub(
        ['[{"id": "a", "name": "A"}]', '[{"id": "b", "name": "B"}]'],
        judge=judge_no_a)
    check("judge (compute) rejection corrected on turn 2",
          obj == [{"id": "b", "name": "B"}] and n == 2, f"n={n}")

    # 4. never valid → raises after max_attempts
    try:
        run_stub(["nope", "still nope", "nope"], max_attempts=3)
        check("capped retries raise after max_attempts", False, "no exception")
    except ValueError as exc:
        check("capped retries raise after max_attempts",
              "3 attempts" in str(exc), str(exc))

    # 5. unreachable LLM → fails fast, never retried
    calls = {"n": 0}

    def dead_runner(staged_path, stream):
        calls["n"] += 1
        raise RuntimeError("no credential reachable")

    try:
        sensing.extract_structured(SCHEMA, "produce the things", runner=dead_runner)
        check("unreachable LLM fails fast (no retry)", False, "no exception")
    except RuntimeError:
        check("unreachable LLM fails fast (no retry)", calls["n"] == 1,
              f"n={calls['n']}")

    # 6. the correction prompt carries the error and the previous response
    seen = []

    def spy_runner(staged_path, stream):
        seen.append(Path(staged_path).read_text())
        return '[{"id": "a", "name": "A"}]'

    sensing.extract_structured(SCHEMA, "produce the things",
                               runner=spy_runner, max_attempts=2)
    # first turn passes on attempt 1, so only one prompt — check the
    # happy path note instead; then force a rejection to inspect turn 2
    def spy_runner2(staged_path, stream):
        seen.append(Path(staged_path).read_text())
        return "garbage" if len(seen) == 1 else '[{"id": "a", "name": "A"}]'

    del seen[:]
    sensing.extract_structured(SCHEMA, "produce the things",
                               runner=spy_runner2, max_attempts=2)
    check("the correction turn carries the error + previous response",
          len(seen) == 2 and "rejected by the judge layer" in seen[1]
          and "garbage" in seen[1], f"prompts={len(seen)}")

    failed = RESULTS.count(False)
    print()
    print(f"{len(RESULTS) - failed}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
