"""Agreement statistics for graded relevance labels.

Used to check whether several judges agree with each other (inter-rater
reliability) and with human gold labels (calibration). All functions take plain
integer grades, so they also work for labels that did not come from this package.

Undefined statistics, for example kappa when every label is identical, are
returned as ``None`` instead of an arbitrary number.
"""

from __future__ import annotations

import itertools
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from llm_search_eval.models import MAX_RELEVANCE, MIN_RELEVANCE

DEFAULT_CATEGORIES: tuple[int, ...] = tuple(range(MIN_RELEVANCE, MAX_RELEVANCE + 1))
WEIGHTS = (None, "linear", "quadratic")
LEVELS = ("nominal", "ordinal", "interval")


def _check_pairs(a: Sequence[int], b: Sequence[int]) -> None:
    if len(a) != len(b):
        raise ValueError("label sequences must have equal length")


def percent_agreement(a: Sequence[int], b: Sequence[int]) -> float | None:
    """Share of items where both raters chose the same grade."""
    _check_pairs(a, b)
    if not a:
        return None
    return sum(1 for x, y in zip(a, b, strict=True) if x == y) / len(a)


def within_one(a: Sequence[int], b: Sequence[int]) -> float | None:
    """Share of items where the grades differ by at most one step."""
    _check_pairs(a, b)
    if not a:
        return None
    return sum(1 for x, y in zip(a, b, strict=True) if abs(x - y) <= 1) / len(a)


def confusion_matrix(
    a: Sequence[int], b: Sequence[int], categories: Sequence[int] = DEFAULT_CATEGORIES
) -> list[list[int]]:
    """Counts with rows for ``a`` and columns for ``b``, in ``categories`` order."""
    _check_pairs(a, b)
    index = {c: i for i, c in enumerate(categories)}
    matrix = [[0] * len(categories) for _ in categories]
    for x, y in zip(a, b, strict=True):
        if x not in index or y not in index:
            raise ValueError(f"grade outside categories {list(categories)}: {x}, {y}")
        matrix[index[x]][index[y]] += 1
    return matrix


def _weight(i: int, j: int, size: int, weights: str | None) -> float:
    if weights is None:
        return 0.0 if i == j else 1.0
    span = max(1, size - 1)
    if weights == "linear":
        return abs(i - j) / span
    if weights == "quadratic":
        return ((i - j) / span) ** 2
    raise ValueError(f"unknown weights {weights!r}; use None, 'linear', or 'quadratic'")


def cohen_kappa(
    a: Sequence[int],
    b: Sequence[int],
    weights: str | None = None,
    categories: Sequence[int] = DEFAULT_CATEGORIES,
) -> float | None:
    """Cohen's kappa for two raters, optionally linear or quadratic weighted.

    Quadratic weighting suits ordinal relevance grades because a 0 versus 3
    disagreement is penalized more than 2 versus 3.
    """
    matrix = confusion_matrix(a, b, categories)
    n = len(a)
    if n == 0:
        return None
    size = len(categories)
    rows = [sum(r) for r in matrix]
    cols = [sum(matrix[i][j] for i in range(size)) for j in range(size)]
    observed = expected = 0.0
    for i in range(size):
        for j in range(size):
            w = _weight(i, j, size, weights)
            observed += w * matrix[i][j] / n
            expected += w * rows[i] * cols[j] / (n * n)
    if expected == 0:
        return None
    return 1.0 - observed / expected


def fleiss_kappa(
    items: Sequence[Sequence[int]], categories: Sequence[int] = DEFAULT_CATEGORIES
) -> float | None:
    """Fleiss' kappa for any fixed number of raters per item.

    ``items`` holds one sequence of grades per rated item. Every item needs the
    same number of ratings (at least two); use :func:`krippendorff_alpha` when
    some ratings are missing.
    """
    if not items:
        return None
    raters = len(items[0])
    if raters < 2 or any(len(item) != raters for item in items):
        raise ValueError("every item needs the same number of ratings, at least two")
    index = {c: i for i, c in enumerate(categories)}
    totals = [0] * len(categories)
    agreement = 0.0
    for item in items:
        counts = [0] * len(categories)
        for grade in item:
            if grade not in index:
                raise ValueError(f"grade {grade} outside categories {list(categories)}")
            counts[index[grade]] += 1
        for i, c in enumerate(counts):
            totals[i] += c
        agreement += (sum(c * c for c in counts) - raters) / (raters * (raters - 1))
    p_bar = agreement / len(items)
    shares = [t / (len(items) * raters) for t in totals]
    p_e = sum(p * p for p in shares)
    if p_e >= 1.0:
        return None
    return (p_bar - p_e) / (1.0 - p_e)


def krippendorff_alpha(
    units: Sequence[Sequence[int | None]], level: str = "ordinal"
) -> float | None:
    """Krippendorff's alpha with missing ratings allowed.

    ``units`` holds one sequence per item with each rater's grade or ``None``.
    Items with fewer than two grades are ignored. ``level`` is ``nominal``,
    ``ordinal``, or ``interval``.
    """
    if level not in LEVELS:
        raise ValueError(f"unknown level {level!r}; use one of: {', '.join(LEVELS)}")
    coincidence: Counter[tuple[int, int]] = Counter()
    pairable = 0
    for unit in units:
        values = [v for v in unit if v is not None]
        m = len(values)
        if m < 2:
            continue
        pairable += m
        for i, j in itertools.permutations(range(m), 2):
            coincidence[(values[i], values[j])] += 1.0 / (m - 1)  # type: ignore[assignment]
    if pairable < 2:
        return None
    values_sorted = sorted({c for pair in coincidence for c in pair})
    marginals = {c: sum(coincidence[(c, k)] for k in values_sorted) for c in values_sorted}
    n = sum(marginals.values())

    def delta(c: int, k: int) -> float:
        if level == "nominal":
            return 0.0 if c == k else 1.0
        if level == "interval":
            return float((c - k) ** 2)
        low, high = min(c, k), max(c, k)
        between = sum(marginals[g] for g in values_sorted if low <= g <= high)
        return (between - (marginals[c] + marginals[k]) / 2) ** 2

    observed = sum(coincidence[(c, k)] * delta(c, k) for c in values_sorted for k in values_sorted)
    expected = sum(
        marginals[c] * marginals[k] * delta(c, k) for c in values_sorted for k in values_sorted
    )
    if expected == 0:
        return None
    return 1.0 - (n - 1) * observed / expected


def pairwise_agreement(
    ratings: Mapping[str, Sequence[int | None]],
) -> list[dict[str, Any]]:
    """Cohen's kappa (plain and quadratic) for every pair of raters.

    ``ratings`` maps rater name to grades aligned by item; ``None`` marks a
    missing grade and excludes the item for that pair only.
    """
    out = []
    for first, second in itertools.combinations(ratings, 2):
        pairs = [
            (x, y)
            for x, y in zip(ratings[first], ratings[second], strict=True)
            if x is not None and y is not None
        ]
        a = [x for x, _ in pairs]
        b = [y for _, y in pairs]
        out.append(
            {
                "a": first,
                "b": second,
                "n": len(pairs),
                "percent_agreement": percent_agreement(a, b),
                "cohen_kappa": cohen_kappa(a, b),
                "weighted_kappa": cohen_kappa(a, b, weights="quadratic"),
            }
        )
    return out


def inter_judge_agreement(ratings: Mapping[str, Sequence[int | None]]) -> dict[str, Any]:
    """Summary of agreement between several raters over the same items."""
    names = list(ratings)
    if len(names) < 2:
        raise ValueError("agreement needs at least two raters")
    length = len(ratings[names[0]])
    if any(len(ratings[name]) != length for name in names):
        raise ValueError("every rater needs one entry per item")
    units = [[ratings[name][i] for name in names] for i in range(length)]
    complete = [[v for v in unit if v is not None] for unit in units]
    complete = [unit for unit in complete if len(unit) == len(names)]
    unanimous = sum(1 for unit in complete if len(set(unit)) == 1)
    return {
        "raters": names,
        "items": length,
        "complete_items": len(complete),
        "unanimous": None if not complete else unanimous / len(complete),
        "fleiss_kappa": fleiss_kappa(complete) if complete else None,
        "krippendorff_alpha": {
            "nominal": krippendorff_alpha(units, "nominal"),
            "ordinal": krippendorff_alpha(units, "ordinal"),
            "interval": krippendorff_alpha(units, "interval"),
        },
        "pairwise": pairwise_agreement(ratings),
    }


def gold_agreement(
    predicted: Sequence[int], gold: Sequence[int], threshold: int = 2
) -> dict[str, Any]:
    """Compare one rater with gold labels: exact, within one, binary, and kappa."""
    _check_pairs(predicted, gold)
    binary_p = [int(x >= threshold) for x in predicted]
    binary_g = [int(x >= threshold) for x in gold]
    n = len(gold)
    return {
        "n": n,
        "exact": percent_agreement(predicted, gold),
        "within_one": within_one(predicted, gold),
        "binary_agreement": percent_agreement(binary_p, binary_g),
        "cohen_kappa": cohen_kappa(predicted, gold),
        "weighted_kappa": cohen_kappa(predicted, gold, weights="quadratic"),
        "binary_kappa": cohen_kappa(binary_p, binary_g, categories=(0, 1)),
        "mean_bias": (
            None if not n else sum(p - g for p, g in zip(predicted, gold, strict=True)) / n
        ),
        "confusion": {
            "rows": "gold",
            "columns": "judge",
            "categories": list(DEFAULT_CATEGORIES),
            "matrix": confusion_matrix(gold, predicted),
        },
    }
