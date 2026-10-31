"""Evaluation pipeline: collect labels, score each system, and compare systems."""

from __future__ import annotations

import datetime as _dt
import logging
import random
import statistics
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from llm_search_eval.agreement import gold_agreement, inter_judge_agreement
from llm_search_eval.errors import ConfigError, JudgeError
from llm_search_eval.judges.base import Judge, Vote
from llm_search_eval.judges.cache import JudgmentCache, cache_key
from llm_search_eval.judges.panel import JudgePanel
from llm_search_eval.metrics import DEFAULT_METRICS, Metric, parse_metrics
from llm_search_eval.models import Dataset, Qrels, Query, Run
from llm_search_eval.sampling import SampleResult, query_stratum, sample_queries
from llm_search_eval.stats import bootstrap_ci, paired_bootstrap_ci
from llm_search_eval.usage import BudgetExceededError, CostTracker

if TYPE_CHECKING:
    from llm_search_eval.judges.pairwise import PairwiseJudge
    from llm_search_eval.pairwise import PairwiseCache

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int], None]


@dataclass(slots=True)
class EvaluationConfig:
    """Settings that control labelling, scoring, and system comparison."""

    metrics: Sequence[str] = DEFAULT_METRICS
    #: Rank cutoff applied to every run. Defaults to the largest metric cutoff.
    depth: int | None = None
    #: Minimum grade treated as relevant by binary metrics (precision, recall, MRR, MAP).
    threshold: int = 2
    gain: str = "exponential"
    baseline: str | None = None
    primary_metric: str | None = None
    permutations: int = 10_000
    seed: int = 13
    #: Bootstrap resamples for confidence intervals; 0 turns intervals off.
    bootstrap: int = 1000
    #: Confidence level of the bootstrap intervals.
    confidence: float = 0.95
    concurrency: int = 4
    title: str = "Search evaluation report"
    #: Also judge pairs that have gold labels, to measure judge versus gold agreement.
    #: Gold labels still decide the score; the extra judgments are only for calibration.
    calibrate: bool = False
    #: Judge at most this many gold pairs (random sample with ``seed``) when calibrating.
    calibration_sample: int | None = None
    #: Store rankings, labels, and product titles in the report for the HTML dashboard.
    include_details: bool = True
    #: Evaluate a random sample of the queries: a count, or a fraction in (0, 1].
    sample_size: int | float | None = None
    #: Query field (``lang`` or an extra column) for stratified sampling and a
    #: per-group breakdown of the primary metric.
    stratify_by: str | None = None
    #: Smallest number of queries drawn from each group when sampling.
    min_per_stratum: int = 1
    #: Results per system shown to the pairwise judge.
    pairwise_k: int = 5
    #: Judge each query in both orders to cancel position bias.
    pairwise_swap: bool = True
    #: ``(system_a, system_b)`` pairs to compare; default: each system vs the baseline.
    pairwise_pairs: Sequence[tuple[str, str]] | None = None

    def parsed_metrics(self) -> list[Metric]:
        return parse_metrics(self.metrics)

    def resolved_depth(self) -> int:
        if self.depth is not None:
            if self.depth < 1:
                raise ConfigError("depth must be a positive integer")
            return self.depth
        cutoffs = [m.k for m in self.parsed_metrics() if m.k]
        return max(cutoffs, default=10)

    def resolved_primary(self) -> Metric:
        metrics = self.parsed_metrics()
        if self.primary_metric:
            primary = Metric.parse(self.primary_metric)
            if primary not in metrics:
                raise ConfigError(f"primary metric {primary.label!r} is not in the metric list")
            return primary
        return next((m for m in reversed(metrics) if m.name == "ndcg"), metrics[0])

    def validate(self) -> None:
        self.parsed_metrics()
        self.resolved_depth()
        self.resolved_primary()
        if not 1 <= self.threshold <= 3:
            raise ConfigError("threshold must be between 1 and 3")
        if self.gain not in {"exponential", "linear"}:
            raise ConfigError("gain must be 'exponential' or 'linear'")
        if self.permutations < 0:
            raise ConfigError("permutations must be zero or positive")
        if self.calibration_sample is not None and self.calibration_sample < 1:
            raise ConfigError("calibration_sample must be a positive integer")
        if self.min_per_stratum < 0:
            raise ConfigError("min_per_stratum must not be negative")
        if self.pairwise_k < 1:
            raise ConfigError("pairwise_k must be a positive integer")
        if self.bootstrap < 0:
            raise ConfigError("bootstrap must be zero or positive")
        if not 0.0 < self.confidence < 1.0:
            raise ConfigError("confidence must be between 0 and 1, for example 0.95")


@dataclass(frozen=True, slots=True)
class JudgedPair:
    query_id: str
    product_id: str
    relevance: int
    reason: str
    source: str  # "judge" or "cache"
    votes: tuple[Vote, ...] = ()
    #: Gold label of the pair; set only for calibration judgments.
    gold: int | None = None


@dataclass(slots=True)
class LabelStats:
    gold_used: int = 0
    judged: int = 0
    cached: int = 0
    failed: int = 0
    unknown_products: int = 0
    unlabeled: int = 0
    skipped_budget: int = 0
    calibration: int = 0
    judge: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "judge": self.judge,
            "gold_used": self.gold_used,
            "judged": self.judged,
            "cached": self.cached,
            "failed": self.failed,
            "unknown_products": self.unknown_products,
            "unlabeled": self.unlabeled,
            "skipped_budget": self.skipped_budget,
            "calibration": self.calibration,
            "errors": self.errors[:20],
        }


@dataclass(slots=True)
class EvaluationReport:
    """Everything produced by one evaluation; serializable with :meth:`to_dict`."""

    data: dict[str, Any]
    judgments: list[JudgedPair]

    def to_dict(self) -> dict[str, Any]:
        return self.data

    def system(self, name: str) -> dict[str, Any]:
        for system in self.data["systems"]:
            if system["name"] == name:
                return system
        raise KeyError(name)

    def mean(self, system: str, metric: str) -> float | None:
        return self.system(system)["metrics"][metric]["mean"]


def _calibration_pairs(dataset: Dataset, sample: int | None, seed: int) -> list[tuple[str, str]]:
    pairs = [
        (qid, pid)
        for qid, rels in sorted(dataset.qrels.items())
        if qid in dataset.queries
        for pid in sorted(rels)
        if pid in dataset.products
    ]
    if sample is not None and sample < len(pairs):
        pairs = sorted(random.Random(seed).sample(pairs, sample))
    return pairs


def pending_pairs(dataset: Dataset, runs: Sequence[Run], depth: int) -> list[tuple[str, str]]:
    """``(query_id, product_id)`` pairs in the runs' top ``depth`` that have no gold label.

    Each pair appears once, in run order. Pairs whose product is missing from
    the catalog are included; callers decide what to do with them.
    """
    pending: dict[tuple[str, str], None] = {}  # ordered set
    for run in runs:
        for qid in dataset.queries:
            for pid in run.ranking(qid, depth):
                if (qid, pid) not in pending and dataset.gold_label(qid, pid) is None:
                    pending[(qid, pid)] = None
    return list(pending)


def calibration_pairs(dataset: Dataset, sample: int | None, seed: int) -> list[tuple[str, str]]:
    """Gold-labeled pairs a calibrating judge grades as well."""
    return _calibration_pairs(dataset, sample, seed)


def build_labels(
    dataset: Dataset,
    runs: Sequence[Run],
    depth: int,
    judge: Judge | None = None,
    cache: JudgmentCache | None = None,
    concurrency: int = 4,
    progress: ProgressFn | None = None,
    *,
    tracker: CostTracker | None = None,
    calibrate: bool = False,
    calibration_sample: int | None = None,
    seed: int = 13,
) -> tuple[Qrels, LabelStats, list[JudgedPair]]:
    """Merge gold labels with judge labels for every pair in the runs' top ``depth``.

    With ``calibrate``, gold-labeled pairs are judged as well so the report can
    measure judge versus gold agreement. Their gold labels are kept for scoring.
    """
    stats = LabelStats(judge=judge.label if judge else None)
    labels: Qrels = {qid: dict(rels) for qid, rels in dataset.qrels.items()}
    pending = pending_pairs(dataset, runs, depth)
    stats.gold_used = sum(
        1
        for qid in dataset.queries
        for pid in {p for run in runs for p in run.ranking(qid, depth)}
        if dataset.gold_label(qid, pid) is not None
    )

    todo: list[tuple[str, str]] = []
    for qid, pid in pending:
        if pid not in dataset.products:
            stats.unknown_products += 1
            stats.unlabeled += 1
        elif judge is None:
            stats.unlabeled += 1
        else:
            todo.append((qid, pid))
    if judge is not None and calibrate:
        calibration = _calibration_pairs(dataset, calibration_sample, seed)
        stats.calibration = len(calibration)
        todo += calibration

    judged: list[JudgedPair] = []
    if judge is None or not todo:
        return labels, stats, judged

    if cache is None:
        cache = JudgmentCache()
    if tracker is None:
        tracker = CostTracker()
    provenance = judge.info

    def grade(pair: tuple[str, str]) -> JudgedPair:
        qid, pid = pair
        query, product = dataset.queries[qid], dataset.products[pid]
        gold = dataset.gold_label(qid, pid)
        key = cache_key(judge.fingerprint, query, product)
        hit = cache.get(key)
        if hit is not None:
            tracker.record_cache_hit()
            return JudgedPair(qid, pid, hit.relevance, hit.reason, "cache", hit.votes, gold)
        tracker.reserve()
        result = judge.judge(query, product)
        tracker.record(result.usages())
        cache.put(key, result, query_id=qid, product_id=pid, judge=provenance)
        return JudgedPair(qid, pid, result.relevance, result.reason, "judge", result.votes, gold)

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(grade, pair): pair for pair in todo}
        for future in as_completed(futures):
            done += 1
            qid, pid = futures[future]
            is_gold = dataset.gold_label(qid, pid) is not None
            try:
                pair = future.result()
            except BudgetExceededError:
                stats.skipped_budget += 1
                if not is_gold:
                    stats.unlabeled += 1
            except JudgeError as exc:
                stats.failed += 1
                if not is_gold:
                    stats.unlabeled += 1
                stats.errors.append(str(exc))
                log.warning("%s", exc)
            else:
                judged.append(pair)
                if not is_gold:
                    labels.setdefault(qid, {})[pid] = pair.relevance
                if pair.source == "cache":
                    stats.cached += 1
                else:
                    stats.judged += 1
            if progress:
                progress(done, len(todo))
    if stats.skipped_budget:
        log.warning(
            "budget reached: %d pair(s) were not judged (%s)",
            stats.skipped_budget,
            tracker.exhausted_reason,
        )
    judged.sort(key=lambda p: (p.query_id, p.product_id))
    return labels, stats, judged


def _provenance(info: dict[str, Any]) -> dict[str, Any]:
    return {k: info.get(k) for k in ("provider", "model", "prompt_version", "prompt_hash")}


def judge_analysis(
    judged: Sequence[JudgedPair], judge: Judge | None, threshold: int
) -> dict[str, Any] | None:
    """Label distribution, inter-judge agreement, and judge versus gold agreement."""
    if judge is None:
        return None
    members = list(judge.labels) if isinstance(judge, JudgePanel) else []
    distribution = Counter(p.relevance for p in judged)
    out: dict[str, Any] = {
        "judge": judge.label,
        "fingerprint": judge.fingerprint,
        **_provenance(judge.info),
        "panel": None,
        "pairs": len(judged),
        "label_distribution": {str(g): distribution.get(g, 0) for g in range(4)},
        "agreement": None,
        "gold_agreement": None,
    }
    if members:
        assert isinstance(judge, JudgePanel)
        out["panel"] = {
            "members": members,
            "aggregation": judge.aggregation,
            "min_votes": judge.min_votes,
            "judges": [{"judge": m["judge"], **_provenance(m)} for m in judge.info["members"]],
        }
        with_votes = [p for p in judged if p.votes]
        ratings: dict[str, list[int | None]] = {name: [] for name in members}
        for pair in with_votes:
            by_name = {v.judge: v.relevance for v in pair.votes}
            for name in members:
                ratings[name].append(by_name.get(name))
        if with_votes:
            out["agreement"] = inter_judge_agreement(ratings)
    calibration = [p for p in judged if p.gold is not None]
    if calibration:
        gold = [p.gold for p in calibration if p.gold is not None]
        result: dict[str, Any] = {
            "threshold": threshold,
            "judge": gold_agreement([p.relevance for p in calibration], gold, threshold),
            "members": {},
        }
        for name in members:
            pairs = [
                (v.relevance, p.gold)
                for p in calibration
                for v in p.votes
                if v.judge == name and v.relevance is not None and p.gold is not None
            ]
            if pairs:
                result["members"][name] = gold_agreement(
                    [a for a, _ in pairs], [b for _, b in pairs], threshold
                )
        out["gold_agreement"] = result
    return out


def build_details(
    dataset: Dataset, runs: Sequence[Run], depth: int, judged: Sequence[JudgedPair]
) -> dict[str, Any]:
    """Rankings, labels, and product summaries for per-query drilldown views."""
    judged_by_pair = {(p.query_id, p.product_id): p for p in judged if p.gold is None}
    rankings = {run.name: {qid: run.ranking(qid, depth) for qid in dataset.queries} for run in runs}
    shown = {pid for system in rankings.values() for ranked in system.values() for pid in ranked}
    labels: dict[str, dict[str, dict[str, Any]]] = {}
    for qid in dataset.queries:
        pids = {pid for system in rankings.values() for pid in system[qid]}
        pids |= set(dataset.qrels.get(qid, {}))
        for pid in sorted(pids):
            gold = dataset.gold_label(qid, pid)
            entry: dict[str, Any] | None = None
            if gold is not None:
                entry = {"grade": gold, "source": "gold"}
            elif (qid, pid) in judged_by_pair:
                pair = judged_by_pair[(qid, pid)]
                entry = {"grade": pair.relevance, "source": pair.source, "reason": pair.reason}
                if pair.votes:
                    entry["votes"] = {v.judge: v.relevance for v in pair.votes}
            if entry is not None:
                labels.setdefault(qid, {})[pid] = entry
    products = {}
    for pid in sorted(shown):
        product = dataset.products.get(pid)
        if product is None:
            continue
        products[pid] = {
            "title": product.title,
            "brand": product.brand,
            "category": product.category,
            "price": product.price,
        }
    return {
        "queries": {
            qid: {"text": q.text, "lang": q.lang or "und"} for qid, q in dataset.queries.items()
        },
        "rankings": rankings,
        "labels": labels,
        "products": products,
    }


def score_run(
    run: Run,
    dataset: Dataset,
    labels: Qrels,
    metrics: Sequence[Metric],
    depth: int,
    threshold: int,
    gain: str,
    *,
    bootstrap: int = 0,
    confidence: float = 0.95,
    seed: int = 13,
) -> dict[str, Any]:
    per_query: dict[str, dict[str, float | None]] = {}
    slots = labeled = unknown = 0
    for qid in dataset.queries:
        ranking = run.ranking(qid, depth)
        qlabels = labels.get(qid, {})
        per_query[qid] = {
            m.label: m.compute(ranking, qlabels, threshold=threshold, gain=gain) for m in metrics
        }
        slots += len(ranking)
        labeled += sum(1 for pid in ranking if pid in qlabels)
        unknown += sum(1 for pid in ranking if pid not in dataset.products)
    aggregate = {}
    for m in metrics:
        values = [x for v in per_query.values() if (x := v[m.label]) is not None]
        entry: dict[str, Any] = {
            "mean": statistics.fmean(values) if values else None,
            "n": len(values),
        }
        if bootstrap:
            ci = bootstrap_ci(values, confidence=confidence, resamples=bootstrap, seed=seed)
            entry["ci_low"] = None if ci is None else ci.low
            entry["ci_high"] = None if ci is None else ci.high
        aggregate[m.label] = entry
    return {
        "name": run.name,
        "metrics": aggregate,
        "coverage": {
            "queries_answered": sum(1 for q in dataset.queries if run.rankings.get(q)),
            "queries_total": len(dataset.queries),
            "results_at_depth": slots,
            "labeled_at_depth": (labeled / slots) if slots else None,
            "unknown_products": unknown,
        },
        "per_query": per_query,
    }


def paired_randomization_test(
    a: Sequence[float], b: Sequence[float], permutations: int = 10_000, seed: int = 13
) -> float | None:
    """Two-sided paired sign-flip randomization test on the mean difference.

    Returns ``None`` when there are no paired observations or ``permutations`` is 0.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have equal length")
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    if not diffs or permutations <= 0:
        return None
    observed = abs(sum(diffs))
    if observed == 0:
        return 1.0
    rng = random.Random(seed)
    extreme = 0
    for _ in range(permutations):
        total = sum(d if rng.random() < 0.5 else -d for d in diffs)
        if abs(total) >= observed - 1e-12:
            extreme += 1
    return (extreme + 1) / (permutations + 1)


def _paired(system: dict[str, Any], base: dict[str, Any], metric: str) -> list[tuple[float, float]]:
    """Per-query values of ``metric`` for queries where both systems have one."""
    return [
        (system["per_query"][q][metric], base["per_query"][q][metric])
        for q in base["per_query"]
        if system["per_query"].get(q, {}).get(metric) is not None
        and base["per_query"][q][metric] is not None
    ]


def compare_systems(
    systems: Sequence[dict[str, Any]],
    metrics: Sequence[Metric],
    baseline: str,
    primary: Metric,
    permutations: int,
    seed: int,
    *,
    bootstrap: int = 0,
    confidence: float = 0.95,
) -> dict[str, Any]:
    base = next(s for s in systems if s["name"] == baseline)
    deltas = []
    tests = []
    for system in systems:
        if system["name"] == baseline:
            continue
        for m in metrics:
            b = base["metrics"][m.label]["mean"]
            v = system["metrics"][m.label]["mean"]
            delta = None if b is None or v is None else v - b
            relative = None if delta is None or not b else delta / b
            row: dict[str, Any] = {
                "system": system["name"],
                "metric": m.label,
                "baseline": b,
                "value": v,
                "delta": delta,
                "relative": relative,
            }
            if bootstrap:
                paired = _paired(system, base, m.label)
                ci = paired_bootstrap_ci(
                    [x for x, _ in paired],
                    [y for _, y in paired],
                    confidence=confidence,
                    resamples=bootstrap,
                    seed=seed,
                )
                row["ci_low"] = None if ci is None else ci.low
                row["ci_high"] = None if ci is None else ci.high
            deltas.append(row)
        pairs = _paired(system, base, primary.label)
        wins = sum(1 for x, y in pairs if x > y + 1e-9)
        losses = sum(1 for x, y in pairs if y > x + 1e-9)
        tests.append(
            {
                "system": system["name"],
                "metric": primary.label,
                "n": len(pairs),
                "wins": wins,
                "ties": len(pairs) - wins - losses,
                "losses": losses,
                "p_value": paired_randomization_test(
                    [x for x, _ in pairs], [y for _, y in pairs], permutations, seed
                ),
            }
        )
    ranking = sorted(
        (s["name"] for s in systems),
        key=lambda n: (
            -(next(s for s in systems if s["name"] == n)["metrics"][primary.label]["mean"] or 0.0)
        ),
    )
    return {
        "baseline": baseline,
        "primary_metric": primary.label,
        "ranking": ranking,
        "deltas": deltas,
        "significance": tests,
    }


def _by_group(
    dataset: Dataset,
    systems: Sequence[dict[str, Any]],
    primary: Metric,
    group: Callable[[Query], str],
) -> dict[str, dict[str, dict[str, Any]]]:
    keys = sorted({group(q) for q in dataset.queries.values()})
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for system in systems:
        out[system["name"]] = {}
        for key in keys:
            values: list[float] = [
                system["per_query"][qid][primary.label]
                for qid, q in dataset.queries.items()
                if group(q) == key and system["per_query"][qid][primary.label] is not None
            ]
            out[system["name"]][key] = {
                "mean": statistics.fmean(values) if values else None,
                "n": len(values),
            }
    return out


def _by_language(
    dataset: Dataset, systems: Sequence[dict[str, Any]], primary: Metric
) -> dict[str, dict[str, dict[str, Any]]]:
    return _by_group(dataset, systems, primary, lambda q: q.lang or "und")


def apply_sampling(
    dataset: Dataset, config: EvaluationConfig
) -> tuple[Dataset, SampleResult | None]:
    """Restrict ``dataset`` to the configured query sample (no-op without one)."""
    if config.sample_size is None:
        return dataset, None
    result = sample_queries(
        dataset.queries,
        config.sample_size,
        stratify_by=config.stratify_by,
        seed=config.seed,
        min_per_stratum=config.min_per_stratum,
    )
    qrels = {qid: rels for qid, rels in dataset.qrels.items() if qid in result.queries}
    return Dataset(result.queries, dataset.products, qrels), result


def evaluate(
    dataset: Dataset,
    runs: Sequence[Run],
    config: EvaluationConfig | None = None,
    judge: Judge | None = None,
    cache: JudgmentCache | None = None,
    progress: ProgressFn | None = None,
    tracker: CostTracker | None = None,
    pairwise_judge: PairwiseJudge | None = None,
    pairwise_cache: PairwiseCache | None = None,
) -> EvaluationReport:
    """Score every run against gold labels, filling gaps with ``judge`` when given.

    Pass a :class:`~llm_search_eval.usage.CostTracker` to price token usage and
    enforce a budget. Pairs left unjudged because of the budget count as unlabeled.
    With ``pairwise_judge``, systems are also compared head to head (see
    :mod:`llm_search_eval.pairwise`); that shares the tracker and budget.
    """
    from llm_search_eval import __version__

    config = config or EvaluationConfig()
    config.validate()
    if not runs:
        raise ConfigError("at least one system run is required")
    names = [r.name for r in runs]
    duplicates = [n for n, c in Counter(names).items() if c > 1]
    if duplicates:
        raise ConfigError(f"duplicate system names: {', '.join(duplicates)}")
    baseline = config.baseline or names[0]
    if baseline not in names:
        raise ConfigError(f"baseline {baseline!r} is not one of the systems: {', '.join(names)}")

    metrics = config.parsed_metrics()
    depth = config.resolved_depth()
    primary = config.resolved_primary()

    population = len(dataset.queries)
    dataset, sampling = apply_sampling(dataset, config)
    tracker = tracker or CostTracker()
    labels, stats, judged = build_labels(
        dataset,
        runs,
        depth,
        judge,
        cache,
        config.concurrency,
        progress,
        tracker=tracker,
        calibrate=config.calibrate,
        calibration_sample=config.calibration_sample,
        seed=config.seed,
    )
    systems = [
        score_run(
            run,
            dataset,
            labels,
            metrics,
            depth,
            config.threshold,
            config.gain,
            bootstrap=config.bootstrap,
            confidence=config.confidence,
            seed=config.seed,
        )
        for run in runs
    ]
    comparison = compare_systems(
        systems,
        metrics,
        baseline,
        primary,
        config.permutations,
        config.seed,
        bootstrap=config.bootstrap,
        confidence=config.confidence,
    )
    pairwise = None
    if pairwise_judge is not None:
        from llm_search_eval.pairwise import PairwiseCache, compare_pair, resolve_pairs

        by_name = {run.name: run for run in runs}
        shared_cache = PairwiseCache() if pairwise_cache is None else pairwise_cache
        pairwise = {
            "judge": pairwise_judge.label,
            **_provenance(pairwise_judge.info),
            "k": config.pairwise_k,
            "swap": config.pairwise_swap,
            "comparisons": [
                compare_pair(
                    dataset,
                    by_name[a],
                    by_name[b],
                    pairwise_judge,
                    k=config.pairwise_k,
                    swap=config.pairwise_swap,
                    concurrency=config.concurrency,
                    tracker=tracker,
                    cache=shared_cache,
                    confidence=config.confidence,
                )
                for a, b in resolve_pairs(names, baseline, list(config.pairwise_pairs or []))
            ],
        }
    langs = Counter(q.lang or "und" for q in dataset.queries.values())
    data = {
        "tool": {"name": "llm-search-eval", "version": __version__},
        "title": config.title,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
        "config": {
            "metrics": [m.label for m in metrics],
            "primary_metric": primary.label,
            "depth": depth,
            "threshold": config.threshold,
            "gain": config.gain,
            "baseline": baseline,
            "permutations": config.permutations,
            "seed": config.seed,
            "bootstrap": config.bootstrap,
            "confidence": config.confidence,
            "calibrate": config.calibrate,
            "calibration_sample": config.calibration_sample,
            "sample_size": config.sample_size,
            "stratify_by": config.stratify_by,
        },
        "dataset": {
            "queries": len(dataset.queries),
            "products": len(dataset.products),
            "gold_labels": sum(len(v) for v in dataset.qrels.values()),
            "languages": dict(sorted(langs.items())),
            "population": population,
            "sampling": None if sampling is None else sampling.to_dict(),
        },
        "labels": stats.to_dict(),
        "systems": systems,
        "comparison": comparison,
        "by_language": _by_language(dataset, systems, primary),
        "by_stratum": None
        if not config.stratify_by or config.stratify_by in {"lang", "language"}
        else {
            "field": config.stratify_by,
            "systems": _by_group(
                dataset, systems, primary, lambda q: query_stratum(q, config.stratify_by or "")
            ),
        },
        "judging": judge_analysis(judged, judge, config.threshold),
        "pairwise": pairwise,
        "cost": tracker.to_dict(),
    }
    if config.include_details:
        data["details"] = build_details(dataset, runs, depth, judged)
    return EvaluationReport(data=data, judgments=judged)
