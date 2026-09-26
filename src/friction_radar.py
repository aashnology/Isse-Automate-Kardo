"""
Friction Radar: workflow reconstruction, frequency/time-cost analysis, and
an explainable automation-potential score. No LLM involved -- this is
sequence aggregation over the event log.
"""

from collections import defaultdict
from synthetic_data import STEP_JUDGMENT_COST


class FrictionRadar:
    def __init__(self, events):
        self.events = events
        self.runs = self._group_into_runs(events)

    def _group_into_runs(self, events):
        runs = defaultdict(list)
        for e in events:
            runs[e["workflow_run_id"]].append(e)
        for run_id in runs:
            runs[run_id].sort(key=lambda e: e["timestamp"])
        return runs

    def detect_workflows(self):
        """Group runs by workflow_name (in a system without labels, this is
        where sequence-similarity clustering would go -- here the label is
        already present in the synthetic data, so we aggregate directly)."""
        by_workflow = defaultdict(list)
        for run in self.runs.values():
            by_workflow[run[0]["workflow_name"]].append(run)
        return by_workflow

    def top_friction_points(self, top_k=3):
        by_workflow = self.detect_workflows()
        results = []
        for name, runs in by_workflow.items():
            frequency = len(runs)
            total_minutes = sum(sum(e["duration_minutes"] for e in run) for run in runs)
            avg_minutes = total_minutes / frequency
            rework_rate = sum(1 for run in runs for e in run if e["outcome"] == "rework") / max(
                1, sum(len(run) for run in runs)
            )
            steps = [e["activity"] for e in runs[0]]
            avg_judgment_cost = sum(STEP_JUDGMENT_COST.get(s, 0.5) for s in steps) / len(steps)
            automation_potential = self._automation_score(
                frequency, avg_judgment_cost, total_minutes, rework_rate
            )
            results.append({
                "workflow_name": name,
                "frequency": frequency,
                "total_time_cost_minutes": round(total_minutes, 1),
                "avg_duration_minutes": round(avg_minutes, 1),
                "rework_rate": round(rework_rate, 3),
                "steps": steps,
                "automation_potential": round(automation_potential, 3),
                "automation_tier": self._tier(automation_potential),
            })
        results.sort(key=lambda r: -r["total_time_cost_minutes"])
        return results[:top_k]

    def _automation_score(self, frequency, avg_judgment_cost, total_minutes, rework_rate):
        """
        automation_potential = repetition_norm * predictability * time_cost_norm

        - repetition_norm: more occurrences -> more worth automating (caps at 1.0)
        - predictability: inverse of judgment cost and rework rate (steps needing
          human judgment, or that frequently need rework, are less automatable)
        - time_cost_norm: bigger time sink -> higher priority (caps at 1.0)
        """
        repetition_norm = min(1.0, frequency / 10)
        predictability = max(0.0, (1 - avg_judgment_cost) * (1 - rework_rate))
        time_cost_norm = min(1.0, total_minutes / 300)
        return repetition_norm * predictability * time_cost_norm

    def _tier(self, score):
        if score >= 0.4:
            return "highly automatable"
        if score >= 0.15:
            return "partially automatable"
        return "poor automation candidate"

    def explain(self, workflow_name):
        points = {p["workflow_name"]: p for p in self.top_friction_points(top_k=99)}
        p = points.get(workflow_name)
        if not p:
            return f"I don't have friction data for '{workflow_name}'."
        return (
            f"'{workflow_name}' occurred {p['frequency']} times, costing about "
            f"{round(p['total_time_cost_minutes'] / 60, 1)} hours total. It's "
            f"{p['automation_tier']} because "
            + ("it repeats often and its steps are mostly low-judgment." if p['automation_potential'] >= 0.15
               else "it either doesn't repeat enough or needs too much human judgment.")
        )

    def debug_workflow(self, workflow_name):
        """Root-cause style breakdown: which steps actually consume the time
        in this workflow, on average, across all observed runs. This is the
        'why did this take so long' answer -- a bottleneck analysis over the
        already-collected event log, not a new data source."""
        by_workflow = self.detect_workflows()
        runs = by_workflow.get(workflow_name)
        if not runs:
            return {"error": f"No data for workflow '{workflow_name}'"}

        step_totals = defaultdict(list)
        rework_steps = defaultdict(int)
        for run in runs:
            for e in run:
                step_totals[e["activity"]].append(e["duration_minutes"])
                if e["outcome"] == "rework":
                    rework_steps[e["activity"]] += 1

        step_stats = []
        total_avg = sum(sum(v) / len(v) for v in step_totals.values())
        for step, durations in step_totals.items():
            avg = sum(durations) / len(durations)
            step_stats.append({
                "step": step,
                "avg_minutes": round(avg, 1),
                "share_of_total": round(avg / total_avg, 3) if total_avg else 0,
                "rework_occurrences": rework_steps.get(step, 0),
            })
        step_stats.sort(key=lambda s: -s["avg_minutes"])

        bottlenecks = [s for s in step_stats if s["share_of_total"] >= 0.2]
        top_names = ", ".join(f"'{b['step']}'" for b in bottlenecks[:2]) if bottlenecks else "no single step"
        bottleneck_share = round(sum(b["share_of_total"] for b in bottlenecks[:2]) * 100)

        return {
            "workflow_name": workflow_name,
            "step_breakdown": step_stats,
            "bottleneck_steps": [b["step"] for b in bottlenecks],
            "narrative": (
                f"Most of the time isn't the whole workflow -- it's {top_names}, "
                f"which together account for about {bottleneck_share}% of the total time."
                if bottlenecks else
                "Time is fairly evenly spread across steps; no single bottleneck dominates."
            ),
        }

    def estimate_time_cost(self, workflow_name):
        points = {p["workflow_name"]: p for p in self.top_friction_points(top_k=99)}
        p = points.get(workflow_name)
        if not p:
            return None
        return {
            "workflow_name": workflow_name,
            "total_minutes": p["total_time_cost_minutes"],
            "total_hours": round(p["total_time_cost_minutes"] / 60, 2),
            "frequency": p["frequency"],
        }
