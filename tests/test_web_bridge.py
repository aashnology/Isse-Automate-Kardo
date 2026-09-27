import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import server as web_server
import user_memory


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(user_memory, "_STORE_PATH", str(tmp_path / "user_memory.json"))
    web_server.app.config["TESTING"] = True
    with web_server.app.test_client() as c:
        yield c


def test_index_serves_the_frontend(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"orbi" in resp.data.lower() or b"Orbi" in resp.data


def test_friction_points_matches_the_real_pipeline(client):
    resp = client.get("/api/friction-points?top_k=3")
    data = resp.get_json()
    assert len(data["friction_points"]) > 0
    costs = [p["total_time_cost_minutes"] for p in data["friction_points"]]
    assert costs == sorted(costs, reverse=True)


def test_debug_endpoint_returns_real_step_breakdown(client):
    resp = client.get("/api/debug/weekly_reporting")
    data = resp.get_json()
    assert data["workflow_name"] == "weekly_reporting"
    assert len(data["step_breakdown"]) > 0


def test_propose_confirm_flow_through_the_bridge(client):
    proposal = client.post(
        "/api/propose", json={"workflow_name": "weekly_reporting"}
    ).get_json()
    assert proposal["proposal_id"] is not None

    result = client.post(
        "/api/confirm", json={"proposal_id": proposal["proposal_id"]}
    ).get_json()
    assert result["status"] == "executed"


def test_propose_on_judgment_heavy_workflow_returns_no_proposal(client):
    # bug_triage's steps aren't in AUTOMATABLE_STEPS -- the honest answer is
    # "nothing to propose," not a fabricated one.
    proposal = client.post(
        "/api/propose", json={"workflow_name": "bug_triage"}
    ).get_json()
    assert proposal["proposal_id"] is None


def test_dismiss_then_friction_points_excludes_it(client):
    before = client.get("/api/friction-points?top_k=5").get_json()
    target = before["friction_points"][0]["workflow_name"]

    client.post("/api/dismiss", json={"workflow_name": target, "reason": "test"})

    after = client.get("/api/friction-points?top_k=5").get_json()
    names = [p["workflow_name"] for p in after["friction_points"]]
    assert target not in names


def test_dismiss_persists_across_a_fresh_bridge_import(client, tmp_path, monkeypatch):
    # Simulates the exact claim the demo makes on camera: restart the
    # process, the dismissal is still there.
    path = str(tmp_path / "user_memory.json")
    monkeypatch.setattr(user_memory, "_STORE_PATH", path)
    client.post("/api/dismiss", json={"workflow_name": "bug_triage"})

    import importlib
    reloaded = importlib.reload(user_memory)
    monkeypatch.setattr(reloaded, "_STORE_PATH", path)
    assert reloaded.is_dismissed("bug_triage") is True


def test_propose_respects_a_standing_dismissal(client):
    client.post("/api/dismiss", json={"workflow_name": "weekly_reporting"})
    proposal = client.post(
        "/api/propose", json={"workflow_name": "weekly_reporting"}
    ).get_json()
    assert proposal["proposal_id"] is None
    assert "previously asked" in proposal["summary"]


def test_restore_reverses_dismissal_through_the_bridge(client):
    client.post("/api/dismiss", json={"workflow_name": "weekly_reporting"})
    client.post("/api/restore", json={"workflow_name": "weekly_reporting"})
    listed = client.get("/api/dismissed").get_json()
    assert listed["dismissed_workflows"] == []
