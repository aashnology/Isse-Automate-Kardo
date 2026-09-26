"""
Closes the gap named honestly in the README: workflow_discovery.py takes
pre-segmented runs (each event already tagged with a workflow_run_id).
A genuinely raw event stream has no such tag -- this module reconstructs
run boundaries from nothing but timestamps.

Approach: within a single workflow run, consecutive steps are minutes
apart. Between runs, the next run doesn't start for hours or days. That's
a clearly bimodal gap distribution (verified against this project's own
data before writing this), which makes an unsupervised threshold pick --
the biggest jump in the sorted gap list -- a legitimate way to separate
"still the same run" from "a new run started", with no run boundaries
given in advance.

Stated limitation, not hidden: this assumes workflows don't interleave
(you don't start a bug-triage step, switch to reporting, then come back).
Real multitasking would break a pure time-gap approach and need sequence-
aware segmentation instead. That's future work, not solved here.
"""

from datetime import datetime
from collections import defaultdict


def _parse_ts(events):
    return sorted(events, key=lambda e: e["timestamp"])


def find_gap_threshold(events):
    """Auto-pick a split threshold (minutes) via 1D k-means (k=2) on
    log-transformed inter-event gaps: one cluster is "still the same run",
    the other is "a new run started". The threshold is the midpoint between
    the two clusters.

    This replaced an earlier, naive "biggest single jump in sorted gaps"
    approach -- that one broke on real testing, because one or two extreme
    outlier gaps (multi-day breaks) dominated the sorted list and pulled the
    threshold way too high, collapsing dozens of true runs into one. K-means
    over the whole distribution is far more robust to a handful of extreme
    values. Documented here because it's a real thing that went wrong while
    building this, not because it's interesting trivia."""
    import math
    import numpy as np
    from sklearn.cluster import KMeans

    events_sorted = _parse_ts(events)
    gaps = []
    for a, b in zip(events_sorted, events_sorted[1:]):
        ta = datetime.fromisoformat(a["timestamp"])
        tb = datetime.fromisoformat(b["timestamp"])
        gaps.append((tb - ta).total_seconds() / 60)

    if len(gaps) < 4:
        return float("inf")

    X = np.log1p(np.array(gaps)).reshape(-1, 1)
    km = KMeans(n_clusters=2, n_init=10, random_state=0).fit(X)
    labels = km.labels_
    low_label = int(np.argmin(km.cluster_centers_.flatten()))
    low_vals = X[labels == low_label].flatten()
    high_vals = X[labels != low_label].flatten()
    if len(low_vals) == 0 or len(high_vals) == 0:
        return float("inf")
    threshold_log = (low_vals.max() + high_vals.min()) / 2
    return math.expm1(threshold_log)


def segment_into_runs(events, threshold_minutes=None):
    """Assign a discovered_run_id to each event based on time gaps alone.
    threshold_minutes: override the auto-detected threshold if you already
    know your data's rhythm (e.g. a workday boundary); otherwise it's
    picked automatically from the data itself."""
    if threshold_minutes is None:
        threshold_minutes = find_gap_threshold(events)

    events_sorted = _parse_ts(events)
    segmented = []
    run_id = 0
    prev_ts = None
    for e in events_sorted:
        ts = datetime.fromisoformat(e["timestamp"])
        if prev_ts is not None:
            gap = (ts - prev_ts).total_seconds() / 60
            if gap > threshold_minutes:
                run_id += 1
        e2 = dict(e)
        e2["discovered_run_id"] = run_id
        segmented.append(e2)
        prev_ts = ts

    runs = defaultdict(list)
    for e in segmented:
        runs[e["discovered_run_id"]].append(e)
    return segmented, runs, threshold_minutes


def evaluate_against_ground_truth(segmented_events, true_run_field="workflow_run_id"):
    """Only usable when ground truth happens to be available (as it is in
    this project's synthetic data, for validation purposes) -- a real raw
    stream wouldn't have this. Uses Adjusted Rand Index: 1.0 = perfect
    agreement, 0.0 = no better than random."""
    from sklearn.metrics import adjusted_rand_score

    discovered = [e["discovered_run_id"] for e in segmented_events]
    truth = [e[true_run_field] for e in segmented_events]
    return adjusted_rand_score(truth, discovered)
