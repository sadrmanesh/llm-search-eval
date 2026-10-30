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
class Judgment:
    """A graded relevance decision for one (query, product) pair."""

    relevance: int
    reason: str = ""


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

    @abstractmethod
    def judge(self, query: Query, product: Product) -> Judgment:
        """Grade ``product`` for ``query``."""

    def close(self) -> None:  # noqa: B027 - optional hook, intentionally empty
        """Release resources such as HTTP sessions."""


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
    except TypeError as exc:
        raise ConfigError(f"invalid options for judge {spec!r}: {exc}") from exc
    if not isinstance(judge, Judge):
        raise ConfigError(f"{spec!r} did not produce a Judge instance")
    return judge
