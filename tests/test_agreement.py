"""Agreement statistics, checked against scikit-learn, statsmodels and krippendorff."""

from __future__ import annotations

import pytest

from llm_search_eval.agreement import (
    cohen_kappa,
    confusion_matrix,
    fleiss_kappa,
    gold_agreement,
    inter_judge_agreement,
    krippendorff_alpha,
    pairwise_agreement,
    percent_agreement,
    within_one,
)

A = [0, 1, 2, 3, 3, 2, 1, 0, 2, 3]
B = [0, 1, 2, 2, 3, 1, 1, 0, 3, 3]
UNITS = [
    [1, 1, None],
    [2, 2, 3],
    [3, 3, 3],
    [3, 3, 3],
    [2, 2, 2],
    [1, 2, 3],
    [0, 0, 0],
    [1, 1, 2],
]


def test_cohen_kappa_matches_reference_values():
    assert cohen_kappa(A, B) == pytest.approx(0.6)
    assert cohen_kappa(A, B, weights="linear") == pytest.approx(0.758064516)
    assert cohen_kappa(A, B, weights="quadratic") == pytest.approx(0.878048780)


def test_cohen_kappa_edge_cases():
    assert cohen_kappa([], []) is None
    assert cohen_kappa([2, 2, 2], [2, 2, 2]) is None  # chance agreement is total
    assert cohen_kappa([0, 3], [3, 0]) == pytest.approx(-1.0)
    with pytest.raises(ValueError, match="equal length"):
        cohen_kappa([1, 2], [1])
    with pytest.raises(ValueError, match="unknown weights"):
        cohen_kappa([1], [1], weights="cubic")


def test_simple_agreement_and_confusion():
    assert percent_agreement(A, B) == pytest.approx(0.7)
    assert within_one(A, B) == pytest.approx(1.0)
    matrix = confusion_matrix(A, B)
    assert sum(map(sum, matrix)) == len(A)
    assert matrix[3][2] == 1  # one item rated 3 by A and 2 by B
    assert percent_agreement([], []) is None


def test_fleiss_kappa_matches_statsmodels():
    items = [[0, 0, 1], [2, 2, 2], [3, 2, 3], [1, 1, 0]]
    assert fleiss_kappa(items) == pytest.approx(0.320754717)


@pytest.mark.parametrize(
    ("level", "expected"),
    [("nominal", 0.596858639), ("ordinal", 0.763955119), ("interval", 0.805653710)],
)
def test_krippendorff_alpha_matches_reference(level, expected):
    assert krippendorff_alpha(UNITS, level) == pytest.approx(expected)


def test_krippendorff_alpha_handles_degenerate_input():
    assert krippendorff_alpha([[1, None], [None, 2]]) is None  # no pairable values
    assert krippendorff_alpha([[2, 2], [2, 2]]) is None  # no variation
    with pytest.raises(ValueError, match="unknown level"):
        krippendorff_alpha(UNITS, "ratio")


def test_inter_judge_agreement_summary():
    ratings = {
        "a": [u[0] for u in UNITS],
        "b": [u[1] for u in UNITS],
        "c": [u[2] for u in UNITS],
    }
    summary = inter_judge_agreement(ratings)
    assert summary["raters"] == ["a", "b", "c"]
    assert summary["items"] == 8
    assert summary["complete_items"] == 7
    assert summary["unanimous"] == pytest.approx(4 / 7)
    assert summary["krippendorff_alpha"]["ordinal"] == pytest.approx(0.763955119)
    assert len(summary["pairwise"]) == 3
    with pytest.raises(ValueError, match="at least two raters"):
        inter_judge_agreement({"a": [1]})
    with pytest.raises(ValueError, match="one entry per item"):
        inter_judge_agreement({"a": [1], "b": [1, 2]})


def test_pairwise_agreement_skips_missing_votes():
    (pair,) = pairwise_agreement({"x": [1, None, 3], "y": [1, 2, 3]})
    assert pair["n"] == 2
    assert pair["percent_agreement"] == pytest.approx(1.0)


def test_gold_agreement():
    result = gold_agreement(B, A, threshold=2)
    assert result["n"] == 10
    assert result["exact"] == pytest.approx(0.7)
    assert result["weighted_kappa"] == pytest.approx(0.878048780)
    assert result["mean_bias"] == pytest.approx(-0.1)
    assert result["binary_agreement"] == pytest.approx(0.9)
    assert result["confusion"]["rows"] == "gold"
