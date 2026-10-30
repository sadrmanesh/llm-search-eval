from __future__ import annotations

import math

import pytest

from llm_search_eval.errors import ConfigError
from llm_search_eval.metrics import (
    Metric,
    average_precision,
    dcg,
    ndcg_at_k,
    parse_metrics,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

LABELS = {"a": 3, "b": 2, "c": 0, "d": 1, "e": 2}


def test_dcg_exponential_and_linear():
    assert dcg([3, 2, 0]) == pytest.approx(7 + 3 / math.log2(3))
    assert dcg([3, 2, 0], gain="linear") == pytest.approx(3 + 2 / math.log2(3))
    assert dcg([]) == 0.0


def test_dcg_rejects_unknown_gain():
    with pytest.raises(ConfigError):
        dcg([1], gain="cubic")


def test_ndcg_perfect_ranking_is_one():
    assert ndcg_at_k(["a", "b", "e", "d"], LABELS, 4) == pytest.approx(1.0)


def test_ndcg_hand_computed():
    # ranking c, a, b with ideal a, b, e (grades 3, 2, 2)
    actual = 0 + 7 / math.log2(3) + 3 / math.log2(4)
    ideal = 7 + 3 / math.log2(3) + 3 / math.log2(4)
    assert ndcg_at_k(["c", "a", "b"], LABELS, 3) == pytest.approx(actual / ideal)


def test_ndcg_unlabeled_items_count_as_zero():
    assert ndcg_at_k(["zzz"], LABELS, 1) == 0.0


def test_ndcg_undefined_without_relevant_labels():
    assert ndcg_at_k(["a"], {"a": 0}, 5) is None
    assert ndcg_at_k(["a"], {}, 5) is None


def test_precision_uses_k_as_denominator():
    assert precision_at_k(["a", "c"], LABELS, 5) == pytest.approx(1 / 5)
    assert precision_at_k(["a", "b", "e"], LABELS, 2) == pytest.approx(1.0)


def test_threshold_controls_binary_relevance():
    assert precision_at_k(["d"], LABELS, 1, threshold=2) == 0.0
    assert precision_at_k(["d"], LABELS, 1, threshold=1) == 1.0


def test_recall():
    assert recall_at_k(["a", "c", "e"], LABELS, 3) == pytest.approx(2 / 3)
    assert recall_at_k(["a"], {"a": 0}, 3) is None


def test_reciprocal_rank():
    assert reciprocal_rank(["c", "d", "b"], LABELS) == pytest.approx(1 / 3)
    assert reciprocal_rank(["c", "d"], LABELS) == 0.0
    assert reciprocal_rank(["c"], {"c": 0}) is None


def test_average_precision():
    # relevant (>=2): a, b, e. Ranking: a(hit 1/1), c, b(hit 2/3)
    assert average_precision(["a", "c", "b"], LABELS) == pytest.approx((1 + 2 / 3) / 3)
    assert average_precision([], LABELS) == 0.0


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("ndcg@10", Metric("ndcg", 10)),
        ("NDCG@5", Metric("ndcg", 5)),
        ("p@3", Metric("precision", 3)),
        ("recall@20", Metric("recall", 20)),
        ("mrr", Metric("mrr")),
        ("mrr@10", Metric("mrr", 10)),
        ("map", Metric("map")),
    ],
)
def test_metric_parse(spec, expected):
    assert Metric.parse(spec) == expected


@pytest.mark.parametrize("spec", ["ndcg", "precision", "foo@3", "ndcg@0", "ndcg@x", ""])
def test_metric_parse_errors(spec):
    with pytest.raises(ConfigError):
        Metric.parse(spec)


def test_metric_cutoff_applies_to_mrr():
    assert Metric("mrr", 1).compute(["c", "a"], LABELS) == 0.0
    assert Metric("mrr").compute(["c", "a"], LABELS) == 0.5


def test_parse_metrics_dedupes_and_requires_one():
    metrics = parse_metrics("ndcg@10, mrr, ndcg@10")
    assert [m.label for m in metrics] == ["ndcg@10", "mrr"]
    with pytest.raises(ConfigError):
        parse_metrics("")
