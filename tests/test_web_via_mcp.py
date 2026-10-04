"""Hexi's REST endpoints go through the MCP server first and report which
path answered in a `via` field."""

import os
import socket
import subprocess
import sys
import time

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "web"))
sys.path.insert(0, os.path.join(ROOT, "src"))

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
def live(mcp_url, monkeypatch):
    monkeypatch.setenv("HEXI_MCP_URL", mcp_url)
    monkeypatch.setattr(web_server, "_mcp_down_until", 0.0)
    web_server.app.config["TESTING"] = True
    with web_server.app.test_client() as c:
        yield c


@pytest.fixture
def down(monkeypatch):
    monkeypatch.setenv("HEXI_MCP_URL", f"http://127.0.0.1:{_free_port()}/mcp")
    monkeypatch.setattr(web_server, "_mcp_down_until", 0.0)
    web_server.app.config["TESTING"] = True
    with web_server.app.test_client() as c:
        yield c


READ_PATHS = ["/api/friction-points?top_k=2", "/api/dismissed", "/api/brief"]


@pytest.mark.parametrize("path", READ_PATHS)
def test_reads_go_through_mcp(live, path):
    res = live.get(path)
    assert res.status_code == 200
    assert res.get_json()["via"] == "mcp"


def test_debug_and_anomalies_go_through_mcp(live):
    name = live.get("/api/friction-points?top_k=1").get_json()["friction_points"][0]["workflow_name"]
    assert live.get(f"/api/debug/{name}").get_json()["via"] == "mcp"
    assert live.get(f"/api/anomalies/{name}").get_json()["via"] == "mcp"


def test_propose_goes_through_mcp(live):
    name = live.get("/api/friction-points?top_k=1").get_json()["friction_points"][0]["workflow_name"]
    body = live.post("/api/propose", json={"workflow_name": name}).get_json()
    assert body["via"] == "mcp"


@pytest.mark.parametrize("path", READ_PATHS)
def test_falls_back_to_direct_when_mcp_is_down(down, path):
    res = down.get(path)
    assert res.status_code == 200
    assert res.get_json()["via"] == "direct"


def test_failure_starts_a_cooldown(down):
    down.get("/api/dismissed")
    assert web_server._mcp_down_until > time.time()


def test_mcp_and_direct_return_the_same_analysis(mcp_url, monkeypatch):
    web_server.app.config["TESTING"] = True
    monkeypatch.setattr(web_server, "_mcp_down_until", 0.0)
    with web_server.app.test_client() as c:
        monkeypatch.setenv("HEXI_MCP_URL", mcp_url)
        via_mcp = c.get("/api/friction-points?top_k=3").get_json()
        monkeypatch.setenv("HEXI_MCP_URL", f"http://127.0.0.1:{_free_port()}/mcp")
        monkeypatch.setattr(web_server, "_mcp_down_until", 0.0)
        via_direct = c.get("/api/friction-points?top_k=3").get_json()
    assert via_mcp.pop("via") == "mcp"
    assert via_direct.pop("via") == "direct"
    assert via_mcp == via_direct
