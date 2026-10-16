import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import aspen_bridge
import server as web_server


@pytest.fixture
def client():
    web_server.app.config["TESTING"] = True
    with web_server.app.test_client() as c:
        yield c


def test_not_installed_without_aspen_home(monkeypatch, client):
    monkeypatch.delenv("ASPEN_HOME", raising=False)
    assert aspen_bridge.call() == "not_installed"
    assert client.get("/api/aspen").get_json() == {"installed": False}


def test_nothing_starts_without_an_explicit_action(client):
    for body in ({}, {"action": "launch"}, {"action": "call; rm -rf /"}):
        resp = client.post("/api/aspen", json=body)
        assert resp.status_code == 400 and resp.get_json()["state"] == "ignored"


def test_call_starts_aspen_once(monkeypatch, tmp_path):
    (tmp_path / "main.py").write_text("import time; time.sleep(30)")
    monkeypatch.setenv("ASPEN_HOME", str(tmp_path))
    monkeypatch.setattr(aspen_bridge, "_proc", None)
    assert aspen_bridge.call() == "started"
    assert aspen_bridge.call() == "already_running"
    aspen_bridge._proc.kill()


def test_stop_uses_the_stop_flag_only(monkeypatch, tmp_path):
    (tmp_path / "main.py").write_text("import sys; sys.exit(0 if sys.argv[1:] == ['--stop'] else 3)")
    monkeypatch.setenv("ASPEN_HOME", str(tmp_path))
    assert aspen_bridge.stop() == "stopped"


def test_api_reports_not_installed_cleanly(monkeypatch, client):
    monkeypatch.delenv("ASPEN_HOME", raising=False)
    data = client.post("/api/aspen", json={"action": "call"}).get_json()
    assert data["state"] == "not_installed" and "carry on without him" in data["reply"]
