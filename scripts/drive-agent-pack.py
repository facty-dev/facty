#!/usr/bin/env python3
# drive-agent-pack.py — drive the embedded agent (pi RPC) to author a
# pack via the meta-Facty loop (ask_questions elicitation). This script
# plays the domain expert: it answers the agent's questions and lets the
# agent generate the pack artifacts.
#
# Usage:
#   python3 scripts/drive-agent-pack.py <pack-slug> "<domain description>"
#
# The answers are provided by the ANSWERS dict below (keyed by question
# header or substring). Edit it for your domain.

import json
import sys
import threading
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))
import agent  # noqa: E402
import pack   # noqa: E402

# ── The domain expert's answers ────────────────────────────────────
# Keyed by a substring of the question header or question text.
# Value: the answer (for select: the option label; for input: free text).

ANSWERS = {
    # Entities
    "entit": "person, organization, object",
    "entities": "person, organization, object",

    # Predicates
    "predicate": "estimatedDamage, incidentType, hasWitnesses, hasPaintTransfer, relationshipToClaimant, totalAmount, hasPaintCorrection, hasTotalLossAdjusterFee, claimCount, priorParkingLotClaims",
    "facts say": "estimatedDamage, incidentType, hasWitnesses, hasPaintTransfer, relationshipToClaimant, totalAmount, hasPaintCorrection, claimCount",

    # Hypotheses (the explanation space)
    "explanation": "staged accident, inflated damages, pre-existing damage, legitimate claim",
    "hypothes": "H1 staged accident, H2 inflated damages, H3 pre-existing damage, H4 legitimate claim",
    "competing": "staged accident, inflated damages, pre-existing damage, legitimate claim",

    # Rules
    "rule": "when there are no witnesses and no paint transfer and the witness saw suspicious activity, derive stagedAccidentLikely; when the estimate has paint correction or total loss adjuster fee, derive inflatedDamagesLikely; when prior claims show repeated parking lot claims, derive repeatClaimant; when the claim is a hit-and-run with no evidence, raise H1-H4",
    "fire": "when there are no witnesses and no paint transfer, derive stagedAccidentLikely; when the estimate has suspicious items, derive inflatedDamagesLikely",

    # Labels (for the label sensor)
    "label": "legitimate, inflated, staged, pre-existing",
    "sensor": "legitimate, inflated, staged, pre-existing",
    "classif": "legitimate, inflated, staged, pre-existing",

    # Constraints
    "constraint": "if stagedAccidentLikely is true, eliminate H4 (legitimate claim); if inflatedDamagesLikely is true, support H2; if the witness has a relationship to the claimant, support H1",
    "eliminate": "if stagedAccidentLikely, eliminate legitimate claim; if no suspicious items, eliminate inflated damages",
    "support": "if inflatedDamagesLikely, support inflated damages hypothesis",

    # Domain description
    "domain": "insurance claim fraud — I investigate suspicious car insurance claims for staged accidents, inflated damages, and repeat fraud",
    "describe": "insurance claim fraud — staged accidents, inflated repair estimates, repeat claimants",
}


def find_answer(request):
    """Find the answer for a request (select/input) based on the title."""
    title = (request.get("title", "") + " " + request.get("header", "")).lower()
    for key, answer in ANSWERS.items():
        if key.lower() in title:
            return answer
    # Default: for select, pick the first option; for input, a generic answer
    if request.get("method") == "select":
        options = request.get("options", [])
        return options[0] if options else None
    return "see the pack's existing artifacts for the vocabulary"


def ui_handler(request):
    """Handle an extension_ui_request (ask_questions dialog).
    Prints the question and returns the domain expert's answer."""
    method = request.get("method", "input")
    title = request.get("title", "")
    print(f"\n  📋 Agent asks ({method}): {title}")
    if method == "select":
        options = request.get("options", [])
        for i, opt in enumerate(options, 1):
            print(f"     {i}. {opt}")
    answer = find_answer(request)
    print(f"  → Answer: {answer}")
    return answer


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 scripts/drive-agent-pack.py <pack-slug> \"<domain>\"")
        sys.exit(1)
    slug = sys.argv[1]
    domain = sys.argv[2]
    pack_dir = Path("packs") / slug
    if not pack_dir.exists():
        print(f"error: pack directory does not exist: {pack_dir}")
        sys.exit(1)

    # Build the pack context
    ctx = agent.pack_context(pack_dir)
    print(f"=== Pack context ===\n{ctx}\n")

    # Create the agent session
    print("=== Starting the agent (pi RPC) ===")
    sess = agent.AgentSession(pack_context=ctx + f"\n\nThe domain: {domain}")

    # The message to the agent
    message = f"""Help me author a pack for: {domain}

Use ask_questions to interview me about the domain. Ask about:
1. The entities (what things exist in this domain?)
2. The predicates (what can facts say about them?)
3. The hypotheses (what are the competing explanations?)
4. The rules (what rules should fire? when → then)
5. The labels (what labels should the sensor use for repair line items?)
6. The constraints (what should eliminate/support a hypothesis?)

Batch related questions (up to 4 per ask_questions call). After you
have the answers, generate the pack artifacts:
- packs/{slug}/pack/rules.json
- packs/{slug}/pack/constraints.json
- packs/{slug}/pack/hypotheses.json
- packs/{slug}/classify.json (if the domain has categorical evidence)

Write the artifacts and tell me what you wrote. I'll validate them
with the engine."""

    print(f"=== Sending message to the agent ===\n")
    response_lines = []

    def stream(line):
        response_lines.append(line)
        print(f"  agent: {line}")

    try:
        response = sess.send(message, stream=stream, ui_handler=ui_handler)
    except RuntimeError as exc:
        print(f"\n❌ Agent error: {exc}")
        sess.close()
        sys.exit(1)
    finally:
        sess.close()

    print(f"\n=== Agent finished ===")
    print(f"Response length: {len(response)} chars")

    # Check what the agent wrote
    print(f"\n=== Pack artifacts after the agent ===")
    for name in ["pack/rules.json", "pack/constraints.json",
                 "pack/hypotheses.json", "classify.json"]:
        path = pack_dir / name
        if path.exists():
            try:
                data = json.loads(path.read_text())
                count = len(data) if isinstance(data, list) else "config"
                print(f"  {name}: {count}")
            except json.JSONDecodeError:
                print(f"  {name}: (invalid JSON)")
        else:
            print(f"  {name}: (not written)")


if __name__ == "__main__":
    main()
