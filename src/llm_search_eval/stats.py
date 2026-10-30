"""Resampling statistics: bootstrap confidence intervals and simple tests.

Everything here uses only the standard library and a seeded
:class:`random.Random`, so results are reproducible across runs and machines.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_RESAMPLES = 1000
DEFAULT_CONFIDENCE = 0.95


@dataclass(frozen=True, slots=True)
class Interval:
    """A confidence interval around ``estimate``."""

    estimate: float
    low: float
    high: float
    confidence: float

    def contains(self, value: float) -> bool:
        return self.low - 1e-12 <= value <= self.high + 1e-12

    def to_dict(self) -> dict[str, float]:
        return {"low": self.low, "high": self.high, "confidence": self.confidence}


def _check(confidence: float, resamples: int) -> None:
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if resamples < 1:
        raise ValueError("resamples must be a positive integer")


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear interpolation between closest ranks (same as numpy's default)."""
    if not sorted_values:
        raise ValueError("no values")
    pos = q * (len(sorted_values) - 1)
    lower = math.floor(pos)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = pos - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def bootstrap_means(values: Sequence[float], resamples: int, seed: int) -> list[float]:
    """Means of ``resamples`` samples drawn with replacement from ``values``."""
    n = len(values)
    rng = random.Random(seed)
    data = list(values)
    out = []
    for _ in range(resamples):
        total = 0.0
        for _ in range(n):
            total += data[int(rng.random() * n)]
        out.append(total / n)
    return out


def bootstrap_ci(
    values: Sequence[float],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 13,
) -> Interval | None:
    """Percentile bootstrap interval for the mean of ``values``.

    Returns ``None`` for an empty sample. One value gives a zero-width interval.
    """
    _check(confidence, resamples)
    if not values:
        return None
    mean = statistics.fmean(values)
    if len(values) == 1 or max(values) == min(values):
        return Interval(mean, mean, mean, confidence)
    means = sorted(bootstrap_means(values, resamples, seed))
    alpha = (1.0 - confidence) / 2
    return Interval(mean, _quantile(means, alpha), _quantile(means, 1.0 - alpha), confidence)


def paired_bootstrap_ci(
    a: Sequence[float],
    b: Sequence[float],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    resamples: int = DEFAULT_RESAMPLES,
    seed: int = 13,
) -> Interval | None:
    """Bootstrap interval for the mean paired difference ``a - b``.

    Queries are resampled as units, so both systems see the same queries in
    each resample. This is the interval that matches the paired randomization
    test used for p-values.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    return bootstrap_ci(
        [x - y for x, y in zip(a, b, strict=True)],
        confidence=confidence,
        resamples=resamples,
        seed=seed,
    )


def wilson_interval(
    successes: int, trials: int, confidence: float = DEFAULT_CONFIDENCE
) -> Interval | None:
    """Wilson score interval for a proportion; ``None`` when there are no trials."""
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if trials <= 0:
        return None
    if not 0 <= successes <= trials:
        raise ValueError("successes must be between 0 and trials")
    z = statistics.NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    return Interval(p, max(0.0, centre - half), min(1.0, centre + half), confidence)


def sign_test(wins: int, losses: int) -> float | None:
    """Exact two-sided binomial sign test; ties are ignored. ``None`` without data."""
    if wins < 0 or losses < 0:
        raise ValueError("counts must not be negative")
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)
