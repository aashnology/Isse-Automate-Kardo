"""
Diagnosis and time-saved estimation.

Nothing here executes anything against a user's real applications. Automation
is evaluated in *shadow mode*: the proposed steps are replayed against the
recorded history to measure what they would have saved, and the estimate is
checked on a chronological holdout (fit on the earlier runs, scored on the
later ones). That makes "how much time did it save" a measured quantity on
the user's own data, with an interval, rather than a guess.

reliability() turns the evidence behind that estimate into a 0-100 score with
named components, so every point of the score can be defended.
"""

import random
import statistics
from collections import Counter
from datetime import datetime, timezone

from automation_model import step_verdicts
from workflow_discovery import sequence_similarity

RESIDUAL_OVERHEAD = 0.10   # share of an automated step's time still spent supervising it
HOLDOUT_FRACTION = 0.30
MIN_RUNS_FOR_HOLDOUT = 6
BOOTSTRAP_SAMPLES = 1000
WEEKS_PER_MONTH = 4.345
TARGET_RUNS = 12            # runs at which sample-size evidence is treated as full

WEIGHTS = {"evidence": 0.20, "stability": 0.20, "coverage": 0.20,
           "cohesion": 0.15, "holdout": 0.15, "outcome": 0.10}


def _ts(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _runs(ws, workflow):
    runs = ws.radar.detect_workflows().get(workflow) or []
    return sorted(runs, key=lambda r: _ts(r[0]["timestamp"]))


def _saving(run, steps):
    return sum(e["duration_minutes"] for e in run if e["activity"] in steps) * (1 - RESIDUAL_OVERHEAD)


def _runs_per_week(runs):
    first = _ts(runs[0][0]["timestamp"])
    last = max(_ts(e["timestamp"]) for r in runs for e in r)
    weeks = max(1.0, (last - first).total_seconds() / 86400 / 7)
    return len(runs) / weeks


def time_saved(ws, workflow, steps):
    runs = _runs(ws, workflow)
    if not runs or not steps:
        return None
    steps = set(steps)
    per_run = [_saving(r, steps) for r in runs]
    mean = statistics.fmean(per_run)
    rpw = _runs_per_week(runs)

    rng = random.Random(7)
    means = sorted(statistics.fmean(rng.choices(per_run, k=len(per_run))) for _ in range(BOOTSTRAP_SAMPLES))
    low, high = means[int(0.10 * BOOTSTRAP_SAMPLES)], means[int(0.90 * BOOTSTRAP_SAMPLES) - 1]

    holdout = None
    if len(runs) >= MIN_RUNS_FOR_HOLDOUT:
        cut = max(1, int(round(len(runs) * (1 - HOLDOUT_FRACTION))))
        train, test = per_run[:cut], per_run[cut:]
        if test:
            predicted, actual = statistics.fmean(train), statistics.fmean(test)
            error = abs(predicted - actual) / actual if actual else (0.0 if not predicted else 1.0)
            holdout = {"train_runs": len(train), "test_runs": len(test),
                       "predicted_minutes_per_run": round(predicted, 1),
                       "actual_minutes_per_run": round(actual, 1), "relative_error": round(error, 3)}

    return {
        "mode": "shadow_replay",
        "runs_replayed": len(runs),
        "minutes_saved_per_run": round(mean, 1),
        "history_minutes_saved": round(sum(per_run), 1),
        "runs_per_week": round(rpw, 2),
        "hours_saved_per_week": round(mean * rpw / 60, 2),
        "hours_saved_per_month": round(mean * rpw * WEEKS_PER_MONTH / 60, 1),
        "weekly_hours_interval_80": [round(low * rpw / 60, 2), round(high * rpw / 60, 2)],
        "supervision_overhead": RESIDUAL_OVERHEAD,
        "holdout": holdout,
    }


def _cv(values):
    if len(values) < 2:
        return 1.0
    m = statistics.fmean(values)
    return statistics.pstdev(values) / m if m else 1.0


def reliability(ws, workflow, steps, saved):
    runs = _runs(ws, workflow)
    n, steps = len(runs), set(steps)

    per_step = {s: [e["duration_minutes"] for r in runs for e in r if e["activity"] == s] for s in steps}
    stability = 1 - min(1.0, statistics.fmean(_cv(v) for v in per_step.values())) if per_step else 0.0
    coverage = sum(1 for r in runs if steps <= {e["activity"] for e in r}) / n if n else 0.0
    seqs = [tuple(e["activity"] for e in r) for r in runs]
    canonical = Counter(seqs).most_common(1)[0][0] if seqs else ()
    cohesion = statistics.fmean(sequence_similarity(s, canonical) for s in seqs) if seqs else 0.0
    h = saved.get("holdout") if saved else None
    holdout = max(0.0, 1 - min(1.0, h["relative_error"])) if h else 0.5
    outcome = 1.0 if ws.outcome_known else 0.7

    comps = {"evidence": min(1.0, n / TARGET_RUNS), "stability": stability, "coverage": coverage,
             "cohesion": cohesion, "holdout": holdout, "outcome": outcome}
    score = round(100 * sum(WEIGHTS[k] * v for k, v in comps.items()))
    grade, label = (("A", "High confidence") if score >= 80 else ("B", "Good confidence") if score >= 65
                    else ("C", "Moderate confidence") if score >= 50 else ("D", "Low confidence"))

    caveats = ["Savings come from replaying recorded history; nothing ran against your live apps."]
    improve = []
    if n < TARGET_RUNS:
        caveats.append(f"Only {n} run(s) observed; estimates firm up around {TARGET_RUNS}.")
        improve.append("Import more history of this workflow.")
    if not ws.outcome_known:
        caveats.append("This data has no success or rework signal, so result quality is unverified.")
        improve.append("Add an outcome (ok / rework) per run.")
    if h is None:
        caveats.append(f"Too few runs for a holdout check (needs {MIN_RUNS_FOR_HOLDOUT}).")
    elif h["relative_error"] > 0.3:
        caveats.append(f"Holdout missed by {round(h['relative_error'] * 100)}%: recent runs differ from earlier ones.")
    if ws.source == "pasted":
        caveats.append("Pasted steps carry no real timestamps, so weekly and monthly figures assume the import's spacing; per-run savings are the reliable number.")
    if coverage < 0.8:
        caveats.append(f"Only {round(coverage * 100)}% of runs contain every proposed step.")
    if stability < 0.5:
        caveats.append("Durations of the automated steps vary a lot between runs.")

    return {"score": score, "grade": grade, "label": label,
            "components": {k: round(v, 2) for k, v in comps.items()}, "weights": WEIGHTS,
            "caveats": caveats, "to_improve": improve}


def _effort(judgment):
    return "low" if judgment <= 0.2 else "medium" if judgment <= 0.5 else "high"


def build_spec(ws, workflow, steps, verdicts, runs):
    """A declarative description of the proposed automation. It is a plan a
    person or a runner can act on, not executable code."""
    durations = sorted(sum(e["duration_minutes"] for e in r) for r in runs)
    p90 = durations[min(len(durations) - 1, int(0.9 * len(durations)))] if durations else None
    by_step = {v["step"]: v for v in verdicts}
    order = []
    for e in (runs[0] if runs else []):
        if e["activity"] not in order:
            order.append(e["activity"])
    return {
        "workflow": workflow,
        "trigger": f"about {round(_runs_per_week(runs), 1)} run(s) per week, started when the first step appears" if runs else None,
        "steps": [{"step": s, "mode": "automate" if s in steps else "human",
                   "guardrail": ("pause and notify if it runs far past its usual time" if s in steps
                                 else "stays with a person: " + by_step.get(s, {}).get("reason", "needs judgment"))}
                  for s in order or [v["step"] for v in verdicts]],
        "stop_condition_minutes": round(p90 * 1.5, 1) if p90 else None,
    }


def automation_report(ws, workflow, steps):
    """What confirm returns: the shadow-mode result for the steps that were approved."""
    runs = _runs(ws, workflow)
    saved = time_saved(ws, workflow, steps)
    if not saved:
        return {"error": f"Nothing to replay for '{workflow}'."}
    debug = ws.radar.debug_workflow(workflow)
    verdicts = step_verdicts(debug["step_breakdown"], len(runs))
    return {"mode": "shadow_replay", "dataset_id": ws.id, "dataset_label": ws.label,
            "executed_steps": list(steps), "time_saved": saved,
            "reliability": reliability(ws, workflow, steps, saved),
            "automation_spec": build_spec(ws, workflow, set(steps), verdicts, runs)}


def diagnose(ws, workflow):
    """Findings and ranked prescriptions for one workflow, before anything is approved."""
    debug = ws.radar.debug_workflow(workflow)
    if "error" in debug:
        return debug
    runs = _runs(ws, workflow)
    n = len(runs)
    verdicts = step_verdicts(debug["step_breakdown"], n)
    stats = {s["step"]: s for s in debug["step_breakdown"]}
    auto = [v["step"] for v in verdicts if v["automatable"]]
    point = next((p for p in ws.radar.top_friction_points(top_k=999) if p["workflow_name"] == workflow), {})
    total_h = round(point.get("total_time_cost_minutes", 0) / 60, 1)

    findings = []
    top = debug["step_breakdown"][0]
    findings.append({"kind": "bottleneck", "step": top["step"],
                     "text": f"'{top['step']}' is the biggest time sink at {round(top['share_of_total'] * 100)}% of each run ({top['avg_minutes']} min on average)."})
    shaky = max(debug["step_breakdown"], key=lambda s: s.get("cv", 0))
    if shaky.get("cv", 0) > 0.5 and n > 1:
        findings.append({"kind": "variance", "step": shaky["step"],
                         "text": f"'{shaky['step']}' is unpredictable: its duration swings by about {round(shaky['cv'] * 100)}% between runs."})
    if point.get("rework_rate", 0) > 0.05:
        findings.append({"kind": "rework", "text": f"{round(point['rework_rate'] * 100)}% of steps needed rework."})
    anomalies = ws.discovery.detect_anomalous_runs(workflow).get("anomalies", [])
    if anomalies:
        a = anomalies[0]
        findings.append({"kind": "anomaly", "step": a["likely_cause_step"],
                         "text": f"The worst run took {a['total_minutes']} min against a normal ceiling of {a['typical_upper_bound_minutes']}, mostly in '{a['likely_cause_step']}'."})

    saved = time_saved(ws, workflow, auto) if auto else None
    prescriptions = []
    if auto and saved:
        j = max(v["judgment_cost"] for v in verdicts if v["step"] in auto)
        prescriptions.append({"action": "Automate " + ", ".join(auto), "effort": _effort(j),
                              "saves_hours_per_week": saved["hours_saved_per_week"],
                              "why": "These steps are mechanical and consistent across runs."})
    blocked = [v for v in verdicts if not v["automatable"] and stats[v["step"]]["share_of_total"] >= 0.2]
    for v in blocked[:2]:
        prescriptions.append({"action": f"Keep '{v['step']}' with a person, but prepare its inputs ahead of time",
                              "effort": "medium", "saves_hours_per_week": None,
                              "why": f"It takes {round(stats[v['step']]['share_of_total'] * 100)}% of the time and was flagged: {v['reason']}; staging inputs shortens it without removing judgment."})
    if findings and findings[-1]["kind"] == "anomaly":
        prescriptions.append({"action": f"Add an early alert when '{findings[-1]['step']}' overruns", "effort": "low",
                              "saves_hours_per_week": None, "why": "Outlier runs are where most of the lost time hides."})

    return {
        "workflow_name": workflow, "dataset_id": ws.id, "dataset_label": ws.label,
        "observed": {"runs": n, "total_hours": total_h, "avg_minutes_per_run": point.get("avg_duration_minutes"),
                     "rework_rate": point.get("rework_rate"), "automation_tier": point.get("automation_tier"),
                     "automation_potential": point.get("automation_potential")},
        "steps": verdicts, "findings": findings, "prescriptions": prescriptions[:4],
        "automation": ({"eligible_steps": auto, "time_saved": saved,
                        "reliability": reliability(ws, workflow, auto, saved)} if saved else None),
        "next_best_action": prescriptions[0]["action"] if prescriptions else "Collect more runs before automating.",
    }
