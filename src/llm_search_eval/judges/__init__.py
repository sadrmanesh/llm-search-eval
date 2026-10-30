"""Relevance judges. Importing this package registers the built-in judges."""

from llm_search_eval.judges.base import (
    Judge,
    Judgment,
    available_judges,
    create_judge,
    register_judge,
)
from llm_search_eval.judges.cache import JudgmentCache
from llm_search_eval.judges.mock import MockJudge
from llm_search_eval.judges.openai_compat import OpenAICompatibleJudge, parse_judgment

__all__ = [
    "Judge",
    "Judgment",
    "JudgmentCache",
    "MockJudge",
    "OpenAICompatibleJudge",
    "available_judges",
    "create_judge",
    "parse_judgment",
    "register_judge",
]
