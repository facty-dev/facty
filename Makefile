# redyarn — the detective DSS (symbolic engine + LLM sensing)
#
# The product: a domain-agnostic abductive decision-support engine
# (engine/) — evidence in, ranked hypotheses out, full reasoning trace.
# Domains are packs (engine/cases/).
#
# The machinery: two AI agents (decision + coding) run inside isolated
# gondolin micro-VMs as the pack factory — a gated SDLC: discovery → PRD →
# BDD → implementation → review. Every agent run is audited to
# .agentic/audit.jsonl.
#
# ── Quick start ──────────────────────────────────────────────────────────────
#
#   make dss-demo             # Run the Silver Blaze case (phase 1)
#   make dss-demo-2           # Apply the ledger test (phase 2)
#   make dss-selftest         # Acceptance test — the PoC happy path, asserted
#
#   make vm-up                # Boot the pack-factory VM session (from YOUR terminal)
#   make agent-decision PHASE=discovery TASK="..."
#   make agent-coding TASK=<task-file>
#   make vm-status            # Session state (safe from sandboxed sessions)
#   make vm-down              # Stop the session (from YOUR terminal)
#
# Runtime: gondolin micro-VMs + pi (template: ~/code/gondolin-pi).
# Secrets: host-side placeholder substitution — never guest-readable.

# ── Help ─────────────────────────────────────────────────────────────────────
.PHONY: help info

help:
	@echo "redyarn — the detective DSS (symbolic engine + LLM sensing)"
	@echo ""
	@echo "═══ redyarn engine (the product) ═══"
	@echo "  make dss-demo           Run the Silver Blaze case (phase 1)"
	@echo "  make dss-demo-2         Apply the ledger test (phase 2)"
	@echo "  make dss-selftest       Acceptance test — the PoC happy path, asserted"
	@echo ""
	@echo "═══ Pack-factory VM session ═══"
	@echo "  make vm-up              Boot the SDLC VM session (from your terminal)"
	@echo "  make vm-status          Show session state"
	@echo "  make vm-down            Stop the session (from your terminal)"
	@echo ""
	@echo "═══ SDLC agents ═══"
	@echo "  make agent-decision PHASE=<discovery|prd|bdd|review> [TASK=\"<task>\"]"
	@echo "  make agent-coding TASK=<task-file> [BDD=<feature-file>]"
	@echo "  make run-agent AGENT=<decision|coding> [PHASE=...] [TASK=...] [BDD=...]"
	@echo "  make sdlc-start         SDLC quickstart help"
	@echo ""
	@echo "═══ Agentic runtime ═══"
	@echo "  make asset-init         Initialize asset graph (assets/graph.json)"
	@echo "  make asset-status       Show asset graph status"
	@echo "  make asset-lineage KEY=<key>  Show lineage for an asset"
	@echo "  make audit-trail        Show audit trail"
	@echo ""
	@echo "═══ Git-native pipeline ═══"
	@echo "  make sdlc-new FEATURE=<slug>         Start new SDLC for feature"
	@echo "  make sdlc-branch PHASE=<phase> FEATURE=<slug>  Create phase branch"
	@echo "  make sdlc-merge PHASE=<phase> FEATURE=<slug> Merge with skip-ahead"
	@echo "  make sdlc-status [FEATURE=<slug>]    Show SDLC status"
	@echo "  make sdlc-list                       List SDLC branches"
	@echo "  make sdlc-simulate FEATURE=<slug>    Simulate full pipeline locally"
	@echo ""
	@echo "  Phases: ost → prd → bdd → impl   |   Branches: sdlc/<phase>/<slug>"

info:
	@echo "gondolin:  $$(command -v gondolin || echo 'not found')"
	@echo "pi:        $$(command -v pi || echo 'not found')"
	@echo "session:   $$(./scripts/vm-session.sh status | head -1)"
	@echo "template:  $$(ls ~/code/gondolin-pi/snapshots/pi-sandbox.qcow2 >/dev/null 2>&1 && echo ok || echo missing)"

# ── redyarn engine (the product) ─────────────────────────────────────────────
# The deterministic symbolic half: forward/backward chaining + constraints
# over canonical case artifacts. The LLM senses and proposes; the engine
# decides. See docs/adr/0003-detective-dss-neurosymbolic-core.md.

.PHONY: dss-demo dss-demo-2 dss-selftest

dss-demo:
	python3 engine/engine.py run --case engine/cases/silver-blaze

dss-demo-2:
	python3 engine/engine.py run --case engine/cases/silver-blaze --add-facts engine/cases/silver-blaze/facts-ledger.json

dss-selftest:
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

# Run decision agent in the gondolin-pi VM (PRD-003)
agent-decision:
	@if [ -z "$(PHASE)" ]; then \
		echo "Usage: make agent-decision PHASE=<discovery|prd|bdd|review> [TASK=\"<task>\"]"; \
		exit 1; \
	fi
	@./scripts/agent-pi.sh decision --phase $(PHASE) --task "$(TASK)"

# Run coding agent in the gondolin-pi VM (PRD-003)
agent-coding:
	@if [ -z "$(TASK)" ]; then \
		echo "Usage: make agent-coding TASK=<task-file> [BDD=<feature-file>]"; \
		exit 1; \
	fi
	@./scripts/agent-pi.sh coding --task $(TASK) $(if $(BDD),--bdd "$(BDD)")

# SDLC VM session lifecycle — boot from YOUR shell (or pi `!` escape) so the
# API key stays host-side; sandboxed agents exec phases into it over IPC.
vm-up:
	@./scripts/vm-session.sh up

vm-down:
	@./scripts/vm-session.sh down

vm-status:
	@./scripts/vm-session.sh status

# Generic entry point (PRD-003 REQ-013)
run-agent:
	@if [ -z "$(AGENT)" ]; then \
		echo "Usage: make run-agent AGENT=<decision|coding> [PHASE=...] [TASK=...] [BDD=...]"; \
		exit 1; \
	fi
	@if [ "$(AGENT)" = "decision" ]; then \
		make agent-decision PHASE="$(PHASE)" TASK="$(TASK)"; \
	else \
		make agent-coding TASK="$(TASK)" BDD="$(BDD)"; \
	fi

# Start SDLC locally (simulation)
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

# Show SDLC status: see the sdlc-status target in the git-native section below.

# Evaluate rules for an asset
rules-eval:
	@if [ -z "$(ASSET)" ]; then \
		echo "Usage: make rules-eval ASSET=<asset-key>"; \
		exit 1; \
	fi
	@echo "Evaluating rules for asset: $(ASSET)"
	@echo "TODO: Implement rules engine (PRD-002)"
	@echo "  ./scripts/rules.sh eval $(ASSET)"

# Test a rule
rules-test:
	@if [ -z "$(RULE)" ]; then \
		echo "Usage: make rules-test RULE=<rule-id> [FIXTURE=<file>]"; \
		exit 1; \
	fi
	@echo "Testing rule: $(RULE)"
	@echo "TODO: Implement rules engine (PRD-002)"

# Show audit trail
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
