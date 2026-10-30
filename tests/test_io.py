from __future__ import annotations

import json

import pytest

from llm_search_eval.errors import DatasetError
from llm_search_eval.io import (
    load_products,
    load_qrels,
    load_queries,
    load_run,
    read_records,
    write_json,
    write_run,
)
from llm_search_eval.models import Run


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def test_load_example_dataset(example_dataset):
    assert len(example_dataset.queries) == 10
    assert len(example_dataset.products) == 22
    assert example_dataset.gold_label("q01", "p06") == 3
    assert example_dataset.gold_label("q01", "p99") is None


def test_query_language_is_detected_when_missing(example_dataset):
    assert example_dataset.queries["q09"].lang == "fa"
    assert example_dataset.queries["q01"].lang == "en"


def test_queries_accept_aliases_and_csv(tmp_path):
    path = write(tmp_path / "q.csv", "QID,Query\n1,red shoes\n2,کفش قرمز\n")
    queries = load_queries(path)
    assert queries["1"].text == "red shoes"
    assert queries["2"].lang == "fa"


def test_duplicate_query_ids_rejected(tmp_path):
    path = write(
        tmp_path / "q.jsonl", '{"query_id": 1, "text": "a"}\n{"query_id": 1, "text": "b"}\n'
    )
    with pytest.raises(DatasetError, match="duplicate query id"):
        load_queries(path)


def test_invalid_jsonl_reports_line_number(tmp_path):
    path = write(tmp_path / "q.jsonl", '{"query_id": "1", "text": "a"}\n{oops}\n')
    with pytest.raises(DatasetError, match=r"q\.jsonl:2"):
        load_queries(path)


def test_missing_field_is_reported(tmp_path):
    path = write(tmp_path / "q.jsonl", '{"query_id": "1"}\n')
    with pytest.raises(DatasetError, match="missing query text"):
        load_queries(path)


def test_missing_file_and_unknown_suffix(tmp_path):
    with pytest.raises(DatasetError, match="file not found"):
        read_records(tmp_path / "nope.jsonl")
    with pytest.raises(DatasetError, match="unsupported file type"):
        read_records(write(tmp_path / "data.xml", "<x/>"))


def test_empty_queries_rejected(tmp_path):
    with pytest.raises(DatasetError, match="no queries"):
        load_queries(write(tmp_path / "q.jsonl", "\n"))


def test_json_array_and_wrapped_object(tmp_path):
    records = [{"query_id": "1", "text": "a"}]
    write(tmp_path / "a.json", json.dumps(records))
    write(tmp_path / "b.json", json.dumps({"queries": records}))
    assert load_queries(tmp_path / "a.json")["1"].text == "a"
    assert load_queries(tmp_path / "b.json")["1"].text == "a"
    with pytest.raises(DatasetError):
        load_queries(write(tmp_path / "c.json", '"text"'))


def test_products_collect_extra_columns_as_attributes(tmp_path):
    path = write(
        tmp_path / "p.csv",
        "id,name,brand,color,size\nsku1,Trail Shoe,Fleet,red,42\n",
    )
    product = load_products(path)["sku1"]
    assert product.title == "Trail Shoe"
    assert product.brand == "Fleet"
    assert product.attributes == {"color": "red", "size": "42"}
    assert "color: red" in product.to_text()


def test_products_attributes_from_json_string(tmp_path):
    path = write(
        tmp_path / "p.jsonl",
        '{"product_id": "x", "title": "T", "attributes": {"color": "blue", "tags": ["a", "b"]}}\n',
    )
    assert load_products(path)["x"].attributes == {"color": "blue", "tags": "a, b"}


def test_product_text_is_truncated():
    from llm_search_eval.models import Product

    text = Product("x", "T", description="d" * 5000).to_text(max_chars=100)
    assert len(text) == 100
    assert text.endswith("...")


def test_qrels_validation(tmp_path):
    good = write(tmp_path / "g.csv", "qid,doc_id,label\nq,p,2\nq,r,0\n")
    assert load_qrels(good) == {"q": {"p": 2, "r": 0}}
    for bad in ("4", "1.5", "high", "-1"):
        path = write(tmp_path / "b.csv", f"query_id,product_id,relevance\nq,p,{bad}\n")
        with pytest.raises(DatasetError):
            load_qrels(path)


def test_trec_qrels(tmp_path):
    path = write(tmp_path / "x.qrels", "q1 0 p1 3\nq1 0 p2 0\n\n")
    assert load_qrels(path) == {"q1": {"p1": 3, "p2": 0}}
    with pytest.raises(DatasetError, match="expected"):
        load_qrels(write(tmp_path / "bad.qrels", "q1 p1 3\n"))


def test_run_sorted_by_rank(tmp_path):
    path = write(
        tmp_path / "r.jsonl",
        '{"query_id": "q", "product_id": "b", "rank": 2}\n'
        '{"query_id": "q", "product_id": "a", "rank": 1}\n',
    )
    assert load_run(path).rankings == {"q": ["a", "b"]}
    assert load_run(path).name == "r"


def test_run_sorted_by_score_desc(tmp_path):
    path = write(tmp_path / "r.csv", "query_id,product_id,score\nq,a,0.1\nq,b,0.9\n")
    assert load_run(path, "x").rankings == {"q": ["b", "a"]}


def test_run_file_order_and_duplicates(tmp_path, caplog):
    path = write(tmp_path / "r.csv", "query_id,product_id\nq,a\nq,b\nq,a\n")
    assert load_run(path).rankings == {"q": ["a", "b"]}
    assert "duplicate product" in caplog.text


def test_run_results_list_layout(tmp_path):
    path = write(
        tmp_path / "r.jsonl",
        '{"query_id": "q", "results": ["c", {"product_id": "a"}]}\n',
    )
    assert load_run(path).rankings == {"q": ["c", "a"]}
    csv_path = write(tmp_path / "r.csv", "query_id,results\nq,c|a|b\n")
    assert load_run(csv_path).rankings == {"q": ["c", "a", "b"]}
    bad = write(tmp_path / "bad.jsonl", '{"query_id": "q", "results": 5}\n')
    with pytest.raises(DatasetError, match="must be a list"):
        load_run(bad)


def test_trec_run(example_runs):
    hybrid = example_runs[2]
    assert hybrid.ranking("q01") == ["p06", "p16", "p07", "p05"]
    assert hybrid.ranking("q01", depth=2) == ["p06", "p16"]
    assert hybrid.ranking("missing") == []


def test_trec_run_errors(tmp_path):
    with pytest.raises(DatasetError, match="expected"):
        load_run(write(tmp_path / "x.run", "q1 Q0 p1\n"))
    with pytest.raises(DatasetError, match="not a number"):
        load_run(write(tmp_path / "y.run", "q1 Q0 p1 first 1.0 t\n"))


def test_write_json_creates_parents(tmp_path):
    target = tmp_path / "a" / "b.json"
    write_json(target, {"متن": "سلام"})
    assert "سلام" in target.read_text(encoding="utf-8")


@pytest.mark.parametrize("suffix", [".jsonl", ".trec"])
def test_write_run_round_trips(tmp_path, suffix):
    run = Run("my system", {"q1": ["a", "b"], "q2": ["c"]})
    path = write_run(tmp_path / f"out{suffix}", run)
    assert load_run(path, "x").rankings == run.rankings
