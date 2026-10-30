"""Token and cost accounting for judge requests, with optional budgets.

Prices are never guessed. Supply them per model (USD per million tokens) with
:class:`PriceTable`, a JSON file, or ``--price`` on the command line. Requests to
models without a price still count tokens, and the report shows the cost as
unknown instead of zero.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from llm_search_eval.errors import ConfigError, LLMSearchEvalError
from llm_search_eval.judges.base import TokenUsage


class BudgetExceededError(LLMSearchEvalError):
    """Raised when a new judge request would exceed the configured budget."""


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD per one million input and output tokens."""

    input_per_million: float
    output_per_million: float

    def cost(self, usage: TokenUsage) -> float:
        return (
            usage.prompt_tokens * self.input_per_million
            + usage.completion_tokens * self.output_per_million
        ) / 1_000_000


class PriceTable:
    """Maps model names to prices.

    Lookups match the exact name first, then the longest configured prefix, so a
    price for ``gpt-4o-mini`` also covers a dated snapshot such as
    ``gpt-4o-mini-2024-07-18``. Matching is case-insensitive.
    """

    def __init__(self, prices: Mapping[str, ModelPrice] | None = None) -> None:
        self._prices = {name.lower(): price for name, price in (prices or {}).items()}

    def __len__(self) -> int:
        return len(self._prices)

    def __contains__(self, model: object) -> bool:
        return isinstance(model, str) and self.get(model) is not None

    def set(self, model: str, price: ModelPrice) -> None:
        self._prices[model.lower()] = price

    def get(self, model: str) -> ModelPrice | None:
        key = model.lower()
        if key in self._prices:
            return self._prices[key]
        matches = [name for name in self._prices if key.startswith(name)]
        return self._prices[max(matches, key=len)] if matches else None

    def to_dict(self) -> dict[str, dict[str, float]]:
        return {
            name: {
                "input_per_million": p.input_per_million,
                "output_per_million": p.output_per_million,
            }
            for name, p in sorted(self._prices.items())
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PriceTable:
        """Accept ``{"model": {"input_per_million": x, "output_per_million": y}}``.

        ``{"model": [x, y]}`` and the shorter keys ``input`` and ``output`` also work.
        """
        table = cls()
        for model, raw in data.items():
            try:
                if isinstance(raw, Mapping):
                    price = ModelPrice(
                        float(raw.get("input_per_million", raw.get("input"))),
                        float(raw.get("output_per_million", raw.get("output"))),
                    )
                else:
                    first, second = raw
                    price = ModelPrice(float(first), float(second))
            except (TypeError, ValueError) as exc:
                raise ConfigError(f"invalid price for model {model!r}: {raw!r}") from exc
            if price.input_per_million < 0 or price.output_per_million < 0:
                raise ConfigError(f"price for model {model!r} must not be negative")
            table.set(str(model), price)
        return table

    @classmethod
    def from_file(cls, path: str | Path) -> PriceTable:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"cannot read price file {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"price file {path} must contain a JSON object")
        return cls.from_dict(data)

    @classmethod
    def parse_specs(cls, specs: Iterable[str], base: PriceTable | None = None) -> PriceTable:
        """Parse ``MODEL=INPUT,OUTPUT`` strings (USD per million tokens)."""
        table = base or cls()
        for spec in specs:
            model, sep, prices = spec.partition("=")
            parts = [p.strip() for p in prices.replace(":", ",").split(",")]
            if not sep or not model.strip() or len(parts) != 2:
                raise ConfigError(f"invalid price {spec!r}; expected MODEL=INPUT,OUTPUT")
            parsed = cls.from_dict({model.strip(): parts}).get(model.strip())
            assert parsed is not None
            table.set(model.strip(), parsed)
        return table


@dataclass(frozen=True, slots=True)
class Budget:
    """Upper limits for one evaluation. ``None`` means unlimited."""

    max_cost_usd: float | None = None
    max_tokens: int | None = None
    max_judgments: int | None = None

    def __post_init__(self) -> None:
        for name in ("max_cost_usd", "max_tokens", "max_judgments"):
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ConfigError(f"{name} must not be negative")

    @property
    def active(self) -> bool:
        return any(v is not None for v in (self.max_cost_usd, self.max_tokens, self.max_judgments))

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_cost_usd": self.max_cost_usd,
            "max_tokens": self.max_tokens,
            "max_judgments": self.max_judgments,
        }


@dataclass(slots=True)
class ModelUsage:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 6),
        }


@dataclass
class CostTracker:
    """Thread-safe accumulator of token usage and cost per model.

    :meth:`reserve` is called before each judge request and raises
    :class:`BudgetExceededError` once a limit is reached. With concurrent
    requests, up to ``concurrency - 1`` requests that were already in flight can
    finish after the limit is hit, so keep a small margin.
    """

    prices: PriceTable = field(default_factory=PriceTable)
    budget: Budget = field(default_factory=Budget)
    models: dict[str, ModelUsage] = field(default_factory=dict)
    judgments: int = 0
    cache_hits: int = 0
    skipped: int = 0
    exhausted_reason: str | None = None
    _started: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def requests(self) -> int:
        return sum(m.requests for m in self.models.values())

    @property
    def total_tokens(self) -> int:
        return sum(m.prompt_tokens + m.completion_tokens for m in self.models.values())

    @property
    def total_cost(self) -> float | None:
        """Total USD, or ``None`` when any request used a model without a price."""
        total = 0.0
        for usage in self.models.values():
            if usage.cost_usd is None:
                return None
            total += usage.cost_usd
        return total

    @property
    def known_cost(self) -> float:
        return sum(m.cost_usd or 0.0 for m in self.models.values())

    def _limit_reason(self) -> str | None:
        b = self.budget
        if b.max_judgments is not None and self._started >= b.max_judgments:
            return f"judgment limit of {b.max_judgments} reached"
        if b.max_tokens is not None and self.total_tokens >= b.max_tokens:
            return f"token limit of {b.max_tokens} reached"
        if b.max_cost_usd is not None and self.known_cost >= b.max_cost_usd:
            return f"cost limit of ${b.max_cost_usd:.4f} reached"
        return None

    def reserve(self) -> None:
        """Claim one judgment slot or raise :class:`BudgetExceededError`."""
        with self._lock:
            reason = self._limit_reason()
            if reason:
                self.skipped += 1
                self.exhausted_reason = reason
                raise BudgetExceededError(reason)
            self._started += 1

    def record(self, usages: Iterable[TokenUsage]) -> None:
        with self._lock:
            self.judgments += 1
            for usage in usages:
                entry = self.models.setdefault(usage.model, ModelUsage())
                entry.requests += 1
                entry.prompt_tokens += usage.prompt_tokens
                entry.completion_tokens += usage.completion_tokens
                price = self.prices.get(usage.model)
                if price is None:
                    entry.cost_usd = None
                elif entry.cost_usd is not None:
                    entry.cost_usd += price.cost(usage)

    def record_cache_hit(self) -> None:
        with self._lock:
            self.cache_hits += 1

    def to_dict(self) -> dict[str, Any]:
        total = self.total_cost
        missing = sorted(name for name, m in self.models.items() if m.cost_usd is None)
        return {
            "judgments": self.judgments,
            "cache_hits": self.cache_hits,
            "requests": self.requests,
            "prompt_tokens": sum(m.prompt_tokens for m in self.models.values()),
            "completion_tokens": sum(m.completion_tokens for m in self.models.values()),
            "total_tokens": self.total_tokens,
            "cost_usd": None if total is None else round(total, 6),
            "known_cost_usd": round(self.known_cost, 6),
            "unpriced_models": missing,
            "models": {name: m.to_dict() for name, m in sorted(self.models.items())},
            "prices": self.prices.to_dict(),
            "budget": {
                **self.budget.to_dict(),
                "exhausted": self.exhausted_reason is not None,
                "reason": self.exhausted_reason,
                "skipped_pairs": self.skipped,
            },
        }
