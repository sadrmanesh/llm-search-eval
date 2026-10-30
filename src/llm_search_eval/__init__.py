"""Evaluate product search quality with IR metrics, LLM judges, and CI quality gates."""

from llm_search_eval.evaluate import EvaluationConfig, EvaluationReport, evaluate
from llm_search_eval.gate import GateResult, check_report
from llm_search_eval.html_report import render_html
from llm_search_eval.judges import Judge, Judgment, create_judge, register_judge
from llm_search_eval.judges.panel import JudgePanel
from llm_search_eval.models import Dataset, Product, Query, Run
from llm_search_eval.usage import Budget, CostTracker, PriceTable

__version__ = "0.2.0"

__all__ = [
    "Budget",
    "CostTracker",
    "Dataset",
    "EvaluationConfig",
    "EvaluationReport",
    "GateResult",
    "Judge",
    "JudgePanel",
    "Judgment",
    "PriceTable",
    "Product",
    "Query",
    "Run",
    "__version__",
    "check_report",
    "create_judge",
    "evaluate",
    "register_judge",
    "render_html",
]
