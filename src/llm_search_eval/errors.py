"""Exception hierarchy used across the package."""

from __future__ import annotations


class LLMSearchEvalError(Exception):
    """Base class for all errors raised by llm-search-eval."""


class DatasetError(LLMSearchEvalError):
    """Raised when an input file is missing, malformed, or inconsistent."""


class JudgeError(LLMSearchEvalError):
    """Raised when a relevance judge cannot produce a valid judgment."""


class ConfigError(LLMSearchEvalError):
    """Raised for invalid evaluation settings, such as an unknown metric."""
