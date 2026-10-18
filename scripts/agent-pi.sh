#!/usr/bin/env bash
# agent-pi.sh — Run an SDLC agent (decision|coding) inside the gondolin-pi VM.
#
# PRD-003 (agent orchestration), pi-VM runtime: each agent run boots pi in
# the gondolin micro-VM (the image config vendored in this repo at gondolin/)
# with this repo mounted at /workspace. Agents read/write repo assets
# directly; every run is appended to .agentic/audit.jsonl.
#
# Usage:
#   ./scripts/agent-pi.sh decision --phase <discovery|prd|bdd|review> [--task "<task>"]
#   ./scripts/agent-pi.sh coding  --task <task-file> [--bdd <bdd-file>]
#
# Env:
#   AGENT_MODEL / AGENT_THINKING  per-run overrides
#     defaults: decision → mistral-large-4 / max   (strong reasoner)
#               coding   → mistral-large-4 / low   (fast implementation)
#   GONDOLIN_PI  path to gondolin-pi.sh
#     (default: <repo>/gondolin/gondolin-pi.sh — the vendored image config)
#   MISTRAL_API_KEY  required by the ephemeral VM runtime (passed as host-secret)
#   AGENT_RUNTIME  runtime selection:
#     auto        (default) use the SDLC VM session if reachable, else ephemeral boot
#     session     require the SDLC VM session; fail if none is reachable
#     ephemeral   skip session detection; boot an ephemeral VM (CI mode)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AUDIT_FILE="$PROJECT_DIR/.agentic/audit.jsonl"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLUE}ℹ${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

usage() {
  sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

[[ $# -ge 2 ]] || usage
ROLE="$1"; shift

PHASE=""
TASK=""
BDD=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase) PHASE="${2:-}"; shift 2 ;;
    --task)  TASK="${2:-}";  shift 2 ;;
    --bdd)   BDD="${2:-}";   shift 2 ;;
    *) err "unknown arg: $1"; usage ;;
  esac
done

GONDOLIN_PI="${GONDOLIN_PI:-$PROJECT_DIR/gondolin/gondolin-pi.sh}"
[[ -x "$GONDOLIN_PI" ]] || { err "gondolin-pi.sh not found: $GONDOLIN_PI (build it: make vm-image)"; exit 1; }

# ── Runtime selection ────────────────────────────────────────────────────────
AGENT_RUNTIME="${AGENT_RUNTIME:-auto}"
case "$AGENT_RUNTIME" in
  auto|session|ephemeral) ;;
  *) err "invalid AGENT_RUNTIME: $AGENT_RUNTIME (expected auto|session|ephemeral)"; usage ;;
esac

# ── Run-mode detection ───────────────────────────────────────────────────────
# Preferred: a long-lived SDLC VM session booted OUTSIDE the sandbox
# (make vm-up) — the API key lives host-side in that session; this script
# and the sandboxed agent driving it never see the real value.
# Fallback: ephemeral boot via gondolin-pi.sh — needs the key in this
# process env (or, unsandboxed, the stored pi credential).
VM_SESSION="./scripts/vm-session.sh"
SESSION_SID=""
if [[ "$AGENT_RUNTIME" != "ephemeral" ]]; then
  SESSION_SID="$("$PROJECT_DIR/$VM_SESSION" status 2>/dev/null | awk '/^session:/ {print $2}')"
fi
if [[ -n "$SESSION_SID" ]]; then
  RUN_MODE="gondolin-pi-session"
elif [[ "$AGENT_RUNTIME" == "session" ]]; then
  err "AGENT_RUNTIME=session but no SDLC VM session is reachable"
  err "run 'make vm-up' from your terminal, then retry"
  exit 1
else
  RUN_MODE="gondolin-pi"
  if [[ -z "${MISTRAL_API_KEY:-}" ]]; then
    if _key="$(pi auth print-api-key --provider mistral 2>/dev/null)" \
       && [[ -n "$_key" && "$_key" != "null" ]]; then
      export MISTRAL_API_KEY="${_key//\"/}"
      info "using stored mistral credential (pi auth)"
    else
      err "no SDLC VM session running and no API key available"
      err "preferred: run 'make vm-up' from your terminal (key stays host-side)"
      err "fallback: export MISTRAL_API_KEY in the shell that launches pi"
      exit 1
    fi
  fi
fi

# ── Role config ──────────────────────────────────────────────────────────────
case "$ROLE" in
  decision)
    MODEL="${AGENT_MODEL:-mistral-large-4}"
    THINKING="${AGENT_THINKING:-max}"
    [[ -n "$PHASE" ]] || { err "decision agent requires --phase"; usage; }
    case "$PHASE" in discovery|prd|bdd|review) ;; *) err "invalid phase: $PHASE"; exit 1 ;; esac
    ROLE_PROMPT="$PROJECT_DIR/templates/sdlc/agents/decision.md"
    ;;
  coding)
    MODEL="${AGENT_MODEL:-mistral-large-4}"
    THINKING="${AGENT_THINKING:-low}"
    [[ -n "$TASK" && -f "$PROJECT_DIR/$TASK" ]] || { err "coding agent requires --task <file> (repo-relative)"; exit 1; }
    ROLE_PROMPT="$PROJECT_DIR/templates/sdlc/agents/coding.md"
    ;;
  *)
    err "unknown role: $ROLE"; usage ;;
esac

# ── Build prompt: role template + phase/task directives ──────────────────────
PROMPT="$(cat "$ROLE_PROMPT")

---

## Current assignment

"
case "$ROLE" in
  decision)
    PROMPT+="Phase: **${PHASE}**

Task:
${TASK:-<no explicit task — follow the phase workflow>}"
    ;;
  coding)
    PROMPT+="Task (from $(cat "$PROJECT_DIR/$TASK" >/dev/null && echo "$TASK")):

$(cat "$PROJECT_DIR/$TASK")"
    if [[ -n "$BDD" ]]; then
      PROMPT+="

BDD feature file: ${BDD}"
    fi
    PROMPT+="

The task file above lives at ${TASK}; read it and any files it references before writing code."
    ;;
esac

# ── Run the agent in the VM ──────────────────────────────────────────────────
mkdir -p "$(dirname "$AUDIT_FILE")" "$PROJECT_DIR/.agentic/tmp"
info "running ${ROLE} agent (${PHASE:-${TASK}}) in gondolin VM (runtime: ${AGENT_RUNTIME})"
if [[ "$RUN_MODE" == "gondolin-pi-session" ]]; then
  info "via SDLC VM session: $SESSION_SID (key held host-side)"
else
  info "via ephemeral boot (gondolin-pi)"
fi
info "model: ${MODEL} (thinking: ${THINKING})"

START_EPOCH=$(date +%s)
set +e
if [[ "$RUN_MODE" == "gondolin-pi-session" ]]; then
  # Pass the prompt via @file to avoid multi-KB args over the session socket.
  PROMPT_NAME="run-${ROLE}-$(date +%s).md"
  printf '%s\n' "$PROMPT" > "$PROJECT_DIR/.agentic/tmp/$PROMPT_NAME"
  "$PROJECT_DIR/$VM_SESSION" exec -- bash -lc \
    "set -a; . /root/.session-env/mistral.sh 2>/dev/null || true; set +a; cd /workspace && exec pi -p --no-session --model '$MODEL' --thinking '$THINKING' '@/workspace/.agentic/tmp/$PROMPT_NAME'"
  RUN_RC=$?
  rm -f "$PROJECT_DIR/.agentic/tmp/$PROMPT_NAME"
else
  # Ephemeral path: stage the prompt as a file and pass a short pointer.
  # Multi-KB/multiline prompts break gondolin's --env arg handling (the value
  # gets re-split by the CLI); @file avoids the issue entirely and matches
  # the session path's mechanism.
  PROMPT_NAME="run-${ROLE}-$(date +%s).md"
  printf '%s\n' "$PROMPT" > "$PROJECT_DIR/.agentic/tmp/$PROMPT_NAME"
  PI_MODEL="$MODEL" PI_THINKING="$THINKING" \
    "$GONDOLIN_PI" "$PROJECT_DIR" -p "Read your complete assignment in @.agentic/tmp/$PROMPT_NAME and execute it in full."
  RUN_RC=$?
  rm -f "$PROJECT_DIR/.agentic/tmp/$PROMPT_NAME"
fi
set -e
DURATION=$(( $(date +%s) - START_EPOCH ))

# ── Audit trail ──────────────────────────────────────────────────────────────
jq -cn \
  --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg role "$ROLE" \
  --arg phase "${PHASE:-}" \
  --arg task "${TASK:-}" \
  --arg model "$MODEL" \
  --arg thinking "$THINKING" \
  --arg runtime "$RUN_MODE" \
  --argjson rc "$RUN_RC" \
  --argjson duration "$DURATION" \
  '{timestamp:$ts, type:"agent-run", role:$role, phase:$phase, task:$task,
    model:$model, thinking:$thinking, runtime:$runtime,
    exit_code:$rc, duration_s:$duration}' >> "$AUDIT_FILE"

if [[ $RUN_RC -eq 0 ]]; then
  ok "${ROLE} agent finished in ${DURATION}s (audited)"
else
  err "${ROLE} agent failed (rc=${RUN_RC}) after ${DURATION}s (audited)"
fi
exit $RUN_RC
