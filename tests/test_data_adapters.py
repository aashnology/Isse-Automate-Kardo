import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from data_adapters import from_activitywatch_events, from_toggl_csv
from workflow_discovery import WorkflowDiscovery


def test_from_activitywatch_events_maps_app_field():
    aw_events = [
        {"timestamp": "2026-01-01T09:00:00+00:00", "duration": 300, "data": {"app": "Slack", "title": "general"}},
        {"timestamp": "2026-01-01T09:05:00+00:00", "duration": 900, "data": {"app": "Excel", "title": "Q3.xlsx"}},
    ]
    result = from_activitywatch_events(aw_events)
    assert result[0]["activity"] == "Slack"
    assert result[0]["duration_minutes"] == 5.0
    assert result[1]["activity"] == "Excel"
    assert result[1]["duration_minutes"] == 15.0


def test_from_activitywatch_events_can_use_title_instead():
    aw_events = [{"timestamp": "2026-01-01T09:00:00+00:00", "duration": 60, "data": {"app": "Chrome", "title": "Gmail"}}]
    result = from_activitywatch_events(aw_events, activity_field="title")
    assert result[0]["activity"] == "Gmail"


def test_from_activitywatch_events_skips_unidentifiable_events():
    aw_events = [{"timestamp": "2026-01-01T09:00:00+00:00", "duration": 60, "data": {}}]
    assert from_activitywatch_events(aw_events) == []


def test_from_toggl_csv_parses_standard_export(tmp_path):
    csv_path = tmp_path / "toggl_export.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Project", "Description", "Start date", "Start time", "Duration"])
        writer.writerow(["Reporting", "export_data", "2026-01-01", "09:00:00", "00:12:30"])
        writer.writerow(["Reporting", "cross_check", "2026-01-01", "09:12:30", "00:05:00"])

    result = from_toggl_csv(str(csv_path))
    assert len(result) == 2
    assert result[0]["activity"] == "export_data"
    assert result[0]["duration_minutes"] == 12.5
    assert result[0]["timestamp"] == "2026-01-01T09:00:00"


def test_from_toggl_csv_can_group_by_project_instead(tmp_path):
    csv_path = tmp_path / "toggl_export.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Project", "Description", "Start date", "Start time", "Duration"])
        writer.writerow(["Reporting", "export_data", "2026-01-01", "09:00:00", "00:10:00"])

    result = from_toggl_csv(str(csv_path), activity_column="Project")
    assert result[0]["activity"] == "Reporting"


def test_adapted_activitywatch_data_flows_through_discovery():
    # End-to-end check: real-shaped data (no run_id, no workflow_name, no
    # outcome) with two obviously repeated app-switch sequences should
    # still cluster into a discovered workflow using nothing but timing +
    # sequence similarity.
    aw_events = []
    base_sequence = [("VSCode", 600), ("Chrome", 120), ("Terminal", 180)]
    for day in range(1, 5):
        ts_hour = 9
        for app, duration in base_sequence:
            aw_events.append({
                "timestamp": f"2026-01-0{day}T{ts_hour:02d}:00:00+00:00",
                "duration": duration,
                "data": {"app": app},
            })
            ts_hour += 1
        ts_hour += 20  # push the next day's run far enough away to segment cleanly

    raw = from_activitywatch_events(aw_events)
    wd = WorkflowDiscovery.from_raw_events(raw, similarity_threshold=0.6)
    clusters = wd.discover()
    assert len(clusters) >= 1
    assert clusters[0]["run_count"] >= 2
