"""
Voice path end to end against a real MCP server process: Flask bridge ->
official MCP client -> Streamable HTTP -> tools. Also checks the two-step
automation guard and the protocol floor.
"""

import os
import socket
import subprocess
import sys
import time

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "web"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import mcp_bridge
import server as web_server


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mcp_url():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "mcp_server.py"], cwd=os.path.join(ROOT, "src"),
                            env={**os.environ, "MCP_SERVER_PORT": str(port)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail("MCP server did not start")
    yield f"http://127.0.0.1:{port}/mcp"
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def client(mcp_url, monkeypatch):
    monkeypatch.setenv("HEXI_MCP_URL", mcp_url)
    web_server.app.config["TESTING"] = True
    with web_server.app.test_client() as c:
        yield c


def _ask(client, **body):
    return client.post("/api/agent", json=body)


def test_friction_answer_comes_from_the_mcp_tool_at_the_required_protocol(client):
    r = _ask(client, intent="friction").get_json()
    assert r["tools"] == ["get_top_friction_points"]
    assert r["protocol"] >= mcp_bridge.MIN_PROTOCOL
    assert "costs" in r["reply"]


def test_why_uses_debug_workflow(client):
    r = _ask(client, intent="why", workflow="weekly_reporting").get_json()
    assert r["tools"] == ["debug_workflow"] and "biggest share" in r["reply"]


def test_brief_matches_the_narrate_briefing_tool(client):
    import mcp_server
    r = _ask(client, intent="brief").get_json()
    assert r["reply"] == mcp_server.narrate_briefing()["narration"]


def test_automate_only_proposes_until_a_second_utterance_confirms(client):
    first = _ask(client, intent="automate", workflow="weekly_reporting").get_json()
    assert first["tools"] == ["propose_automation"]
    assert first["pending_proposal_id"] and "Say yes" in first["reply"]

    second = _ask(client, intent="automate", workflow="weekly_reporting",
                  proposal_id=first["pending_proposal_id"]).get_json()
    assert second["tools"] == ["confirm_automation"] and second["mood"] == "confirmed"

    replay = _ask(client, intent="automate", workflow="weekly_reporting",
                  proposal_id=first["pending_proposal_id"]).get_json()
    assert replay["mood"] != "confirmed"  # a used proposal can't be replayed


def test_judgment_heavy_workflow_gets_an_honest_refusal(client):
    r = _ask(client, intent="automate", workflow="bug_triage").get_json()
    assert r["pending_proposal_id"] is None and r["mood"] == "watching"


def test_workflow_required_intents_ask_instead_of_guessing(client):
    r = _ask(client, intent="why").get_json()
    assert r["tools"] == [] and "Which workflow" in r["reply"]


def test_unknown_intent_is_a_400(client):
    assert _ask(client, intent="format_disk").status_code == 400


def test_unreachable_mcp_server_is_a_503_not_a_silent_fallback(monkeypatch):
    monkeypatch.setenv("HEXI_MCP_URL", f"http://127.0.0.1:{_free_port()}/mcp")
    web_server.app.config["TESTING"] = True
    with web_server.app.test_client() as c:
        assert c.post("/api/agent", json={"intent": "friction"}).status_code == 503


def test_an_old_protocol_version_is_refused(mcp_url, monkeypatch):
    monkeypatch.setattr(mcp_bridge, "MIN_PROTOCOL", "2999-01-01")
    with pytest.raises(mcp_bridge.McpUnavailable) as e:
        mcp_bridge.call_tools([("get_top_friction_points", {})], url=mcp_url)
    assert "need 2999-01-01+" in str(e.value)
