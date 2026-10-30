import pytest

from llm_search_eval import EvaluationConfig, evaluate
from llm_search_eval.errors import ConfigError
from llm_search_eval.models import Dataset, Product, Query, Run
from llm_search_eval.report import render_markdown
from llm_search_eval.stats import (
    bootstrap_ci,
    paired_bootstrap_ci,
    sign_test,
    wilson_interval,
)


def test_bootstrap_ci_contains_the_mean_and_is_reproducible():
    values = [0.1, 0.4, 0.5, 0.9, 1.0, 0.3, 0.7, 0.2]
    first = bootstrap_ci(values, resamples=500, seed=3)
    second = bootstrap_ci(values, resamples=500, seed=3)
    assert first == second
    assert first is not None
    assert first.low < first.estimate < first.high
    assert first.low >= 0.0
    assert first.high <= 1.0


def test_bootstrap_ci_edge_cases():
    assert bootstrap_ci([]) is None
    single = bootstrap_ci([0.5])
    assert single is not None
    assert single.low == single.high == 0.5
    flat = bootstrap_ci([1.0, 1.0, 1.0])
    assert flat is not None
    assert flat.low == flat.high == 1.0
    with pytest.raises(ValueError, match="confidence"):
        bootstrap_ci([1.0, 2.0], confidence=1.5)
    with pytest.raises(ValueError, match="resamples"):
        bootstrap_ci([1.0, 2.0], resamples=0)


def test_wider_confidence_gives_wider_interval():
    values = [i / 20 for i in range(21)]
    narrow = bootstrap_ci(values, confidence=0.8, resamples=400)
    wide = bootstrap_ci(values, confidence=0.99, resamples=400)
    assert narrow is not None
    assert wide is not None
    assert wide.high - wide.low > narrow.high - narrow.low


def test_paired_bootstrap_ci():
    a = [0.9, 0.8, 0.95, 0.85, 0.9, 0.7]
    b = [0.5, 0.6, 0.55, 0.45, 0.5, 0.6]
    ci = paired_bootstrap_ci(a, b, resamples=500)
    assert ci is not None
    assert ci.low > 0
    assert ci.contains(ci.estimate)
    with pytest.raises(ValueError, match="equal length"):
        paired_bootstrap_ci([1.0], [1.0, 2.0])


def test_wilson_interval_and_sign_test():
    ci = wilson_interval(8, 10)
    assert ci is not None
    assert ci.low == pytest.approx(0.490, abs=1e-3)
    assert ci.high == pytest.approx(0.943, abs=1e-3)
    assert wilson_interval(0, 0) is None
    assert sign_test(0, 0) is None
    assert sign_test(5, 5) == 1.0
    assert sign_test(8, 2) == pytest.approx(0.109375)
    assert sign_test(10, 0) == pytest.approx(2 / 1024)


def _dataset() -> Dataset:
    queries = {f"q{i}": Query(f"q{i}", f"query {i}", "en") for i in range(12)}
    products = {f"p{i}": Product(f"p{i}", f"product {i}") for i in range(4)}
    qrels = {f"q{i}": {"p1": 3, "p2": 1 if i % 3 else 3} for i in range(12)}
    return Dataset(queries, products, qrels)


def test_evaluate_reports_intervals():
    dataset = _dataset()
    runs = [
        Run("a", {q: ["p0", "p2", "p1"] for q in dataset.queries}),
        Run("b", {q: ["p1", "p2", "p0"] for q in dataset.queries}),
    ]
    report = evaluate(dataset, runs, EvaluationConfig(bootstrap=300, permutations=200))
    entry = report.system("a")["metrics"]["ndcg@10"]
    assert entry["ci_low"] <= entry["mean"] <= entry["ci_high"]
    delta = next(d for d in report.data["comparison"]["deltas"] if d["metric"] == "ndcg@10")
    assert delta["ci_low"] > 0
    assert report.data["config"]["bootstrap"] == 300
    text = render_markdown(report)
    assert "Confidence intervals" in text
    assert "95% CI" in text


def test_bootstrap_can_be_turned_off():
    dataset = _dataset()
    runs = [Run("a", {q: ["p1"] for q in dataset.queries})]
    report = evaluate(dataset, runs, EvaluationConfig(bootstrap=0))
    assert "ci_low" not in report.system("a")["metrics"]["ndcg@10"]
    assert "Confidence intervals" not in render_markdown(report)


@pytest.mark.parametrize("kwargs", [{"bootstrap": -1}, {"confidence": 1.0}])
def test_invalid_bootstrap_settings(kwargs):
    with pytest.raises(ConfigError):
        EvaluationConfig(**kwargs).validate()
