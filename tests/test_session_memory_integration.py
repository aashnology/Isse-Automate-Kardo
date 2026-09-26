import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import user_memory
import mcp_server


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(user_memory, "_STORE_PATH", str(tmp_path / "user_memory.json"))
    yield


def test_dismissed_workflow_is_excluded_from_top_friction_points():
    before = mcp_server.get_top_friction_points(top_k=10)
    names_before = [p["workflow_name"] for p in before["friction_points"]]
    assert len(names_before) > 0
    target = names_before[0]

    mcp_server.dismiss_workflow_suggestions(target, reason="handled manually")
    after = mcp_server.get_top_friction_points(top_k=10)
    names_after = [p["workflow_name"] for p in after["friction_points"]]
    assert target not in names_after


def test_include_dismissed_overrides_the_filter():
    before = mcp_server.get_top_friction_points(top_k=1)
    target = before["friction_points"][0]["workflow_name"]
    mcp_server.dismiss_workflow_suggestions(target)

    with_dismissed = mcp_server.get_top_friction_points(top_k=10, include_dismissed=True)
    names = [p["workflow_name"] for p in with_dismissed["friction_points"]]
    assert target in names


def test_propose_automation_respects_a_standing_dismissal():
    points = mcp_server.get_top_friction_points(top_k=1)
    target = points["friction_points"][0]["workflow_name"]

    mcp_server.dismiss_workflow_suggestions(target, reason="I review it myself")
    proposal = mcp_server.propose_automation(target)
    assert proposal["proposal_id"] is None
    assert "previously asked" in proposal["summary"]


def test_restore_makes_propose_automation_work_again():
    points = mcp_server.get_top_friction_points(top_k=1)
    target = points["friction_points"][0]["workflow_name"]

    mcp_server.dismiss_workflow_suggestions(target)
    mcp_server.restore_workflow_suggestions(target)
    proposal = mcp_server.propose_automation(target)
    # Not asserting proposal_id is not None here -- that depends on whether
    # the workflow actually has automatable steps, which isn't this test's
    # concern. What matters: it's no longer being blocked by a dismissal.
    assert "previously asked" not in proposal["summary"]


def test_list_dismissed_reflects_current_state():
    assert mcp_server.list_dismissed_workflow_suggestions()["dismissed_workflows"] == []
    mcp_server.dismiss_workflow_suggestions("bug_triage", reason="test")
    listed = mcp_server.list_dismissed_workflow_suggestions()["dismissed_workflows"]
    assert len(listed) == 1
    assert listed[0]["workflow_name"] == "bug_triage"
