"""
Validates the from_raw_events pipeline end to end: strips all labels down to
timestamp/activity/duration, runs segmentation + discovery blind, then
checks the result against the ground truth this project's synthetic data
happens to carry (a real raw stream wouldn't have this to check against --
this is purely for validating the method while building it).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from workflow_discovery import WorkflowDiscovery
from session_segmentation import segment_into_runs, evaluate_against_ground_truth, find_gap_threshold


def run_eval():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    events = json.load(open(os.path.join(data_dir, "activity_events.json")))

    threshold = find_gap_threshold(events)
    segmented, runs, _ = segment_into_runs(events)
    ari = evaluate_against_ground_truth(segmented)

    print(f"Auto-detected gap threshold: {threshold:.1f} minutes")
    print(f"True runs: {len(set(e['workflow_run_id'] for e in events))}")
    print(f"Discovered runs: {len(runs)}")
    print(f"Adjusted Rand Index vs ground truth: {ari:.3f}")
    print()

    raw_events = [
        {"timestamp": e["timestamp"], "activity": e["activity"],
         "duration_minutes": e["duration_minutes"], "outcome": e["outcome"]}
        for e in events
    ]
    wd = WorkflowDiscovery.from_raw_events(raw_events)
    clusters = wd.discover()
    print(f"Discovered {len(clusters)} workflow clusters from a fully raw, unlabeled stream:")
    for c in clusters:
        print(f"  {c['discovered_id']}: {c['run_count']} runs -- {c['canonical_sequence']}")

    # honest note on where it struggles: clusters whose canonical sequence
    # is longer than any single known workflow are chimeras -- two
    # back-to-back runs that got merged because they happened close together
    chimera_count = sum(1 for c in clusters if len(c["canonical_sequence"]) > 6)
    print()
    print(f"Chimera clusters (likely two runs merged into one): {chimera_count}")
    print("These come from infrequent workflows (fewer occurrences -> the model")
    print("has less data to learn that workflow's normal timing rhythm).")


if __name__ == "__main__":
    run_eval()
