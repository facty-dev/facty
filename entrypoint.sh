#!/bin/sh
# SmolVM image entrypoint: boot TerminusDB, then run the given command (or a shell).
set -e
mkdir -p "$TERMINUSDB_SERVER_DB_PATH"
terminusdb serve &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
# wait for the store
i=0
while ! curl -sf -o /dev/null -u admin:"${TERMINUSDB_ADMIN_PASS:-root}" \
      http://127.0.0.1:6363/api/ok 2>/dev/null; do
  i=$((i+1)); [ "$i" -gt 60 ] && { echo "terminusdb did not start" >&2; exit 1; }
  sleep 1
done
exec "$@"
