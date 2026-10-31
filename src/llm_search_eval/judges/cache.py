"""Append-only JSONL cache so repeated runs never pay for the same judgment twice."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

from llm_search_eval.judges.base import Judgment, Vote
from llm_search_eval.models import Product, Query

log = logging.getLogger(__name__)


def cache_key(fingerprint: str, query: Query, product: Product) -> str:
    material = "\x1f".join((fingerprint, query.text, query.lang or "", product.to_text()))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class JudgmentCache:
    """Thread-safe cache keyed by judge fingerprint, query text, and product content.

    Keys hash the content, not the ids, so editing a product description or the
    query text correctly triggers a fresh judgment. The fingerprint of an LLM
    judge includes its prompt version and prompt hash, so a judgment made with a
    different prompt has a different key and is never reused. Each entry also
    records the judge's provenance (see :attr:`Judge.info`) under ``judge``.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._entries: dict[str, Judgment] = {}
        self._lock = threading.Lock()
        if self.path and self.path.is_file():
            self._load(self.path)

    def _load(self, path: Path) -> None:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                votes = tuple(
                    Vote(
                        str(v["judge"]),
                        None if v.get("relevance") is None else int(v["relevance"]),
                        str(v.get("reason", "")),
                    )
                    for v in rec.get("votes") or ()
                )
                self._entries[rec["key"]] = Judgment(
                    int(rec["relevance"]), rec.get("reason", ""), votes=votes
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                log.warning("%s:%d: skipping corrupt cache entry", path, lineno)

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> Judgment | None:
        with self._lock:
            return self._entries.get(key)

    def put(
        self,
        key: str,
        judgment: Judgment,
        *,
        query_id: str = "",
        product_id: str = "",
        judge: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._entries[key] = judgment
            if self.path is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            record: dict[str, object] = {
                "key": key,
                "query_id": query_id,
                "product_id": product_id,
                "relevance": judgment.relevance,
                "reason": judgment.reason,
            }
            if judge is not None:
                record["judge"] = judge
            if judgment.votes:
                record["votes"] = [
                    {"judge": v.judge, "relevance": v.relevance, "reason": v.reason}
                    for v in judgment.votes
                ]
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
