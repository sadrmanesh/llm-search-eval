import json

import pytest

from llm_search_eval import EvaluationConfig, evaluate
from llm_search_eval.cli import main
from llm_search_eval.errors import ConfigError
from llm_search_eval.io import load_queries, write_queries
from llm_search_eval.models import Dataset, Product, Query, Run
from llm_search_eval.report import render_markdown
from llm_search_eval.sampling import (
    MISSING_STRATUM,
    allocate,
    query_stratum,
    resolve_size,
    sample_queries,
)


def _queries(n: int = 100) -> dict[str, Query]:
    out = {}
    for i in range(n):
        segment = "head" if i < 70 else "torso" if i < 95 else "tail"
        out[f"q{i}"] = Query(f"q{i}", f"phone {i}", "en" if i % 4 else "fa", {"segment": segment})
    return out


def test_resolve_size():
    assert resolve_size(None, 50) == 50
    assert resolve_size(10, 50) == 10
    assert resolve_size(500, 50) == 50
    assert resolve_size(0.1, 50) == 5
    assert resolve_size(1.0, 50) == 50
    assert resolve_size(0.001, 50) == 1
    for bad in (0, -3, 2.5, True):
        with pytest.raises(ConfigError, match="sample size"):
            resolve_size(bad, 50)


def test_allocate_is_proportional_with_a_minimum():
    sizes = {"head": 70, "torso": 25, "tail": 5}
    assert allocate(sizes, 20) == {"head": 14, "torso": 5, "tail": 1}
    alloc = allocate(sizes, 10, minimum=2)
    assert sum(alloc.values()) == 10
    assert alloc["tail"] == 2
    assert alloc["torso"] >= 2
    assert allocate(sizes, 200) == sizes
    assert sum(allocate({"a": 1, "b": 1, "c": 1}, 2).values()) == 2


def test_simple_sample_is_reproducible_and_keeps_order():
    queries = _queries()
    first = sample_queries(queries, 10, seed=4)
    assert first.queries == sample_queries(queries, 10, seed=4).queries
    assert len(first.queries) == 10
    assert list(first.queries) == [q for q in queries if q in first.queries]
    assert first.queries != sample_queries(queries, 10, seed=5).queries
    assert first.strata == {}


def test_stratified_sample_covers_small_groups():
    result = sample_queries(_queries(), 10, stratify_by="segment", min_per_stratum=2)
    assert len(result.queries) == 10
    counts = {name: s["sampled"] for name, s in result.strata.items()}
    assert counts == {"head": 6, "tail": 2, "torso": 2}
    segments = [q.attributes["segment"] for q in result.queries.values()]
    assert segments.count("tail") == 2
    assert result.to_dict()["stratify_by"] == "segment"


def test_query_stratum():
    query = Query("q", "text", None, {"segment": "head"})
    assert query_stratum(query, "lang") == "und"
    assert query_stratum(query, "segment") == "head"
    assert query_stratum(query, "missing") == MISSING_STRATUM


def test_queries_keep_extra_fields(tmp_path):
    path = tmp_path / "q.jsonl"
    path.write_text(
        json.dumps({"query_id": "a", "text": "گوشی سامسونگ", "segment": "head", "traffic": 12})
        + "\n",
        encoding="utf-8",
    )
    queries = load_queries(path)
    assert queries["a"].attributes == {"segment": "head", "traffic": "12"}
    out = write_queries(tmp_path / "out.jsonl", queries)
    assert load_queries(out)["a"] == queries["a"]
    assert load_queries(out)["a"].attributes["segment"] == "head"


def _dataset() -> Dataset:
    segments = ("head", "torso", "tail")
    queries = {
        f"q{i}": Query(f"q{i}", f"phone {i}", "en", {"segment": segments[i % 3]}) for i in range(40)
    }
    products = {"p1": Product("p1", "phone"), "p2": Product("p2", "case")}
    qrels = {qid: {"p1": 3, "p2": 0} for qid in queries}
    return Dataset(queries, products, qrels)


def test_evaluate_with_sampling_and_breakdown():
    dataset = _dataset()
    run = Run("a", {qid: ["p1" if i % 2 else "p2", "p2"] for i, qid in enumerate(dataset.queries)})
    config = EvaluationConfig(sample_size=0.5, stratify_by="segment", bootstrap=0)
    report = evaluate(dataset, [run], config)
    data = report.to_dict()
    assert data["dataset"]["queries"] == 20
    assert data["dataset"]["population"] == 40
    assert data["dataset"]["gold_labels"] == 40
    assert data["dataset"]["sampling"]["sampled"] == 20
    assert set(data["by_stratum"]["systems"]["a"]) == {"head", "torso", "tail"}
    text = render_markdown(report)
    assert "**Sample:** 20 of 40 queries" in text
    assert "by `segment`" in text


def test_breakdown_without_sampling_and_no_duplicate_language_table():
    dataset = _dataset()
    run = Run("a", {qid: ["p1"] for qid in dataset.queries})
    data = evaluate(dataset, [run], EvaluationConfig(stratify_by="segment", bootstrap=0)).data
    assert data["dataset"]["sampling"] is None
    assert data["by_stratum"]["field"] == "segment"
    lang = evaluate(dataset, [run], EvaluationConfig(sample_size=10, stratify_by="lang")).data
    assert lang["by_stratum"] is None
    assert lang["dataset"]["queries"] == 10


def test_sample_command(tmp_path, capsys):
    source = tmp_path / "q.jsonl"
    write_queries(source, _queries())
    out = tmp_path / "s.jsonl"
    code = main(
        ["sample", "-q", str(source), "-o", str(out), "--sample", "20%", "--stratify", "segment"]
    )
    assert code == 0
    assert len(load_queries(out)) == 20
    assert "tail" in capsys.readouterr().err
    assert main(["sample", "-q", str(source), "-o", str(out)]) == 2


@pytest.mark.parametrize("value", ["0", "-1", "1.5", "abc", "150%"])
def test_sample_flag_rejects_bad_values(value, tmp_path):
    with pytest.raises(SystemExit):
        main(["sample", "-q", "q.jsonl", "-o", str(tmp_path / "x"), "--sample", value])
