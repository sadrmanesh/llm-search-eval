"""Pairwise A-versus-B comparison of two systems with a pairwise judge.

For every query the judge sees both top-k lists side by side. With ``swap``
(the default) each query is judged twice, once in each order, and a system
wins only when both orders agree. That cancels the position bias LLM judges are
known for; disagreements count as ties and are reported as ``inconsistent``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_search_eval.errors import ConfigError, JudgeError
from llm_search_eval.judges.pairwise import FIRST, SECOND, TIE, PairwiseJudge, PairwiseVerdict
from llm_search_eval.models import Dataset, Product, Query, Run
from llm_search_eval.stats import sign_test, wilson_interval
from llm_search_eval.usage import BudgetExceededError, CostTracker

log = logging.getLogger(__name__)


def pairwise_key(
    fingerprint: str, query: Query, first: list[Product], second: list[Product]
) -> str:
    parts = [fingerprint, query.text, query.lang or ""]
    parts += [p.to_text() for p in first] + ["\x1e"] + [p.to_text() for p in second]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class PairwiseCache:
    """Append-only JSONL cache of pairwise verdicts, keyed by content."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._entries: dict[str, PairwiseVerdict] = {}
        self._lock = threading.Lock()
        if self.path and self.path.is_file():
            for lineno, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    self._entries[rec["key"]] = PairwiseVerdict(
                        rec["winner"], rec.get("reason", "")
                    )
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    log.warning("%s:%d: skipping corrupt pairwise cache entry", self.path, lineno)

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> PairwiseVerdict | None:
        with self._lock:
            return self._entries.get(key)

    def put(self, key: str, verdict: PairwiseVerdict, *, query_id: str = "") -> None:
        with self._lock:
            self._entries[key] = verdict
            if self.path is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "key": key,
                "query_id": query_id,
                "winner": verdict.winner,
                "reason": verdict.reason,
            }
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")


@dataclass(frozen=True, slots=True)
class _Outcome:
    query_id: str
    winner: str  # "a", "b" or "tie"
    orders: tuple[str, ...]
    reason: str
    source: str
    inconsistent: bool = False


def _products(dataset: Dataset, ranking: list[str]) -> list[Product]:
    return [dataset.products[pid] for pid in ranking if pid in dataset.products]


def _combine(forward: PairwiseVerdict, backward: PairwiseVerdict | None) -> tuple[str, bool]:
    """Winner as ``a``/``b``/``tie``; ``backward`` was judged with B shown first."""
    first = {FIRST: "a", SECOND: "b", TIE: "tie"}[forward.winner]
    if backward is None:
        return first, False
    second = {FIRST: "b", SECOND: "a", TIE: "tie"}[backward.winner]
    if first == second:
        return first, False
    inconsistent = "tie" not in (first, second)
    return "tie", inconsistent


def compare_pair(
    dataset: Dataset,
    run_a: Run,
    run_b: Run,
    judge: PairwiseJudge,
    *,
    k: int = 5,
    swap: bool = True,
    concurrency: int = 4,
    tracker: CostTracker | None = None,
    cache: PairwiseCache | None = None,
    confidence: float = 0.95,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Judge ``run_a`` against ``run_b`` on every query and summarize the result.

    Queries where both systems return the same top ``k`` are ties without a
    judge call; queries where neither returns anything are skipped.
    """
    if k < 1:
        raise ConfigError("pairwise k must be a positive integer")
    tracker = tracker or CostTracker()
    cache = PairwiseCache() if cache is None else cache

    def ask(
        query: Query, first: list[Product], second: list[Product]
    ) -> tuple[PairwiseVerdict, str]:
        key = pairwise_key(judge.fingerprint, query, first, second)
        hit = cache.get(key)
        if hit is not None:
            tracker.record_cache_hit()
            return hit, "cache"
        tracker.reserve()
        verdict = judge.compare(query, first, second)
        tracker.record([verdict.usage] if verdict.usage else [])
        cache.put(key, verdict, query_id=query.query_id)
        return verdict, "judge"

    def run_query(qid: str) -> _Outcome:
        query = dataset.queries[qid]
        ranked_a, ranked_b = run_a.ranking(qid, k), run_b.ranking(qid, k)
        if ranked_a == ranked_b:
            return _Outcome(qid, "tie", (), "identical results", "identical")
        a, b = _products(dataset, ranked_a), _products(dataset, ranked_b)
        forward, source = ask(query, a, b)
        backward = None
        if swap:
            backward, second_source = ask(query, b, a)
            source = "judge" if "judge" in (source, second_source) else "cache"
        winner, inconsistent = _combine(forward, backward)
        orders = (forward.winner,) if backward is None else (forward.winner, backward.winner)
        reason = forward.reason if winner != "b" or backward is None else backward.reason
        return _Outcome(qid, winner, orders, reason, source, inconsistent)

    todo = [q for q in dataset.queries if run_a.ranking(q, k) or run_b.ranking(q, k)]
    outcomes: list[_Outcome] = []
    failed: list[str] = []
    skipped = 0
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(run_query, qid): qid for qid in todo}
        for future in as_completed(futures):
            done += 1
            qid = futures[future]
            try:
                outcomes.append(future.result())
            except BudgetExceededError:
                skipped += 1
            except JudgeError as exc:
                failed.append(f"{qid}: {exc}")
                log.warning("%s", exc)
            if progress:
                progress(done, len(todo))
    position = {qid: i for i, qid in enumerate(todo)}
    outcomes.sort(key=lambda o: position[o.query_id])
    wins_a = sum(1 for o in outcomes if o.winner == "a")
    wins_b = sum(1 for o in outcomes if o.winner == "b")
    ties = len(outcomes) - wins_a - wins_b
    decided = wins_a + wins_b
    interval = wilson_interval(wins_b, decided, confidence) if decided else None
    return {
        "system_a": run_a.name,
        "system_b": run_b.name,
        "judge": judge.label,
        "fingerprint": judge.fingerprint,
        "k": k,
        "swap": swap,
        "queries": len(outcomes),
        "wins_a": wins_a,
        "wins_b": wins_b,
        "ties": ties,
        "inconsistent": sum(1 for o in outcomes if o.inconsistent),
        "identical": sum(1 for o in outcomes if o.source == "identical"),
        "failed": len(failed),
        "skipped_budget": skipped,
        "errors": failed[:20],
        "win_rate_b": None if not decided else wins_b / decided,
        "win_rate_ci": None if interval is None else interval.to_dict(),
        "preference_b": None if not outcomes else (wins_b + 0.5 * ties) / len(outcomes),
        "p_value": sign_test(wins_a, wins_b),
        "per_query": {
            o.query_id: {
                "winner": o.winner,
                "orders": list(o.orders),
                "reason": o.reason,
                "source": o.source,
            }
            for o in outcomes
        },
    }


def resolve_pairs(
    names: list[str], baseline: str, pairs: list[tuple[str, str]] | None
) -> list[tuple[str, str]]:
    """Default to every system against the baseline; validate explicit pairs."""
    if not pairs:
        return [(baseline, name) for name in names if name != baseline]
    for a, b in pairs:
        for name in (a, b):
            if name not in names:
                raise ConfigError(f"pairwise system {name!r} is not one of: {', '.join(names)}")
        if a == b:
            raise ConfigError(f"pairwise comparison needs two different systems, got {a!r} twice")
    return list(pairs)
