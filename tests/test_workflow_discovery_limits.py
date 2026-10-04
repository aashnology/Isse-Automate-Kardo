"""
Regression tests for the perf/DoS fixes in workflow_discovery.py:
- discover() is memoized (detect_anomalous_runs used to re-run the full
  O(n^2) clustering on every call).
- WorkflowDiscovery caps run count and per-run step count so untrusted
  imported data can't force an unbounded O(n^2) / O(len*len) computation.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from workflow_discovery import WorkflowDiscovery, MAX_CLUSTERED_RUNS, MAX_STEPS_PER_RUN


def _events(run_id, steps, start_minute=0):
    out = []
    t = start_minute
    for step in steps:
        out.append({
            "workflow_run_id": run_id,
            "timestamp": f"2026-01-01T00:{t:02d}:00",
            "activity": step,
            "duration_minutes": 1.0,
        })
        t += 1
    return out


def test_discover_result_is_memoized_not_recomputed():
    events = _events(1, ["a", "b", "c"]) + _events(2, ["a", "b", "c"], start_minute=10)
    wd = WorkflowDiscovery(events)
    first = wd.discover()
    # Mutate the cache directly -- if discover() actually recomputed, this
    # sentinel would be gone on the next call.
    wd._discover_cache = "sentinel"
    assert wd.discover() == "sentinel"
    assert first is not None


def test_detect_anomalous_runs_uses_the_cached_discovery():
    events = []
    for run_id in range(6):
        events += _events(run_id, ["a", "b", "c"], start_minute=run_id * 10)
    wd = WorkflowDiscovery(events)
    first_result = wd.discover()
    label = first_result[0]["matched_label"]

    # detect_anomalous_runs calls self.discover() internally; if that were
    # still recomputing, it would build a brand-new list each time instead
    # of returning the exact cached object.
    wd.detect_anomalous_runs(label)
    assert wd.discover() is first_result


def test_run_count_is_capped():
    events = []
    for run_id in range(MAX_CLUSTERED_RUNS + 50):
        events += _events(run_id, ["a", "b"], start_minute=0)
    wd = WorkflowDiscovery(events)
    assert len(wd.run_ids) == MAX_CLUSTERED_RUNS


def test_step_count_per_run_is_capped():
    events = _events(1, [f"step_{i}" for i in range(MAX_STEPS_PER_RUN + 100)])
    wd = WorkflowDiscovery(events)
    assert len(wd.sequences[1]) == MAX_STEPS_PER_RUN
