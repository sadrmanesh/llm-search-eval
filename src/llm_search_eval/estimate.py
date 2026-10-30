"""Pre-run cost estimate: how many judge calls, tokens and dollars a run needs.

The estimate walks the same pairs :func:`~llm_search_eval.evaluate.evaluate`
would judge, skips gold labels and cache hits, builds the real prompts and
counts their tokens with a simple heuristic (no tokenizer download). Output
tokens are an assumption, since replies are short JSON objects.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from llm_search_eval.errors import ConfigError
from llm_search_eval.evaluate import (
    EvaluationConfig,
    apply_sampling,
    calibration_pairs,
    pending_pairs,
)
from llm_search_eval.judges.base import Judge
from llm_search_eval.judges.cache import JudgmentCache, cache_key
from llm_search_eval.judges.mock import MockJudge
from llm_search_eval.judges.openai_compat import OpenAICompatibleJudge
from llm_search_eval.judges.panel import JudgePanel
from llm_search_eval.judges.prompts import build_messages, build_pairwise_messages
from llm_search_eval.models import Dataset, Product, Query, Run
from llm_search_eval.usage import Budget, ModelPrice, PriceTable

if TYPE_CHECKING:
    from llm_search_eval.judges.pairwise import PairwiseJudge
    from llm_search_eval.pairwise import PairwiseCache

#: Tokens added per chat message for role and formatting.
MESSAGE_OVERHEAD = 4
#: Assumed reply length of one judge call, in tokens.
DEFAULT_OUTPUT_TOKENS = 40


def estimate_tokens(text: str) -> int:
    """Rough token count: about 4 ASCII characters or 2 other characters per token.

    Persian and other non-Latin scripts take more tokens per character in the
    common BPE vocabularies, so they are counted at a higher rate. Expect the
    result to be within roughly 20 percent of a real tokenizer.
    """
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    other = len(text) - ascii_chars
    return math.ceil(ascii_chars / 4 + other / 2)


def message_tokens(messages: Sequence[dict[str, Any]]) -> int:
    return sum(estimate_tokens(str(m.get("content", ""))) + MESSAGE_OVERHEAD for m in messages)


@dataclass
class ModelEstimate:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = 0.0

    def add(self, prompt: int, completion: int, price: ModelPrice | None) -> None:
        self.calls += 1
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        if price is None:
            self.cost_usd = None
        elif self.cost_usd is not None:
            self.cost_usd += (
                prompt * price.input_per_million + completion * price.output_per_million
            ) / 1e6

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 6),
        }


@dataclass
class CostEstimate:
    """Result of :func:`estimate_run`. ``cost_usd`` is ``None`` if a model has no price."""

    queries: int = 0
    pairs: int = 0
    gold: int = 0
    unknown_products: int = 0
    calibration: int = 0
    cached: int = 0
    to_judge: int = 0
    pairwise_comparisons: int = 0
    pairwise_identical: int = 0
    pairwise_cached: int = 0
    pairwise_calls: int = 0
    free_calls: int = 0
    models: dict[str, ModelEstimate] = field(default_factory=dict)
    budget: Budget = field(default_factory=Budget)
    output_tokens: int = DEFAULT_OUTPUT_TOKENS

    @property
    def calls(self) -> int:
        return sum(m.calls for m in self.models.values())

    @property
    def total_tokens(self) -> int:
        return sum(m.prompt_tokens + m.completion_tokens for m in self.models.values())

    @property
    def cost_usd(self) -> float | None:
        total = 0.0
        for m in self.models.values():
            if m.cost_usd is None:
                return None
            total += m.cost_usd
        return total

    def budget_problems(self) -> list[str]:
        """Budget limits this run is expected to hit, as sentences."""
        b = self.budget
        problems = []
        judgments = self.to_judge + self.pairwise_calls
        if b.max_judgments is not None and judgments > b.max_judgments:
            problems.append(f"{judgments} judgments needed, limit is {b.max_judgments}")
        if b.max_tokens is not None and self.total_tokens > b.max_tokens:
            problems.append(f"about {self.total_tokens} tokens needed, limit is {b.max_tokens}")
        cost = self.cost_usd
        if b.max_cost_usd is not None and cost is not None and cost > b.max_cost_usd:
            problems.append(f"about ${cost:.4f} needed, limit is ${b.max_cost_usd:.4f}")
        return problems

    def to_dict(self) -> dict[str, Any]:
        cost = self.cost_usd
        problems = self.budget_problems()
        return {
            "queries": self.queries,
            "pairs": self.pairs,
            "gold": self.gold,
            "unknown_products": self.unknown_products,
            "calibration": self.calibration,
            "cached": self.cached,
            "to_judge": self.to_judge,
            "pairwise": {
                "comparisons": self.pairwise_comparisons,
                "identical": self.pairwise_identical,
                "cached": self.pairwise_cached,
                "calls": self.pairwise_calls,
            },
            "calls": self.calls,
            "free_calls": self.free_calls,
            "prompt_tokens": sum(m.prompt_tokens for m in self.models.values()),
            "completion_tokens": sum(m.completion_tokens for m in self.models.values()),
            "total_tokens": self.total_tokens,
            "output_tokens_per_call": self.output_tokens,
            "cost_usd": None if cost is None else round(cost, 6),
            "unpriced_models": sorted(n for n, m in self.models.items() if m.cost_usd is None),
            "models": {name: m.to_dict() for name, m in sorted(self.models.items())},
            "budget": {**self.budget.to_dict(), "fits": not problems, "problems": problems},
        }


def _members(judge: Judge) -> list[Judge]:
    return list(judge.judges) if isinstance(judge, JudgePanel) else [judge]


def _is_free(judge: object) -> bool:
    from llm_search_eval.judges.pairwise import MockPairwiseJudge

    return isinstance(judge, MockJudge | MockPairwiseJudge)


def _relevance_cost(member: Judge, query: Query, product: Product) -> tuple[str, int]:
    if isinstance(member, OpenAICompatibleJudge):
        return member.model, message_tokens(
            build_messages(query, product, member.max_product_chars)
        )
    model = str(getattr(member, "model", None) or member.label)
    return model, message_tokens(build_messages(query, product))


def _pairwise_cost(
    judge: PairwiseJudge, query: Query, first: Sequence[Product], second: Sequence[Product]
) -> tuple[str, int]:
    chars = int(getattr(judge, "max_product_chars", 400))
    model = str(getattr(judge, "model", None) or judge.label)
    return model, message_tokens(build_pairwise_messages(query, first, second, chars))


def estimate_run(
    dataset: Dataset,
    runs: Sequence[Run],
    config: EvaluationConfig | None = None,
    *,
    judge: Judge | None = None,
    cache: JudgmentCache | None = None,
    pairwise_judge: PairwiseJudge | None = None,
    pairwise_cache: PairwiseCache | None = None,
    prices: PriceTable | None = None,
    budget: Budget | None = None,
    output_tokens: int = DEFAULT_OUTPUT_TOKENS,
) -> CostEstimate:
    """Estimate the judge calls, tokens and cost of ``evaluate`` with the same inputs.

    Nothing is sent to any judge. Mock judges count as free calls.
    """
    from llm_search_eval.pairwise import pairwise_key, ranked_products, resolve_pairs

    config = config or EvaluationConfig()
    config.validate()
    if output_tokens < 0:
        raise ConfigError("output_tokens must not be negative")
    if not runs:
        raise ConfigError("at least one run is required")
    prices = prices or PriceTable()
    dataset, _ = apply_sampling(dataset, config)
    depth = config.resolved_depth()
    result = CostEstimate(
        queries=len(dataset.queries), budget=budget or Budget(), output_tokens=output_tokens
    )

    def charge(model: str, prompt: int) -> None:
        entry = result.models.setdefault(model, ModelEstimate())
        entry.add(prompt, output_tokens, prices.get(model))

    pending = pending_pairs(dataset, runs, depth)
    result.pairs = len(pending) + sum(
        1
        for qid in dataset.queries
        for pid in {p for run in runs for p in run.ranking(qid, depth)}
        if dataset.gold_label(qid, pid) is not None
    )
    result.gold = result.pairs - len(pending)
    todo = [(q, p) for q, p in pending if p in dataset.products]
    result.unknown_products = len(pending) - len(todo)
    if judge is not None:
        if config.calibrate:
            extra = calibration_pairs(dataset, config.calibration_sample, config.seed)
            result.calibration = len(extra)
            todo += extra
        members = _members(judge)
        for qid, pid in todo:
            query, product = dataset.queries[qid], dataset.products[pid]
            if (
                cache is not None
                and cache.get(cache_key(judge.fingerprint, query, product)) is not None
            ):
                result.cached += 1
                continue
            result.to_judge += 1
            for member in members:
                if _is_free(member):
                    result.free_calls += 1
                else:
                    charge(*_relevance_cost(member, query, product))

    if pairwise_judge is not None:
        names = [r.name for r in runs]
        by_name = {r.name: r for r in runs}
        baseline = config.baseline or names[0]
        pairs = resolve_pairs(names, baseline, list(config.pairwise_pairs or []))
        k = config.pairwise_k
        seen: set[str] = set()
        for a, b in pairs:
            for qid, query in dataset.queries.items():
                ranked_a, ranked_b = by_name[a].ranking(qid, k), by_name[b].ranking(qid, k)
                if not ranked_a and not ranked_b:
                    continue
                result.pairwise_comparisons += 1
                if ranked_a == ranked_b:
                    result.pairwise_identical += 1
                    continue
                first, second = (
                    ranked_products(dataset, ranked_a),
                    ranked_products(dataset, ranked_b),
                )
                orders = (
                    [(first, second), (second, first)]
                    if config.pairwise_swap
                    else [(first, second)]
                )
                for x, y in orders:
                    key = pairwise_key(pairwise_judge.fingerprint, query, x, y)
                    if key in seen or (
                        pairwise_cache is not None and pairwise_cache.get(key) is not None
                    ):
                        result.pairwise_cached += 1
                        continue
                    seen.add(key)
                    result.pairwise_calls += 1
                    if _is_free(pairwise_judge):
                        result.free_calls += 1
                    else:
                        charge(*_pairwise_cost(pairwise_judge, query, x, y))
    return result


def render_estimate(estimate: CostEstimate) -> list[str]:
    """Plain text lines for the terminal."""
    d = estimate.to_dict()
    lines = [
        f"queries: {d['queries']}",
        f"result pairs: {d['pairs']} ({d['gold']} gold, {d['unknown_products']} unknown products)",
    ]
    if d["calibration"]:
        lines.append(f"calibration pairs: {d['calibration']}")
    lines.append(f"pairs to judge: {d['to_judge']} ({d['cached']} already cached)")
    pw = d["pairwise"]
    if pw["comparisons"]:
        lines.append(
            f"pairwise comparisons: {pw['comparisons']} ({pw['identical']} identical), "
            f"judge calls: {pw['calls']} ({pw['cached']} cached)"
        )
    if d["free_calls"]:
        lines.append(f"free calls (mock judges): {d['free_calls']}")
    for name, m in d["models"].items():
        cost = "no price" if m["cost_usd"] is None else f"${m['cost_usd']:.4f}"
        lines.append(
            f"  {name}: {m['calls']} calls, {m['prompt_tokens']} in + "
            f"{m['completion_tokens']} out tokens, {cost}"
        )
    total = "unknown (set --price)" if d["cost_usd"] is None else f"${d['cost_usd']:.4f}"
    lines.append(
        f"total: {d['calls']} calls, about {d['total_tokens']} tokens, {total} "
        f"(assumes {d['output_tokens_per_call']} output tokens per call)"
    )
    if d["unpriced_models"]:
        lines.append(f"no price for: {', '.join(d['unpriced_models'])}")
    budget = d["budget"]
    if any(budget[k] is not None for k in ("max_cost_usd", "max_tokens", "max_judgments")):
        if budget["fits"]:
            lines.append("budget: fits")
        else:
            lines += [f"budget: exceeded: {p}" for p in budget["problems"]]
    return lines
