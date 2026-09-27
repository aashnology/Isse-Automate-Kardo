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
from datetime import datetime, timedelta, timezone


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


def from_pasted_steps(text, default_duration=5.0, run_gap_hours=36):
    """The lowest-effort real input this project accepts: no export file,
    just a list of step names typed or pasted directly. Blank-line-separated
    blocks are separate runs; each line is "step name" or
    "step name, duration_minutes" (duration defaults to 5 if omitted).

    This format carries no real timestamps, so synthetic ones are assigned
    (steps 2 minutes apart within a run, runs run_gap_hours apart, most
    recent block last) purely to give the pipeline something to sort and
    segment by -- the sequence itself, and any duration you provide, are
    the only real input here. Said plainly rather than left implicit: this
    is the weakest-evidence import path of the three (ActivityWatch and
    Toggl at least carry real timestamps), useful for a quick "does my
    process look like this" check, not for anything claiming duration
    accuracy."""
    blocks = [b.strip() for b in text.strip().split("\n\n") if b.strip()]
    out = []
    now = datetime.now(timezone.utc)
    for run_idx, block in enumerate(blocks):
        t = now - timedelta(hours=run_gap_hours * (len(blocks) - run_idx))
        for line in block.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",")]
            activity = parts[0]
            if not activity:
                continue
            try:
                duration = float(parts[1]) if len(parts) > 1 else default_duration
            except ValueError:
                duration = default_duration
            out.append({
                "timestamp": t.isoformat(),
                "activity": activity,
                "duration_minutes": duration,
            })
            t += timedelta(minutes=duration)
    return out


def from_github_pull_requests(owner, repo, max_prs=30, token=None):
    """Turns a public GitHub repo's own pull-request history into workflow
    data -- read-only, one API call, nothing cloned or executed. Deliberately
    scoped this way: mining a repo's own process metadata (when was a PR
    opened, last updated, merged) is safe and genuinely useful; running its
    code because someone pasted a link is a different, much riskier thing
    this project does not do, under any framing.

    Each closed/merged PR becomes one run of two steps -- pr_opened (timed
    from created_at to updated_at) and pr_merged/pr_closed (timed from
    updated_at to merged_at/closed_at) -- using each PR's own number as the
    run boundary. This is why the caller must pass run_id_field="pr_number"
    to WorkflowDiscovery directly rather than going through from_raw_events:
    PRs are routinely open concurrently in any active repo, so a single
    global time-gap segmentation would incorrectly interleave events from
    different PRs. Knowing the true boundary (the PR itself) sidesteps that
    entirely, rather than working around it after the fact.

    Every PR shares the same two step names by construction, so
    discover_workflows finds one cluster -- the actual signal here is
    detect_anomalous_runs surfacing which specific PRs took unusually long,
    and whether that was mostly waiting on the author (pr_opened) or on
    review (pr_merged/pr_closed).

    Unauthenticated requests are capped at 60/hour by GitHub -- fine for a
    single demo call. Pass a personal access token via `token` only if you
    hit that limit; never required for a public repo."""
    import json as _json
    import urllib.request

    url = (
        f"https://api.github.com/repos/{owner}/{repo}/pulls"
        f"?state=closed&per_page={max_prs}&sort=updated&direction=desc"
    )
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "isse-automate-kardo-hackathon-demo",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        prs = _json.loads(resp.read().decode())

    out = []
    for pr in prs:
        end = pr.get("merged_at") or pr.get("closed_at")
        if not pr.get("created_at") or not end:
            continue
        created = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
        updated = datetime.fromisoformat(pr["updated_at"].replace("Z", "+00:00"))
        closed = datetime.fromisoformat(end.replace("Z", "+00:00"))
        # updated_at can land at/before created_at (no activity) or after
        # closed_at (an unrelated later metadata edit) -- clamp so neither
        # derived duration below goes negative.
        updated = max(created, min(updated, closed))

        out.append({
            "workflow_run_id": pr["number"],
            "timestamp": created.isoformat(),
            "activity": "pr_opened",
            "duration_minutes": max((updated - created).total_seconds() / 60, 0.1),
        })
        out.append({
            "workflow_run_id": pr["number"],
            "timestamp": updated.isoformat(),
            "activity": "pr_merged" if pr.get("merged_at") else "pr_closed",
            "duration_minutes": max((closed - updated).total_seconds() / 60, 0.1),
        })
    out.sort(key=lambda e: e["timestamp"])
    return out
