"""
Minimal evaluation harness for the ranking engine.

This is deliberately small: a handful of manually-labeled items rather than
a large labeled set, because the point for the hackathon (and for an
interview) is to demonstrate the *methodology* -- Precision@K and a novelty
check -- not to claim a rigorously validated model. Be upfront about that
limitation in the README and in interviews.
"""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ranking_engine import RankingEngine


def precision_at_k(ranked_ids, relevant_ids, k):
    top_k = ranked_ids[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for i in top_k if i in relevant_ids)
    return hits / len(top_k)


def run_eval():
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    items = json.load(open(os.path.join(data_dir, "information_stream.json")))
    user_interests = ["recommendation systems", "large language models", "MLOps"]

    # Manual labels: an item is "relevant" for this eval if its topic is one
    # of the user's stated interests. This is a proxy label, not ground
    # truth from a real user -- documented here so it's not overstated.
    relevant_ids = {it["id"] for it in items if it["topic"] in user_interests}

    engine = RankingEngine(items, user_interests=user_interests)
    ranked = engine.rank(top_k=10)
    ranked_ids = [r["id"] for r in ranked]

    for k in (3, 5, 10):
        p = precision_at_k(ranked_ids, relevant_ids, k)
        print(f"Precision@{k}: {p:.2f}")

    # Diversity check: how many distinct topics appear in the top 5?
    top5_topics = {r["topic"] for r in ranked[:5]}
    print(f"Distinct topics in top 5: {len(top5_topics)} -> {sorted(top5_topics)}")

    # Dedup check: total items vs. deduped representatives
    reps, groups = engine.deduplicate()
    print(f"Items: {len(items)} -> deduplicated to {len(reps)} representatives")


if __name__ == "__main__":
    run_eval()
