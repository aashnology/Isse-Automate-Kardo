"""
Adapters from real, existing export formats into the raw event schema this
project's discovery pipeline actually needs: a list of
{"timestamp": <ISO 8601 str>, "activity": <str>, "duration_minutes": <float>}
dicts, fed to WorkflowDiscovery.from_raw_events(...).

This is deliberately the *minimal* schema the pipeline requires -- no
run_id, no workflow_name, no outcome. discover() and detect_anomalous_runs()
never touch those fields; only V1's label-based FrictionRadar does, and only
because the synthetic data happens to carry that label. Real exported data
never will, and doesn't need to -- that's the whole point of shipping the
sequence-clustering path in workflow_discovery.py rather than relying on
FrictionRadar's group-by.

Honest limitation, stated once here rather than repeated at every call
site: none of these real formats carry a success/rework outcome the way the
synthetic data does, so rework_rate and judgment-cost scoring (V1's
FrictionRadar) can't run meaningfully on adapted data. What does work end to
end on real data: session_segmentation -> workflow_discovery (clustering,
label_purity naturally comes back None) -> detect_anomalous_runs. That's
the genuinely-unsupervised half of this project, and it's the half real
data actually needs, since nobody's time tracker labels "which workflow was
this and did it need rework."
"""

import csv
from datetime import datetime


def from_activitywatch_events(aw_events, activity_field="app"):
    """ActivityWatch (github.com/ActivityWatch/activitywatch) is an open
    source, cross-platform time tracker. Its REST/query API returns events
    shaped like {"timestamp": "<ISO8601>", "duration": <seconds>,
    "data": {"app": "...", "title": "..."}} -- see aw-client's IEvent
    interface. `aw-client`'s own query/report examples pull exactly this
    shape out of a running aw-server instance; this function is what sits
    between that and this project's pipeline.

    activity_field picks what to use as the step name: "app" (e.g. the
    window watcher's active application) is the sane default; pass "title"
    for finer-grained, page/document-level activity."""
    out = []
    for e in aw_events:
        data = e.get("data", {})
        activity = data.get(activity_field) or data.get("app") or data.get("title")
        if not activity:
            continue  # skip events with no identifiable activity (e.g. AFK buckets)
        out.append({
            "timestamp": e["timestamp"],
            "activity": str(activity),
            "duration_minutes": round(e.get("duration", 0) / 60, 3),
        })
    out.sort(key=lambda e: e["timestamp"])
    return out


def from_toggl_csv(path, activity_column="Description"):
    """Toggl Track (track.toggl.com) CSV export. Standard export columns
    include "Start date", "Start time", "Duration" (as HH:MM:SS), and
    "Description" / "Project" -- this reads whichever activity_column is
    passed ("Description" by default; "Project" groups more coarsely)."""
    out = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            activity = row.get(activity_column)
            if not activity:
                continue
            timestamp = f"{row['Start date']}T{row['Start time']}"
            h, m, s = (int(x) for x in row["Duration"].split(":"))
            duration_minutes = h * 60 + m + s / 60
            out.append({
                "timestamp": timestamp,
                "activity": activity,
                "duration_minutes": round(duration_minutes, 3),
            })
    out.sort(key=lambda e: e["timestamp"])
    return out
