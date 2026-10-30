from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from llm_search_eval import EvaluationConfig, evaluate
from llm_search_eval.html_report import render_html, write_html
from llm_search_eval.judges import MockJudge
from llm_search_eval.judges.panel import JudgePanel
from llm_search_eval.models import Run

ELEMENT_IDS = [
    "overview-cards",
    "summary-table",
    "metric-select",
    "metric-chart",
    "comparison-table",
    "compare-select",
    "delta-chart",
    "language-table",
    "label-chart",
    "judging-info",
    "gold-info",
    "cost-table",
    "query-filter",
    "query-table",
    "query-detail",
]


@pytest.fixture
def report(example_dataset, example_runs):
    panel = JudgePanel([MockJudge(noise=0.3, seed=1), MockJudge(noise=0.3, seed=2)])
    config = EvaluationConfig(permutations=200, calibrate=True, title="Shop <search> & co")
    return evaluate(example_dataset, example_runs, config, judge=panel)


def _embedded(html: str) -> dict:
    match = re.search(
        r'<script type="application/json" id="report-data">(.*?)</script>', html, re.S
    )
    assert match
    return json.loads(match.group(1))


def test_dashboard_is_self_contained(report):
    html = render_html(report)
    assert html.startswith("<!DOCTYPE html>")
    assert not re.search(r"(src|href)=\"(https?:)?//", html)
    assert "<link" not in html
    for element_id in ELEMENT_IDS:
        assert f'id="{element_id}"' in html
    assert "<title>Shop &lt;search&gt; &amp; co</title>" in html


def test_embedded_data_round_trips_and_cannot_close_the_script(report):
    data = report.to_dict()
    data["title"] = "</script><script>alert(1)</script>"
    html = render_html(data)
    assert html.count("</script>") == 2  # the data block and the dashboard script
    embedded = _embedded(html)
    assert embedded["title"] == data["title"]
    assert embedded["judging"]["agreement"]["raters"]
    assert set(embedded["details"]["rankings"]) == {"bm25", "semantic", "hybrid"}


def test_write_html(tmp_path, report):
    path = write_html(report, tmp_path / "nested" / "report.html")
    assert path.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_dashboard_script_parses(tmp_path, report):
    html = render_html(report)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    assert len(scripts) == 1
    path = tmp_path / "dashboard.js"
    path.write_text(scripts[0], encoding="utf-8")
    subprocess.run(["node", "--check", str(path)], check=True)


def test_dashboard_renders_without_judge_or_details(tiny_dataset):
    config = EvaluationConfig(include_details=False)
    report = evaluate(tiny_dataset, [Run("s", {"q1": ["a"]})], config)
    data = _embedded(render_html(report))
    assert "details" not in data
    assert data["judging"] is None


def test_dashboard_has_interval_pairwise_and_strata_views(example_dataset, example_runs):
    from llm_search_eval import EvaluationConfig, evaluate
    from llm_search_eval.html_report import render_html
    from llm_search_eval.judges.pairwise import MockPairwiseJudge

    report = evaluate(
        example_dataset,
        example_runs,
        EvaluationConfig(permutations=50, bootstrap=100),
        pairwise_judge=MockPairwiseJudge(),
    )
    page = render_html(report)
    for marker in ('id="pairwise"', 'id="strata"', 'id="summary-note"', "renderPairwise", "ci_low"):
        assert marker in page
