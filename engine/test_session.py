#!/usr/bin/env python3
# test_session.py — the pi session scoping (no LLM needed: the session
# class is faked, like the runner stubs in test_cache.py).
#
# The rule under test: ONE pi session per run (a case phase instance).
# Within a session_scope the run's LLM calls share one session (one
# process, one conversation prefix — the provider's prompt cache hits
# across the calls, measured ~40% of the second call's input on the demo
# cases); a new scope starts a fresh session, so nothing crosses
# case/phase boundaries — the cache benefits without the bias.
#
# Usage: python3 engine/test_session.py   (or: ./facty test)

import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))
import sensing  # noqa: E402

RESULTS = []
REAL_SUMMARY = sensing.SensingSession.summary


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f" — {detail}" if detail and not ok else ""))


class FakeSession:
    """Stands in for SensingSession: records calls/closes, returns canned
    text with usage (to exercise the summary aggregation)."""

    instances = []

    def __init__(self):
        self.calls = 0
        self.usage = []
        self.closed = False
        FakeSession.instances.append(self)

    def call(self, staged_path, stream):
        self.calls += 1
        self.usage.append({"input": 1000 * self.calls,
                           "cacheRead": 0 if self.calls == 1 else 400,
                           "output": 100})
        if stream is not None:
            stream("canned line")  # the stream contract: bare lines
        return "canned response"

    def close(self):
        self.closed = True

    def summary(self):
        return REAL_SUMMARY(self)


def main():
    real = sensing.SensingSession
    sensing.SensingSession = FakeSession
    try:
        # outside a scope: every runner call gets its own one-shot session
        FakeSession.instances = []
        sensing._pi_runner("a.md", None)
        sensing._pi_runner("b.md", None)
        check("outside a scope: one session per call (nothing shared)",
              len(FakeSession.instances) == 2
              and all(s.closed for s in FakeSession.instances),
              f"{len(FakeSession.instances)} sessions")

        # inside a scope: the run's calls share ONE session (one process,
        # one conversation prefix — the provider cache hits across them)
        FakeSession.instances = []
        with sensing.session_scope() as sess:
            texts = [sensing._pi_runner(f"p{i}.md", None) for i in range(4)]
            check("the runner returns the call's text within a scope",
                  texts == ["canned response"] * 4, str(texts))
            check("within a scope: one session for the run's calls",
                  len(FakeSession.instances) == 1
                  and FakeSession.instances[0].calls == 4,
                  f"{len(FakeSession.instances)} sessions")
            check("the scope yields the shared session",
                  sess is FakeSession.instances[0])
            check("the session is open inside the scope",
                  not FakeSession.instances[0].closed)
        check("leaving the scope closes the session (pi shuts down)",
              FakeSession.instances[0].closed)

        # the scope closes the session even on error
        FakeSession.instances = []
        try:
            with sensing.session_scope():
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        check("the scope closes the session on exception",
              len(FakeSession.instances) == 1
              and FakeSession.instances[0].closed)

        # the summary aggregates the provider cache across the calls
        s = FakeSession()
        s.usage = [{"input": 1000, "cacheRead": 0, "output": 100},
                   {"input": 2000, "cacheRead": 900, "output": 100},
                   {"input": 3000, "cacheRead": 1200, "output": 100}]
        summary = s.summary()
        check("the summary reports the provider cache across the calls",
              "2100/6000" in summary and "35%" in summary
              and "3 LLM calls" in summary, summary)
        s2 = FakeSession()
        s2.usage = [{"input": 10, "cacheRead": 0, "output": 1}]
        check("the summary is empty for a single call (nothing to hit)",
              s2.summary() == "")

        # the runner streams through the session (the live contract)
        seen = []
        FakeSession.instances = []
        with sensing.session_scope():
            sensing._pi_runner("p.md", seen.append)
        check("the runner streams the call's lines through the session",
              seen == ["canned line"], str(seen))
    finally:
        sensing.SensingSession = real

    print("")
    n = len(RESULTS)
    print(f"{sum(RESULTS)}/{n} checks passed")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
