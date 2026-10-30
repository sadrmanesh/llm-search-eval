"""Query-set sampling with optional stratification.

Judging every query of a large query log is slow and costs money. A random
sample keeps the cost down; stratifying by a field such as ``lang`` or
``segment`` keeps every group represented in proportion to its size, so a
small sample still covers rare but important groups.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from llm_search_eval.errors import ConfigError
from llm_search_eval.models import Query

#: Stratum name for queries that do not have the stratification field.
MISSING_STRATUM = "(none)"


def query_stratum(query: Query, key: str) -> str:
    """The group ``query`` belongs to: its language for ``lang``, else an attribute."""
    if key in {"lang", "language"}:
        return query.lang or "und"
    value = query.attributes.get(key)
    return value if value else MISSING_STRATUM


@dataclass(slots=True)
class SampleResult:
    """The sampled queries plus a description of how they were drawn."""

    queries: dict[str, Query]
    population: int
    seed: int
    stratify_by: str | None = None
    #: stratum -> {"population": n, "sampled": m}
    strata: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "population": self.population,
            "sampled": len(self.queries),
            "seed": self.seed,
            "stratify_by": self.stratify_by,
            "strata": self.strata,
        }


def resolve_size(size: int | float | None, population: int) -> int:
    """Turn a count or a fraction into a number of queries.

    Integers (and floats above 1) are counts; floats in ``(0, 1]`` are fractions.
    ``None`` means the whole population.
    """
    if size is None:
        return population
    if isinstance(size, bool) or size <= 0:
        raise ConfigError("sample size must be a positive count or a fraction in (0, 1]")
    if isinstance(size, float) and size <= 1.0:
        return max(1, round(size * population))
    if isinstance(size, float) and not size.is_integer():
        raise ConfigError("sample size above 1 must be a whole number of queries")
    return min(int(size), population)


def allocate(sizes: Mapping[str, int], total: int, minimum: int = 1) -> dict[str, int]:
    """Split ``total`` across strata in proportion to ``sizes`` (largest remainder).

    Every stratum gets at least ``minimum`` items (or all it has) when ``total``
    allows, so small groups are never dropped from the sample.
    """
    population = sum(sizes.values())
    if total >= population:
        return dict(sizes)
    quotas = {name: total * n / population for name, n in sizes.items()}
    alloc = {name: min(n, max(minimum, math.floor(quotas[name]))) for name, n in sizes.items()}
    used = sum(alloc.values())
    # Too many because of the minimum: take back from the most over-allocated strata.
    while used > total:
        candidates = [name for name in alloc if alloc[name] > minimum]
        if not candidates:
            candidates = [name for name in alloc if alloc[name] > 0]
        name = max(candidates, key=lambda n: (alloc[n] - quotas[n], alloc[n], n))
        alloc[name] -= 1
        used -= 1
    # Too few: hand out the rest by largest remainder.
    while used < total:
        candidates = [name for name in alloc if alloc[name] < sizes[name]]
        name = max(candidates, key=lambda n: (quotas[n] - alloc[n], sizes[n], n))
        alloc[name] += 1
        used += 1
    return alloc


def sample_queries(
    queries: Mapping[str, Query],
    size: int | float | None = None,
    *,
    stratify_by: str | None = None,
    seed: int = 13,
    min_per_stratum: int = 1,
) -> SampleResult:
    """Draw a reproducible random sample of ``queries``.

    With ``stratify_by``, the sample is allocated across groups in proportion to
    their size, with at least ``min_per_stratum`` queries from each group. The
    returned queries keep their original order.
    """
    if min_per_stratum < 0:
        raise ConfigError("min_per_stratum must not be negative")
    population = len(queries)
    target = resolve_size(size, population)
    rng = random.Random(seed)
    ids = list(queries)
    if not stratify_by:
        chosen = set(ids) if target >= population else set(rng.sample(ids, target))
        picked = {qid: q for qid, q in queries.items() if qid in chosen}
        return SampleResult(picked, population, seed)

    groups: dict[str, list[str]] = {}
    for qid, query in queries.items():
        groups.setdefault(query_stratum(query, stratify_by), []).append(qid)
    alloc = allocate(
        {name: len(members) for name, members in groups.items()}, target, min_per_stratum
    )
    chosen = set()
    strata: dict[str, dict[str, int]] = {}
    for name in sorted(groups):
        members = groups[name]
        take = alloc[name]
        chosen.update(members if take >= len(members) else rng.sample(members, take))
        strata[name] = {"population": len(members), "sampled": take}
    picked = {qid: q for qid, q in queries.items() if qid in chosen}
    return SampleResult(picked, population, seed, stratify_by, strata)
