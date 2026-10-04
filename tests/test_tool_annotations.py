"""
Regression test for MCP tool annotations (readOnlyHint/destructiveHint/
idempotentHint). These are advisory metadata an MCP client can use to decide
how much confirmation a tool call needs -- a client that trusts them should
never need to double-check with the user before a read-only call, and should
always treat confirm_automation as the one genuinely destructive action in
this project. Getting these wrong is a silent correctness issue: nothing
crashes, a client just over- or under-trusts a tool.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import mcp_server

READ_ONLY_TOOLS = {
    "discover_workflows", "discover_workflows_from_import",
    "get_top_friction_points", "explain_friction", "estimate_time_cost",
    "debug_workflow", "detect_anomalous_runs", "narrate_briefing",
    "list_dismissed_workflow_suggestions",
}
WRITE_TOOLS = {
    "propose_automation", "confirm_automation",
    "dismiss_workflow_suggestions", "restore_workflow_suggestions",
}


@pytest.fixture(scope="module")
def tool_map():
    import asyncio

    async def _list():
        tools = await mcp_server.mcp.list_tools()
        return {t.name: t.annotations for t in tools}

    return asyncio.run(_list())


def test_every_tool_is_classified(tool_map):
    assert set(tool_map) == READ_ONLY_TOOLS | WRITE_TOOLS


def test_read_only_tools_are_marked_read_only_and_idempotent(tool_map):
    for name in READ_ONLY_TOOLS:
        ann = tool_map[name]
        assert ann.readOnlyHint is True, name
        assert ann.idempotentHint is True, name


def test_write_tools_are_not_marked_read_only(tool_map):
    for name in WRITE_TOOLS:
        assert tool_map[name].readOnlyHint is False, name


def test_confirm_automation_is_the_one_destructive_tool(tool_map):
    assert tool_map["confirm_automation"].destructiveHint is True
    for name in WRITE_TOOLS - {"confirm_automation"}:
        assert tool_map[name].destructiveHint is False, name


def test_dismiss_and_restore_are_idempotent_but_propose_is_not(tool_map):
    assert tool_map["dismiss_workflow_suggestions"].idempotentHint is True
    assert tool_map["restore_workflow_suggestions"].idempotentHint is True
    # Calling propose_automation twice creates two different proposal_ids,
    # not the same end state, so it must not claim idempotency.
    assert tool_map["propose_automation"].idempotentHint is False
    assert tool_map["confirm_automation"].idempotentHint is False
