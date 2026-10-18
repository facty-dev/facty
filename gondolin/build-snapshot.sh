#!/usr/bin/env bash
# build-snapshot.sh — build the reusable pi-sandbox VM snapshot.
#
# Boots a fresh gondolin VM, installs pi + textual (for projects
# with a Textual CLI/workbench, e.g. facty's `./facty`) + the skill set
# onto the root disk, then snapshots it. Future runs resume from the
# snapshot instantly (qcow2 overlay) — nothing is installed at session
# start.
#
# Idempotent: re-run any time to rebuild (e.g. after bumping the pi version
# or editing the skills/).
#
# No web-search tooling (ddgr or similar) is baked in, by design: Facty
# cases handle sensitive data, so the VM must not be able to leak it to
# an untrusted third party. Runtime egress is api.mistral.ai +
# registry.npmjs.org only (see gondolin-pi.sh).
#
# Notes:
# - Installs go to /usr/local and /usr/lib (root disk — persisted in snapshots).
# - /root is tmpfs and NOT captured by snapshots, so the skills are stored
#   at /opt/skills; the runner symlinks them into /root/.agents/skills at boot.
# - the pi-mistral-subscription extension is installed with
#   PI_CODING_AGENT_DIR=/opt/pi-agent (also persisted); the runner exports
#   that env var at boot so pi loads it. Users can then /login with a
#   Mistral Pro subscription inside the VM to bill their quotas.
#   (No pi-sandbox in the guest: the VM itself — hypervisor, egress
#   allow-list, host-secret injection, ephemeral disk — is the
#   isolation; pi-sandbox is for host-side pi sessions only.)
# - pi is symlinked into /usr/bin so it is on the guest's default PATH.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SNAPSHOT_DIR="$HERE/snapshots"
SNAP="$SNAPSHOT_DIR/pi-sandbox.qcow2"
TMP_SNAP="$SNAPSHOT_DIR/.pi-sandbox.tmp-$$.qcow2"
BUILD_TAG="pi-sandbox-build-$$"   # unique marker, appears in gondolin list LABEL

mkdir -p "$SNAPSHOT_DIR"

if [[ -e "$SNAP" ]]; then
  echo ">> snapshot already exists: $SNAP"
  echo ">> delete it first (rm $SNAP) or run: $0 --force"
  [[ "${1:-}" == "--force" ]] || exit 0
  rm -f "$SNAP"
fi

cleanup() {
  if [[ -n "${SETUP_PID:-}" ]] && kill -0 "$SETUP_PID" 2>/dev/null; then
    echo ">> cleaning up setup VM (pid $SETUP_PID)" >&2
    kill "$SETUP_PID" 2>/dev/null || true
    wait "$SETUP_PID" 2>/dev/null || true
  fi
  rm -f "$TMP_SNAP"
}
trap cleanup EXIT

echo ">> booting setup VM ($BUILD_TAG)"
# Setup egress only: package mirrors + github (for the git extension install).
# LLM/search hosts are runtime-only.
gondolin bash --rootfs-size 4G \
  --mount-hostfs "$HERE/skills:/mnt/skills:ro" \
  --allow-host dl-cdn.alpinelinux.org \
  --allow-host pypi.org --allow-host files.pythonhosted.org \
  --allow-host registry.npmjs.org \
  --allow-host github.com --allow-host codeload.github.com \
  -- bash -c "set -eu; echo '>> (vm) apk add py3-pip'; apk add -q --no-progress py3-pip git ca-certificates; echo '>> (vm) pip install textual (the facty CLI workbench)'; python3 -m pip install --break-system-packages --no-cache-dir --root-user-action=ignore -q textual; echo '>> (vm) npm install -g pi'; npm install -g --silent @earendil-works/pi-coding-agent; echo '>> (vm) put npm global bin on PATH (gondolin bash PATH lacks /usr/local/bin)'; export PATH="$(npm prefix -g)/bin:$PATH"; command -v pi; echo '>> (vm) install the mistral-subscription extension to /opt/pi-agent/'; export PI_CODING_AGENT_DIR=/opt/pi-agent; pi install https://github.com/5omeOtherGuy/pi-mistral-subscription; echo '>> (vm) install skills to /opt/skills/'; mkdir -p /opt/skills; cp -r /mnt/skills/. /opt/skills/; echo '>> (vm) link pi onto default PATH (/usr/bin)'; ln -sf /usr/local/bin/pi /usr/bin/; touch /opt/.pi-sandbox-ready; echo '>> (vm) setup complete'; sleep 600 # $BUILD_TAG" > "$SNAPSHOT_DIR/build.log" 2>&1 &
SETUP_PID=$!

# Wait for the session to register.
SID=""
for _ in $(seq 1 60); do
  SID=$(gondolin list 2>/dev/null | awk -v tag="$BUILD_TAG" '$0 ~ tag {print $1}' | tail -1)
  [[ -n "$SID" ]] && break
  sleep 2
done
if [[ -z "$SID" ]]; then
  echo "error: setup VM did not register a session" >&2
  tail -20 "$SNAPSHOT_DIR/build.log" >&2 || true
  exit 1
fi
echo ">> setup session: $SID"

# Wait for the readiness marker inside the VM.
echo ">> waiting for in-VM setup (log: $SNAPSHOT_DIR/build.log)"
READY=0
for _ in $(seq 1 60); do
  if gondolin exec --sock "$SID" -- test -f /opt/.pi-sandbox-ready >/dev/null 2>&1; then
    READY=1
    break
  fi
  if ! kill -0 "$SETUP_PID" 2>/dev/null; then
    echo "error: setup VM exited before completion" >&2
    tail -20 "$SNAPSHOT_DIR/build.log" >&2 || true
    exit 1
  fi
  sleep 5
done
if [[ $READY -ne 1 ]]; then
  echo "error: timed out waiting for setup" >&2
  tail -20 "$SNAPSHOT_DIR/build.log" >&2 || true
  exit 1
fi

echo ">> snapshotting"
gondolin snapshot "$SID" --output "$TMP_SNAP" >/dev/null
wait "$SETUP_PID" 2>/dev/null || true
mv "$TMP_SNAP" "$SNAP"

echo ">> done: $SNAP"
echo ">> resume with: gondolin bash --resume $SNAP"
