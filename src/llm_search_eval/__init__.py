"""Evaluate product search and recommendation quality with LLM judges and IR metrics."""

from llm_search_eval.evaluate import EvaluationConfig, EvaluationReport, evaluate
from llm_search_eval.judges import Judge, Judgment, create_judge, register_judge
from llm_search_eval.models import Dataset, Product, Query, Run

__version__ = "0.1.0"

__all__ = [
    "Dataset",
    "EvaluationConfig",
    "EvaluationReport",
    "Judge",
    "Judgment",
    "Product",
    "Query",
    "Run",
    "__version__",
    "create_judge",
    "evaluate",
    "register_judge",
]
