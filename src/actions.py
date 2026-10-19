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
from automation_model import LEGACY_AUTOMATABLE as AUTOMATABLE_STEPS, eligible_steps  # noqa: E402

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


def propose_action(workflow_name, debug_result, workspace=None):
    """Build a concrete proposal from a debug_workflow result. Which steps are
    safe to automate is decided per step (automation_model), so this works for
    any workflow, not just the sample's. With a workspace, the proposal also
    carries a shadow-mode projection of the time it would save."""
    breakdown = debug_result.get("step_breakdown", [])
    proposed_steps = eligible_steps(breakdown, debug_result.get("total_runs") or 1)
    if not proposed_steps:
        blocked = [s["step"] for s in breakdown][:3]
        return {
            "proposal_id": None,
            "workflow_name": workflow_name,
            "summary": "No steps in this workflow are safe to automate without human judgment."
                       + (f" The biggest ones ({', '.join(blocked)}) need a person." if blocked else ""),
        }

    proposal_id = str(uuid.uuid4())
    proposal = {
        "proposal_id": proposal_id,
        "workflow_name": workflow_name,
        "proposed_automation": proposed_steps,
        "summary": f"Automate these steps in '{workflow_name}': {', '.join(proposed_steps)}.",
        "status": "pending_confirmation",
        "created_at": time.time(),
        "dataset_id": workspace.id if workspace else None,
    }
    if workspace:
        from diagnosis import time_saved
        saved = time_saved(workspace, workflow_name, proposed_steps)
        if saved:
            proposal["projection"] = {"minutes_saved_per_run": saved["minutes_saved_per_run"],
                                      "hours_saved_per_week": saved["hours_saved_per_week"]}
            proposal["summary"] += (f" Replaying your history, that saves about {saved['minutes_saved_per_run']} min per run"
                                    f" (~{saved['hours_saved_per_week']} h a week).")
    with _PROPOSALS_LOCK:
        _prune_expired_locked()
        if len(_PROPOSALS) >= MAX_STORED_PROPOSALS:
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

        # Execution is a stub in this build; the report below is a shadow-mode replay of history -- in a real system
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
        dataset_id = proposal.get("dataset_id")

    report = None
    try:
        from workspace import get_workspace
        from diagnosis import automation_report
        report = automation_report(get_workspace(dataset_id), workflow_name, proposed_automation)
    except Exception:  # noqa: BLE001 -- the approval already happened; a failed report must not undo it
        report = None

    return {
        "proposal_id": proposal_id,
        "status": "executed",
        "note": (
            f"Simulated execution: steps {proposed_automation} for "
            f"'{workflow_name}' marked as automated. (Hackathon demo stub -- "
            f"a production version would trigger the actual script/integration here.)"
        ),
        "report": report,
    }
