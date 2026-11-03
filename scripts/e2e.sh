#!/usr/bin/env bash
# e2e.sh — end-to-end demo of the Facty engine (TerminusDB-backed) on a realistic knowledge pack
# (insurance-claim-fraud): LLM senses the evidence, the deterministic engine on
# TerminusDB does the abduction and owns the verdict.
#
# Usage:
#   scripts/e2e.sh                 # offline: golden facts, no LLM key needed
#   scripts/e2e.sh --live          # live sensing via pydantic-ai (mistral-large-4)
#   scripts/e2e.sh --case <dir>    # default packs/insurance-claim-fraud
#
# Env: TERMINUSDB_URL (default http://127.0.0.1:6363), TERMINUSDB_DB (default facty-e2e),
#      MISTRAL_API_KEY (only for --live), FACTY_SENSE=cache forces offline.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

LIVE=0
KEEP=0
CASE_DIR="$PROJECT_DIR/packs/insurance-claim-fraud"
while [ $# -gt 0 ]; do
  case "$1" in
    --live) LIVE=1; shift;;
    --keep) KEEP=1; shift;;   # reuse the existing db (idempotent re-run)
    --case) CASE_DIR="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 1;;
  esac
done

export TERMINUSDB_DB="${TERMINUSDB_DB:-facty-e2e}"
REF="case-$(basename "$CASE_DIR")-demo"
DROP="$PROJECT_DIR/demos/fraud-phase2-drop.json"
PY="uv run python -m facty"
cd "$PROJECT_DIR"

step() { printf '\n=== %s ===\n' "$1"; }

step "0. TerminusDB health + fresh db (start the server first: docker compose -f compose.yaml up -d; --keep to reuse)"
curl -sf -u "${TERMINUSDB_USER:-admin}:${TERMINUSDB_PASS:-root}" \
  "${TERMINUSDB_URL:-http://127.0.0.1:6363}/api/ok" && echo " ok"
if [ "$KEEP" = "0" ]; then
  curl -sf -u "${TERMINUSDB_USER:-admin}:${TERMINUSDB_PASS:-root}" \
    -X DELETE "${TERMINUSDB_URL:-http://127.0.0.1:6363}/api/db/${TERMINUSDB_ORG:-admin}/$TERMINUSDB_DB" >/dev/null 2>&1 || true
  echo "db $TERMINUSDB_DB reset"
fi

step "1. init-db (create + install the artifact-model schema)"
$PY init-db

step "2. load-pack $CASE_DIR (rules + hypotheses + constraints as schema-validated documents)"
$PY load-pack "$CASE_DIR" --name "$(basename "$CASE_DIR")"

step "3. facts — the LLM's only job: read evidence into facts (confidence + source spans)"
if [ "$LIVE" = "1" ]; then
  [ -n "${MISTRAL_API_KEY:-}" ] || { echo "MISTRAL_API_KEY required for --live" >&2; exit 1; }
  $PY sense "$CASE_DIR" --out .cache/e2e-facts-live.json
  FACTS=.cache/e2e-facts-live.json
  echo "(live-sensed $(uv run --python 3.14 python -c "import json;print(len(json.load(open('$FACTS'))))") facts; golden set has $(uv run --python 3.14 python -c "import json;print(len(json.load(open('$CASE_DIR/terminusdb/facts-staged.json'))))") — drift is reported, never decided on)"
else
  FACTS="$CASE_DIR/terminusdb/facts-staged.json"
  echo "offline mode: using golden facts $FACTS (FACTY_SENSE=cache equivalent)"
fi
$PY load-facts "$FACTS" --message "phase 1 facts"

step "4. run phase 1 on branch $REF — engine only: chain, prune, rank (no LLM call)"
$PY run "$(basename "$CASE_DIR")" --phase 1 --ref "$REF"

step "5. determinism proof A — verdict doc hash, then re-run with NO API key and cache mode"
H1=$(env -u MISTRAL_API_KEY FACTY_SENSE=cache $PY verdict --ref "$REF" | jq -S . | sha256sum | cut -d' ' -f1)
env -u MISTRAL_API_KEY FACTY_SENSE=cache $PY run "$(basename "$CASE_DIR")" --phase 1 --ref "$REF" >/dev/null
H2=$(env -u MISTRAL_API_KEY FACTY_SENSE=cache $PY verdict --ref "$REF" | jq -S . | sha256sum | cut -d' ' -f1)
echo "verdict hash before: $H1"
echo "verdict hash after : $H2 (run executed with MISTRAL_API_KEY unset — no LLM in the verdict path)"
[ "$H1" = "$H2" ] && echo "DETERMINISM OK: byte-identical verdict on replay" || { echo "DETERMINISM FAIL" >&2; exit 1; }

step "6. capture branch head commit (for time-travel replay)"
COMMIT=$(curl -sf -u "${TERMINUSDB_USER:-admin}:${TERMINUSDB_PASS:-root}" \
  "${TERMINUSDB_URL:-http://127.0.0.1:6363}/api/log/${TERMINUSDB_ORG:-admin}/$TERMINUSDB_DB" \
  | jq -r '.[0].identifier // .[0].id // empty')
echo "head commit: ${COMMIT:-<unparsed>}"

step "7. phase 2 — apply the discriminating-test results (new evidence drop) and re-run"
$PY load-facts "$DROP" --message "phase 2: discriminating tests applied" --ref "$REF"
$PY run "$(basename "$CASE_DIR")" --phase 2 --ref "$REF"

step "8. determinism proof B — time-travel: verdict at the phase-1 commit"
if [ -n "${COMMIT:-}" ]; then
  TERMINUSDB_REF="commit:$COMMIT" $PY verdict | jq -r '.[] | select(.phase=="1") | .id'
  echo "(phase-1 verdict replayed from the immutable commit — the audit trail)"
fi

step "9. the trace — derivations and prunes as committed graph data"
$PY run "$(basename "$CASE_DIR")" --phase 2 --ref "$REF" >/dev/null  # idempotent re-run
uv run --python 3.14 python - "$REF" <<'PYEOF'
import json, os, sys
from facty.client import Client
c = Client(); c.ref = sys.argv[1]
docs = c.get_all_docs()
for d in docs:
    if d.get("@type") == "Derivation":
        print(f"  {d['id']}: {d['fact']}  <- {d['rule']}  <- {d['via']}")
for d in docs:
    if d.get("@type") == "Hypothesis" and d.get("status") == "pruned":
        print(f"  pruned {d['id']} by {d.get('prunedBy')}")
v = [d for d in docs if d.get("@type") == "Verdict" and d["phase"] == "2"]
if v:
    print("  verdict:", v[0].get("winner"), "| ranking:",
          [(r["hypothesis"], r["score"]) for r in v[0]["ranking"]])
PYEOF

step "DONE — summary"
echo "LLM role: extracted facts only (step 3). Engine role: everything else (steps 4-9)."
echo "Verdicts replay byte-identically (step 5) and time-travel from commits (step 8)."
