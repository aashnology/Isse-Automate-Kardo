import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "web"))

import pytest

from data_adapters import (
    from_csv_text, google_export_url, fetch_google_file, MAX_REMOTE_BYTES,
)
from bedrock_narrator import BedrockNarrator
from briefing import build_briefing
from friction_radar import FrictionRadar
from synthetic_data import generate_activity_events
from workflow_discovery import WorkflowDiscovery
import user_memory


# ---------------------------- generic CSV importer ---------------------------

def test_csv_with_plain_headers():
    text = "activity,timestamp,minutes\ndownload,2026-03-04 09:00:00,2\nclean,2026-03-04 09:02:00,10\n"
    rows = from_csv_text(text)
    assert [r["activity"] for r in rows] == ["download", "clean"]
    assert rows[1]["duration_minutes"] == 10.0


def test_csv_header_matching_is_case_insensitive():
    rows = from_csv_text("Task,Start,Duration\nexport,2026-03-04T09:00:00,00:03:00\n")
    assert rows[0]["activity"] == "export"
    assert rows[0]["duration_minutes"] == 3.0


def test_csv_understands_toggl_style_split_date_and_time():
    text = "Description,Start date,Start time,Duration\nexport,2026-03-04,09:00:00,00:12:30\n"
    assert from_csv_text(text)[0]["duration_minutes"] == 12.5


def test_csv_duration_is_optional():
    assert from_csv_text("activity,timestamp\nexport,2026-03-04 09:00:00\n")[0]["duration_minutes"] == 5.0


def test_csv_missing_columns_gives_an_actionable_error():
    with pytest.raises(ValueError) as e:
        from_csv_text("foo,bar\n1,2\n")
    assert "activity column" in str(e.value)


def test_csv_ambiguous_locale_dates_are_rejected_not_guessed():
    # 03/04/2026 is March 4th or April 3rd depending on the sheet's locale.
    with pytest.raises(ValueError) as e:
        from_csv_text("activity,timestamp\nexport,03/04/2026 09:00:00\n")
    assert "2026-03-04 09:15:00" in str(e.value)


def test_csv_mixed_timezone_awareness_does_not_break_ordering():
    text = ("activity,timestamp\n"
            "b,2026-03-04T10:00:00+00:00\n"
            "a,2026-03-04 09:00:00\n")
    assert [r["activity"] for r in from_csv_text(text)] == ["a", "b"]


# ---------------------------- google link handling ---------------------------

def test_sheet_link_becomes_a_fixed_csv_export_url():
    url, kind = google_export_url("https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp/edit#gid=42")
    assert kind == "sheet"
    assert url == "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp/export?format=csv&gid=42"


def test_drive_link_becomes_a_fixed_download_url():
    url, kind = google_export_url("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing")
    assert kind == "drive"
    assert url.startswith("https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOp")


@pytest.mark.parametrize("hostile", [
    "https://evil.example/docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp",
    "http://169.254.169.254/latest/meta-data/?docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp",
    "https://docs.google.com.evil.example/spreadsheets/d/1AbCdEfGhIjKlMnOp",
])
def test_the_fetched_host_is_always_google_whatever_was_pasted(hostile):
    # The pasted link is only mined for an ID; it is never fetched itself.
    try:
        url, _ = google_export_url(hostile)
    except ValueError:
        return
    assert url.startswith(("https://docs.google.com/", "https://drive.google.com/"))


@pytest.mark.parametrize("bad", [
    "", "not a link", "https://example.com/file.csv", "https://docs.google.com/spreadsheets/d/short",
    "file:///etc/passwd", "http://localhost:5000/api/dismissed",
])
def test_non_google_or_malformed_links_are_rejected(bad):
    with pytest.raises(ValueError):
        google_export_url(bad)


class _FakeResponse:
    def __init__(self, body, content_type="text/csv"):
        self._body, self.headers = body, {"Content-Type": content_type}

    def read(self, n=-1):
        return self._body if n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


LINK = "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOp/edit"


def test_public_file_is_read():
    text = fetch_google_file(LINK, opener=lambda u: _FakeResponse(b"activity,timestamp\na,2026-03-04 09:00:00\n"))
    assert text.startswith("activity")


def test_private_file_gets_a_clear_message_not_a_parse_error():
    html = b"<!DOCTYPE html><html><body>Sign in</body></html>"
    with pytest.raises(ValueError) as e:
        fetch_google_file(LINK, opener=lambda u: _FakeResponse(html, "text/html; charset=utf-8"))
    assert "anyone with the link" in str(e.value)


def test_oversized_files_are_refused():
    big = b"x" * (MAX_REMOTE_BYTES + 10)
    with pytest.raises(ValueError):
        fetch_google_file(LINK, opener=lambda u: _FakeResponse(big))


# ---------------------------- shared briefing --------------------------------

@pytest.fixture(scope="module")
def parts():
    events = generate_activity_events()
    return (FrictionRadar(events), WorkflowDiscovery(events, similarity_threshold=0.75),
            BedrockNarrator(enabled=False))


def test_briefing_names_the_top_workflow_and_says_it_used_the_template(parts):
    radar, wd, narrator = parts
    result = build_briefing(radar, wd, narrator, top_k=2)
    top = radar.top_friction_points(top_k=1)[0]["workflow_name"]
    assert top.replace("_", " ") in result["narration"].replace("_", " ")
    assert result["source"] == "template"


def test_briefing_leaves_out_dismissed_workflows(parts):
    radar, wd, narrator = parts
    top = radar.top_friction_points(top_k=1)[0]["workflow_name"]
    result = build_briefing(radar, wd, narrator, top_k=3, exclude={top})
    names = [p["workflow_name"] for p in result["based_on"]["top_friction_points"]]
    assert top not in names
    assert top not in result["narration"]


def test_briefing_with_everything_excluded_says_so(parts):
    radar, wd, narrator = parts
    every = {p["workflow_name"] for p in radar.top_friction_points(top_k=10)}
    result = build_briefing(radar, wd, narrator, top_k=3, exclude=every)
    assert "nothing to report" in result["narration"].lower()


# ---------------------------- through the web bridge -------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    import server as web_server
    monkeypatch.setattr(user_memory, "_STORE_PATH", str(tmp_path / "user_memory.json"))
    web_server.app.config["TESTING"] = True
    with web_server.app.test_client() as c:
        yield c


def test_brief_endpoint_matches_the_mcp_tool(client):
    import mcp_server
    via_web = client.get("/api/brief?top_k=2").get_json()
    via_mcp = mcp_server.narrate_briefing(top_k=2)
    assert via_web["narration"] == via_mcp["narration"]


def test_brief_endpoint_respects_a_dismissal(client):
    top = client.get("/api/friction-points?top_k=1").get_json()["friction_points"][0]["workflow_name"]
    client.post("/api/dismiss", json={"workflow_name": top})
    assert top not in client.get("/api/brief").get_json()["narration"]


def test_import_google_sheet_csv(client, monkeypatch):
    import server as web_server
    csv_text = ("activity,timestamp,minutes\n"
                "download,2026-03-01 09:00:00,2\nclean,2026-03-01 09:02:00,10\nexport,2026-03-01 09:12:00,3\n"
                "download,2026-03-03 09:00:00,2\nclean,2026-03-03 09:02:00,9\nexport,2026-03-03 09:11:00,3\n"
                "download,2026-03-05 09:00:00,2\nclean,2026-03-05 09:02:00,11\nexport,2026-03-05 09:13:00,3\n")
    monkeypatch.setattr(web_server, "fetch_google_file", lambda link: csv_text)
    data = client.post("/api/import", json={"google_link": LINK}).get_json()
    assert data["events_imported"] == 9
    assert len(data["discovered_workflows"]) >= 1


def test_import_drive_file_containing_activitywatch_json(client, monkeypatch):
    import json, server as web_server
    aw = [{"timestamp": "2026-01-01T09:00:00+00:00", "duration": 300, "data": {"app": "Slack"}},
          {"timestamp": "2026-01-01T09:05:00+00:00", "duration": 600, "data": {"app": "Excel"}}]
    monkeypatch.setattr(web_server, "fetch_google_file", lambda link: json.dumps(aw))
    assert client.post("/api/import", json={"google_link": LINK}).get_json()["events_imported"] == 2


def test_import_private_sheet_shows_the_user_a_useful_error(client):
    import server as web_server
    def private(link):
        raise ValueError("I can only read files shared as 'anyone with the link can view'.")
    import pytest as _p
    mp = _p.MonkeyPatch()
    mp.setattr(web_server, "fetch_google_file", private)
    try:
        resp = client.post("/api/import", json={"google_link": LINK})
    finally:
        mp.undo()
    assert resp.status_code == 400
    assert "anyone with the link" in resp.get_json()["error"]
