"""
Protocol-level check: start the actual server process and talk to it with a
real MCP client over Streamable HTTP, the same way Alexa+ (or any MCP
client) would. Everything else in tests/ calls the tool functions directly
or goes through the Flask bridge -- useful, but neither proves the track's
hard requirement (an MCP server, spec 2025-11-25+, Streamable HTTP) is
actually met by the running process. This does.
"""

import asyncio
import os
import socket
import subprocess
import sys
import time

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    port = _free_port()
    env = {**os.environ, "MCP_SERVER_PORT": str(port)}
    proc = subprocess.Popen(
        [sys.executable, "mcp_server.py"],
        cwd=SRC_DIR, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail("MCP server did not start listening in time")
    yield f"http://127.0.0.1:{port}/mcp"
    proc.terminate()
    proc.wait(timeout=10)


def _run(coro):
    return asyncio.run(coro)


def test_negotiates_the_required_protocol_version(server_url):
    async def go():
        async with streamable_http_client(server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                return (await session.initialize()).protocolVersion

    # Hackathon minimum is 2025-11-25; string comparison is safe for
    # ISO-formatted dates.
    assert _run(go()) >= "2025-11-25"


def test_lists_the_expected_tools(server_url):
    async def go():
        async with streamable_http_client(server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return {t.name for t in (await session.list_tools()).tools}

    names = _run(go())
    for expected in (
        "discover_workflows", "get_top_friction_points", "debug_workflow",
        "detect_anomalous_runs", "propose_automation", "confirm_automation",
        "dismiss_workflow_suggestions", "narrate_briefing",
    ):
        assert expected in names


def test_a_tool_call_returns_real_data(server_url):
    async def go():
        async with streamable_http_client(server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool("get_top_friction_points", {"top_k": 1})

    result = _run(go())
    assert not result.isError
    assert "friction_points" in result.content[0].text
