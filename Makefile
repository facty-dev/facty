# Facty — the detective DSS (symbolic engine + LLM sensing)
#
# The product: a domain-agnostic abductive decision-support engine —
# evidence in, ranked hypotheses out, full reasoning trace. Domains are
# packs (engine/cases/, packs/).
#
# Implementation (ADR-0005): TerminusDB-backed engine in src/facty, SmolVM
# image (Dockerfile), Vibe CLI + pydantic-ai for the LLM half. The PoC under
# engine/ stays as the golden oracle (make poc-oracle).
#
# ── Quick start ──────────────────────────────────────────────────────────────
#
#   make deps                              # uv sync (Python 3.14, .python-version)
#   docker compose -f compose.yaml up -d   # TerminusDB on :6363
#   make selftest                          # golden acceptance — every case
#   make e2e                               # end-to-end demo (offline)
#   make e2e-live                          # with live LLM sensing
#
# See docs/IMPLEMENTATION.md and docs/CLEANROOM-METHOD.md.

# ── Help ─────────────────────────────────────────────────────────────────────
.PHONY: help info cases selftest e2e e2e-live poc-oracle

help:
	@echo "Facty — the detective DSS"
	@echo ""
	@echo "═══ Engine (the product; ADR-0005 stack) ═══"
	@echo "  make deps               uv sync (Python from .python-version)"
	@echo "  make cases              ./facty cases — migrated cases/packs"
	@echo "  make selftest           ./facty selftest — golden acceptance, all cases"
	@echo "  make e2e / e2e-live     scripts/e2e.sh [--live] — end-to-end demo"
	@echo "  make poc-oracle         python3 engine/engine.py selftest (PoC oracle)"
	@echo "  make deps-sensors       optional label-sensor deps (host/CI only)"
	@echo ""
	@echo "═══ Assets / SDLC pipeline ═══"
	@echo "  make asset-status · sdlc-status · sdlc-new FEATURE=<slug> · audit-trail"

info:
	@echo "python:    $$(uv run python --version 2>/dev/null || python3 --version)"
	@echo "terminusdb: $$(curl -sf -u admin:root http://127.0.0.1:6363/api/ok >/dev/null 2>&1 && echo 'up on :6363' || echo 'down — docker compose -f compose.yaml up -d')"
	@echo "smolvm:    $$(command -v smolvm || echo 'not found')"
	@echo "vibe:      $$(command -v vibe || echo 'not found')"


OP ?= facts
deps:
	uv sync

# The optional sensor layer (engine/label.py): the label sensor (a small
# CPU-only zero-shot classifier). Host/CI-only — the SmolVM image
# has no pypi egress (by design); see requirements-sensors.txt.
deps-sensors:
	uv sync
	uv pip install -r requirements-sensors.txt

# ── Facty engine (TerminusDB-backed; see docs/IMPLEMENTATION.md) ────────────
# TerminusDB on :6363 first: docker compose -f compose.yaml up -d
cases:
	./facty cases

selftest:
	./facty selftest

e2e:
	TERMINUSDB_DB=facty-e2e bash scripts/e2e.sh

e2e-live:
	TERMINUSDB_DB=facty-e2e bash scripts/e2e.sh --live

poc-oracle:
	python3 engine/engine.py selftest

# ── Agentic Runtime (SDLC) ──────────────────────────────────────────────────
# Asset-oriented SDLC: OST → PRD → BDD → Implementation → ADRs
# See docs/ASSET-MODEL.md and docs/prd/ for details.

ASSET_DIR   = assets
GRAPH_FILE  = $(ASSET_DIR)/graph.json
AUDIT_FILE  = .agentic/audit.jsonl

.PHONY: asset-init asset-status asset-lineage asset-materialize
.PHONY: agent-decision agent-coding sdlc-start sdlc-status
.PHONY: rules-eval rules-test audit-trail audit-verify

# Initialize the asset graph
asset-init:
	@mkdir -p $(ASSET_DIR)/schemas $(ASSET_DIR)/materialized
	@mkdir -p .agentic/messages/{decision-to-coding,coding-to-decision,human-review}
	@mkdir -p .agentic/rules
	@if [ ! -f $(GRAPH_FILE) ]; then \
		echo '{ "version": "1.0", "nodes": {}, "edges": [] }' > $(GRAPH_FILE); \
		echo "Initialized asset graph: $(GRAPH_FILE)"; \
	else \
		echo "Asset graph already exists: $(GRAPH_FILE)"; \
	fi
	@if [ ! -f $(AUDIT_FILE) ]; then \
		touch $(AUDIT_FILE); \
		echo "Initialized audit trail: $(AUDIT_FILE)"; \
	fi

# Show asset graph status
asset-status:
	@if [ -f $(GRAPH_FILE) ]; then \
		jq . $(GRAPH_FILE) 2>/dev/null || cat $(GRAPH_FILE); \
	else \
		echo "No asset graph. Run: make asset-init"; \
	fi

# Show lineage for an asset
asset-lineage:
	@if [ -z "$(KEY)" ]; then \
		echo "Usage: make asset-lineage KEY=<asset-key>"; \
		exit 1; \
	fi
	@jq --arg key "$(KEY)" '.nodes[$key] // "Asset not found: $(KEY)"' $(GRAPH_FILE) 2>/dev/null || cat $(GRAPH_FILE)

# Materialize an asset (manual)
asset-materialize:
	@if [ -z "$(KEY)" ] || [ -z "$(FILE)" ]; then \
		echo "Usage: make asset-materialize KEY=<asset-key> FILE=<path>"; \
		exit 1; \
	fi
	@./scripts/asset.sh materialize "$(KEY)" "$(FILE)" 2>/dev/null || \
		echo "TODO: scripts/asset.sh not yet implemented (PRD-001)"
sdlc-start:
	@echo "Starting agentic SDLC locally..."
	@echo "Phases: Discovery → PRD → BDD → Implementation → Review → Merge"
	@echo ""
	@echo "1. Initialize:  make asset-init"
	@echo "2. Discovery:   make agent-decision PHASE=discovery TASK='Build OST from PR description'"
	@echo "3. PRD:         make agent-decision PHASE=prd TASK='Generate PRD from OST'"
	@echo "4. BDD:         make agent-decision PHASE=bdd TASK='Generate specs from PRD'"
	@echo "5. Implement:   make agent-coding TASK=.agentic/messages/decision-to-coding/001-task.md"
	@echo "6. Review:      make agent-decision PHASE=review TASK='Review code and record ADRs'"
	@echo ""
	@echo "Or in CI/CD: label a PR with 'sdlc'"

# ── Pack factory (the meta-Facty loop) ─────────────────────────────────────
# Author a pack (a domain's knowledge engine) with pi + ask_questions.
# The engine generates questions; the user answers; pi generates the
# symbolic representations; the engine validates. See the pack-factory skill.

.PHONY: pack-factory
audit-trail:
	@if [ -f $(AUDIT_FILE) ]; then \
		echo "═══ Audit Trail (Reification Stream) ═══"; \
		jq -c '{event_type, timestamp, actor: .actor.id, asset: .asset.key}' $(AUDIT_FILE) 2>/dev/null || cat $(AUDIT_FILE); \
	else \
		echo "No audit trail. Run: make asset-init"; \
	fi

# Verify audit trail integrity
audit-verify:
	@if [ -f $(AUDIT_FILE) ]; then \
		echo "Verifying audit trail integrity..."; \
		echo "TODO: Implement hash chain verification (PRD-004)"; \
	else \
		echo "No audit trail to verify."; \
	fi

# ── SDLC Phase targets (local simulation) ────────────────────────────────────

sdlc-discovery:
	@make agent-decision PHASE=discovery TASK='Build Opportunity Solution Tree from stakeholder input'

sdlc-prd:
	@make agent-decision PHASE=prd TASK='Generate PRD from approved OST'

sdlc-bdd:
	@make agent-decision PHASE=bdd TASK='Generate BDD specs from PRD'

sdlc-implement:
	@make agent-coding TASK=.agentic/messages/decision-to-coding/current-task.md

sdlc-review:
	@make agent-decision PHASE=review TASK='Review code, run tests, record ADRs'

# ── Git-Native Pipeline (SDLC branch management) ─────────────────────────────
# Branches are assets. Merges are materializations. PRs are gates.
# See docs/GIT-NATIVE-PIPELINE.md

.PHONY: sdlc-new sdlc-branch sdlc-merge sdlc-inject sdlc-status sdlc-list sdlc-simulate

FEATURE ?=

# Start new SDLC for a feature
sdlc-new:
	@if [ -z "$(FEATURE)" ]; then \
		echo "Usage: make sdlc-new FEATURE=<slug>"; \
		exit 1; \
	fi
	@./scripts/sdlc-branch.sh start "$(FEATURE)"

# Create a phase branch
sdlc-branch:
	@if [ -z "$(PHASE)" ] || [ -z "$(FEATURE)" ]; then \
		echo "Usage: make sdlc-branch PHASE=<ost|prd|bdd|impl> FEATURE=<slug>"; \
		exit 1; \
	fi
	@./scripts/sdlc-branch.sh branch "$(PHASE)" "$(FEATURE)"

# Merge a phase branch (with skip-ahead detection)
sdlc-merge:
	@if [ -z "$(PHASE)" ] || [ -z "$(FEATURE)" ]; then \
		echo "Usage: make sdlc-merge PHASE=<phase> FEATURE=<slug>"; \
		exit 1; \
	fi
	@./scripts/sdlc-branch.sh merge "$(PHASE)" "$(FEATURE)"

# Human injection: add your own asset file
sdlc-inject:
	@if [ -z "$(PHASE)" ] || [ -z "$(FEATURE)" ] || [ -z "$(FILE)" ]; then \
		echo "Usage: make sdlc-inject PHASE=<phase> FEATURE=<slug> FILE=<path>"; \
		exit 1; \
	fi
	@./scripts/sdlc-branch.sh inject "$(PHASE)" "$(FEATURE)" "$(FILE)"

# Show SDLC status
sdlc-status:
	@./scripts/sdlc-branch.sh status $(if $(FEATURE),"$(FEATURE)",)

# List all SDLC branches
sdlc-list:
	@./scripts/sdlc-branch.sh list

# Simulate full pipeline locally
sdlc-simulate:
	@if [ -z "$(FEATURE)" ]; then \
		echo "Usage: make sdlc-simulate FEATURE=<slug>"; \
		echo ""; \
		echo "This runs the full SDLC pipeline locally:"; \
		echo "  1. Create sdlc/ost/<feature> branch"; \
		echo "  2. Run decision agent (OST)"; \
		echo "  3. Merge to main → trigger PRD"; \
		echo "  4. Run decision agent (PRD)"; \
		echo "  5. Merge to main → trigger BDD"; \
		echo "  6. Run decision agent (BDD)"; \
		echo "  7. Merge to main → trigger implementation"; \
		echo "  8. Run coding agent (code + ADRs)"; \
		echo "  9. Merge to main → done"; \
		exit 1; \
	fi
	@echo "═══ Simulating SDLC for: $(FEATURE) ═══"
	@echo ""
	@echo "Step 1/9: Create OST branch"
	@./scripts/sdlc-branch.sh start "$(FEATURE)"
	@echo ""
	@echo "Step 2/9: Run decision agent (OST)"
	@echo "  → make agent-decision PHASE=discovery TASK='Build OST for $(FEATURE)'"
	@echo "  (simulated — run manually)"
	@echo ""
	@echo "Step 3/9: Merge OST → triggers PRD"
	@echo "  → make sdlc-merge PHASE=ost FEATURE=$(FEATURE)"
	@echo ""
	@echo "... (continue with prd, bdd, impl phases)"
	@echo ""
	@echo "Or run agents manually between merges."
	@echo "See: docs/GIT-NATIVE-PIPELINE.md"
