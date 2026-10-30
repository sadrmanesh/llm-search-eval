from __future__ import annotations

import json
import subprocess
import sys

import pytest

from llm_search_eval import __version__
from llm_search_eval.cli import EXIT_GATE_FAILED, EXIT_JUDGE_FAILURES, EXIT_USAGE, main


@pytest.fixture
def base_args(example_dir):
    return [
        "--queries", str(example_dir / "queries.jsonl"),
        "--products", str(example_dir / "products.jsonl"),
        "--qrels", str(example_dir / "qrels.csv"),
        "--system", f"bm25={example_dir / 'runs' / 'bm25.jsonl'}",
        "--system", f"semantic={example_dir / 'runs' / 'semantic.csv'}",
        "--system", str(example_dir / "runs" / "hybrid.trec"),
    ]  # fmt: skip


def test_run_with_mock_judge(tmp_path, base_args, capsys):
    out = tmp_path / "reports"
    code = main(["run", *base_args, "--judge", "mock", "-o", str(out), "--permutations", "500"])
    assert code == 0
    stdout = capsys.readouterr().out
    assert "| `hybrid` |" in stdout
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert [s["name"] for s in data["systems"]] == ["bm25", "semantic", "hybrid"]
    assert data["config"]["permutations"] == 500
    assert (out / "report.md").is_file()
    assert (out / "judgments.jsonl").is_file()


def test_run_options(tmp_path, base_args):
    out = tmp_path / "r"
    code = main(
        [
            "run", *base_args, "--metrics", "ndcg@3,mrr", "--primary", "mrr",
            "--baseline", "semantic", "--threshold", "3", "--gain", "linear",
            "--format", "json", "--quiet", "-o", str(out),
        ]
    )  # fmt: skip
    assert code == 0
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["config"]["metrics"] == ["ndcg@3", "mrr"]
    assert data["config"]["baseline"] == "semantic"
    assert data["config"]["depth"] == 3
    assert not (out / "report.md").exists()


def test_run_with_judge_cache(tmp_path, base_args):
    cache = tmp_path / "cache.jsonl"
    args = ["run", *base_args, "--judge", "mock", "--cache", str(cache), "--quiet"]
    assert main([*args, "-o", str(tmp_path / "a")]) == 0
    assert cache.is_file()
    assert main([*args, "-o", str(tmp_path / "b")]) == 0
    data = json.loads((tmp_path / "b" / "report.json").read_text(encoding="utf-8"))
    assert data["labels"]["judged"] == 0
    assert data["labels"]["cached"] > 0


def test_run_without_labels_warns(tmp_path, example_dir, capsys):
    code = main(
        [
            "run", "-q", str(example_dir / "queries.jsonl"),
            "-p", str(example_dir / "products.jsonl"),
            "-s", f"x={example_dir / 'runs' / 'bm25.jsonl'}", "-o", str(tmp_path), "--quiet",
        ]
    )  # fmt: skip
    assert code == 0
    assert "every result will count as not relevant" in capsys.readouterr().err


def test_run_reports_judge_failures(tmp_path, base_args):
    code = main(
        ["run", *base_args, "--judge", "tests.test_evaluate:FailingJudge", "-o", str(tmp_path),
         "--quiet"]
    )  # fmt: skip
    assert code == EXIT_JUDGE_FAILURES


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--judge", "nope"], "unknown judge"),
        (["--metrics", "ndcg"], "needs a cutoff"),
        (["--format", "pdf"], "unknown report format"),
        (["--baseline", "zzz"], "baseline"),
    ],
)
def test_run_usage_errors(tmp_path, base_args, capsys, extra, message):
    code = main(["run", *base_args, *extra, "-o", str(tmp_path), "--quiet"])
    assert code == EXIT_USAGE
    assert message in capsys.readouterr().err


def test_run_requires_a_system(example_dir, capsys):
    code = main(
        ["run", "-q", str(example_dir / "queries.jsonl"), "-p", str(example_dir / "products.jsonl")]
    )
    assert code == EXIT_USAGE
    assert "--system" in capsys.readouterr().err


def test_openai_judge_without_key_is_a_usage_error(tmp_path, base_args, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    code = main(["run", *base_args, "--judge", "openai", "-o", str(tmp_path)])
    assert code == EXIT_USAGE
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_missing_input_file(tmp_path, capsys):
    code = main(["validate", "-q", str(tmp_path / "x.jsonl"), "-p", str(tmp_path / "y.jsonl")])
    assert code == EXIT_USAGE
    assert "file not found" in capsys.readouterr().err


def test_bad_system_argument(example_dir):
    with pytest.raises(SystemExit):
        main(["run", "-q", "q", "-p", "p", "-s", "=path"])


def test_validate_reports_warnings(example_dir, capsys):
    code = main(
        [
            "validate", "-q", str(example_dir / "queries.jsonl"),
            "-p", str(example_dir / "products.jsonl"), "--qrels", str(example_dir / "qrels.csv"),
            "-s", f"bm25={example_dir / 'runs' / 'bm25.jsonl'}",
        ]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0
    assert "10 queries" in out
    assert "bm25: no results for 1 query(ies)" in out


def test_validate_flags_inconsistencies(tmp_path, capsys):
    (tmp_path / "q.csv").write_text("query_id,text\nq1,shoes\n", encoding="utf-8")
    (tmp_path / "p.csv").write_text("product_id,title\na,Shoe\n", encoding="utf-8")
    (tmp_path / "l.csv").write_text(
        "query_id,product_id,relevance\nq1,a,1\nq9,zz,0\n", encoding="utf-8"
    )
    (tmp_path / "r.csv").write_text("query_id,product_id\nq1,ghost\nq7,a\n", encoding="utf-8")
    main(
        [
            "validate", "-q", str(tmp_path / "q.csv"), "-p", str(tmp_path / "p.csv"),
            "--qrels", str(tmp_path / "l.csv"), "-s", str(tmp_path / "r.csv"),
        ]
    )  # fmt: skip
    out = capsys.readouterr().out
    assert "unknown query id 'q9'" in out
    assert "unknown product 'zz'" in out
    assert "labels look binary" in out
    assert "1 unknown product(s) for query q1" in out
    assert "unknown query id 'q7'" in out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_module_entry_point():
    result = subprocess.run(
        [sys.executable, "-m", "llm_search_eval", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "run" in result.stdout
    assert "validate" in result.stdout


# Panels, cost, report, gate and fetch ---------------------------------------------


def test_run_with_panel_prices_and_budget(tmp_path, base_args, capsys):
    out = tmp_path / "panel"
    code = main(
        ["run", *base_args,
         "--judge", "mock=noise=0.3,seed=1", "--judge", "mock=noise=0.3,seed=2",
         "--judge", "mock=noise=0.3,seed=3", "--aggregate", "median", "--min-votes", "3",
         "--calibrate", "--calibration-sample", "5", "--price", "gpt-4o-mini=0.15,0.6",
         "--max-judgments", "1000", "--permutations", "100", "-o", str(out)]
    )  # fmt: skip
    assert code == 0
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["judging"]["panel"]["aggregation"] == "median"
    assert data["judging"]["panel"]["min_votes"] == 3
    assert data["labels"]["calibration"] == 5
    assert data["cost"]["prices"]["gpt-4o-mini"]["input_per_million"] == 0.15
    assert data["cost"]["budget"]["max_judgments"] == 1000
    assert {p.name for p in out.iterdir()} == {
        "report.md", "report.json", "report.html", "cost.json", "judgments.jsonl"
    }  # fmt: skip
    record = json.loads((out / "judgments.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert len(record["votes"]) == 3
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "### Inter-judge agreement" in md
    assert "### Agreement with gold labels" in md
    assert "judge requests: 0" in capsys.readouterr().err


def test_run_budget_warning(tmp_path, base_args, capsys):
    code = main(
        ["run", *base_args, "--judge", "mock", "--max-judgments", "3", "--concurrency", "1",
         "--format", "json", "-o", str(tmp_path), "--quiet"]
    )  # fmt: skip
    assert code == 0
    assert "pair(s) were not judged" in capsys.readouterr().err
    cost = json.loads((tmp_path / "cost.json").read_text(encoding="utf-8"))
    assert cost["budget"]["exhausted"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--judge", "mock=noise"], "invalid options for judge"),
        (["--judge", "mock=bad-key=1"], "invalid judge option"),
        (["--calibrate"], "needs at least one --judge"),
        (["--price", "m=1"], "invalid price"),
        (
            ["--judge", "mock", "--judge", "mock", "--aggregate", "mean", "--min-votes", "5"],
            "votes",
        ),
    ],
)
def test_run_judge_option_errors(tmp_path, base_args, capsys, extra, message):
    code = main(["run", *base_args, *extra, "-o", str(tmp_path), "--quiet"])
    assert code == EXIT_USAGE
    assert message in capsys.readouterr().err


@pytest.fixture
def saved_report(tmp_path, base_args):
    out = tmp_path / "saved"
    assert main(["run", *base_args, "--permutations", "200", "-o", str(out), "--quiet"]) == 0
    return out / "report.json"


def test_report_command_rerenders(tmp_path, saved_report):
    target = tmp_path / "rendered"
    assert main(["report", str(saved_report), "-o", str(target), "--format", "md,html"]) == 0
    assert (target / "report.html").read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert "## Summary" in (target / "report.md").read_text(encoding="utf-8")
    assert main(["report", str(saved_report), "--format", "json"]) == EXIT_USAGE


def test_gate_command(tmp_path, saved_report, capsys):
    summary = tmp_path / "summary.md"
    result_json = tmp_path / "gate.json"
    code = main(
        ["gate", str(saved_report), "--min", "ndcg@10=0.5", "--max-drop", "0.5",
         "--summary", str(summary), "--json", str(result_json)]
    )  # fmt: skip
    assert code == 0
    assert "Search quality gate: passed" in capsys.readouterr().out
    assert "passed" in summary.read_text(encoding="utf-8")
    assert json.loads(result_json.read_text(encoding="utf-8"))["passed"] is True
    code = main(["gate", str(saved_report), "--min", "ndcg@10=0.99", "--system", "bm25"])
    assert code == EXIT_GATE_FAILED
    code = main(["gate", str(saved_report), "--reference", str(saved_report), "--max-drop", "0"])
    assert code == 0


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "set at least one"),
        (["--min", "ndcg@10"], "METRIC=VALUE"),
        (["--min", "ndcg@7=0.1"], "not in the report"),
    ],
)
def test_gate_usage_errors(saved_report, capsys, args, message):
    with_report = ["gate", str(saved_report), *args]
    if message == "METRIC=VALUE":
        with pytest.raises(SystemExit):
            main(with_report)
    else:
        assert main(with_report) == EXIT_USAGE
    assert message in capsys.readouterr().err


def test_fetch_command(tmp_path, example_dir, monkeypatch, capsys):
    from llm_search_eval.connectors import ElasticsearchConnector

    def fake_search(self, query, k):
        assert self.index == "products"
        assert self.fields == ["title^2", "brand"]
        return [f"{query.query_id}-a", f"{query.query_id}-b"][:k]

    monkeypatch.setattr(ElasticsearchConnector, "search", fake_search)
    output = tmp_path / "live.jsonl"
    code = main(
        ["fetch", "-q", str(example_dir / "queries.jsonl"), "--backend", "elasticsearch",
         "--url", "http://localhost:9200", "--index", "products", "--fields", "title^2,brand",
         "-k", "1", "-o", str(output)]
    )  # fmt: skip
    assert code == 0
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["results"] == [f"{rows[0]['query_id']}-a"]
    assert "from elasticsearch" in capsys.readouterr().err


def test_fetch_reports_failures_and_bad_options(tmp_path, example_dir, monkeypatch, capsys):
    from llm_search_eval.connectors import AlgoliaConnector
    from llm_search_eval.errors import ConnectorError

    def failing(self, query, k):
        raise ConnectorError("HTTP 403")

    monkeypatch.setattr(AlgoliaConnector, "search", failing)
    monkeypatch.setenv("ALGOLIA_API_KEY", "key")
    base = ["fetch", "-q", str(example_dir / "queries.jsonl"), "--backend", "algolia",
            "--app-id", "APP", "--index", "products", "-o", str(tmp_path / "a.jsonl")]  # fmt: skip
    assert main(base) == EXIT_JUDGE_FAILURES
    assert "HTTP 403" in capsys.readouterr().err
    assert main([*base, "--params", "[1]"]) == EXIT_USAGE
    assert "must be a JSON object" in capsys.readouterr().err
    template = tmp_path / "missing.json"
    code = main(
        ["fetch", "-q", str(example_dir / "queries.jsonl"), "--backend", "opensearch",
         "--url", "http://os", "--index", "p", "--template", str(template), "-o",
         str(tmp_path / "o.jsonl")]
    )  # fmt: skip
    assert code == EXIT_USAGE
