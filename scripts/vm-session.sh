#!/usr/bin/env bash
# vm-session.sh — Manage the long-lived drawbridge SDLC VM session.
#
# Secrets model (gondolin): the session is created OUTSIDE the agent sandbox
# (`make vm-up` from your own terminal). The API key is injected host-side at
# boot (--host-secret): the guest and any sandboxed agent that attaches via
# session IPC only ever see placeholders — real values exist only in the
# session's host-side proxy and are substituted into outbound requests to
# allowed hosts.
#
# IMPORTANT (sandbox interaction): `gondolin list`/`exec-by-id` garbage-collect
# sessions whose owning PID cannot be signaled (process.kill(pid, 0)). From
# inside the pi-sandbox, signaling the session's host process is DENIED, so
# those commands would misclassify a live session as stale and DELETE its
# registry files. Therefore this script never uses id-based discovery from
# the sandboxed side: `up` records {id,pid,socketPath} to
# .agentic/vm-session.json (via a user-side watcher), and `exec`/`status`
# use the SOCKET PATH only (which bypasses the GC).
#
# Usage:
#   ./scripts/vm-session.sh up              # boot session (from YOUR terminal)
#   ./scripts/vm-session.sh status          # show session state (sandbox-safe)
#   ./scripts/vm-session.sh exec -- <cmd…>  # run a command inside the VM
#   ./scripts/vm-session.sh down            # stop the session (from YOUR side)
#
# Env:
#   MISTRAL_API_KEY      boot-time source for the host-secret; falls back
#                        to `pi auth print-api-key` (stored credential —
#                        only readable outside the pi-sandbox)
#   PI_SNAPSHOT          VM snapshot (default: gondolin-pi template's)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLUE}ℹ${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

SESSION_TAG="drawbridge-sdlc-vm"
SESSION_META="$PROJECT_DIR/.agentic/vm-session.json"
SESSIONS_DIR="${GONDOLIN_SESSIONS_DIR:-$HOME/.cache/gondolin/sessions}"
SNAP="${PI_SNAPSHOT:-/Users/chart/code/gondolin-pi/snapshots/pi-sandbox.qcow2}"

# Probe liveness by connecting to the session socket (no pid signaling).
socket_alive() {
  local sock="$1"
  [[ -n "$sock" && -S "$sock" ]] || return 1
  python3 - "$sock" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket(socket.AF_UNIX)
s.settimeout(2)
try:
    s.connect(sys.argv[1])
except OSError:
    sys.exit(1)
sys.exit(0)
PY
}

meta_sock() { jq -r '.socketPath // empty' "$SESSION_META" 2>/dev/null; }
meta_pid()  { jq -r '.pid // empty'        "$SESSION_META" 2>/dev/null; }
meta_id()   { jq -r '.id // empty'         "$SESSION_META" 2>/dev/null; }

session_up() {
  local sock; sock="$(meta_sock)"
  [[ -n "$sock" ]] && socket_alive "$sock"
}

resolve_key() {
  if [[ -n "${MISTRAL_API_KEY:-}" ]]; then return 0; fi
  if _key="$(pi auth print-api-key --provider mistral 2>/dev/null)" \
     && [[ -n "$_key" && "$_key" != "null" ]]; then
    export MISTRAL_API_KEY="${_key//\"/}"
    info "using stored mistral credential (pi auth)"
    return 0
  fi
  err "MISTRAL_API_KEY not set and no stored credential readable"
  err "(run vm-up from an unsandboxed shell: your terminal or pi's ! escape)"
  exit 1
}

cmd_up() {
  if session_up; then
    ok "SDLC VM session already running: $(meta_id)"
    return 0
  fi
  [[ -e "$SNAP" ]] || { err "snapshot not found: $SNAP"; exit 1; }
  resolve_key

  # User-side watcher: record the session metadata once gondolin registers
  # it. Runs in YOUR (unsandboxed) shell, where pid checks behave correctly.
  (
    for _ in $(seq 1 60); do
      f="$(grep -l "$SESSION_TAG" "$SESSIONS_DIR"/*.json 2>/dev/null | head -1 || true)"
      if [[ -n "$f" ]]; then
        mkdir -p "$(dirname "$SESSION_META")"
        cp "$f" "$SESSION_META"
        break
      fi
      sleep 2
    done
  ) &

  info "starting SDLC VM session (foreground — this terminal hosts the session)"
  info "KEEP THIS TERMINAL OPEN: the session lives as long as this process"
  info "to peek from another terminal: gondolin attach $(meta_id || echo '<session-id>')"
  info "  (Ctrl-] there detaches safely; but Ctrl-] HERE kills the session)"
  info "to stop: make vm-down (or close this guest shell with exit)"
  exec gondolin bash \
    --rootfs-size 4G \
    --resume "$SNAP" \
    --mount-hostfs "$PROJECT_DIR:/workspace" \
    --allow-host api.mistral.ai \
    --allow-host duckduckgo.com \
    --allow-host html.duckduckgo.com \
    --allow-host lite.duckduckgo.com \
    --allow-host registry.npmjs.org \
    --host-secret MISTRAL_API_KEY@api.mistral.ai \
    -- bash -c "mkdir -p /root/.agents/skills /root/.session-env; umask 077; [ -n \"\${MISTRAL_API_KEY:-}\" ] && printf 'export MISTRAL_API_KEY=%s\\n' \"\$MISTRAL_API_KEY\" > /root/.session-env/mistral.sh; for s in /opt/skills/*/; do ln -sfn \"\$s\" \"/root/.agents/skills/\$(basename \"\$s\")\"; done; [ -f /opt/skills/SKILL-INDEX.md ] && ln -sfn /opt/skills/SKILL-INDEX.md /root/.agents/SKILL-INDEX.md; touch /root/.vm-ready; cd /workspace; exec bash -l # $SESSION_TAG"
}

cmd_status() {
  if ! session_up; then
    echo "status: down (run: make vm-up)"
    [[ -f "$SESSION_META" ]] && echo "note: stale metadata at $SESSION_META"
    return 0
  fi
  echo "status: up"
  echo "session: $(meta_id)"
  echo "project: $PROJECT_DIR -> /workspace"
  echo "egress: api.mistral.ai, duckduckgo.com (+html/lite), registry.npmjs.org"
  echo "secrets: MISTRAL_API_KEY (host-side placeholder substitution)"
}

cmd_exec() {
  session_up || { err "no live SDLC VM session (socket unreachable)"; exit 1; }
  # Socket PATH (not session id) — bypasses gondolin's pid-based session GC,
  # which misfires under the pi-sandbox and would delete the session files.
  exec gondolin exec --sock "$(meta_sock)" -- "$@"
}

cmd_down() {
  local pid; pid="$(meta_pid)"
  if [[ -z "$pid" ]]; then
    err "no session metadata at $SESSION_META"
    exit 1
  fi
  if kill "$pid" 2>/dev/null; then
    ok "SDLC VM session stopped (pid $pid)"
  else
    warn "cannot signal pid $pid — run 'make vm-down' from your own terminal"
    warn "(the pi-sandbox denies cross-process signals from sandboxed agents)"
    exit 1
  fi
  rm -f "$SESSION_META"
}

case "${1:-}" in
  up)     shift; cmd_up "$@" ;;
  status) shift; cmd_status "$@" ;;
  exec)   shift; [[ "${1:-}" == "--" ]] && shift; cmd_exec "$@" ;;
  down)   shift; cmd_down "$@" ;;
  *) err "unknown command: ${1:-<none>}"; echo "usage: $0 up|status|exec|down" >&2; exit 1 ;;
esac
