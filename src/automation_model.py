"""
Step-level automation suitability.

The original scorer only knew a fixed list of step names from the synthetic
dataset, so any real workflow (different step names) had nothing it could
propose. This module scores a step from two things instead:

  * a prior on how much human judgment the step needs, read from the verbs in
    its name (download/export/rename are mechanical, review/approve/debug are
    not), and
  * what the data says about it: how consistently it shows up across runs,
    how much its duration varies, and how often it needed rework.

Steps the synthetic dataset already defines keep exactly their original
verdicts, so existing behaviour is unchanged.
"""

import re

from synthetic_data import STEP_JUDGMENT_COST

LEGACY_AUTOMATABLE = {"column_cleanup", "rename", "export", "upload", "file_download", "account_create"}

_LOW_JUDGMENT_STEMS = (
    "download", "export", "upload", "copy", "paste", "renam", "sav", "format", "clean", "sort",
    "filter", "convert", "backup", "sync", "fetch", "pull", "push", "merge", "archiv", "attach",
    "scan", "print", "refresh", "transform", "extract", "load", "import", "rout", "forward",
    "notif", "remind", "schedul", "populat", "generat", "compil", "aggregat", "collat", "pivot",
    "dedup", "validat", "label",
    "send", "creat", "collect", "regist", "provision", "updat", "record", "log", "enter",
    "assign", "submit", "publish", "book", "generat", "ingest", "queue", "post",
)
_HIGH_JUDGMENT_STEMS = (
    "review", "approv", "decid", "discuss", "meet", "call", "design", "writ", "debug",
    "investigat", "fix", "escalat", "negotiat", "plan", "brainstorm", "interview", "triag",
    "reason", "research", "analy", "communicat", "chat", "repl", "respond", "diagnos", "draft",
    "think", "code",
)

MAX_AUTOMATABLE_JUDGMENT = 0.30
MIN_PRESENCE = 0.60
MAX_STEP_REWORK = 0.20


def prior_judgment_cost(step):
    """0 (mechanical) .. 1 (needs a person). Known steps use the original table."""
    if step in STEP_JUDGMENT_COST:
        return STEP_JUDGMENT_COST[step]
    tokens = [t for t in re.split(r"[^a-z0-9]+", str(step).lower()) if t]
    low = any(t.startswith(_LOW_JUDGMENT_STEMS) for t in tokens)
    high = any(t.startswith(_HIGH_JUDGMENT_STEMS) for t in tokens)
    if low and not high:
        return 0.2
    if high and not low:
        return 0.75
    return 0.5


def step_verdicts(step_breakdown, total_runs):
    """One verdict per step from debug_workflow's breakdown. Never raises on
    thin data: missing stats fall back to neutral values."""
    verdicts = []
    for s in step_breakdown:
        step = s["step"]
        known = step in STEP_JUDGMENT_COST
        prior = prior_judgment_cost(step)
        cv = float(s.get("cv", 0.0) or 0.0)
        with_step = s.get("runs_with_step", total_runs) or 0
        presence = (with_step / total_runs) if total_runs else 0.0
        rework_rate = s.get("rework_occurrences", 0) / with_step if with_step else 0.0
        judgment = prior if known else round(0.75 * prior + 0.25 * min(1.0, cv), 3)

        if known:
            automatable = step in LEGACY_AUTOMATABLE
            reason = ("mechanical step" if automatable else "needs human judgment")
        elif presence < MIN_PRESENCE:
            automatable, reason = False, f"only appears in {round(presence * 100)}% of runs"
        elif rework_rate > MAX_STEP_REWORK:
            automatable, reason = False, f"needed rework in {round(rework_rate * 100)}% of its runs"
        elif judgment > MAX_AUTOMATABLE_JUDGMENT:
            automatable, reason = False, ("needs judgment" if prior >= 0.5 else "too variable to automate safely")
        else:
            automatable, reason = True, "mechanical and consistent across runs"

        verdicts.append({
            "step": step,
            "automatable": automatable,
            "judgment_cost": round(judgment, 2),
            "presence": round(presence, 2),
            "reason": reason,
        })
    return verdicts


def eligible_steps(step_breakdown, total_runs):
    return [v["step"] for v in step_verdicts(step_breakdown, total_runs) if v["automatable"]]
