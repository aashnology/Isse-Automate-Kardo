"""
Two small pieces that turn "two separate systems" into "one product":

1. find_related_signal -- given a friction workflow, find information items
   whose topic is plausibly relevant (crude keyword overlap between the
   workflow's step names and item topics/titles). This is intentionally
   simple: a real version would use the same TF-IDF space as the ranking
   engine, but keyword overlap is honest about what it is and easy to
   defend in an interview -- no hidden magic.

2. A minimal human-in-the-loop action layer: propose_action never executes
   anything. It returns a proposal with an id. Only a matching
   confirm_action call executes it. This is the whole "autonomy model"
   from the design doc, implemented as the smallest thing that could work.
"""

import re
import uuid

# a tiny, honest keyword map -- not ML, just enough to demo the bridge
WORKFLOW_KEYWORDS = {
    "bug_triage": ["context", "switching", "latency", "reliability", "database", "distributed"],
    "weekly_reporting": ["data", "engineering", "pipeline", "quality"],
    "onboarding_new_partner": ["product", "analytics", "developer", "tools"],
}

# steps that are safe to propose automating (low judgment cost, from friction_radar's own scoring)
AUTOMATABLE_STEPS = {"column_cleanup", "rename", "export", "upload", "file_download", "account_create"}

_PROPOSALS = {}  # in-memory store: proposal_id -> proposal dict


def find_related_signal(ranking_engine, workflow_name, top_k=2):
    keywords = WORKFLOW_KEYWORDS.get(workflow_name, [])
    if not keywords:
        return {"workflow_name": workflow_name, "related_items": []}

    scored = []
    for item in ranking_engine.items:
        text = (item["title"] + " " + item["topic"]).lower()
        hits = sum(1 for kw in keywords if kw in text)
        if hits > 0:
            scored.append((hits, item))
    scored.sort(key=lambda x: -x[0])

    return {
        "workflow_name": workflow_name,
        "matched_on_keywords": keywords,
        "related_items": [
            {"id": it["id"], "title": it["title"], "topic": it["topic"], "keyword_hits": hits}
            for hits, it in scored[:top_k]
        ],
    }


def propose_action(workflow_name, debug_result):
    """Build a concrete, reversible-sounding proposal from a debug_workflow
    result -- only steps already known to be automatable are proposed."""
    steps = [s["step"] for s in debug_result.get("step_breakdown", [])]
    proposed_steps = [s for s in steps if s in AUTOMATABLE_STEPS]
    if not proposed_steps:
        return {
            "proposal_id": None,
            "workflow_name": workflow_name,
            "summary": "No steps in this workflow are safe to automate without human judgment.",
        }

    proposal_id = str(uuid.uuid4())[:8]
    proposal = {
        "proposal_id": proposal_id,
        "workflow_name": workflow_name,
        "proposed_automation": proposed_steps,
        "summary": f"Automate these steps in '{workflow_name}': {', '.join(proposed_steps)}.",
        "status": "pending_confirmation",
    }
    _PROPOSALS[proposal_id] = proposal
    return proposal


def confirm_action(proposal_id):
    proposal = _PROPOSALS.get(proposal_id)
    if not proposal:
        return {"error": f"No pending proposal with id '{proposal_id}'. Proposals expire after being confirmed once."}
    if proposal["status"] == "executed":
        return {"error": f"Proposal '{proposal_id}' was already executed."}

    # This is a hackathon stub for the execution step -- in a real system this
    # would trigger the actual automation (a script, a Zapier-style hook, etc).
    # It's deliberately left as a stub rather than faked as "done" silently:
    # the response says exactly what would happen and what's simulated.
    proposal["status"] = "executed"
    return {
        "proposal_id": proposal_id,
        "status": "executed",
        "note": (
            f"Simulated execution: steps {proposal['proposed_automation']} for "
            f"'{proposal['workflow_name']}' marked as automated. (Hackathon demo stub -- "
            f"a production version would trigger the actual script/integration here.)"
        ),
    }
