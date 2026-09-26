"""
Signal vs Noise ranking engine.

Deliberately keeps the LLM out of the ranking decision entirely. Everything
here is deterministic and inspectable: TF-IDF similarity for relevance and
dedup, a recency-decay novelty score, and MMR for diversity. The LLM's only
job (done elsewhere, in mcp_server.py) is to turn the *already-ranked*
output into natural language -- it never decides what's important.
"""

from datetime import datetime, timezone
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np


class RankingEngine:
    def __init__(self, items, user_interests=None):
        """
        items: list of dicts from synthetic_data.generate_information_stream
        user_interests: list of topic strings the user cares about (weights relevance)
        """
        self.items = items
        self.user_interests = set(user_interests or [])
        self._vectorizer = TfidfVectorizer(stop_words="english")
        titles = [it["title"] for it in items]
        self._tfidf = self._vectorizer.fit_transform(titles)
        self._sim_matrix = cosine_similarity(self._tfidf)

    # ---- individual scoring components, each independently explainable ----

    def _relevance(self, idx):
        topic = self.items[idx]["topic"]
        return 1.0 if topic in self.user_interests else 0.4

    def _novelty(self, idx, seen_ids):
        """1.0 if nothing similar has been seen; decays toward 0 the more
        similar items already appeared (whether 'seen' by the user or just
        earlier in today's batch)."""
        if not seen_ids:
            return 1.0
        seen_idx = [i for i, it in enumerate(self.items) if it["id"] in seen_ids]
        if not seen_idx:
            return 1.0
        max_sim = max(self._sim_matrix[idx][j] for j in seen_idx)
        return max(0.0, 1.0 - max_sim)

    def _recency(self, idx):
        ts = datetime.fromisoformat(self.items[idx]["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
        return max(0.0, 1.0 - age_hours / (24 * 10))  # decays over ~10 days

    def deduplicate(self, threshold=0.92):
        """Collapse near-duplicates (explicit near_dup_of tag, OR high TF-IDF
        similarity AND matching topic) into groups. Returns (representative_indices, groups).

        Requiring same-topic alongside high similarity matters here: short,
        templated titles ("X update for Y") share enough vocabulary that raw
        TF-IDF similarity alone over-clusters unrelated items. Topic + high
        similarity is a much more reliable duplicate signal. In a real system
        this would use sentence embeddings over full article text instead of
        titles, which wouldn't have this template-vocabulary problem."""
        n = len(self.items)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for i, it in enumerate(self.items):
            if it.get("near_dup_of"):
                for j, other in enumerate(self.items):
                    if other["id"] == it["near_dup_of"]:
                        union(i, j)
        for i in range(n):
            for j in range(i + 1, n):
                if self._sim_matrix[i][j] >= threshold and self.items[i]["topic"] == self.items[j]["topic"]:
                    union(i, j)

        groups = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        representatives = list(groups.keys())
        return representatives, groups

    def rank(self, top_k=5, diversity_lambda=0.7):
        """
        Returns top_k items with a full score breakdown attached, after
        dedup and MMR-based diversity selection.

        diversity_lambda: 1.0 = pure relevance ranking, 0.0 = pure diversity.
        """
        reps, groups = self.deduplicate()
        seen_ids = set()
        candidates = []
        for idx in reps:
            rel = self._relevance(idx)
            nov = self._novelty(idx, seen_ids)
            rec = self._recency(idx)
            impact = self.items[idx]["potential_impact_prior"]
            credibility = self.items[idx]["credibility_prior"]
            # normalized weighted combination -- weights are a starting point,
            # tune against the labeled eval set in evaluation.py
            score = (0.35 * rel + 0.25 * nov + 0.15 * rec + 0.15 * impact + 0.10 * credibility)
            candidates.append({
                "idx": idx,
                "score": score,
                "breakdown": {
                    "relevance": round(rel, 2), "novelty": round(nov, 2),
                    "recency": round(rec, 2), "impact": round(impact, 2),
                    "credibility": round(credibility, 2),
                },
                "group_size": len(groups[idx]),
            })

        selected = []
        remaining = sorted(candidates, key=lambda c: -c["score"])
        while remaining and len(selected) < top_k:
            if not selected:
                best = remaining.pop(0)
            else:
                def mmr_score(c):
                    max_sim_to_selected = max(
                        self._sim_matrix[c["idx"]][s["idx"]] for s in selected
                    )
                    return diversity_lambda * c["score"] - (1 - diversity_lambda) * max_sim_to_selected
                remaining.sort(key=lambda c: -mmr_score(c))
                best = remaining.pop(0)
            selected.append(best)
            seen_ids.add(self.items[best["idx"]]["id"])
            # recompute novelty for the rest now that `best` has been "seen"
            for c in remaining:
                c["breakdown"]["novelty"] = round(self._novelty(c["idx"], seen_ids), 2)
                c["score"] = (0.35 * c["breakdown"]["relevance"] + 0.25 * c["breakdown"]["novelty"]
                              + 0.15 * c["breakdown"]["recency"] + 0.15 * c["breakdown"]["impact"]
                              + 0.10 * c["breakdown"]["credibility"])

        results = []
        for c in selected:
            item = self.items[c["idx"]]
            results.append({
                "id": item["id"],
                "title": item["title"],
                "topic": item["topic"],
                "source": item["source"],
                "score": round(c["score"], 3),
                "why": c["breakdown"],
                "duplicate_count": c["group_size"] - 1,
            })
        return results

    def explain(self, item_id):
        for i, it in enumerate(self.items):
            if it["id"] == item_id:
                rel = self._relevance(i)
                rec = self._recency(i)
                parts = []
                if rel > 0.5:
                    parts.append("it matches a topic you follow")
                if rec > 0.7:
                    parts.append("it's very recent")
                if it["potential_impact_prior"] > 0.7:
                    parts.append("it has high estimated impact")
                if not parts:
                    parts.append("it scored moderately across relevance, novelty, and recency")
                return "This ranked highly because " + ", and ".join(parts) + "."
        return "I don't have that item in the current digest."
