#!/usr/bin/env bash
# scripts/demo.sh — the realistic end-to-end demo: a signed bundle + real evidence
# files go through the full neurosymbolic loop on the headless CLI:
#
#   case init → ingest (content-addressed originals) → sense (LIVE LLM: evidence→facts)
#   → run phase 1 (deterministic engine: chain/prune/rank, opens discriminating
#   questions) → apply the discriminating-test drop → run phase 2 → verdict.
#
# Usage: bash scripts/demo.sh [--cache]     (--cache replays sensed facts, no LLM key needed)
# Env:   TERMINUSDB_DB (default facty-demo), MISTRAL_API_KEY for live sensing
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

DB="${TERMINUSDB_DB:-facty-demo}"
CASE="claim-2026-014"
BUNDLE="$PROJECT_DIR/bundles/insurance-claim-fraud"
REF="case-$CASE"
PY="uv run python -m facty"
CACHE=0
for a in "$@"; do [ "$a" = "--cache" ] && CACHE=1; done

step() { printf '\n=== %s ===\n' "$1"; }

step "0. fresh db $DB (TerminusDB must be up: docker compose -f compose.yaml up -d)"
curl -sf -u "${TERMINUSDB_USER:-admin}:${TERMINUSDB_PASS:-root}" \
  "${TERMINUSDB_URL:-http://127.0.0.1:6363}/api/ok" >/dev/null && echo "ok"
curl -sf -u admin:root -X DELETE "http://127.0.0.1:6363/api/db/admin/$DB" >/dev/null 2>&1 || true
TERMINUSDB_DB="$DB" $PY init-db

step "1. case init $CASE — branch case-$CASE + SIGNED bundle gate"
TERMINUSDB_DB="$DB" $PY bundle verify "$BUNDLE"
TERMINUSDB_DB="$DB" $PY case init "$CASE" --bundle "$BUNDLE"

step "2. ingest evidence — content-addressed originals, custody manifest, parsers"
TERMINUSDB_DB="$DB" $PY ingest "$BUNDLE/evidence" --source "claim-file" --case "$CASE"

step "3. sense — the LLM's ONLY job: read the ingested evidence into facts"
if [ "$CACHE" = "1" ]; then
  echo "(cache mode: replaying golden facts)"
  cp "$BUNDLE/fixtures/facts-staged.json" .cache/demo-facts.json 2>/dev/null || mkdir -p .cache && cp "$BUNDLE/fixtures/facts-staged.json" .cache/demo-facts.json
else
  mkdir -p .cache
  TERMINUSDB_DB="$DB" $PY sense --case "$CASE" --out .cache/demo-facts.json
fi
TERMINUSDB_DB="$DB" $PY load-facts .cache/demo-facts.json --ref "$REF" --message "phase 1: sensed facts"

step "4. run phase 1 — engine only: forward chain, prune, rank; opens discriminating questions"
TERMINUSDB_DB="$DB" $PY run "$CASE" --phase 1 --ref "$REF"

step "5. phase 2 — the discriminating test comes back (new evidence drop), re-run"
TERMINUSDB_DB="$DB" $PY run "$CASE" --phase 2 --ref "$REF" --add-facts "$PROJECT_DIR/demos/fraud-phase2-drop.json"

step "6. the audit trail — case manifest, docs, commit log"
TERMINUSDB_DB="$DB" $PY case show "$CASE" | head -30
TERMINUSDB_DB="$DB" $PY log --ref "$REF" | python3 -c "import json,sys; [print(c['@id'][:12], c.get('message','')) for c in json.load(sys.stdin)]" | tail -8

step "DONE — verdict above; trace is committed graph data on branch $REF"
