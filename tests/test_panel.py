from __future__ import annotations

import pytest

from llm_search_eval.errors import ConfigError, JudgeError
from llm_search_eval.judges import Judge, Judgment, MockJudge
from llm_search_eval.judges.base import TokenUsage
from llm_search_eval.judges.panel import JudgePanel, aggregate_grades
from llm_search_eval.models import Product, Query

QUERY = Query("q1", "red running shoes", "en")
PRODUCT = Product("p1", "Red Running Shoes")


class Fixed(Judge):
    name = "fixed"

    def __init__(self, grade: int | None, model: str = "m") -> None:
        self.grade = grade
        self.model = model
        self.closed = False

    @property
    def fingerprint(self) -> str:
        return f"fixed:{self.grade}"

    def judge(self, query, product):
        if self.grade is None:
            raise JudgeError("boom")
        return Judgment(self.grade, f"says {self.grade}", usage=TokenUsage(self.model, 10, 2))

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("grades", "method", "expected"),
    [
        ([3, 3, 1], "majority", 3),
        ([0, 3], "majority", 0),  # tie: both equally close to the mean, lower wins
        ([1, 2, 3, 3, 2], "majority", 2),  # tie between 2 and 3; 2 is closer to the mean
        ([1, 2], "mean", 2),  # 1.5 rounds half up
        ([0, 1, 1], "mean", 1),
        ([0, 2, 3], "median", 2),
        ([0, 2, 3], "min", 0),
        ([0, 2, 3], "max", 3),
    ],
)
def test_aggregate_grades(grades, method, expected):
    assert aggregate_grades(grades, method) == expected


def test_aggregate_grades_rejects_bad_input():
    with pytest.raises(ValueError, match="at least one grade"):
        aggregate_grades([], "majority")
    with pytest.raises(ConfigError):
        aggregate_grades([1], "mode")


def test_panel_combines_votes_and_usage():
    panel = JudgePanel([Fixed(3, "a"), Fixed(3, "b"), Fixed(1, "c")])
    result = panel.judge(QUERY, PRODUCT)
    assert result.relevance == 3
    assert [v.relevance for v in result.votes] == [3, 3, 1]
    assert [u.model for u in result.usages()] == ["a", "b", "c"]
    assert "majority of" in result.reason
    assert panel.min_votes == 2


def test_panel_labels_are_unique_and_fingerprint_is_stable():
    panel = JudgePanel([Fixed(1), Fixed(2)], aggregation="mean")
    assert panel.labels == ["fixed#1", "fixed#2"]
    assert panel.fingerprint == JudgePanel([Fixed(1), Fixed(2)], aggregation="mean").fingerprint
    assert panel.fingerprint != JudgePanel([Fixed(1), Fixed(2)]).fingerprint
    assert panel.label.startswith("panel(mean:")


def test_panel_tolerates_failures_down_to_min_votes():
    panel = JudgePanel([Fixed(2), Fixed(None), Fixed(2)], parallel=False)
    result = panel.judge(QUERY, PRODUCT)
    assert result.relevance == 2
    assert [v.relevance for v in result.votes] == [2, None, 2]
    strict = JudgePanel([Fixed(2), Fixed(None), Fixed(2)], min_votes=3)
    with pytest.raises(JudgeError, match="2 of 3 required votes"):
        strict.judge(QUERY, PRODUCT)


def test_panel_validation_and_close():
    with pytest.raises(ConfigError):
        JudgePanel([Fixed(1)])
    with pytest.raises(ConfigError):
        JudgePanel([Fixed(1), Fixed(2)], aggregation="mode")
    with pytest.raises(ConfigError):
        JudgePanel([Fixed(1), Fixed(2)], min_votes=3)
    members = [Fixed(1), Fixed(2)]
    JudgePanel(members).close()
    assert all(m.closed for m in members)


def test_mock_judges_with_noise_disagree_reproducibly():
    products = [Product(f"p{i}", "Red Running Shoes") for i in range(40)]
    a, b = MockJudge(noise=0.5, seed=1), MockJudge(noise=0.5, seed=2)
    grades_a = [a.judge(QUERY, p).relevance for p in products]
    grades_b = [b.judge(QUERY, p).relevance for p in products]
    assert grades_a != grades_b
    assert grades_a == [MockJudge(noise=0.5, seed=1).judge(QUERY, p).relevance for p in products]
    assert all(g in (2, 3) for g in grades_a)  # one step at most from 3
    assert a.fingerprint != MockJudge().fingerprint
    with pytest.raises(ValueError, match="noise"):
        MockJudge(noise=2)
