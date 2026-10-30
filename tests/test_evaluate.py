from __future__ import annotations

import pytest

from llm_search_eval import EvaluationConfig, evaluate
from llm_search_eval.errors import ConfigError, JudgeError
from llm_search_eval.evaluate import build_labels, paired_randomization_test
from llm_search_eval.judges import Judge, Judgment, JudgmentCache, MockJudge
from llm_search_eval.models import Run


class CountingJudge(Judge):
    name = "counting"

    def __init__(self, grade: int = 3) -> None:
        self.grade = grade
        self.calls = 0

    def judge(self, query, product):
        self.calls += 1
        return Judgment(self.grade, "ok")


class FailingJudge(Judge):
    name = "failing"

    def judge(self, query, product):
        raise JudgeError(f"cannot grade {product.product_id}")


def test_gold_only_evaluation(tiny_dataset):
    runs = [Run("perfect", {"q1": ["a", "b"], "q2": ["d"]}), Run("bad", {"q1": ["c", "a"]})]
    report = evaluate(tiny_dataset, runs, EvaluationConfig(metrics=["ndcg@2", "mrr"]))
    assert report.mean("perfect", "ndcg@2") == pytest.approx(1.0)
    assert report.mean("perfect", "mrr") == pytest.approx(1.0)
    assert report.mean("bad", "mrr") == pytest.approx(0.25)  # (1/2 + 0) / 2
    labels = report.to_dict()["labels"]
    assert labels["judge"] is None
    assert labels["unlabeled"] == 1  # product c for q1


def test_judge_fills_only_missing_labels(tiny_dataset):
    judge = CountingJudge(grade=3)
    runs = [Run("sys", {"q1": ["a", "c"], "q2": ["d", "b"]})]
    report = evaluate(tiny_dataset, runs, judge=judge)
    assert judge.calls == 2  # (q1, c) and (q2, b); gold pairs are never re-judged
    assert {(j.query_id, j.product_id) for j in report.judgments} == {("q1", "c"), ("q2", "b")}
    assert report.to_dict()["labels"]["judged"] == 2


def test_cache_prevents_repeat_calls(tiny_dataset, tmp_path):
    runs = [Run("sys", {"q1": ["c"], "q2": ["b"]})]
    first = CountingJudge()
    evaluate(tiny_dataset, runs, judge=first, cache=JudgmentCache(tmp_path / "c.jsonl"))
    second = CountingJudge()
    report = evaluate(tiny_dataset, runs, judge=second, cache=JudgmentCache(tmp_path / "c.jsonl"))
    assert first.calls == 2
    assert second.calls == 0
    assert report.to_dict()["labels"]["cached"] == 2
    assert {j.source for j in report.judgments} == {"cache"}


def test_unknown_products_are_counted_not_judged(tiny_dataset):
    judge = CountingJudge()
    report = evaluate(tiny_dataset, [Run("sys", {"q1": ["ghost", "a"]})], judge=judge)
    assert judge.calls == 0
    data = report.to_dict()
    assert data["labels"]["unknown_products"] == 1
    assert data["systems"][0]["coverage"]["unknown_products"] == 1


def test_judge_failures_are_recorded(tiny_dataset):
    report = evaluate(tiny_dataset, [Run("sys", {"q1": ["c"]})], judge=FailingJudge())
    labels = report.to_dict()["labels"]
    assert labels["failed"] == 1
    assert "cannot grade c" in labels["errors"][0]


def test_depth_limits_judging(tiny_dataset):
    judge = CountingJudge()
    runs = [Run("sys", {"q1": ["a", "b", "c"]})]
    evaluate(tiny_dataset, runs, EvaluationConfig(metrics=["ndcg@2"]), judge=judge)
    assert judge.calls == 0
    evaluate(tiny_dataset, runs, EvaluationConfig(metrics=["ndcg@2"], depth=3), judge=judge)
    assert judge.calls == 1


def test_queries_without_relevant_labels_are_excluded(tiny_dataset):
    tiny_dataset.qrels["q2"] = {"d": 0}
    report = evaluate(tiny_dataset, [Run("sys", {"q1": ["a"], "q2": ["d"]})])
    assert report.system("sys")["metrics"]["ndcg@10"]["n"] == 1
    assert report.system("sys")["per_query"]["q2"]["ndcg@10"] is None


def test_example_end_to_end_with_mock_judge(example_dataset, example_runs):
    report = evaluate(example_dataset, example_runs, judge=MockJudge())
    data = report.to_dict()
    assert data["config"]["primary_metric"] == "ndcg@10"
    assert data["config"]["baseline"] == "bm25"
    assert data["comparison"]["ranking"][0] in {"semantic", "hybrid"}
    assert data["labels"]["unlabeled"] == 0
    for system in data["systems"]:
        assert system["coverage"]["labeled_at_depth"] == pytest.approx(1.0)
    sem = next(t for t in data["comparison"]["significance"] if t["system"] == "semantic")
    assert sem["wins"] > sem["losses"]
    assert sem["p_value"] < 0.05
    assert set(data["by_language"]["semantic"]) == {"en", "fa"}


def test_evaluation_is_deterministic(example_dataset, example_runs):
    a = evaluate(example_dataset, example_runs, judge=MockJudge()).to_dict()
    b = evaluate(example_dataset, example_runs, judge=MockJudge()).to_dict()
    a.pop("generated_at")
    b.pop("generated_at")
    assert a == b


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (EvaluationConfig(metrics=["bogus"]), "unknown metric"),
        (EvaluationConfig(depth=0), "depth"),
        (EvaluationConfig(threshold=0), "threshold"),
        (EvaluationConfig(gain="square"), "gain"),
        (EvaluationConfig(permutations=-1), "permutations"),
        (EvaluationConfig(metrics=["mrr"], primary_metric="ndcg@5"), "primary metric"),
        (EvaluationConfig(baseline="missing"), "baseline"),
        (EvaluationConfig(calibration_sample=0), "calibration_sample"),
    ],
)
def test_invalid_configuration(tiny_dataset, config, message):
    with pytest.raises(ConfigError, match=message):
        evaluate(tiny_dataset, [Run("sys", {"q1": ["a"]})], config)


def test_run_list_validation(tiny_dataset):
    with pytest.raises(ConfigError, match="at least one"):
        evaluate(tiny_dataset, [])
    with pytest.raises(ConfigError, match="duplicate"):
        evaluate(tiny_dataset, [Run("x", {}), Run("x", {})])


def test_primary_metric_defaults():
    assert EvaluationConfig(metrics=["mrr", "ndcg@5", "ndcg@10"]).resolved_primary().label == (
        "ndcg@10"
    )
    assert EvaluationConfig(metrics=["mrr", "map"]).resolved_primary().label == "mrr"
    assert EvaluationConfig(metrics=["mrr"]).resolved_depth() == 10
    assert EvaluationConfig(metrics=["ndcg@20", "p@5"]).resolved_depth() == 20


def test_build_labels_progress_callback(tiny_dataset):
    calls = []
    build_labels(
        tiny_dataset,
        [Run("s", {"q1": ["c"], "q2": ["a", "b"]})],
        depth=5,
        judge=CountingJudge(),
        concurrency=2,
        progress=lambda done, total: calls.append((done, total)),
    )
    assert calls[-1] == (3, 3)


def test_randomization_test():
    assert paired_randomization_test([], []) is None
    assert paired_randomization_test([1.0], [0.0], permutations=0) is None
    assert paired_randomization_test([0.5, 0.5], [0.5, 0.5]) == 1.0
    better = [0.9] * 12
    worse = [0.1] * 12
    assert paired_randomization_test(better, worse, permutations=2000) < 0.01
    noisy = paired_randomization_test([0.6, 0.4, 0.5, 0.5], [0.4, 0.6, 0.5, 0.5])
    assert noisy > 0.5
    with pytest.raises(ValueError, match="equal length"):
        paired_randomization_test([1.0], [])


def test_randomization_test_is_seeded():
    a = [0.3, 0.8, 0.5, 0.9, 0.2, 0.7]
    b = [0.2, 0.6, 0.5, 0.4, 0.3, 0.5]
    assert paired_randomization_test(a, b, seed=1) == paired_randomization_test(a, b, seed=1)


# Panels, calibration, cost and budgets --------------------------------------------


class MeteredJudge(CountingJudge):
    name = "metered"

    def judge(self, query, product):
        from llm_search_eval.judges.base import TokenUsage

        self.calls += 1
        return Judgment(self.grade, "ok", usage=TokenUsage("m", 100, 10))


def test_cost_tracking_and_cache_hits(tiny_dataset):
    from llm_search_eval.usage import CostTracker, PriceTable

    runs = [Run("sys", {"q1": ["a", "c"], "q2": ["d", "b"]})]
    cache = JudgmentCache()
    tracker = CostTracker(prices=PriceTable.parse_specs(["m=1,10"]))
    report = evaluate(tiny_dataset, runs, judge=MeteredJudge(), cache=cache, tracker=tracker)
    cost = report.to_dict()["cost"]
    assert cost["requests"] == 2
    assert cost["total_tokens"] == 220
    assert cost["cost_usd"] == pytest.approx(2 * (100 * 1 + 10 * 10) / 1_000_000)
    again = evaluate(tiny_dataset, runs, judge=MeteredJudge(), cache=cache)
    assert again.to_dict()["cost"]["cache_hits"] == 2
    assert again.to_dict()["cost"]["requests"] == 0


def test_budget_leaves_pairs_unlabeled(tiny_dataset):
    from llm_search_eval.usage import Budget, CostTracker

    runs = [Run("sys", {"q1": ["a", "c"], "q2": ["d", "b", "c"]})]
    judge = MeteredJudge()
    tracker = CostTracker(budget=Budget(max_judgments=1))
    config = EvaluationConfig(concurrency=1)
    report = evaluate(tiny_dataset, runs, config, judge=judge, tracker=tracker)
    data = report.to_dict()
    assert judge.calls == 1
    assert data["labels"]["skipped_budget"] == 2
    assert data["labels"]["unlabeled"] == 2
    assert data["cost"]["budget"]["exhausted"]


def test_panel_agreement_and_calibration(example_dataset, example_runs):
    from llm_search_eval.judges.panel import JudgePanel

    panel = JudgePanel([MockJudge(noise=0.3, seed=s) for s in (1, 2, 3)])
    config = EvaluationConfig(permutations=100, calibrate=True)
    report = evaluate(example_dataset, example_runs, config, judge=panel)
    data = report.to_dict()
    judging = data["judging"]
    assert judging["panel"]["members"] == panel.labels
    assert judging["panel"]["min_votes"] == 2
    assert judging["agreement"]["complete_items"] == judging["pairs"]
    assert -1 <= judging["agreement"]["fleiss_kappa"] <= 1
    gold = judging["gold_agreement"]
    assert gold["judge"]["n"] == data["labels"]["calibration"] > 0
    assert set(gold["members"]) == set(panel.labels)
    # Calibration never changes scores: gold labels still win.
    plain = evaluate(example_dataset, example_runs, EvaluationConfig(permutations=100), judge=panel)
    assert report.mean("bm25", "ndcg@10") == plain.mean("bm25", "ndcg@10")


def test_calibration_sample_and_details(tiny_dataset):
    judge = CountingJudge(grade=1)
    config = EvaluationConfig(calibrate=True, calibration_sample=2)
    runs = [Run("sys", {"q1": ["a", "c"]})]
    data = evaluate(tiny_dataset, runs, config, judge=judge).to_dict()
    assert data["labels"]["calibration"] == 2
    assert judge.calls == 3  # two gold pairs plus (q1, c)
    details = data["details"]
    assert details["rankings"]["sys"]["q1"] == ["a", "c"]
    assert details["labels"]["q1"]["a"]["source"] == "gold"
    assert details["labels"]["q1"]["c"]["source"] == "judge"
    assert details["products"]["a"]["title"] == "Red Running Shoes"
