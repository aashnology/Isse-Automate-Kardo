"""
The one piece of state in this project that's meant to outlive a single
Alexa+ session: if you tell it "stop suggesting automation for X," that has
to still be true the next time you talk to it -- tomorrow, next week, after
the server restarts. Everything else in this project (a proposal_id from
propose_automation, for instance) is deliberately short-lived and in-memory,
because it's answering "did you confirm *this specific* proposal," which
has no meaning after the process restarts. A dismissal is different: it's a
standing preference, not a transaction, so it's the one thing here backed
by a file on disk rather than a dict in memory.

Storage is a single JSON file (data/user_memory.json) rather than a real
database, on purpose -- this project has exactly one user per deployment
(there's no multi-tenant auth story here), so a file is the honest amount
of infrastructure for what this actually needs, not a database bolted on
to look more "production" than the rest of the project claims to be.
"""

import json
import os
from datetime import datetime, timezone

_STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "user_memory.json")


def _load():
    if not os.path.exists(_STORE_PATH):
        return {"dismissed_workflows": {}}
    with open(_STORE_PATH) as f:
        return json.load(f)


def _save(state):
    os.makedirs(os.path.dirname(_STORE_PATH), exist_ok=True)
    tmp_path = f"{_STORE_PATH}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp_path, _STORE_PATH)  # atomic -- a failed write can't corrupt prior state


def dismiss_workflow(workflow_name: str, reason: str = "") -> dict:
    """Record that automation shouldn't be suggested for this workflow again,
    until explicitly restored. Persists across restarts and sessions."""
    state = _load()
    state["dismissed_workflows"][workflow_name] = {
        "reason": reason,
        "dismissed_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(state)
    return {"workflow_name": workflow_name, "status": "dismissed", "reason": reason}


def restore_workflow(workflow_name: str) -> dict:
    state = _load()
    if workflow_name not in state["dismissed_workflows"]:
        return {"error": f"'{workflow_name}' isn't currently dismissed."}
    del state["dismissed_workflows"][workflow_name]
    _save(state)
    return {"workflow_name": workflow_name, "status": "restored"}


def is_dismissed(workflow_name: str) -> bool:
    return workflow_name in _load()["dismissed_workflows"]


def list_dismissed() -> list:
    state = _load()
    return [
        {"workflow_name": name, **info}
        for name, info in state["dismissed_workflows"].items()
    ]
