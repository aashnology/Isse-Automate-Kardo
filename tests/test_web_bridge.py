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
    assert b"hexi" in resp.data.lower() or b"Hexi" in resp.data


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


def test_import_pasted_text(client):
    text = "download, 2\nclean, 10\nexport, 3\n\ndownload, 2\nclean, 9\nexport, 3\n\ndownload, 2\nclean, 11\nexport, 3"
    resp = client.post("/api/import", json={"pasted_text": text})
    data = resp.get_json()
    assert data["events_imported"] > 0
    assert len(data["discovered_workflows"]) >= 1


def test_import_activitywatch_json_file(client):
    import io
    import json as _json
    aw_events = [
        {"timestamp": "2026-01-01T09:00:00+00:00", "duration": 300, "data": {"app": "Slack"}},
        {"timestamp": "2026-01-01T09:05:00+00:00", "duration": 600, "data": {"app": "Excel"}},
    ]
    data = client.post(
        "/api/import",
        data={"file": (io.BytesIO(_json.dumps(aw_events).encode()), "export.json")},
        content_type="multipart/form-data",
    ).get_json()
    assert data["events_imported"] == 2


def test_import_toggl_csv_file(client):
    import io
    csv_content = (
        "Project,Description,Start date,Start time,Duration\n"
        "Reporting,export_data,2026-01-01,09:00:00,00:12:30\n"
    )
    data = client.post(
        "/api/import",
        data={"file": (io.BytesIO(csv_content.encode()), "export.csv")},
        content_type="multipart/form-data",
    ).get_json()
    assert data["events_imported"] == 1


def test_import_unsupported_file_extension_errors_cleanly(client):
    import io
    resp = client.post(
        "/api/import",
        data={"file": (io.BytesIO(b"whatever"), "export.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_import_with_nothing_provided_errors_cleanly(client):
    resp = client.post("/api/import", json={})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_import_github_repo_bad_format_errors_cleanly(client):
    resp = client.post("/api/import", json={"github_repo": "not-a-valid-spec"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_import_github_repo_uses_the_pr_adapter(client, monkeypatch):
    # Mocked to avoid depending on live network / GitHub's rate limit in
    # CI -- the adapter itself (from_github_pull_requests) has its own
    # correctness covered by a real, unmocked call during development.
    fake_events = [
        {"workflow_run_id": 1, "timestamp": "2026-01-01T00:00:00+00:00", "activity": "pr_opened", "duration_minutes": 60},
        {"workflow_run_id": 1, "timestamp": "2026-01-01T01:00:00+00:00", "activity": "pr_merged", "duration_minutes": 5},
        {"workflow_run_id": 2, "timestamp": "2026-01-02T00:00:00+00:00", "activity": "pr_opened", "duration_minutes": 30},
        {"workflow_run_id": 2, "timestamp": "2026-01-02T00:30:00+00:00", "activity": "pr_merged", "duration_minutes": 5},
    ]
    import server as web_server
    monkeypatch.setattr(web_server, "from_github_pull_requests", lambda owner, repo, max_prs, token: fake_events)

    resp = client.post("/api/import", json={"github_repo": "someowner/somerepo"})
    data = resp.get_json()
    assert data["events_imported"] == 4
    assert len(data["discovered_workflows"]) >= 1


def test_import_github_repo_parses_full_url(client, monkeypatch):
    import server as web_server
    captured = {}

    def fake_adapter(owner, repo, max_prs, token):
        captured["owner"], captured["repo"] = owner, repo
        return [
            {"workflow_run_id": 1, "timestamp": "2026-01-01T00:00:00+00:00", "activity": "pr_opened", "duration_minutes": 10},
            {"workflow_run_id": 1, "timestamp": "2026-01-01T00:10:00+00:00", "activity": "pr_merged", "duration_minutes": 5},
        ]
    monkeypatch.setattr(web_server, "from_github_pull_requests", fake_adapter)

    client.post("/api/import", json={"github_repo": "https://github.com/pallets/flask"})
    assert captured == {"owner": "pallets", "repo": "flask"}
