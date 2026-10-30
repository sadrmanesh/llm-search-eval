"""Pairwise judges: which of two ranked result lists serves a query better.

Graded labels say how good each product is. A pairwise judge answers the
question product teams usually ask instead: "is the new ranking better than
the old one for this query?" It looks at both top-k lists side by side, which
catches problems that per-product grades miss, such as duplicates or a weak
first result.
"""

from __future__ import annotations

import json
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from llm_search_eval.errors import ConfigError, JudgeError
from llm_search_eval.judges.base import TokenUsage
from llm_search_eval.judges.mock import MockJudge
from llm_search_eval.judges.openai_compat import DEFAULT_MODEL, OpenAICompatibleJudge
from llm_search_eval.judges.prompts import PAIRWISE_PROMPT_VERSION, build_pairwise_messages
from llm_search_eval.models import Product, Query

#: Verdict values, always from the point of view of the order shown to the judge.
FIRST, SECOND, TIE = "A", "B", "tie"


@dataclass(frozen=True, slots=True)
class PairwiseVerdict:
    """Which list won: ``"A"`` (shown first), ``"B"`` (shown second) or ``"tie"``."""

    winner: str
    reason: str = ""
    usage: TokenUsage | None = None

    def __post_init__(self) -> None:
        if self.winner not in (FIRST, SECOND, TIE):
            raise ValueError(f"winner must be 'A', 'B' or 'tie', not {self.winner!r}")


class PairwiseJudge(ABC):
    """Compares two ranked lists of products for one query.

    Implementations must be thread-safe; comparisons run concurrently.
    """

    name: str = "pairwise"

    @property
    def fingerprint(self) -> str:
        """Identifies the configuration; part of the verdict cache key."""
        return self.name

    @property
    def label(self) -> str:
        return self.name

    @abstractmethod
    def compare(
        self, query: Query, first: Sequence[Product], second: Sequence[Product]
    ) -> PairwiseVerdict:
        """Return the better list, from the order given."""

    def close(self) -> None:  # noqa: B027 - optional hook, intentionally empty
        """Release resources."""


PairwiseFactory = Callable[..., PairwiseJudge]
_REGISTRY: dict[str, PairwiseFactory] = {}


def register_pairwise_judge(name: str) -> Callable[[PairwiseFactory], PairwiseFactory]:
    def decorator(factory: PairwiseFactory) -> PairwiseFactory:
        _REGISTRY[name] = factory
        return factory

    return decorator


def available_pairwise_judges() -> list[str]:
    return sorted(_REGISTRY)


def create_pairwise_judge(spec: str, **options: Any) -> PairwiseJudge:
    """Instantiate a pairwise judge by registry name or ``module:Class`` path."""
    import importlib

    options = {k: v for k, v in options.items() if v is not None}
    if spec in _REGISTRY:
        factory = _REGISTRY[spec]
    elif ":" in spec:
        module_name, _, attr = spec.partition(":")
        try:
            factory = getattr(importlib.import_module(module_name), attr)
        except (ImportError, AttributeError) as exc:
            raise ConfigError(f"cannot load pairwise judge {spec!r}: {exc}") from exc
    else:
        known = ", ".join(available_pairwise_judges())
        raise ConfigError(f"unknown pairwise judge {spec!r}; available: {known}, or 'module:Class'")
    try:
        judge = factory(**options)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid options for pairwise judge {spec!r}: {exc}") from exc
    if not isinstance(judge, PairwiseJudge):
        raise ConfigError(f"{spec!r} did not produce a PairwiseJudge instance")
    return judge


_WINNERS = {
    "a": FIRST,
    "1": FIRST,
    "first": FIRST,
    "b": SECOND,
    "2": SECOND,
    "second": SECOND,
    "tie": TIE,
    "draw": TIE,
    "equal": TIE,
    "both": TIE,
    "neither": TIE,
    "none": TIE,
}
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_pairwise(content: str) -> PairwiseVerdict:
    """Read a verdict from a model reply: JSON (possibly wrapped) or a bare A, B or tie."""
    bare = _WINNERS.get(content.strip().strip(".\"'").lower())
    if bare:
        return PairwiseVerdict(bare)
    match = _JSON_OBJECT.search(content)
    if not match:
        raise JudgeError(f"pairwise reply contains no JSON object: {content[:200]!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeError(f"pairwise reply is not valid JSON: {content[:200]!r}") from exc
    raw = data.get("winner", data.get("preference", data.get("better")))
    winner = _WINNERS.get(str(raw).strip().lower()) if raw is not None else None
    if winner is None:
        raise JudgeError(f"pairwise reply has no valid winner: {content[:200]!r}")
    return PairwiseVerdict(winner, str(data.get("reason", "")).strip())


def _dcg(grades: Sequence[int]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


@register_pairwise_judge("mock")
class MockPairwiseJudge(PairwiseJudge):
    """Offline pairwise judge: compares the DCG of the mock judge's grades.

    Deterministic and free, for tests, CI dry runs and trying out the report.
    ``margin`` is the relative DCG difference below which the lists tie.
    """

    name = "mock"

    def __init__(self, margin: float = 0.05, include_description: bool = False) -> None:
        if not 0.0 <= margin < 1.0:
            raise ValueError("margin must be between 0 and 1")
        self.margin = float(margin)
        self._grader = MockJudge(include_description=include_description)

    @property
    def fingerprint(self) -> str:
        return f"pairwise-mock:margin={self.margin:g}:{self._grader.fingerprint}"

    @property
    def label(self) -> str:
        return "mock"

    def compare(
        self, query: Query, first: Sequence[Product], second: Sequence[Product]
    ) -> PairwiseVerdict:
        a = _dcg([self._grader.judge(query, p).relevance for p in first])
        b = _dcg([self._grader.judge(query, p).relevance for p in second])
        scale = max(a, b)
        if scale == 0 or abs(a - b) <= self.margin * scale:
            return PairwiseVerdict(TIE, f"similar DCG ({a:.2f} vs {b:.2f})")
        winner = FIRST if a > b else SECOND
        return PairwiseVerdict(winner, f"DCG {a:.2f} vs {b:.2f}")


@register_pairwise_judge("openai")
class OpenAIPairwiseJudge(PairwiseJudge):
    """LLM pairwise judge over any OpenAI-compatible chat completions endpoint.

    Accepts the same connection options as the ``openai`` relevance judge.
    """

    name = "openai"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        max_product_chars: int = 400,
        client: OpenAICompatibleJudge | None = None,
        **options: Any,
    ) -> None:
        self._client = client or OpenAICompatibleJudge(model=model, **options)
        self.max_product_chars = max_product_chars

    @property
    def model(self) -> str:
        return self._client.model

    @property
    def fingerprint(self) -> str:
        c = self._client
        return f"pairwise-openai:{c.base_url}:{c.model}:t={c.temperature}:{PAIRWISE_PROMPT_VERSION}"

    @property
    def label(self) -> str:
        return f"openai:{self._client.model}"

    def compare(
        self, query: Query, first: Sequence[Product], second: Sequence[Product]
    ) -> PairwiseVerdict:
        messages = build_pairwise_messages(query, first, second, self.max_product_chars)
        content, usage = self._client.complete(messages, what=f"pairwise {query.query_id}")
        verdict = parse_pairwise(content)
        return PairwiseVerdict(verdict.winner, verdict.reason, usage)

    def close(self) -> None:
        self._client.close()
