"""Classic ranking metrics over graded relevance labels.

All functions take a ranked list of product ids and a mapping of known labels
for one query. Products without a label count as non-relevant. Metrics that are
undefined for a query (no relevant product exists among the known labels) return
``None`` so callers can exclude the query instead of silently scoring it as zero.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from llm_search_eval.errors import ConfigError

Labels = Mapping[str, int]


def _gain(rel: int, scheme: str) -> float:
    if rel <= 0:
        return 0.0
    if scheme == "exponential":
        return float(2**rel - 1)
    if scheme == "linear":
        return float(rel)
    raise ConfigError(f"unknown gain scheme {scheme!r} (use 'exponential' or 'linear')")


def dcg(relevances: Sequence[int], gain: str = "exponential") -> float:
    """Discounted cumulative gain with the standard ``log2(rank + 1)`` discount."""
    return sum(_gain(rel, gain) / math.log2(i + 2) for i, rel in enumerate(relevances))


def ndcg_at_k(
    ranking: Sequence[str], labels: Labels, k: int, gain: str = "exponential"
) -> float | None:
    """Normalized DCG at ``k``. The ideal ranking is built from all known labels."""
    ideal = sorted((r for r in labels.values() if r > 0), reverse=True)[:k]
    idcg = dcg(ideal, gain)
    if idcg == 0:
        return None
    return dcg([labels.get(pid, 0) for pid in ranking[:k]], gain) / idcg


def _num_relevant(labels: Labels, threshold: int) -> int:
    return sum(1 for r in labels.values() if r >= threshold)


def precision_at_k(
    ranking: Sequence[str], labels: Labels, k: int, threshold: int = 2
) -> float | None:
    """Fraction of the top ``k`` slots holding a relevant product (denominator is ``k``)."""
    if _num_relevant(labels, threshold) == 0:
        return None
    hits = sum(1 for pid in ranking[:k] if labels.get(pid, 0) >= threshold)
    return hits / k


def recall_at_k(ranking: Sequence[str], labels: Labels, k: int, threshold: int = 2) -> float | None:
    """Fraction of all known relevant products retrieved in the top ``k``."""
    total = _num_relevant(labels, threshold)
    if total == 0:
        return None
    hits = sum(1 for pid in ranking[:k] if labels.get(pid, 0) >= threshold)
    return hits / total


def reciprocal_rank(ranking: Sequence[str], labels: Labels, threshold: int = 2) -> float | None:
    """``1 / rank`` of the first relevant product, or 0 when none is retrieved."""
    if _num_relevant(labels, threshold) == 0:
        return None
    for i, pid in enumerate(ranking, start=1):
        if labels.get(pid, 0) >= threshold:
            return 1.0 / i
    return 0.0


def average_precision(ranking: Sequence[str], labels: Labels, threshold: int = 2) -> float | None:
    """Mean of precision values at each relevant rank, divided by all known relevant."""
    total = _num_relevant(labels, threshold)
    if total == 0:
        return None
    hits = 0
    score = 0.0
    for i, pid in enumerate(ranking, start=1):
        if labels.get(pid, 0) >= threshold:
            hits += 1
            score += hits / i
    return score / total


_SPEC = re.compile(r"^(?P<name>[a-z_]+)(?:@(?P<k>\d+))?$")
_ALIASES = {
    "ndcg": "ndcg",
    "precision": "precision",
    "p": "precision",
    "recall": "recall",
    "r": "recall",
    "mrr": "mrr",
    "rr": "mrr",
    "map": "map",
    "ap": "map",
}
_NEEDS_K = {"ndcg", "precision", "recall"}


@dataclass(frozen=True, slots=True)
class Metric:
    """A parsed metric specification such as ``ndcg@10`` or ``mrr``."""

    name: str
    k: int | None = None

    @property
    def label(self) -> str:
        return f"{self.name}@{self.k}" if self.k else self.name

    def compute(
        self,
        ranking: Sequence[str],
        labels: Labels,
        *,
        threshold: int = 2,
        gain: str = "exponential",
    ) -> float | None:
        if self.name == "ndcg":
            assert self.k is not None
            return ndcg_at_k(ranking, labels, self.k, gain)
        if self.name == "precision":
            assert self.k is not None
            return precision_at_k(ranking, labels, self.k, threshold)
        if self.name == "recall":
            assert self.k is not None
            return recall_at_k(ranking, labels, self.k, threshold)
        ranked = ranking[: self.k] if self.k else ranking
        if self.name == "mrr":
            return reciprocal_rank(ranked, labels, threshold)
        return average_precision(ranked, labels, threshold)

    @classmethod
    def parse(cls, spec: str) -> Metric:
        match = _SPEC.match(spec.strip().lower())
        if not match or match["name"] not in _ALIASES:
            raise ConfigError(
                f"unknown metric {spec!r}; expected ndcg@k, precision@k, recall@k, mrr, or map"
            )
        name = _ALIASES[match["name"]]
        k = int(match["k"]) if match["k"] else None
        if name in _NEEDS_K and not k:
            raise ConfigError(f"metric {name!r} needs a cutoff, for example {name}@10")
        if k is not None and k < 1:
            raise ConfigError(f"metric cutoff must be positive in {spec!r}")
        return cls(name=name, k=k)


DEFAULT_METRICS = ("ndcg@5", "ndcg@10", "precision@5", "recall@10", "mrr", "map")


def parse_metrics(specs: Sequence[str] | str) -> list[Metric]:
    if isinstance(specs, str):
        specs = [s for s in specs.split(",") if s.strip()]
    metrics: list[Metric] = []
    for spec in specs:
        metric = Metric.parse(spec)
        if metric not in metrics:
            metrics.append(metric)
    if not metrics:
        raise ConfigError("at least one metric is required")
    return metrics
