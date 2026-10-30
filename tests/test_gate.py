from __future__ import annotations

import copy
import json

import pytest

from llm_search_eval import EvaluationConfig, evaluate
from llm_search_eval.errors import ConfigError
from llm_search_eval.gate import check_report, load_report
from llm_search_eval.models import Run


@pytest.fixture
def report(tiny_dataset):
    runs = [
        Run("base", {"q1": ["a", "b"], "q2": ["d"]}),
        Run("worse", {"q1": ["c", "b", "a"], "q2": ["c", "d"]}),
    ]
    config = EvaluationConfig(metrics=["ndcg@3", "mrr"], permutations=200)
    return evaluate(tiny_dataset, runs, config).to_dict()


def test_floors(report):
    result = check_report(report, floors={"mrr": 0.9})
    assert not result.passed
    assert [c.system for c in result.failures] == ["worse"]
    assert check_report(report, floors={"mrr": 0.4}).passed


def test_baseline_regression_limits(report):
    result = check_report(report, max_drop=0.1)
    assert not result.passed
    (check,) = result.checks
    assert check.kind == "baseline"
    assert check.metric == "ndcg@3"  # the primary metric by default
    assert "dropped" in check.message
    assert check_report(report, max_drop=0.9).passed
    assert not check_report(report, max_relative_drop=0.1).passed


def test_significant_only_ignores_noisy_drops(report):
    # Two queries cannot make any difference significant.
    result = check_report(report, max_drop=0.0, significant_only=True)
    assert result.passed
    assert "not significant" in result.checks[0].message


def test_reference_comparison(report):
    reference = copy.deepcopy(report)
    for system in reference["systems"]:
        system["metrics"]["ndcg@3"]["mean"] = 1.0
    result = check_report(report, reference=reference, max_drop=0.05, systems=["base", "worse"])
    assert [c.kind for c in result.checks] == ["reference", "reference"]
    assert [c.passed for c in result.checks] == [True, False]
    reference["systems"] = reference["systems"][:1]
    result = check_report(report, reference=reference, max_drop=0.05)
    assert result.checks[1].message == "not in the reference report"


def test_markdown_and_dict(report):
    result = check_report(report, floors={"mrr": 0.9}, max_drop=0.5)
    md = result.to_markdown()
    assert md.startswith("### Search quality gate: failed")
    assert "**FAIL**" in md
    assert result.to_dict()["passed"] is False
    assert "No checks" in check_report(report).to_markdown()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"floors": {"ndcg@10": 0.5}}, "not in the report"),
        ({"systems": ["nope"]}, "not in the report"),
        ({"max_drop": -1}, "must not be negative"),
        ({"alpha": 2}, "alpha"),
    ],
)
def test_validation(report, kwargs, message):
    with pytest.raises(ConfigError, match=message):
        check_report(report, **kwargs)


def test_load_report(tmp_path, report):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert load_report(path)["systems"]
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_report(path)
