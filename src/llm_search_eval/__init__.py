"""Evaluate product search quality with IR metrics, LLM judges, and CI quality gates."""

from llm_search_eval.evaluate import EvaluationConfig, EvaluationReport, evaluate
from llm_search_eval.gate import GateResult, check_report
from llm_search_eval.html_report import render_html
from llm_search_eval.judges import Judge, Judgment, create_judge, register_judge
from llm_search_eval.judges.pairwise import (
    PairwiseJudge,
    PairwiseVerdict,
    create_pairwise_judge,
    register_pairwise_judge,
)
from llm_search_eval.judges.panel import JudgePanel
from llm_search_eval.models import Dataset, Product, Query, Run
from llm_search_eval.pairwise import compare_pair
from llm_search_eval.sampling import sample_queries
from llm_search_eval.stats import Interval, bootstrap_ci, paired_bootstrap_ci
from llm_search_eval.usage import Budget, CostTracker, PriceTable

__version__ = "0.3.2"

__all__ = [
    "Budget",
    "CostTracker",
    "Dataset",
    "EvaluationConfig",
    "EvaluationReport",
    "GateResult",
    "Interval",
    "Judge",
    "JudgePanel",
    "Judgment",
    "PairwiseJudge",
    "PairwiseVerdict",
    "PriceTable",
    "Product",
    "Query",
    "Run",
    "__version__",
    "bootstrap_ci",
    "check_report",
    "compare_pair",
    "create_judge",
    "create_pairwise_judge",
    "evaluate",
    "paired_bootstrap_ci",
    "register_judge",
    "register_pairwise_judge",
    "render_html",
    "sample_queries",
]
