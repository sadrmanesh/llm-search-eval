import json

import pytest

from llm_search_eval import EvaluationConfig, evaluate
from llm_search_eval.cli import main
from llm_search_eval.errors import ConfigError, JudgeError
from llm_search_eval.judges.base import TokenUsage
from llm_search_eval.judges.openai_compat import HTTPResponse, OpenAICompatibleJudge
from llm_search_eval.judges.pairwise import (
    MockPairwiseJudge,
    OpenAIPairwiseJudge,
    PairwiseJudge,
    PairwiseVerdict,
    available_pairwise_judges,
    create_pairwise_judge,
    parse_pairwise,
)
from llm_search_eval.judges.prompts import pairwise_user_prompt
from llm_search_eval.models import Dataset, Product, Query, Run
from llm_search_eval.pairwise import PairwiseCache, compare_pair, resolve_pairs
from llm_search_eval.report import render_markdown
from llm_search_eval.usage import Budget, CostTracker, ModelPrice, PriceTable


class FirstListJudge(PairwiseJudge):
    """Always prefers the list shown first: a judge with pure position bias."""

    name = "first"

    def __init__(self) -> None:
        self.calls = 0

    def compare(self, query, first, second):
        self.calls += 1
        return PairwiseVerdict("A", "first", TokenUsage("m", 100, 10))


class LongerListJudge(PairwiseJudge):
    name = "longer"

    def compare(self, query, first, second):
        if len(first) == len(second):
            return PairwiseVerdict("tie")
        return PairwiseVerdict("A" if len(first) > len(second) else "B", "longer")


@pytest.fixture
def dataset() -> Dataset:
    queries = {f"q{i}": Query(f"q{i}", f"red shoes {i}", "en") for i in range(6)}
    products = {
        "good": Product("good", "Red running shoes"),
        "ok": Product("ok", "Shoes", brand="Acme"),
        "bad": Product("bad", "Blue kettle"),
    }
    return Dataset(queries, products)


def test_parse_pairwise():
    assert parse_pairwise('{"winner": "A", "reason": "x"}') == PairwiseVerdict("A", "x")
    assert parse_pairwise('```json\n{"winner": "b"}\n```').winner == "B"
    assert parse_pairwise("tie").winner == "tie"
    assert parse_pairwise('{"winner": "neither"}').winner == "tie"
    assert parse_pairwise('"B".').winner == "B"
    with pytest.raises(JudgeError, match="no JSON"):
        parse_pairwise("I like the first one")
    with pytest.raises(JudgeError, match="no valid winner"):
        parse_pairwise('{"winner": "C"}')
    with pytest.raises(ValueError, match="winner"):
        PairwiseVerdict("C")


def test_mock_pairwise_judge(dataset):
    judge = MockPairwiseJudge()
    query = dataset.queries["q0"]
    good, bad = dataset.products["good"], dataset.products["bad"]
    assert judge.compare(query, [good], [bad]).winner == "A"
    assert judge.compare(query, [bad], [good]).winner == "B"
    assert judge.compare(query, [bad], [bad]).winner == "tie"
    assert judge.compare(query, [good, bad], [good]).winner == "tie"
    assert "pairwise-mock" in judge.fingerprint
    with pytest.raises(ValueError, match="margin"):
        MockPairwiseJudge(margin=2)


def test_registry():
    assert {"mock", "openai"} <= set(available_pairwise_judges())
    assert isinstance(create_pairwise_judge("mock", margin=0.1), MockPairwiseJudge)
    with pytest.raises(ConfigError, match="unknown pairwise judge"):
        create_pairwise_judge("nope")
    with pytest.raises(ConfigError, match="invalid options"):
        create_pairwise_judge("mock", colour="red")
    with pytest.raises(ConfigError, match="cannot load"):
        create_pairwise_judge("no_such_module:Judge")


def test_openai_pairwise_judge_sends_both_lists(dataset):
    sent = []

    def transport(url, headers, payload, timeout):
        sent.append(json.loads(payload))
        body = {
            "model": "gpt-test",
            "choices": [{"message": {"content": '{"winner": "B", "reason": "better top"}'}}],
            "usage": {"prompt_tokens": 300, "completion_tokens": 12},
        }
        return HTTPResponse(200, json.dumps(body))

    client = OpenAICompatibleJudge(
        model="gpt-test", api_key="k", transport=transport, sleep=lambda _: None
    )
    judge = OpenAIPairwiseJudge(client=client)
    query = dataset.queries["q0"]
    verdict = judge.compare(query, [dataset.products["bad"]], [dataset.products["good"]])
    assert verdict.winner == "B"
    assert verdict.usage == TokenUsage("gpt-test", 300, 12)
    user = sent[0]["messages"][1]["content"]
    assert "Results A:\n1. Title: Blue kettle" in user
    assert "Results B:\n1. Title: Red running shoes" in user
    assert judge.label == "openai:gpt-test"
    assert "pairwise-v1" in judge.fingerprint


def test_prompt_marks_empty_lists():
    text = pairwise_user_prompt(Query("q", "x", "fa"), [], [])
    assert "Persian" in text
    assert text.count("(no results)") == 2


def test_swap_cancels_position_bias(dataset):
    run_a = Run("a", {q: ["good"] for q in dataset.queries})
    run_b = Run("b", {q: ["bad"] for q in dataset.queries})
    judge = FirstListJudge()
    result = compare_pair(dataset, run_a, run_b, judge, swap=True)
    assert result["wins_a"] == result["wins_b"] == 0
    assert result["ties"] == 6
    assert result["inconsistent"] == 6
    assert judge.calls == 12
    assert result["win_rate_b"] is None
    assert result["p_value"] is None
    single = compare_pair(dataset, run_a, run_b, FirstListJudge(), swap=False)
    assert single["wins_a"] == 6
    assert single["p_value"] == pytest.approx(2 / 64)


def test_compare_pair_counts_and_shortcuts(dataset):
    rankings_a = {"q0": ["good", "ok"], "q1": ["good"], "q2": ["good"], "q3": []}
    rankings_b = {"q0": ["good"], "q1": ["good", "ok"], "q2": ["good"], "q3": []}
    result = compare_pair(dataset, Run("a", rankings_a), Run("b", rankings_b), LongerListJudge())
    assert result["queries"] == 3  # q3..q5 have no results at all
    assert result["wins_a"] == 1
    assert result["wins_b"] == 1
    assert result["identical"] == 1
    assert result["per_query"]["q2"]["source"] == "identical"
    assert result["per_query"]["q1"] == {
        "winner": "b",
        "orders": ["B", "A"],
        "reason": "longer",
        "source": "judge",
    }
    with pytest.raises(ConfigError, match="positive"):
        compare_pair(dataset, Run("a", {}), Run("b", {}), LongerListJudge(), k=0)


def test_cache_and_budget(dataset, tmp_path):
    run_a = Run("a", {q: ["good"] for q in dataset.queries})
    run_b = Run("b", {q: ["bad"] for q in dataset.queries})
    path = tmp_path / "pairwise.jsonl"
    prices = PriceTable({"m": ModelPrice(1.0, 2.0)})
    tracker = CostTracker(prices=prices)
    judge = FirstListJudge()
    compare_pair(
        dataset, run_a, run_b, judge, cache=PairwiseCache(path), tracker=tracker, concurrency=1
    )
    assert judge.calls == 12
    assert tracker.to_dict()["prompt_tokens"] == 1200
    again = FirstListJudge()
    compare_pair(dataset, run_a, run_b, again, cache=PairwiseCache(path))
    assert again.calls == 0
    path.write_text(path.read_text() + "not json\n")
    assert len(PairwiseCache(path)) == 12

    limited = CostTracker(budget=Budget(max_judgments=1))
    result = compare_pair(dataset, run_a, run_b, FirstListJudge(), tracker=limited, concurrency=1)
    assert result["skipped_budget"] >= 1


def test_failures_are_reported(dataset):
    class Broken(PairwiseJudge):
        def compare(self, query, first, second):
            raise JudgeError("boom")

    run_a = Run("a", {"q0": ["good"]})
    run_b = Run("b", {"q0": ["bad"]})
    result = compare_pair(dataset, run_a, run_b, Broken())
    assert result["failed"] == 1
    assert "boom" in result["errors"][0]


def test_resolve_pairs():
    assert resolve_pairs(["a", "b", "c"], "a", None) == [("a", "b"), ("a", "c")]
    assert resolve_pairs(["a", "b"], "a", [("b", "a")]) == [("b", "a")]
    with pytest.raises(ConfigError, match="not one of"):
        resolve_pairs(["a", "b"], "a", [("a", "z")])
    with pytest.raises(ConfigError, match="different"):
        resolve_pairs(["a", "b"], "a", [("a", "a")])


def test_evaluate_with_pairwise(example_dataset, example_runs):
    report = evaluate(
        example_dataset,
        example_runs,
        EvaluationConfig(bootstrap=0, pairwise_k=3),
        pairwise_judge=MockPairwiseJudge(),
    )
    pairwise = report.data["pairwise"]
    assert pairwise["k"] == 3
    assert [(c["system_a"], c["system_b"]) for c in pairwise["comparisons"]] == [
        ("bm25", "semantic"),
        ("bm25", "hybrid"),
    ]
    text = render_markdown(report)
    assert "## Pairwise preference" in text
    assert "`semantic` vs `bm25`" in text


def test_cli_pairwise(example_dir, tmp_path):
    out = tmp_path / "out"
    code = main(
        [
            "run",
            "-q",
            str(example_dir / "queries.jsonl"),
            "-p",
            str(example_dir / "products.jsonl"),
            "-s",
            f"bm25={example_dir / 'runs' / 'bm25.jsonl'}",
            "-s",
            f"semantic={example_dir / 'runs' / 'semantic.csv'}",
            "--pairwise-judge",
            "mock=margin=0.1",
            "--pairwise",
            "semantic:bm25",
            "--no-swap",
            "--pairwise-cache",
            str(tmp_path / "pw.jsonl"),
            "-o",
            str(out),
            "--quiet",
        ]
    )
    assert code == 0
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    comparison = data["pairwise"]["comparisons"][0]
    assert comparison["system_a"] == "semantic"
    assert comparison["swap"] is False
    assert (tmp_path / "pw.jsonl").is_file()
    bad = ["run", "-q", "x", "-p", "y", "-s", "a=b", "--pairwise", "a:b"]
    assert main(bad) == 2
