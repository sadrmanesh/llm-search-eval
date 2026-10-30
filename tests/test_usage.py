from __future__ import annotations

import json

import pytest

from llm_search_eval.errors import ConfigError
from llm_search_eval.judges.base import TokenUsage
from llm_search_eval.usage import (
    Budget,
    BudgetExceededError,
    CostTracker,
    ModelPrice,
    PriceTable,
)


def test_model_price_cost():
    price = ModelPrice(0.15, 0.60)
    assert price.cost(TokenUsage("m", 1_000_000, 0)) == pytest.approx(0.15)
    assert price.cost(TokenUsage("m", 2000, 500)) == pytest.approx(0.0006)


def test_price_table_matches_exact_then_longest_prefix():
    table = PriceTable.parse_specs(["gpt-4o=2.5,10", "gpt-4o-mini=0.15,0.6"])
    assert table.get("gpt-4o-mini-2024-07-18") == ModelPrice(0.15, 0.6)
    assert table.get("GPT-4o-2024-08-06") == ModelPrice(2.5, 10)
    assert table.get("llama3") is None
    assert "gpt-4o" in table
    assert len(table) == 2


def test_price_table_from_file_and_dict_forms(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps(
            {
                "a": {"input_per_million": 1, "output_per_million": 2},
                "b": {"input": 3, "output": 4},
                "c": [5, 6],
            }
        ),
        encoding="utf-8",
    )
    table = PriceTable.from_file(path)
    assert table.get("b") == ModelPrice(3, 4)
    assert table.to_dict()["c"] == {"input_per_million": 5, "output_per_million": 6}
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ConfigError):
        PriceTable.from_file(path)
    with pytest.raises(ConfigError):
        PriceTable.from_file(tmp_path / "missing.json")


@pytest.mark.parametrize("spec", ["gpt", "=1,2", "m=1", "m=a,b", "m=-1,2"])
def test_price_specs_are_validated(spec):
    with pytest.raises(ConfigError):
        PriceTable.parse_specs([spec])


def test_budget_validation():
    assert not Budget().active
    assert Budget(max_tokens=10).active
    with pytest.raises(ConfigError):
        Budget(max_cost_usd=-1)


def test_tracker_accumulates_cost_per_model():
    tracker = CostTracker(prices=PriceTable.parse_specs(["a=1,2"]))
    tracker.reserve()
    tracker.record([TokenUsage("a", 1000, 100)])
    tracker.record_cache_hit()
    data = tracker.to_dict()
    assert data["requests"] == 1
    assert data["judgments"] == 1
    assert data["cache_hits"] == 1
    assert data["total_tokens"] == 1100
    assert data["cost_usd"] == pytest.approx(0.0012)
    assert data["unpriced_models"] == []


def test_unpriced_models_make_total_cost_unknown():
    tracker = CostTracker(prices=PriceTable.parse_specs(["a=1,2"]))
    tracker.record([TokenUsage("a", 1000, 0), TokenUsage("b", 10, 10)])
    data = tracker.to_dict()
    assert data["cost_usd"] is None
    assert data["known_cost_usd"] == pytest.approx(0.001)
    assert data["unpriced_models"] == ["b"]
    assert data["models"]["b"]["cost_usd"] is None


@pytest.mark.parametrize(
    ("budget", "reason"),
    [
        (Budget(max_judgments=2), "judgment limit"),
        (Budget(max_tokens=150), "token limit"),
        (Budget(max_cost_usd=0.00015), "cost limit"),
    ],
)
def test_budget_stops_new_requests(budget, reason):
    tracker = CostTracker(prices=PriceTable.parse_specs(["a=1,1"]), budget=budget)
    for _ in range(2):
        tracker.reserve()
        tracker.record([TokenUsage("a", 50, 50)])
    with pytest.raises(BudgetExceededError, match=reason):
        tracker.reserve()
    data = tracker.to_dict()["budget"]
    assert data["exhausted"]
    assert data["skipped_pairs"] == 1
