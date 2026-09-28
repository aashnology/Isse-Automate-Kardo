"""
One place that builds the spoken briefing, used by both the MCP tool
(narrate_briefing) and Orbi's "brief me". Keeping it here means the two
interfaces can't drift apart: same analysis in, same sentence out.

Workflows the user has dismissed are excluded. A briefing that raised
something they'd asked never to hear about again would contradict the one
piece of state this project persists, so that's checked here rather than
left to each caller.
"""


def build_briefing(friction_radar, workflow_discovery, narrator, top_k=3, exclude=()):
    excluded = set(exclude)
    # Over-fetch so excluding dismissed workflows doesn't shrink the list.
    candidates = friction_radar.top_friction_points(top_k=top_k + len(excluded))
    points = [p for p in candidates if p["workflow_name"] not in excluded][:top_k]

    anomaly_notes = []
    for p in points:
        result = workflow_discovery.detect_anomalous_runs(p["workflow_name"], top_k=1)
        if result.get("anomalies"):
            anomaly_notes.append({"workflow_name": p["workflow_name"], **result["anomalies"][0]})

    payload = {"top_friction_points": points, "anomalies": anomaly_notes}

    if points:
        lines = [
            f"Your biggest time sink is '{points[0]['workflow_name']}' at "
            f"{round(points[0]['total_time_cost_minutes'] / 60, 1)} hours, "
            f"rated {points[0]['automation_tier']}."
        ]
    else:
        lines = ["There's nothing to report right now."]
    if anomaly_notes:
        a = anomaly_notes[0]
        lines.append(
            f"One run of '{a['workflow_name']}' ran long, mainly because of "
            f"'{a['likely_cause_step']}'."
        )

    narration = narrator.narrate(payload, fallback=" ".join(lines))
    return {**narration, "based_on": payload}
