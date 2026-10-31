"""Judge interface and registry for pluggable relevance graders."""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from llm_search_eval.errors import ConfigError
from llm_search_eval.models import Product, Query


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Tokens consumed by one model request."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class Vote:
    """One panel member's label for a pair. ``relevance`` is ``None`` when it failed."""

    judge: str
    relevance: int | None
    reason: str = ""
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class Judgment:
    """A graded relevance decision for one (query, product) pair.

    ``usage`` is set by judges that call a metered model. ``votes`` is set by
    :class:`~llm_search_eval.judges.panel.JudgePanel` and holds each member's label.
    """

    relevance: int
    reason: str = ""
    usage: TokenUsage | None = None
    votes: tuple[Vote, ...] = ()

    def usages(self) -> list[TokenUsage]:
        """Every metered request behind this judgment, including panel members."""
        found = [vote.usage for vote in self.votes if vote.usage is not None]
        if not found and self.usage is not None:
            found.append(self.usage)
        return found


class Judge(ABC):
    """Assigns a graded relevance label (0 to 3) to a product for a query.

    Implementations must be safe to call from multiple threads, because the
    evaluator grades pairs concurrently.
    """

    #: Short registry name, for example ``"mock"`` or ``"openai"``.
    name: str = "judge"

    @property
    def fingerprint(self) -> str:
        """Identifies the judge configuration; part of the judgment cache key.

        Override when the output depends on settings such as model or prompt version,
        so cached labels from a different configuration are never reused.
        """
        return self.name

    @property
    def label(self) -> str:
        """Short human readable name used in reports and agreement tables."""
        return self.name

    @property
    def info(self) -> dict[str, Any]:
        """Provenance written into reports and cache entries.

        Keys: ``judge`` (the label), ``provider``, ``model``, ``prompt_version``,
        and ``prompt_hash``. Values a judge does not have are ``None``.
        """
        return judge_info(self.label)

    @abstractmethod
    def judge(self, query: Query, product: Product) -> Judgment:
        """Grade ``product`` for ``query``."""

    def close(self) -> None:  # noqa: B027 - optional hook, intentionally empty
        """Release resources such as HTTP sessions."""


def judge_info(
    label: str,
    provider: str | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
    prompt_hash: str | None = None,
) -> dict[str, Any]:
    """The provenance record shared by relevance and pairwise judges."""
    return {
        "judge": label,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "prompt_hash": prompt_hash,
    }


def endpoint_provider(base_url: str) -> str:
    """Host (and port) of an OpenAI-compatible endpoint, for example ``api.openai.com``."""
    from urllib.parse import urlsplit

    return urlsplit(base_url).netloc or base_url


JudgeFactory = Callable[..., Judge]
_REGISTRY: dict[str, JudgeFactory] = {}


def register_judge(name: str) -> Callable[[JudgeFactory], JudgeFactory]:
    """Class decorator registering a judge factory under ``name``."""

    def decorator(factory: JudgeFactory) -> JudgeFactory:
        _REGISTRY[name] = factory
        return factory

    return decorator


def available_judges() -> list[str]:
    return sorted(_REGISTRY)


def create_judge(spec: str, **options: Any) -> Judge:
    """Instantiate a judge by registry name or ``"package.module:ClassName"`` path.

    Options whose value is ``None`` are dropped so factories keep their defaults.
    """
    options = {k: v for k, v in options.items() if v is not None}
    if spec in _REGISTRY:
        factory = _REGISTRY[spec]
    elif ":" in spec:
        module_name, _, attr = spec.partition(":")
        try:
            factory = getattr(importlib.import_module(module_name), attr)
        except (ImportError, AttributeError) as exc:
            raise ConfigError(f"cannot load judge {spec!r}: {exc}") from exc
    else:
        known = ", ".join(available_judges())
        raise ConfigError(f"unknown judge {spec!r}; available: {known}, or 'module:Class'")
    try:
        judge = factory(**options)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"invalid options for judge {spec!r}: {exc}") from exc
    if not isinstance(judge, Judge):
        raise ConfigError(f"{spec!r} did not produce a Judge instance")
    return judge
