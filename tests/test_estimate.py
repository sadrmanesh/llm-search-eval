import json

import pytest

from llm_search_eval import EvaluationConfig, evaluate
from llm_search_eval.cli import main
from llm_search_eval.errors import ConfigError
from llm_search_eval.estimate import estimate_run, estimate_tokens, message_tokens, render_estimate
from llm_search_eval.judges import JudgmentCache, MockJudge, OpenAICompatibleJudge
from llm_search_eval.judges.base import Judgment
from llm_search_eval.judges.cache import cache_key
from llm_search_eval.judges.pairwise import MockPairwiseJudge, OpenAIPairwiseJudge
from llm_search_eval.judges.panel import JudgePanel
from llm_search_eval.pairwise import PairwiseCache
from llm_search_eval.usage import Budget, CostTracker, ModelPrice, PriceTable


def openai(model="gpt-test"):
    return OpenAICompatibleJudge(model=model, api_key="k", transport=lambda *a: None)


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd" * 10) == 10
    assert estimate_tokens("کفش ورزشی") == 5  # 8 letters and one ASCII space
    assert message_tokens([{"role": "user", "content": "abcd"}]) == 5


def test_estimate_matches_a_mock_run(example_dataset, example_runs):
    config = EvaluationConfig(bootstrap=0, permutations=100)
    estimate = estimate_run(example_dataset, example_runs, config, judge=MockJudge())
    tracker = CostTracker()
    report = evaluate(example_dataset, example_runs, config, judge=MockJudge(), tracker=tracker)
    assert estimate.to_judge == report.data["labels"]["judged"]
    assert estimate.free_calls == estimate.to_judge
    assert estimate.calls == 0
    assert estimate.cost_usd == 0.0


def test_estimate_prices_and_budget(example_dataset, example_runs):
    prices = PriceTable({"gpt-test": ModelPrice(1.0, 4.0)})
    estimate = estimate_run(
        example_dataset,
        example_runs,
        judge=openai(),
        prices=prices,
        budget=Budget(max_judgments=5, max_tokens=10, max_cost_usd=1.0),
        output_tokens=10,
    )
    data = estimate.to_dict()
    model = data["models"]["gpt-test"]
    assert model["calls"] == estimate.to_judge > 5
    assert model["completion_tokens"] == 10 * model["calls"]
    expected = (model["prompt_tokens"] * 1.0 + model["completion_tokens"] * 4.0) / 1e6
    assert data["cost_usd"] == pytest.approx(expected, abs=1e-6)
    assert data["budget"]["fits"] is False
    assert len(data["budget"]["problems"]) == 2  # judgments and tokens, not cost
    text = "\n".join(render_estimate(estimate))
    assert "budget: exceeded" in text


def test_panel_cache_and_unpriced(example_dataset, example_runs):
    panel = JudgePanel([openai("a"), openai("b"), MockJudge()])
    cache = JudgmentCache()
    dataset = example_dataset
    qid, pid = next(
        (q, p)
        for q in dataset.queries
        for p in example_runs[0].ranking(q, 10)
        if dataset.gold_label(q, p) is None
    )
    key = cache_key(panel.fingerprint, dataset.queries[qid], dataset.products[pid])
    cache.put(key, Judgment(2, "cached"))
    estimate = estimate_run(dataset, example_runs, judge=panel, cache=cache)
    assert estimate.cached == 1
    assert estimate.models["a"].calls == estimate.to_judge
    assert estimate.free_calls == estimate.to_judge
    assert estimate.cost_usd is None
    assert estimate.to_dict()["unpriced_models"] == ["a", "b"]
    assert "set --price" in "\n".join(render_estimate(estimate))


def test_calibration_and_sampling(example_dataset, example_runs):
    base = estimate_run(example_dataset, example_runs, judge=MockJudge())
    calibrated = estimate_run(
        example_dataset, example_runs, EvaluationConfig(calibrate=True), judge=MockJudge()
    )
    assert calibrated.calibration > 0
    assert calibrated.to_judge == base.to_judge + calibrated.calibration
    sampled = estimate_run(
        example_dataset, example_runs, EvaluationConfig(sample_size=3), judge=MockJudge()
    )
    assert sampled.queries == 3
    assert sampled.to_judge < base.to_judge


def test_pairwise_estimate(example_dataset, example_runs, tmp_path):
    judge = OpenAIPairwiseJudge(client=openai())
    swap = estimate_run(example_dataset, example_runs, pairwise_judge=judge)
    once = estimate_run(
        example_dataset, example_runs, EvaluationConfig(pairwise_swap=False), pairwise_judge=judge
    )
    assert swap.pairwise_comparisons == 20  # two pairs vs the baseline, ten queries
    assert swap.pairwise_calls == 2 * once.pairwise_calls
    assert swap.models["gpt-test"].calls == swap.pairwise_calls

    cache = PairwiseCache(tmp_path / "pw.jsonl")
    mock = MockPairwiseJudge()
    evaluate(
        example_dataset,
        example_runs,
        EvaluationConfig(bootstrap=0, permutations=10),
        pairwise_judge=mock,
        pairwise_cache=cache,
    )
    warm = estimate_run(
        example_dataset, example_runs, pairwise_judge=mock, pairwise_cache=PairwiseCache(cache.path)
    )
    assert warm.pairwise_calls == 0
    assert warm.pairwise_cached > 0


def test_estimate_validation(example_dataset, example_runs):
    with pytest.raises(ConfigError, match="output_tokens"):
        estimate_run(example_dataset, example_runs, output_tokens=-1)
    with pytest.raises(ConfigError, match="at least one run"):
        estimate_run(example_dataset, [])


def test_cli_estimate(example_dir, capsys, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    args = [
        "estimate",
        "-q",
        str(example_dir / "queries.jsonl"),
        "-p",
        str(example_dir / "products.jsonl"),
        "--qrels",
        str(example_dir / "qrels.csv"),
        "-s",
        f"bm25={example_dir / 'runs' / 'bm25.jsonl'}",
        "--judge",
        "openai=gpt-test",
        "--price",
        "gpt-test=1,2",
    ]
    assert main([*args, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["models"]["gpt-test"]["calls"] == data["to_judge"]
    assert data["budget"]["fits"] is True
    assert main([*args, "--max-judgments", "1"]) == 1
    assert "budget: exceeded" in capsys.readouterr().out
