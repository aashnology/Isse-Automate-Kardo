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
import threading
import time
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
_PROPOSALS_LOCK = threading.Lock()
MAX_STORED_PROPOSALS = 1000  # bound on _PROPOSALS so a flood of proposals can't grow it unboundedly
PROPOSAL_TTL_SECONDS = 60 * 60  # an hour-old "yes, automate it" shouldn't still be confirmable


def _is_expired(proposal, now=None):
    return (now if now is not None else time.time()) - proposal["created_at"] > PROPOSAL_TTL_SECONDS


def _prune_expired_locked(now=None):
    """Caller must already hold _PROPOSALS_LOCK. Opportunistic cleanup --
    called from propose_action so an idle server doesn't need a background
    thread just to forget old proposals."""
    now = now if now is not None else time.time()
    for pid in [pid for pid, p in _PROPOSALS.items() if _is_expired(p, now)]:
        del _PROPOSALS[pid]


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

    proposal_id = str(uuid.uuid4())
    proposal = {
        "proposal_id": proposal_id,
        "workflow_name": workflow_name,
        "proposed_automation": proposed_steps,
        "summary": f"Automate these steps in '{workflow_name}': {', '.join(proposed_steps)}.",
        "status": "pending_confirmation",
        "created_at": time.time(),
    }
    with _PROPOSALS_LOCK:
        _prune_expired_locked()
        if len(_PROPOSALS) >= MAX_STORED_PROPOSALS:
            # Still at the cap after pruning expired entries -- evict the
            # oldest (dicts preserve insertion order) as a last resort.
            _PROPOSALS.pop(next(iter(_PROPOSALS)))
        _PROPOSALS[proposal_id] = proposal
    return proposal


def confirm_action(proposal_id):
    with _PROPOSALS_LOCK:
        proposal = _PROPOSALS.get(proposal_id)
        if not proposal:
            return {"error": f"No pending proposal with id '{proposal_id}'. Proposals expire after being confirmed once."}
        if _is_expired(proposal):
            del _PROPOSALS[proposal_id]
            return {
                "error": (
                    f"Proposal '{proposal_id}' has expired (proposals are only valid for "
                    f"{PROPOSAL_TTL_SECONDS // 60} minutes). Ask to automate it again to get a new one."
                )
            }
        if proposal["status"] == "executed":
            return {"error": f"Proposal '{proposal_id}' was already executed."}

        # This is a hackathon stub for the execution step -- in a real system
        # this would trigger the actual automation (a script, a Zapier-style
        # hook, etc). It's deliberately left as a stub rather than faked as
        # "done" silently: the response says exactly what would happen and
        # what's simulated. The check-then-set above and this assignment
        # happen under the same lock, so two concurrent confirms of the same
        # proposal_id can't both pass the "already executed" check and both
        # report success -- exactly the double-execution this stub is meant
        # to demonstrate is prevented.
        proposal["status"] = "executed"
        proposed_automation = proposal["proposed_automation"]
        workflow_name = proposal["workflow_name"]

    return {
        "proposal_id": proposal_id,
        "status": "executed",
        "note": (
            f"Simulated execution: steps {proposed_automation} for "
            f"'{workflow_name}' marked as automated. (Hackathon demo stub -- "
            f"a production version would trigger the actual script/integration here.)"
        ),
    }
