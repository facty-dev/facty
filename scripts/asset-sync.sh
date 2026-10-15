#!/usr/bin/env bash
# asset-sync.sh — Derive assets/graph.json from git history.
#
# The asset graph is not maintained independently — it's derived from
# which SDLC branches have merged into main, and what files they contain.
#
# Usage:
#   ./scripts/asset-sync.sh              # Sync graph from git history
#   ./scripts/asset-sync.sh --status     # Show sync status only
#   ./scripts/asset-sync.sh --validate   # Validate graph against files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

# ── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}ℹ${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }

# ── Config ───────────────────────────────────────────────────────────────────
ASSET_DIR="assets"
GRAPH_FILE="$ASSET_DIR/graph.json"
AUDIT_FILE=".agentic/audit.jsonl"

# Phase → directory mapping
declare -A PHASE_DIRS=(
  [discovery]="docs/discovery"
  [prd]="docs/prd"
  [bdd]="specs/features"
  [impl]="src"
)

# Phase → asset key prefix
declare -A PHASE_KEYS=(
  [discovery]="discovery/ost"
  [prd]="define/prd"
  [bdd]="develop/bdd"
  [impl]="deliver/code"
)

# ── Functions ────────────────────────────────────────────────────────────────

# Get all merged SDLC branches with their merge info
get_merged_branches() {
  # Find merge commits that merged sdlc/* branches into main
  git log main --merges --oneline --grep="sdlc/" 2>/dev/null | while read -r line; do
    # Extract branch name from merge commit message
    # Format: "Merge pull request #42 from owner/sdlc/ost/user-auth"
    if [[ "$line" =~ sdlc/([a-z]+)/(.+) ]]; then
      phase="${BASH_REMATCH[1]}"
      slug="${BASH_REMATCH[2]}"
      commit=$(echo "$line" | awk '{print $1}')
      echo "$phase|$slug|$commit"
    fi
  done | sort -u
}

# Get files changed in a merge commit
get_merge_files() {
  local commit="$1"
  git show --name-only --format="" "$commit" 2>/dev/null || true
}

# Compute file hash
hash_file() {
  local file="$1"
  if [[ -f "$file" ]]; then
    shasum -a 256 "$file" 2>/dev/null | awk '{print $1}' || sha256sum "$file" | awk '{print $1}'
  else
    echo "missing"
  fi
}

# Detect if asset was human-produced (check commit author)
is_human_produced() {
  local commit="$1"
  local author
  author=$(git log -1 --format="%an <%ae>" "$commit" 2>/dev/null || echo "unknown")

  # Agent commits have specific authors
  case "$author" in
    *"decision-agent"*|*"coding-agent"*|*"sdlc-bot"*)
      echo "agent"
      ;;
    *)
      echo "human"
      ;;
  esac
}

# Build graph from git history
build_graph() {
  local nodes_json="{}"
  local edges_json="[]"
  local seen_slugs=""

  info "Scanning git history for merged SDLC branches..."

  while IFS='|' read -r phase slug commit; do
    [[ -z "$phase" || -z "$slug" ]] && continue

    # Skip if we've already processed this slug
    if echo "$seen_slugs" | grep -q "$slug"; then
      continue
    fi
    seen_slugs="$seen_slugs $slug"

    local asset_key="${PHASE_KEYS[$phase]:-$phase}"
    local phase_dir="${PHASE_DIRS[$phase]:-}"
    local files
    files=$(get_merge_files "$commit")

    # Find the main asset file
    local main_file=""
    while IFS= read -r file; do
      if [[ -n "$phase_dir" && "$file" == "$phase_dir"* ]]; then
        main_file="$file"
        break
      fi
    done <<< "$files"

    # Compute version (count of merges for this slug+phase)
    local version
    version=$(git log main --oneline --grep="sdlc/$phase/$slug" 2>/dev/null | wc -l | tr -d ' ')

    local hash="missing"
    if [[ -n "$main_file" ]]; then
      hash=$(hash_file "$main_file")
    fi

    local producer
    producer=$(is_human_produced "$commit")

    local merged_at
    merged_at=$(git log -1 --format="%aI" "$commit" 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)

    # Build node JSON
    local node_json
    node_json=$(cat <<EOF
{
  "asset_key": "$asset_key",
  "feature_slug": "$slug",
  "branch": "sdlc/$phase/$slug",
  "path": "$main_file",
  "phase": "$phase",
  "version": $version,
  "hash": "$hash",
  "status": "materialized",
  "produced_by": "$producer",
  "merged_at": "$merged_at",
  "merge_commit": "$commit",
  "depends_on": []
}
EOF
)

    # Merge into nodes (simplified — in production use jq)
    nodes_json="$nodes_json
  \"$asset_key\": $node_json,"

    ok "Found: $asset_key ($slug) v$version by $producer"
  done < <(get_merged_branches)

  # Remove trailing comma
  nodes_json="${nodes_json%,}"

  # Build graph
  cat > "$GRAPH_FILE" <<EOF
{
  "version": "1.0",
  "derived_from": "git history",
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "commit": "$(git rev-parse HEAD)",
  "nodes": {$nodes_json
  },
  "edges": []
}
EOF

  ok "Asset graph written: $GRAPH_FILE"
}

# ── Main ─────────────────────────────────────────────────────────────────────
mkdir -p "$ASSET_DIR" .agentic

case "${1:-}" in
  --status)
    if [[ -f "$GRAPH_FILE" ]]; then
      info "Asset graph exists: $GRAPH_FILE"
      jq -r '.nodes | keys[]' "$GRAPH_FILE" 2>/dev/null || cat "$GRAPH_FILE"
    else
      warn "No asset graph. Run: $0"
    fi
    ;;
  --validate)
    if [[ ! -f "$GRAPH_FILE" ]]; then
      err "No asset graph to validate"
      exit 1
    fi
    info "Validating asset graph..."
    jq empty "$GRAPH_FILE" && ok "Valid JSON" || err "Invalid JSON"
    ;;
  *)
    build_graph
    ;;
esac
