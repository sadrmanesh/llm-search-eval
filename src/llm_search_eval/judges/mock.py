"""Deterministic lexical judge for tests, CI, and offline dry runs."""

from __future__ import annotations

import hashlib

from llm_search_eval.judges.base import Judge, Judgment, register_judge
from llm_search_eval.models import MAX_RELEVANCE, MIN_RELEVANCE, Product, Query
from llm_search_eval.text import tokenize


@register_judge("mock")
class MockJudge(Judge):
    """Grades by query term coverage over the product's title, brand, and category.

    The mock judge needs no network access and always returns the same label for
    the same input, which makes it suitable for unit tests and pipeline checks.
    It understands Persian and English through the shared text normalizer.
    It is not a substitute for a real relevance model.

    ``noise`` is the probability of moving a grade one step up or down. The
    change depends only on ``seed`` and the query and product ids, so a panel of
    mock judges with different seeds disagrees reproducibly, which is useful for
    trying out panels and agreement reports offline.
    """

    name = "mock"

    def __init__(
        self, include_description: bool = False, noise: float = 0.0, seed: int = 0
    ) -> None:
        if not 0.0 <= noise <= 1.0:
            raise ValueError("noise must be between 0 and 1")
        self.include_description = include_description
        self.noise = float(noise)
        self.seed = int(seed)

    @property
    def fingerprint(self) -> str:
        base = f"mock:desc={int(self.include_description)}"
        return base if not self.noise else f"{base}:noise={self.noise:g}:seed={self.seed}"

    @property
    def label(self) -> str:
        return "mock" if not self.noise else f"mock(noise={self.noise:g},seed={self.seed})"

    def _perturb(self, grade: int, query: Query, product: Product) -> int:
        if not self.noise:
            return grade
        key = f"{self.seed}|{query.query_id}|{product.product_id}".encode()
        digest = hashlib.blake2b(key, digest_size=8).digest()
        roll = int.from_bytes(digest[:4], "big") / 2**32
        if roll >= self.noise:
            return grade
        step = 1 if digest[4] % 2 else -1
        if not MIN_RELEVANCE <= grade + step <= MAX_RELEVANCE:
            step = -step
        return grade + step

    def judge(self, query: Query, product: Product) -> Judgment:
        query_terms = set(tokenize(query.text))
        if not query_terms:
            return Judgment(0, "query has no content terms")
        fields = [product.title, product.brand, product.category, *product.attributes.values()]
        if self.include_description:
            fields.append(product.description)
        product_terms = set(tokenize(" ".join(fields)))
        matched = query_terms & product_terms
        coverage = len(matched) / len(query_terms)
        if coverage >= 0.999:
            grade = 3
        elif coverage >= 0.5:
            grade = 2
        elif coverage > 0:
            grade = 1
        else:
            grade = 0
        terms = ", ".join(sorted(matched)) or "none"
        grade = self._perturb(grade, query, product)
        return Judgment(grade, f"matched {len(matched)}/{len(query_terms)} query terms: {terms}")
