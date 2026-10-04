"""The Agent Skill must only name tools the MCP server actually serves."""

import asyncio
import os
import re
import socket
import subprocess
import sys
import time

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = os.path.join(os.path.dirname(__file__), "..")
SKILL = os.path.join(ROOT, "skills", "friction-radar", "SKILL.md")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_tools():
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

    async def names():
        async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return {t.name for t in (await s.list_tools()).tools}
    try:
        yield asyncio.run(names())
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _skill_text():
    with open(SKILL, encoding="utf-8") as f:
        return f.read()


def test_skill_has_frontmatter():
    text = _skill_text()
    assert text.startswith("---\nname: friction-radar\n")
    assert "description:" in text.split("---")[1]


def test_every_tool_named_in_the_skill_exists(server_tools):
    named = {t for t in re.findall(r"`([a-z_]+)`", _skill_text()) if "_" in t}
    assert named and not (named - server_tools), named - server_tools


def test_every_server_tool_the_skill_should_cover_is_named(server_tools):
    named = set(re.findall(r"`([a-z_]+)`", _skill_text()))
    # imports read a caller-supplied file path and are deliberately not in the skill
    assert (server_tools - named) <= {"discover_workflows", "discover_workflows_from_import",
                                      "explain_friction", "estimate_time_cost"}
