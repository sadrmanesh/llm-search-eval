from __future__ import annotations

from pathlib import Path

import pytest

from llm_search_eval.io import load_dataset, load_run
from llm_search_eval.models import Dataset, Product, Query, Run

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "electronics"


@pytest.fixture
def example_dir() -> Path:
    return EXAMPLES


@pytest.fixture
def example_dataset() -> Dataset:
    return load_dataset(
        EXAMPLES / "queries.jsonl", EXAMPLES / "products.jsonl", EXAMPLES / "qrels.csv"
    )


@pytest.fixture
def example_runs() -> list[Run]:
    return [
        load_run(EXAMPLES / "runs" / "bm25.jsonl", "bm25"),
        load_run(EXAMPLES / "runs" / "semantic.csv", "semantic"),
        load_run(EXAMPLES / "runs" / "hybrid.trec", "hybrid"),
    ]


@pytest.fixture
def tiny_dataset() -> Dataset:
    queries = {
        "q1": Query("q1", "red running shoes", "en"),
        "q2": Query("q2", "کفش ورزشی قرمز", "fa"),
    }
    products = {
        "a": Product("a", "Red Running Shoes", brand="Fleet", category="Shoes"),
        "b": Product("b", "Blue Running Shoes", category="Shoes"),
        "c": Product("c", "Coffee Mug"),
        "d": Product("d", "كفش ورزشي قرمز", category="کفش"),
    }
    qrels = {"q1": {"a": 3, "b": 1}, "q2": {"d": 3}}
    return Dataset(queries=queries, products=products, qrels=qrels)
