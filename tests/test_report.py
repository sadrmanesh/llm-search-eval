from __future__ import annotations

import json

from llm_search_eval import EvaluationConfig, evaluate
from llm_search_eval.judges import MockJudge
from llm_search_eval.models import Run
from llm_search_eval.report import render_markdown, write_reports


def test_markdown_sections(example_dataset, example_runs):
    report = evaluate(example_dataset, example_runs, judge=MockJudge())
    md = render_markdown(report)
    for heading in (
        "# Search evaluation report",
        "## Summary",
        "## Comparison against `bm25`",
        "### All metric deltas",
        "## `ndcg@10` by query language",
        "## Label coverage",
    ):
        assert heading in md
    assert "| `semantic` |" in md
    assert "**" in md  # best values highlighted
    assert md == render_markdown(report.to_dict())


def test_single_system_report_has_no_comparison(tiny_dataset):
    report = evaluate(tiny_dataset, [Run("only", {"q1": ["a"], "q2": ["d"]})])
    md = render_markdown(report)
    assert "## Comparison" not in md
    assert "**" not in md.split("## Summary")[1].split("##")[0]


def test_unlabeled_warning_and_escaping(tiny_dataset):
    report = evaluate(
        tiny_dataset,
        [Run("a|b", {"q1": ["c"]})],
        EvaluationConfig(title="Weekly | check"),
    )
    md = render_markdown(report)
    assert "`a\\|b`" in md
    assert "Unlabeled results are treated as not relevant" in md


def test_write_reports(tmp_path, example_dataset, example_runs):
    report = evaluate(example_dataset, example_runs, judge=MockJudge())
    written = write_reports(report, tmp_path / "out")
    names = sorted(p.name for p in written)
    assert names == ["judgments.jsonl", "report.json", "report.md"]
    data = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert data["tool"]["name"] == "llm-search-eval"
    assert data["systems"][0]["name"] == "bm25"
    lines = (tmp_path / "out" / "judgments.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(report.judgments)
    assert json.loads(lines[0])["source"] == "judge"


def test_write_reports_respects_formats(tmp_path, tiny_dataset):
    report = evaluate(tiny_dataset, [Run("s", {"q1": ["a"]})])
    written = write_reports(report, tmp_path, formats=["json"])
    assert [p.name for p in written] == ["report.json"]
