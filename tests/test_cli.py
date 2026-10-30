from __future__ import annotations

import json
import subprocess
import sys

import pytest

from llm_search_eval import __version__
from llm_search_eval.cli import EXIT_JUDGE_FAILURES, EXIT_USAGE, main


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
        (["--format", "html"], "unknown report format"),
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
