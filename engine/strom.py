#!/usr/bin/env python3
# strom.py — the Strom decision tier: a hosted decision-model client
# (Uprelic, Berlin; EU/Paris GPUs) for the label sensor's decider tier.
#
# Strom is a decision API, not a chat model: send the state (one evidence
# row) plus named typed questions; it answers each with a probability
# over the options YOU define — noul = P(yes), choice = one of your
# options (with probabilities for all), score = a position on your
# rubric — and it never writes text, so it can't break the schema or
# invent an option. Probabilities are calibrated (answers at 0.9 are
# right ~90% of the time, on the vendor's held-out data — and measured
# 100% on the 0.9+ bins of our demo pile).
#
# Posture:
#   - the verdict path never calls Strom — induction only (ADR-0003 §1,
#     the same rule as the local classifier);
#   - the key comes from UPRELIC_API_KEY (env / gondolin host-secret
#     injection) — never logged, never in files, never in error text;
#   - the client is stdlib-only (urllib) — the engine core + CLI stay
#     dependency-free and run in the gondolin VM snapshot;
#   - EU hosting (Paris), no third-party AI provider, request contents
#     deleted after 90 days and never used for training (zero data
#     retention available on request / Enterprise).
#
# Library:
#   from strom import from_env, choice, noul, score
#   client = from_env()
#   resp = client.ask({"message": "..."}, {
#       "cls": choice("Classify this alert.", {"a targeted attack": "...", ...}),
#       "urgent": score("How urgent?", ["Can wait", "This week", "Today"]),
#   })
#   resp["answers"]["cls"]["probabilities"]

import json
import os
import threading
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://api.uprelic.com/v1"
DEFAULT_MODEL = "strom-1.0.7"
DEFAULT_RPM = 480  # under the documented 500 req/min account limit
ENV_KEY = "UPRELIC_API_KEY"


class StromError(RuntimeError):
    """Base — a decider-tier failure (typed below). Never carries the key."""


class AuthError(StromError):
    """401 — missing or wrong key."""


class BalanceError(StromError):
    """402 — the prepaid balance is empty (top up in the console)."""


class InvalidRequest(StromError):
    """400/413/422 — the request is malformed (a bug in our call)."""


class RateLimit(StromError):
    """429 — still limited after the retries (500 req/min, 8 concurrent)."""


class ServerError(StromError):
    """5xx — the API failed after the retries."""


class Unreachable(StromError):
    """DNS/TCP/timeout — the API could not be reached."""


def from_env(**kwargs):
    """Build a client from UPRELIC_API_KEY. Raises StromError with the
    posture hint when the key is missing — a missing key cannot be
    corrected by a retry, so callers fail fast (or skip the tier)."""
    key = os.environ.get(ENV_KEY)
    if not key:
        raise StromError(
            f"{ENV_KEY} is not set — the decider tier (Strom) needs it. "
            "Set it in the environment (in the VM it arrives via gondolin's "
            "host-secret injection); never commit it. Without it the label "
            "sensor runs the local tier only.")
    return Client(key, **kwargs)


def choice(instructions, criteria):
    """A choice question: exactly one of the named options. criteria maps
    option name → when it applies (a string; the model goes by the
    descriptions — be concrete)."""
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def noul(instructions, criteria=None):
    """A noul question: the probability that the statement holds."""
    q = {"type": "noul", "instructions": instructions}
    if criteria is not None:
        q["criteria"] = criteria
    return q


def score(instructions, criteria):
    """A score question: a position on the ordered rubric (first = 0)."""
    return {"type": "score", "instructions": instructions, "criteria": criteria}


class Client:
    """The Strom /systemone client: stdlib-only, throttled to the
    documented account limit, retrying 429/5xx/connection failures
    (2 retries, exponential backoff — the official SDK's behavior).
    The key is held in memory and sent as a Bearer token; it never
    appears in errors, logs, or cache entries."""

    def __init__(self, key, base_url=DEFAULT_BASE, model=DEFAULT_MODEL,
                 rpm=DEFAULT_RPM, timeout=60, retries=2, sleep=time.sleep):
        self.key = key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self._sleep = sleep
        self._interval = 60.0 / rpm if rpm else 0.0
        self._gate = threading.Lock()
        self._next = 0.0

    def _throttle(self):
        if not self._interval:
            return
        with self._gate:
            wait = self._next - time.monotonic()
            if wait > 0:
                self._sleep(wait)
            self._next = time.monotonic() + self._interval

    def ask(self, state, questions):
        """POST /systemone: one state + named questions → typed answers.
        Returns the parsed response ({model, answers, usage, metadata}).
        Raises the typed errors; 429/5xx/connection are retried."""
        body = json.dumps({"model": self.model, "state": state,
                           "questions": questions}).encode()
        last = None
        for attempt in range(self.retries + 1):
            self._throttle()
            req = urllib.request.Request(
                self.base_url + "/systemone", data=body, method="POST",
                headers={"Authorization": f"Bearer {self.key}",
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.load(r)
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                if exc.code == 401:
                    raise AuthError(f"Strom 401 — the API key is missing or "
                                    f"wrong ({detail or 'no detail'})")
                if exc.code == 402:
                    raise BalanceError("Strom 402 — the prepaid balance is "
                                       "empty (top up in the console)")
                if exc.code in (400, 413, 422):
                    raise InvalidRequest(f"Strom {exc.code} — the request is "
                                         f"malformed: {detail or 'no detail'}")
                last = f"HTTP {exc.code}"
                if exc.code == 429 and attempt < self.retries:
                    self._sleep(2 ** attempt)
                    continue
                if exc.code == 429:
                    raise RateLimit("Strom 429 — still rate-limited after "
                                    f"{self.retries} retries (500 req/min, "
                                    "8 concurrent per account)")
                if attempt < self.retries:
                    self._sleep(2 ** attempt)
                    continue
                raise ServerError(f"Strom 5xx — the API failed after "
                                  f"{self.retries} retries ({last})")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = f"{type(exc).__name__}: {exc}"
                if attempt < self.retries:
                    self._sleep(2 ** attempt)
                    continue
                raise Unreachable(f"Strom unreachable — {last}")
        raise Unreachable(f"Strom unreachable — {last}")  # pragma: no cover
