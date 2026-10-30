"""Deterministic lexical judge for tests, CI, and offline dry runs."""

from __future__ import annotations

from llm_search_eval.judges.base import Judge, Judgment, register_judge
from llm_search_eval.models import Product, Query
from llm_search_eval.text import tokenize


@register_judge("mock")
class MockJudge(Judge):
    """Grades by query term coverage over the product's title, brand, and category.

    The mock judge needs no network access and always returns the same label for
    the same input, which makes it suitable for unit tests and pipeline checks.
    It understands Persian and English through the shared text normalizer.
    It is not a substitute for a real relevance model.
    """

    name = "mock"

    def __init__(self, include_description: bool = False) -> None:
        self.include_description = include_description

    @property
    def fingerprint(self) -> str:
        return f"mock:desc={int(self.include_description)}"

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
        return Judgment(grade, f"matched {len(matched)}/{len(query_terms)} query terms: {terms}")
