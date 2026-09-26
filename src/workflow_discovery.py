"""
Three upgrades over the V1 friction radar, addressing the same underlying
gap: V1's `detect_workflows()` just group-by's the `workflow_name` field
that the synthetic data generator happens to attach to each event. That's
aggregation, not discovery -- a real event stream has no such label.

This module does the actual process-mining steps: given only run_id + ordered
activity sequences (no workflow_name), cluster runs into workflows by
sequence similarity; separately flag individual runs that are statistically
unusual for their own cluster; and -- via `from_raw_events` -- reconstruct
run boundaries themselves from a truly raw, unsegmented event stream using
session_segmentation.py, so the whole pipeline can run without being handed
pre-cut runs at all.

Honest boundary, stated here and in the README: session segmentation (see
session_segmentation.py) uses time gaps alone, which assumes workflows don't
interleave. Genuinely concurrent/multitasked workflows would need
sequence-aware segmentation, which isn't built here.
"""

from collections import defaultdict
import statistics

from session_segmentation import segment_into_runs


def _lcs_length(a, b):
    """Longest common subsequence length -- classic O(n*m) DP.
    Order-aware, tolerant of insertions/deletions/extra steps, which is
    exactly the noise you'd expect between two runs of 'the same' workflow."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][m]


def sequence_similarity(seq_a, seq_b):
    """Normalized LCS similarity in [0, 1]. 1.0 = identical order-preserved
    sequence; lower values tolerate reordering, extra, or missing steps."""
    if not seq_a or not seq_b:
        return 0.0
    lcs = _lcs_length(seq_a, seq_b)
    return lcs / max(len(seq_a), len(seq_b))


class WorkflowDiscovery:
    def __init__(self, events, similarity_threshold=0.75, run_id_field="workflow_run_id"):
        self.events = events
        self.threshold = similarity_threshold
        self.run_id_field = run_id_field
        self.runs = self._group_into_runs(events)  # run_id -> ordered events
        self.run_ids = list(self.runs.keys())
        self.sequences = {
            rid: tuple(e["activity"] for e in run) for rid, run in self.runs.items()
        }

    @classmethod
    def from_raw_events(cls, raw_events, similarity_threshold=0.75, segmentation_threshold_minutes=None):
        """The genuinely-no-labels entry point: takes events with nothing
        but timestamp/activity/duration (no run id, no workflow name),
        reconstructs run boundaries via session_segmentation, then clusters
        those discovered runs into workflows exactly as __init__ would with
        pre-given runs. This is the honest end-to-end path; __init__ with a
        pre-existing run_id_field is the shortcut used when that boundary is
        already known (e.g. this project's own synthetic data)."""
        segmented, _, _ = segment_into_runs(raw_events, segmentation_threshold_minutes)
        return cls(segmented, similarity_threshold=similarity_threshold, run_id_field="discovered_run_id")

    def _group_into_runs(self, events):
        runs = defaultdict(list)
        for e in events:
            runs[e[self.run_id_field]].append(e)
        for rid in runs:
            runs[rid].sort(key=lambda e: e["timestamp"])
        return runs

    def discover(self):
        """Union-find clustering over pairwise sequence similarity. Does NOT
        look at workflow_name -- that field is only used afterward, to label
        the discovered clusters for the demo narration, and to sanity-check
        the clustering against ground truth while building this."""
        n = len(self.run_ids)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i in range(n):
            for j in range(i + 1, n):
                sim = sequence_similarity(self.sequences[self.run_ids[i]], self.sequences[self.run_ids[j]])
                if sim >= self.threshold:
                    union(i, j)

        clusters = defaultdict(list)
        for i in range(n):
            clusters[find(i)].append(self.run_ids[i])

        results = []
        for cluster_run_ids in clusters.values():
            # canonical sequence = the medoid: the run whose sequence has the
            # highest average similarity to every other run in its cluster
            best_rid, best_avg = None, -1
            for rid in cluster_run_ids:
                sims = [
                    sequence_similarity(self.sequences[rid], self.sequences[other])
                    for other in cluster_run_ids if other != rid
                ] or [1.0]
                avg = sum(sims) / len(sims)
                if avg > best_avg:
                    best_avg, best_rid = avg, rid

            # ground-truth label is only attached for readability in the demo --
            # majority vote over the cluster, never used by the clustering itself.
            # Not available at all on a genuinely raw stream (no workflow_name
            # field exists) -- handled gracefully rather than assumed present.
            if all("workflow_name" in self.runs[rid][0] for rid in cluster_run_ids):
                true_labels = [self.runs[rid][0]["workflow_name"] for rid in cluster_run_ids]
                majority_label = max(set(true_labels), key=true_labels.count)
                label_purity = true_labels.count(majority_label) / len(true_labels)
            else:
                majority_label = f"discovered_workflow_{len(results)}"
                label_purity = None

            results.append({
                "discovered_id": f"cluster_{len(results)}",
                "matched_label": majority_label,
                "label_purity": round(label_purity, 2) if label_purity is not None else None,
                "run_count": len(cluster_run_ids),
                "canonical_sequence": list(self.sequences[best_rid]),
                "run_ids": cluster_run_ids,
            })

        results.sort(key=lambda c: -c["run_count"])
        return results

    def detect_anomalous_runs(self, workflow_label, top_k=3):
        """IQR-based outlier detection on total run duration, scoped to runs
        matching a discovered cluster's majority label. Robust to the
        right-skew you'd expect in time-cost data (most runs cluster near
        the median, a few blow way past it)."""
        clusters = self.discover()
        cluster = next((c for c in clusters if c["matched_label"] == workflow_label), None)
        if not cluster:
            return {"error": f"No discovered cluster matches '{workflow_label}'"}

        durations = []
        for rid in cluster["run_ids"]:
            total = sum(e["duration_minutes"] for e in self.runs[rid])
            durations.append((rid, total))

        values = sorted(d for _, d in durations)
        n = len(values)
        if n < 4:
            return {"workflow_label": workflow_label, "anomalies": [], "note": "Not enough runs to detect outliers reliably."}

        q1 = statistics.median(values[: n // 2])
        q3 = statistics.median(values[(n + 1) // 2:])
        iqr = q3 - q1
        upper_fence = q3 + 1.5 * iqr

        anomalies = []
        for rid, total in durations:
            if total > upper_fence:
                # which step drove it: compare this run's step durations to
                # this cluster's per-step average
                step_avgs = self._step_averages(cluster["run_ids"])
                run_steps = {e["activity"]: e["duration_minutes"] for e in self.runs[rid]}
                worst_step, worst_excess = None, -1
                for step, dur in run_steps.items():
                    excess = dur - step_avgs.get(step, dur)
                    if excess > worst_excess:
                        worst_excess, worst_step = excess, step
                anomalies.append({
                    "run_id": rid,
                    "total_minutes": round(total, 1),
                    "typical_upper_bound_minutes": round(upper_fence, 1),
                    "likely_cause_step": worst_step,
                    "step_excess_minutes": round(worst_excess, 1),
                })

        anomalies.sort(key=lambda a: -a["total_minutes"])
        return {
            "workflow_label": workflow_label,
            "typical_range_minutes": [round(q1, 1), round(q3, 1)],
            "anomalies": anomalies[:top_k],
        }

    def _step_averages(self, run_ids):
        totals = defaultdict(list)
        for rid in run_ids:
            for e in self.runs[rid]:
                totals[e["activity"]].append(e["duration_minutes"])
        return {step: sum(v) / len(v) for step, v in totals.items()}
