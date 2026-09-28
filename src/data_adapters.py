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
import io
import re
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


_ACTIVITY_HEADERS = ("activity", "description", "task", "step", "name", "event", "project")
_TIMESTAMP_HEADERS = ("timestamp", "start", "start time", "datetime", "date time", "time", "date")
_DURATION_HEADERS = ("duration_minutes", "duration", "minutes", "time spent")


def _find_header(headers, candidates):
    lowered = {h.strip().lower(): h for h in headers if h}
    for c in candidates:
        if c in lowered:
            return lowered[c]
    return None


def _parse_duration_minutes(value, default):
    value = (value or "").strip()
    if not value:
        return default
    if ":" in value:  # HH:MM:SS or MM:SS
        parts = [float(x) for x in value.split(":")]
        while len(parts) < 3:
            parts.insert(0, 0.0)
        h, m, sec = parts[-3:]
        return h * 60 + m + sec / 60
    return float(value)


def _parse_timestamp(value):
    """ISO-style only, on purpose. Sheets export dates in the sheet's own
    locale, so "03/04/2026" is March 4th for one person and April 3rd for
    another -- and this project shouldn't silently guess which. Anything
    unambiguous (2026-03-04 09:15:00, or with a T or a timezone) works;
    anything else is rejected with a message saying how to fix the sheet.
    Timezone-aware values are converted to UTC and made naive so a sheet
    mixing the two can't crash the segmentation step."""
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def from_csv_text(text, default_duration=5.0):
    """A generic CSV/Sheet importer for data that isn't a Toggl export.
    Needs an activity column and a timestamp column (found by common header
    names, case-insensitive); duration is optional and defaults to 5
    minutes. Also understands Toggl-style split "Start date" + "Start time"
    columns, so a Toggl export pasted into a Sheet still works.

    Raises ValueError with a message meant to be shown to the user, because
    "your sheet has no recognizable timestamp column" is something they can
    actually fix, unlike a stack trace."""
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    activity_col = _find_header(headers, _ACTIVITY_HEADERS)
    duration_col = _find_header(headers, _DURATION_HEADERS)
    date_col = _find_header(headers, ("start date",))
    time_col = _find_header(headers, ("start time",)) if date_col else None
    ts_col = None if (date_col and time_col) else _find_header(headers, _TIMESTAMP_HEADERS)

    if not activity_col or not (ts_col or (date_col and time_col)):
        raise ValueError(
            "Couldn't find the columns I need. Give the sheet a header row with "
            "an activity column (activity / description / task / step) and a "
            "timestamp column (timestamp / start / datetime), written like "
            "2026-03-04 09:15:00. A duration column (minutes, or HH:MM:SS) is optional."
        )

    out = []
    for row_num, row in enumerate(reader, start=2):
        activity = (row.get(activity_col) or "").strip()
        if not activity:
            continue
        raw_ts = f"{row[date_col]} {row[time_col]}" if (date_col and time_col) else (row.get(ts_col) or "")
        try:
            ts = _parse_timestamp(raw_ts)
            duration = _parse_duration_minutes(row.get(duration_col) if duration_col else None, default_duration)
        except ValueError:
            raise ValueError(
                f"Row {row_num}: couldn't read the timestamp or duration "
                f"({raw_ts!r}). Use dates like 2026-03-04 09:15:00, and a number of "
                "minutes (or HH:MM:SS) for duration."
            )
        out.append({"timestamp": ts.isoformat(), "activity": activity, "duration_minutes": duration})
    out.sort(key=lambda e: e["timestamp"])
    return out


_GOOGLE_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")
MAX_REMOTE_BYTES = 2 * 1024 * 1024


def google_export_url(link):
    """Turn a pasted Google Sheets or Drive link into the one fixed-origin
    URL this project is willing to fetch. The user's link is only ever
    mined for an ID (validated against a strict pattern); it is never
    fetched itself. That matters: a server that fetches whatever URL it's
    handed can be aimed at internal addresses. Here the host is always
    docs.google.com or drive.google.com, no matter what was pasted.

    Returns (url, kind) or raises ValueError. Private files are handled at
    fetch time, since Google answers those with a login page, not an error."""
    link = (link or "").strip()
    m = re.search(r"docs\.google\.com/spreadsheets/d/([^/?#]+)", link)
    if m:
        sheet_id = m.group(1)
        if not _GOOGLE_ID.match(sheet_id):
            raise ValueError("That doesn't look like a valid Google Sheets link.")
        gid = re.search(r"[#&?]gid=(\d+)", link)
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        if gid:
            url += f"&gid={gid.group(1)}"
        return url, "sheet"
    m = re.search(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?[^ ]*?id=)([A-Za-z0-9_-]+)", link)
    if m:
        file_id = m.group(1)
        if not _GOOGLE_ID.match(file_id):
            raise ValueError("That doesn't look like a valid Google Drive link.")
        return f"https://drive.google.com/uc?export=download&id={file_id}", "drive"
    raise ValueError("Paste a link to a Google Sheet or a Drive file that's shared as 'anyone with the link'.")


def fetch_google_file(link, opener=None):
    """Read-only fetch of a publicly shared Sheet/Drive file, capped at
    MAX_REMOTE_BYTES. Returns the file's text. `opener` exists so tests can
    substitute a fake without touching the network."""
    import urllib.request

    url, _ = google_export_url(link)
    open_url = opener or (lambda u: urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": "isse-automate-kardo-hackathon-demo"}),
        timeout=15,
    ))
    import urllib.error

    try:
        with open_url(url) as resp:
            body = resp.read(MAX_REMOTE_BYTES + 1)
            content_type = (resp.headers.get("Content-Type", "") if hasattr(resp, "headers") else "")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            # Google answers a private or mistyped file with one of these;
            # "HTTP 403" alone tells the user nothing they can act on.
            raise ValueError(
                "Google wouldn't give me that file. Check the link, and that it's "
                "shared as 'anyone with the link can view'."
            )
        raise
    if len(body) > MAX_REMOTE_BYTES:
        raise ValueError("That file is larger than 2 MB, which is more than this demo will read.")
    text = body.decode("utf-8-sig", errors="replace")
    # Private files don't error -- Google serves a sign-in HTML page with a 200.
    if "text/html" in content_type.lower() or text.lstrip().lower().startswith(("<!doctype html", "<html")):
        raise ValueError(
            "I can only read files shared as 'anyone with the link can view'. "
            "This one looks private, so Google sent a sign-in page instead."
        )
    return text
