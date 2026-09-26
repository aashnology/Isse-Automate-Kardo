"""
Deterministic synthetic data generators for both halves of the system.

Signal vs Noise needs a stream of "information items" (articles, papers,
updates) with topics, timestamps, and some engineered near-duplicates so
the dedup/novelty logic has something real to do.

Friction Radar needs a stream of workflow "events" with enough repeated
structure that a sequence miner can actually find something.

Everything here is seeded, so re-running produces the same demo data --
important for a reliable live demo.
"""

import random
import json
from datetime import datetime, timedelta, timezone

random.seed(42)

TOPICS = [
    "recommendation systems", "large language models", "data engineering",
    "reinforcement learning", "product analytics", "distributed systems",
    "computer vision", "MLOps", "developer tools", "database internals",
]

SOURCES = ["ArXiv", "TechBlog", "CompanyEng", "Newsletter", "ResearchDigest", "IndustryNews"]

TEMPLATES = [
    "New paper introduces {topic} approach to {problem}",
    "{company} ships {topic} update for {problem}",
    "Deep dive: how {topic} is changing {problem}",
    "Benchmark results for {topic} methods on {problem}",
    "Opinion: why {topic} matters for {problem}",
]

PROBLEMS = ["cold-start ranking", "latency at scale", "data quality", "personalization",
            "model evaluation", "pipeline reliability", "user retention", "search relevance"]

COMPANIES = ["Spotify", "Pinterest", "Netflix", "Meta", "a research lab", "an open-source project"]


def _make_item(item_id, ts, topic, near_dup_of=None):
    template = random.choice(TEMPLATES)
    title = template.format(topic=topic, problem=random.choice(PROBLEMS),
                             company=random.choice(COMPANIES))
    return {
        "id": item_id,
        "title": title if not near_dup_of else title + " (updated coverage)",
        "topic": topic,
        "source": random.choice(SOURCES),
        "timestamp": ts.isoformat(),
        "near_dup_of": near_dup_of,
        # crude synthetic "impact" and "credibility" priors -- in a real system
        # these would come from source reputation, citation counts, etc.
        "credibility_prior": round(random.uniform(0.4, 1.0), 2),
        "potential_impact_prior": round(random.uniform(0.2, 1.0), 2),
    }


def generate_information_stream(n_items=220, days_back=10, out_path=None):
    now = datetime.now(timezone.utc)
    items = []
    for i in range(n_items):
        ts = now - timedelta(
            days=random.uniform(0, days_back),
            hours=random.uniform(0, 24),
        )
        topic = random.choice(TOPICS)
        item = _make_item(f"item_{i:04d}", ts, topic)
        items.append(item)

        # ~15% chance of generating a near-duplicate of what we just made,
        # so the dedup step has real work to do
        if random.random() < 0.15:
            dup_ts = ts + timedelta(hours=random.uniform(0.5, 6))
            items.append(_make_item(f"item_{i:04d}_dup", dup_ts, topic, near_dup_of=item["id"]))

    items.sort(key=lambda x: x["timestamp"])
    if out_path:
        with open(out_path, "w") as f:
            json.dump(items, f, indent=2)
    return items


# --- Friction Radar synthetic events -----------------------------------

WORKFLOWS = {
    "weekly_reporting": ["file_download", "file_open", "column_cleanup", "rename", "export", "upload"],
    "onboarding_new_partner": ["email_intake", "manual_data_entry", "cross_check", "approval_wait", "account_create"],
    "bug_triage": ["ticket_read", "reproduce_attempt", "context_switch", "log_search", "fix_or_escalate"],
}

# how "automatable" each step is (used later to score automation potential)
STEP_JUDGMENT_COST = {
    "file_download": 0.05, "file_open": 0.05, "column_cleanup": 0.2, "rename": 0.05,
    "export": 0.05, "upload": 0.1, "email_intake": 0.3, "manual_data_entry": 0.4,
    "cross_check": 0.5, "approval_wait": 0.6, "account_create": 0.2,
    "ticket_read": 0.3, "reproduce_attempt": 0.7, "context_switch": 0.8,
    "log_search": 0.4, "fix_or_escalate": 0.9,
}


def generate_activity_events(n_weeks=6, out_path=None):
    now = datetime.now(timezone.utc)
    events = []
    workflow_run_id = 0

    for week in range(n_weeks):
        week_start = now - timedelta(weeks=(n_weeks - week))

        # weekly_reporting runs ~1x/week, reliably -- the "obvious" pattern
        occurrences = 1 if random.random() > 0.1 else 2
        for _ in range(occurrences):
            workflow_run_id += 1
            _emit_workflow(events, "weekly_reporting", week_start, workflow_run_id)

        # onboarding runs sporadically, 0-2x/week
        for _ in range(random.choice([0, 0, 1, 2])):
            workflow_run_id += 1
            _emit_workflow(events, "onboarding_new_partner", week_start, workflow_run_id)

        # bug triage runs often, 2-5x/week, with more variable duration/failure
        for _ in range(random.randint(2, 5)):
            workflow_run_id += 1
            _emit_workflow(events, "bug_triage", week_start, workflow_run_id, variable=True)

    events.sort(key=lambda x: x["timestamp"])
    if out_path:
        with open(out_path, "w") as f:
            json.dump(events, f, indent=2)
    return events


def _emit_workflow(events, workflow_name, week_start, run_id, variable=False):
    steps = WORKFLOWS[workflow_name]
    t = week_start + timedelta(
        days=random.uniform(0, 5), hours=random.uniform(8, 18)
    )
    for step in steps:
        base_minutes = {
            "file_download": 2, "file_open": 1, "column_cleanup": 15, "rename": 1,
            "export": 3, "upload": 4, "email_intake": 5, "manual_data_entry": 20,
            "cross_check": 12, "approval_wait": 45, "account_create": 6,
            "ticket_read": 4, "reproduce_attempt": 25, "context_switch": 6,
            "log_search": 10, "fix_or_escalate": 18,
        }[step]
        duration = base_minutes * (random.uniform(0.7, 1.6) if variable else random.uniform(0.9, 1.15))
        outcome = "success"
        if variable and random.random() < 0.15:
            outcome = "rework"
        events.append({
            "workflow_run_id": run_id,
            "workflow_name": workflow_name,
            "activity": step,
            "timestamp": t.isoformat(),
            "duration_minutes": round(duration, 1),
            "outcome": outcome,
        })
        t += timedelta(minutes=duration)


if __name__ == "__main__":
    import os
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    info_path = os.path.join(data_dir, "information_stream.json")
    events_path = os.path.join(data_dir, "activity_events.json")
    generate_information_stream(out_path=info_path)
    generate_activity_events(out_path=events_path)
    print(f"Wrote {info_path} and {events_path}")
