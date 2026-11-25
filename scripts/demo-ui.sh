#!/bin/sh
# demo-ui.sh — Slice 1 headless e2e: drive a demo case end to end through the
# SAME ops the Web UI calls on `facty serve`, then boot the server.
#
# Usage:
#   scripts/demo-ui.sh            # full flow + boot `facty serve` on :8080
#   scripts/demo-ui.sh --check    # run the flow, assert, exit (CI mode, no server)
#
# Env: CASE (default assembly-unpaid-invoice), BUNDLE (default
#      bundles/small-business-contract-claim), PROVE_SUBJECT/PROVE_PREDICATE
#      (default matter/demandReady), TERMINUSDB_URL (default
#      http://127.0.0.1:6363), TERMINUSDB_PASS (root), PORT (8080).
#      Second demo: CASE=verification-nobid-contracts
#      BUNDLE=bundles/public-corruption-dossier PROVE_PREDICATE=dossierReady
#      scripts/demo-ui.sh --check
#      Requires the compose terminusdb service up.
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

PORT="${PORT:-8080}"
CASE="${CASE:-assembly-unpaid-invoice}"
BUNDLE="${BUNDLE:-bundles/small-business-contract-claim}"
PROVE_SUBJECT="${PROVE_SUBJECT:-matter}"
PROVE_PREDICATE="${PROVE_PREDICATE:-demandReady}"
BR="case-$CASE"
FACTY="$PROJECT_DIR/facty"

export TERMINUSDB_URL="${TERMINUSDB_URL:-http://127.0.0.1:6363}"
export TERMINUSDB_PASS="${TERMINUSDB_PASS:-root}"

step() { printf '\033[34m==>\033[0m %s\n' "$*"; }

step "selftest (signed bundles, incl. determinism replay)"
"$FACTY" selftest | tail -1

step "case init $CASE (signed bundle gate)"
"$FACTY" case delete "$CASE" >/dev/null 2>&1 || true
"$FACTY" case init "$CASE" --bundle "$BUNDLE" | tail -1

step "ingest evidence (content-addressed originals + custody)"
"$FACTY" ingest "$BUNDLE/evidence" --source demo --case "$CASE" --no-embed | tail -1

step "load sensed facts (FACTY_SENSE=cache replay layer)"
"$FACTY" load-facts "$BUNDLE/fixtures/facts-initial.json" --ref "$BR" --message "phase 1 sensed facts (cache replay)" | tail -1

step "run engine phase 1 (deterministic: chain → prune → rank → verdict)"
OUT="$("$FACTY" run "$CASE" --ref "$BR")"
echo "$OUT" | grep -E '"winner"|H1|H2|H3'
echo "$OUT" | grep -q '"winner": "H1"' || { echo "FAIL: winner not H1"; exit 1; }

step "backward proof"
"$FACTY" prove "$PROVE_SUBJECT" "$PROVE_PREDICATE" --value true --case "$CASE" | grep -q '"provable": true' || { echo "FAIL: not provable"; exit 1; }

step "deterministic assembly"
"$FACTY" assemble "$CASE" --ref "$BR" | head -3

step "turn dispatcher (ADR-0010 §3): signed pipeline, per-turn determinism modes"
T1="$("$FACTY" turn "$CASE" --all)"
echo "$T1" | grep -q '"awaiting": "choice"' || { echo "FAIL: ranked step should await a choice"; exit 1; }
CHOICE="$(printf '%s' "$T1" | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["options"][0])')"
echo "  ranked options offered by the engine, top pick: $CHOICE"
T2="$("$FACTY" turn "$CASE" --choice "$CHOICE" --value true --all)"
echo "$T2" | grep -q '"done": true' || { echo "FAIL: turn --all should complete"; exit 1; }
echo "$T2" | grep -q '"mode": "ranked"' || { echo "FAIL: ranked turn not recorded"; exit 1; }

step "serve API smoke (same ops the UI calls)"
"$FACTY" serve --port "$PORT" >/tmp/facty-serve.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null || true' EXIT
sleep 2
curl -sf "http://127.0.0.1:$PORT/api/cases" | grep -q "$CASE" || { echo "FAIL: cases"; exit 1; }
curl -sf "http://127.0.0.1:$PORT/api/ops" | grep -q '"turn"' || { echo "FAIL: ops registry"; exit 1; }
curl -sf -X POST -H 'Content-Type: application/json' -d "{\"case\":\"$CASE\"}" "http://127.0.0.1:$PORT/api/turn" | grep -q '"done": true' || { echo "FAIL: /api/turn"; exit 1; }
curl -sf "http://127.0.0.1:$PORT/api/state?case=$CASE" | grep -q AssembledDocument || { echo "FAIL: state"; exit 1; }
curl -sf "http://127.0.0.1:$PORT/api/state?case=$CASE" | grep -q '"@type": "Turn"' || { echo "FAIL: state has no Turn docs"; exit 1; }
curl -sf -X POST -H 'Content-Type: application/json' -d "{\"case\":\"$CASE\",\"text\":\"demo comment\",\"screen\":\"bullseye\"}" "http://127.0.0.1:$PORT/api/feedback" | grep -q '"@type": "Feedback"' || { echo "FAIL: feedback add"; exit 1; }
curl -sf "http://127.0.0.1:$PORT/api/feedback?case=$CASE" | grep -q "demo comment" || { echo "FAIL: feedback list"; exit 1; }
curl -sf -N --max-time 2 "http://127.0.0.1:$PORT/api/watch?case=$CASE" | grep -q "event: state" || { echo "FAIL: SSE"; exit 1; }
curl -sf "http://127.0.0.1:$PORT/" | grep -q "<div id=\"app\">" || { echo "FAIL: UI not served"; exit 1; }

if [ "${1:-}" = "--check" ]; then
  echo "DEMO-UI CHECK PASS — http://127.0.0.1:$PORT/ (case $CASE)"
  exit 0
fi

step "open the demo"
echo ""
echo "  http://127.0.0.1:$PORT/   (case: $CASE — bundle $BUNDLE)"
echo "  try: intent box → run engine → click H1 in the graph → assemble → print/PDF"
echo ""
wait $SRV
