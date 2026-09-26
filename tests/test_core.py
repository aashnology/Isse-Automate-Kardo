"""
Unit tests for the deterministic core: friction scoring, sequence-similarity
clustering, session segmentation, and the propose/confirm action layer.

These are separate from evaluation.py / segmentation_eval.py, which report
*quality* metrics (precision@k, Adjusted Rand Index) meant to be read, not
asserted on with a pass/fail threshold. These tests instead check the
contracts each module promises: shapes, invariants, and edge cases -- the
things that would actually break silently if someone refactored this code.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from synthetic_data import generate_activity_events
from friction_radar import FrictionRadar
from workflow_discovery import WorkflowDiscovery, sequence_similarity
from session_segmentation import segment_into_runs, find_gap_threshold
from actions import propose_action, confirm_action


@pytest.fixture(scope="module")
def events():
    # Regenerated here (not read from data/) so the test suite doesn't
    # depend on synthetic_data.py having been run first -- CI runs it
    # separately, but a fresh checkout shouldn't need that step to test.
    return generate_activity_events()


# ---------------------------- FrictionRadar ---------------------------------

def test_top_friction_points_sorted_by_time_cost(events):
    radar = FrictionRadar(events)
    points = radar.top_friction_points(top_k=10)
    costs = [p["total_time_cost_minutes"] for p in points]
    assert costs == sorted(costs, reverse=True)


def test_top_friction_points_respects_top_k(events):
    radar = FrictionRadar(events)
    assert len(radar.top_friction_points(top_k=1)) == 1
    assert len(radar.top_friction_points(top_k=99)) <= 3  # only 3 synthetic workflows exist


def test_automation_tier_is_monotonic_in_score():
    radar = FrictionRadar([])
    assert radar._tier(0.5) == "highly automatable"
    assert radar._tier(0.2) == "partially automatable"
    assert radar._tier(0.05) == "poor automation candidate"


def test_unknown_workflow_returns_error_not_exception(events):
    radar = FrictionRadar(events)
    assert radar.estimate_time_cost("not_a_real_workflow") is None
    result = radar.debug_workflow("not_a_real_workflow")
    assert "error" in result


def test_debug_workflow_step_shares_sum_to_one(events):
    radar = FrictionRadar(events)
    result = radar.debug_workflow("bug_triage")
    total_share = sum(s["share_of_total"] for s in result["step_breakdown"])
    assert total_share == pytest.approx(1.0, abs=1e-6)


# ---------------------------- WorkflowDiscovery ------------------------------

def test_sequence_similarity_identical_sequences_is_one():
    seq = ("a", "b", "c")
    assert sequence_similarity(seq, seq) == 1.0


def test_sequence_similarity_empty_sequence_is_zero():
    assert sequence_similarity((), ("a", "b")) == 0.0


def test_sequence_similarity_is_symmetric():
    a, b = ("a", "b", "c"), ("a", "c", "d")
    assert sequence_similarity(a, b) == sequence_similarity(b, a)


def test_discover_recovers_the_known_workflow_count(events):
    # Ground truth: synthetic_data.py defines exactly 3 workflow templates.
    # Clustering purely on sequence similarity, with no access to
    # workflow_name, should recover close to that -- this is the actual
    # "did discovery work" check, ground truth is only used for validation.
    wd = WorkflowDiscovery(events, similarity_threshold=0.75)
    clusters = wd.discover()
    assert 1 <= len(clusters) <= 6  # allows some fragmentation, not total collapse or explosion
    for c in clusters:
        assert c["label_purity"] is None or c["label_purity"] >= 0.5


def test_discover_from_raw_events_needs_no_labels(events):
    raw = [
        {"timestamp": e["timestamp"], "activity": e["activity"],
         "duration_minutes": e["duration_minutes"], "outcome": e["outcome"]}
        for e in events
    ]
    wd = WorkflowDiscovery.from_raw_events(raw)
    clusters = wd.discover()
    assert len(clusters) > 0
    # matched_label falls back to a generated name when workflow_name is absent
    assert all(c["matched_label"].startswith("discovered_workflow_") for c in clusters)


def test_anomaly_detection_needs_minimum_sample_size():
    # 3 runs of the same made-up workflow -- below the n>=4 threshold in
    # detect_anomalous_runs -- should report "not enough data", not crash
    # or fabricate an answer.
    tiny_events = []
    for run_id in range(3):
        for i, step in enumerate(["a", "b"]):
            tiny_events.append({
                "workflow_run_id": run_id, "workflow_name": "tiny_flow",
                "activity": step, "timestamp": f"2026-01-0{run_id + 1}T10:0{i}:00",
                "duration_minutes": 5, "outcome": "success",
            })
    wd = WorkflowDiscovery(tiny_events, similarity_threshold=0.75)
    result = wd.detect_anomalous_runs("tiny_flow")
    assert result["anomalies"] == []
    assert "note" in result


# ---------------------------- session_segmentation ---------------------------

def test_segmentation_recovers_ground_truth_reasonably_well(events):
    from session_segmentation import evaluate_against_ground_truth

    segmented, runs, threshold = segment_into_runs(events)
    ari = evaluate_against_ground_truth(segmented)
    # 0.876 measured on the committed dataset (see README); a fresh seeded
    # regeneration should land in the same neighborhood, not collapse.
    assert ari > 0.6


def test_gap_threshold_is_finite_for_realistic_data(events):
    threshold = find_gap_threshold(events)
    assert threshold > 0
    assert threshold != float("inf")


def test_gap_threshold_is_infinite_for_too_little_data():
    tiny = [
        {"timestamp": "2026-01-01T10:00:00", "activity": "a"},
        {"timestamp": "2026-01-01T10:05:00", "activity": "b"},
    ]
    assert find_gap_threshold(tiny) == float("inf")


# ---------------------------- actions (human-in-the-loop) --------------------

def test_propose_then_confirm_executes_once():
    debug_result = {"step_breakdown": [{"step": "export"}, {"step": "cross_check"}]}
    proposal = propose_action("weekly_reporting", debug_result)
    assert proposal["status"] == "pending_confirmation"
    assert proposal["proposed_automation"] == ["export"]  # cross_check needs judgment

    result = confirm_action(proposal["proposal_id"])
    assert result["status"] == "executed"

    # confirming the same proposal twice must not silently "succeed" again
    second = confirm_action(proposal["proposal_id"])
    assert "error" in second


def test_confirm_unknown_proposal_errors_cleanly():
    result = confirm_action("not-a-real-id")
    assert "error" in result


def test_propose_with_no_automatable_steps_returns_no_proposal_id():
    debug_result = {"step_breakdown": [{"step": "approval_wait"}, {"step": "cross_check"}]}
    proposal = propose_action("onboarding_new_partner", debug_result)
    assert proposal["proposal_id"] is None
