#!/usr/bin/env bash
# gondolin-pi.sh — run the pi coding agent inside a gondolin micro-VM,
# with ddgr (DuckDuckGo) web search and the ddgr skill preinstalled.
#
# Usage:
#   gondolin-pi.sh [project-dir]            interactive pi session (default dir: $PWD)
#   gondolin-pi.sh [project-dir] -p "prompt" non-interactive print mode
#   gondolin-pi.sh build [--force]          (re)build the VM snapshot, then exit
#
# Env overrides:
#   PI_MODEL     default: mistral-large-4 (Mistral-served model)
#   PI_THINKING  default: max
#   PI_SNAPSHOT  default: <script-dir>/snapshots/pi-sandbox.qcow2
#
# Requires: MISTRAL_API_KEY in the environment.
#
# The VM is ephemeral per run, but boots instantly from the snapshot —
# pi, ddgr, the skill, and the pi-sandbox + pi-mistral-subscription
# extensions are baked in (see build-snapshot.sh).
# The project directory is mounted read-write at /workspace in the guest.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MODEL="${PI_MODEL:-mistral-large-4}"
THINKING="${PI_THINKING:-max}"
SNAP="${PI_SNAPSHOT:-$HERE/snapshots/pi-sandbox.qcow2}"

if [[ "${1:-}" == "build" ]]; then
  shift
  exec "$HERE/build-snapshot.sh" "$@"
fi

if [[ ! -e "$SNAP" ]]; then
  echo ">> no snapshot at $SNAP — building it (one-time)..."
  "$HERE/build-snapshot.sh"
fi

if [[ -z "${MISTRAL_API_KEY:-}" ]]; then
  echo "error: MISTRAL_API_KEY is not set" >&2
  exit 1
fi

GUEST_ENV=(--env "PI_MODEL=$MODEL" --env "PI_THINKING=$THINKING")
PROJECT_DIR="$PWD"

# Optional project dir as the first positional arg.
if [[ $# -ge 1 && "${1:-}" != "-p" && "${1:-}" != "--print" ]]; then
  PROJECT_DIR="$1"
  shift
fi
[[ -d "$PROJECT_DIR" ]] || { echo "error: not a directory: $PROJECT_DIR" >&2; exit 1; }

if [[ "${1:-}" == "-p" || "${1:-}" == "--print" ]]; then
  shift
  [[ $# -eq 1 ]] || { echo "usage: gondolin-pi.sh [project-dir] -p \"prompt\"" >&2; exit 1; }
  if [[ "$1" == *$'\n'* ]]; then
    # Multiline prompts break gondolin's --env value handling (the CLI
    # re-splits the value across argv). Stage the prompt as a file in the
    # project (mounted at /workspace) and pass a short pointer instead.
    mkdir -p "$PROJECT_DIR/.gondolin-pi"
    _PROMPT_FILE=".gondolin-pi/prompt-$(date +%s).md"
    printf '%s\n' "$1" > "$PROJECT_DIR/$_PROMPT_FILE"
    GUEST_ENV+=("--env" "PI_PROMPT=Read your complete assignment in @$_PROMPT_FILE and execute it in full.")
  else
    GUEST_ENV+=("--env" "PI_PROMPT=$1")
  fi
  shift
fi
[[ $# -eq 0 ]] || { echo "error: unexpected args: $*" >&2; exit 1; }

# Egress allow-list (an explicit --allow-host list replaces the defaults):
#   api.mistral.ai     — LLM API (mistral-large-4 et al.)
#   duckduckgo hosts   — ddgr web search
#   registry.npmjs.org — project npm installs inside the VM
# MISTRAL_API_KEY is passed as a host-secret: the guest only sees a
# placeholder, which the host substitutes into outbound requests to
# api.mistral.ai.
gondolin bash \
  --rootfs-size 4G \
  --resume "$SNAP" \
  ${PROJECT_DIR:+--mount-hostfs "$PROJECT_DIR:/workspace"} \
  --allow-host api.mistral.ai \
  --allow-host duckduckgo.com \
  --allow-host html.duckduckgo.com \
  --allow-host lite.duckduckgo.com \
  --allow-host registry.npmjs.org \
  --host-secret MISTRAL_API_KEY@api.mistral.ai \
  "${GUEST_ENV[@]}" \
  -- bash -c '
    set -e
    # /root is tmpfs (not in the snapshot) — re-link the baked-in skills.
    mkdir -p /root/.agents/skills
    for s in /opt/skills/*/; do ln -sfn "$s" "/root/.agents/skills/$(basename "$s")"; done
    [ -f /opt/skills/SKILL-INDEX.md ] && ln -sfn /opt/skills/SKILL-INDEX.md /root/.agents/SKILL-INDEX.md
    # Extensions (pi-sandbox, pi-mistral-subscription) are baked into the
    # snapshot at /opt/pi-agent (persisted; /root is tmpfs). Older snapshots
    # without it simply run without extensions.
    if [ -d /opt/pi-agent ]; then export PI_CODING_AGENT_DIR=/opt/pi-agent; fi
    cd /workspace 2>/dev/null || cd /root
    if [[ -n "${PI_PROMPT:-}" ]]; then
      exec pi -p --no-session --model "$PI_MODEL" --thinking "$PI_THINKING" "$PI_PROMPT"
    else
      exec pi --model "$PI_MODEL" --thinking "$PI_THINKING"
    fi
  '
