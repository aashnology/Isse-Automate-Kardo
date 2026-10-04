"""
Regression test for the confirm_action race: a check-then-set on
proposal["status"] used to run without a lock, so two concurrent confirms
of the same proposal_id could both pass the "not already executed" check
and both report a successful execution -- exactly the double-execution bug
this hackathon stub is meant to demonstrate is prevented.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from actions import propose_action, confirm_action


def _debug_result():
    return {"step_breakdown": [{"step": "export", "share_of_total": 1.0}]}


def test_concurrent_confirms_execute_exactly_once():
    proposal = propose_action("weekly_reporting", _debug_result())
    proposal_id = proposal["proposal_id"]

    results = []
    results_lock = threading.Lock()
    start = threading.Barrier(20)

    def worker():
        start.wait()
        result = confirm_action(proposal_id)
        with results_lock:
            results.append(result)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r.get("status") == "executed"]
    already_executed = [r for r in results if "error" in r]

    assert len(successes) == 1, f"expected exactly one successful execution, got {len(successes)}"
    assert len(already_executed) == 19


def test_proposal_ids_are_full_uuids_not_truncated():
    proposal = propose_action("weekly_reporting", _debug_result())
    # A truncated 8-char id has a real collision risk under this project's
    # own MAX_STORED_PROPOSALS scale; a full UUID4 (36 chars, hyphenated)
    # does not.
    assert len(proposal["proposal_id"]) == 36


def test_expired_proposal_cannot_be_confirmed(monkeypatch):
    import actions

    proposal = propose_action("weekly_reporting", _debug_result())
    # Age the proposal past the TTL without waiting an hour in a test.
    actions._PROPOSALS[proposal["proposal_id"]]["created_at"] -= actions.PROPOSAL_TTL_SECONDS + 1

    result = confirm_action(proposal["proposal_id"])
    assert "error" in result
    assert "expired" in result["error"].lower()
    # An expired proposal is removed, not left around for a later retry to
    # somehow succeed against.
    assert proposal["proposal_id"] not in actions._PROPOSALS


def test_fresh_proposal_is_not_treated_as_expired():
    proposal = propose_action("weekly_reporting", _debug_result())
    result = confirm_action(proposal["proposal_id"])
    assert result["status"] == "executed"


def test_propose_action_prunes_expired_proposals_opportunistically():
    import actions

    stale = propose_action("weekly_reporting", _debug_result())
    actions._PROPOSALS[stale["proposal_id"]]["created_at"] -= actions.PROPOSAL_TTL_SECONDS + 1

    propose_action("onboarding_new_partner", _debug_result())  # triggers the prune

    assert stale["proposal_id"] not in actions._PROPOSALS
