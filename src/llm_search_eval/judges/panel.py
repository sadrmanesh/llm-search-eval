"""Panels of several judges whose labels are combined into one grade."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from llm_search_eval.errors import ConfigError, JudgeError
from llm_search_eval.judges.base import Judge, Judgment, Vote, judge_info
from llm_search_eval.models import Product, Query

AGGREGATIONS = ("majority", "mean", "median", "min", "max")


def aggregate_grades(grades: Sequence[int], method: str = "majority") -> int:
    """Combine member grades into one 0 to 3 label.

    * ``majority``: the most common grade. Ties go to the tied grade closest to
      the mean, then to the lower grade, so the result is deterministic and
      conservative.
    * ``mean``: the mean rounded half up.
    * ``median``: the median, rounding half up when the count is even.
    * ``min`` / ``max``: the strictest or most lenient member.
    """
    if not grades:
        raise ValueError("at least one grade is required")
    if method == "majority":
        counts = Counter(grades)
        top = max(counts.values())
        tied = [grade for grade, count in counts.items() if count == top]
        mean = statistics.fmean(grades)
        return min(tied, key=lambda g: (abs(g - mean), g))
    if method == "mean":
        return math.floor(statistics.fmean(grades) + 0.5)
    if method == "median":
        return math.floor(statistics.median(grades) + 0.5)
    if method == "min":
        return min(grades)
    if method == "max":
        return max(grades)
    raise ConfigError(f"unknown aggregation {method!r}; use one of: {', '.join(AGGREGATIONS)}")


class JudgePanel(Judge):
    """Asks every member judge and aggregates their grades.

    Members are queried in parallel for each pair. A member that raises
    :class:`JudgeError` is recorded as a failed vote. The panel fails the pair
    only when fewer than ``min_votes`` members succeed (default: a strict
    majority of the panel).

    Each returned :class:`Judgment` carries the individual votes, which the
    evaluator uses for inter-judge agreement and judge versus gold calibration.
    """

    name = "panel"

    def __init__(
        self,
        judges: Sequence[Judge],
        aggregation: str = "majority",
        min_votes: int | None = None,
        parallel: bool = True,
    ) -> None:
        if len(judges) < 2:
            raise ConfigError("a judge panel needs at least two judges")
        if aggregation not in AGGREGATIONS:
            raise ConfigError(
                f"unknown aggregation {aggregation!r}; use one of: {', '.join(AGGREGATIONS)}"
            )
        self.judges = list(judges)
        self.aggregation = aggregation
        self.min_votes = min_votes if min_votes is not None else len(judges) // 2 + 1
        if not 1 <= self.min_votes <= len(judges):
            raise ConfigError(f"min_votes must be between 1 and {len(judges)}")
        self.parallel = parallel
        self.labels = _unique_labels([j.label for j in self.judges])

    @property
    def fingerprint(self) -> str:
        members = "|".join(j.fingerprint for j in self.judges)
        return f"panel:{self.aggregation}:min={self.min_votes}:[{members}]"

    @property
    def label(self) -> str:
        return f"panel({self.aggregation}: {', '.join(self.labels)})"

    @property
    def info(self) -> dict[str, Any]:
        """Panel provenance with one entry per member under ``members``."""
        out = judge_info(self.label, provider="panel")
        out["members"] = [
            {**member.info, "judge": name}
            for member, name in zip(self.judges, self.labels, strict=True)
        ]
        return out

    def _vote(self, index: int, query: Query, product: Product) -> Vote:
        member = self.judges[index]
        try:
            result = member.judge(query, product)
        except JudgeError as exc:
            return Vote(self.labels[index], None, f"failed: {exc}")
        return Vote(self.labels[index], result.relevance, result.reason, result.usage)

    def judge(self, query: Query, product: Product) -> Judgment:
        indexes = range(len(self.judges))
        if self.parallel:
            with ThreadPoolExecutor(max_workers=len(self.judges)) as pool:
                votes = tuple(pool.map(lambda i: self._vote(i, query, product), indexes))
        else:
            votes = tuple(self._vote(i, query, product) for i in indexes)
        grades = [v.relevance for v in votes if v.relevance is not None]
        if len(grades) < self.min_votes:
            failures = "; ".join(v.reason for v in votes if v.relevance is None)
            raise JudgeError(
                f"panel got {len(grades)} of {self.min_votes} required votes for "
                f"{query.query_id}/{product.product_id}: {failures}"
            )
        grade = aggregate_grades(grades, self.aggregation)
        summary = ", ".join(
            f"{v.judge}={'x' if v.relevance is None else v.relevance}" for v in votes
        )
        return Judgment(grade, f"{self.aggregation} of {summary}", votes=votes)

    def close(self) -> None:
        for member in self.judges:
            member.close()


def _unique_labels(labels: Sequence[str]) -> list[str]:
    seen: Counter[str] = Counter(labels)
    counters: Counter[str] = Counter()
    out = []
    for label in labels:
        if seen[label] > 1:
            counters[label] += 1
            out.append(f"{label}#{counters[label]}")
        else:
            out.append(label)
    return out
