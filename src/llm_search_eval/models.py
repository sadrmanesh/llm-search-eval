"""Core data model: queries, products, relevance labels, and system runs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

#: Graded relevance scale shared by gold labels and judges.
RELEVANCE_SCALE: Mapping[int, str] = {
    0: "irrelevant: does not satisfy the query",
    1: "partially relevant: related, but misses key requirements",
    2: "relevant: satisfies the main intent with minor gaps",
    3: "exact match: fully satisfies the query",
}
MIN_RELEVANCE = 0
MAX_RELEVANCE = 3

#: query_id -> product_id -> graded relevance.
Qrels = dict[str, dict[str, int]]


@dataclass(frozen=True, slots=True)
class Query:
    """A search query issued by a user."""

    query_id: str
    text: str
    lang: str | None = None
    #: Extra fields from the queries file, such as ``segment`` or ``traffic``.
    #: Used for stratified sampling and per-group breakdowns.
    attributes: Mapping[str, str] = field(default_factory=dict, compare=False)


@dataclass(frozen=True, slots=True)
class Product:
    """A catalog item that a search system can return."""

    product_id: str
    title: str
    description: str = ""
    category: str = ""
    brand: str = ""
    price: str = ""
    attributes: Mapping[str, str] = field(default_factory=dict)

    def to_text(self, max_chars: int = 2000) -> str:
        """Render the product as a compact, labelled block of text."""
        lines = [f"Title: {self.title}"]
        for label, value in (
            ("Brand", self.brand),
            ("Category", self.category),
            ("Price", self.price),
        ):
            if value:
                lines.append(f"{label}: {value}")
        for key, value in sorted(self.attributes.items()):
            if value:
                lines.append(f"{key}: {value}")
        if self.description:
            lines.append(f"Description: {self.description}")
        text = "\n".join(lines)
        if len(text) > max_chars:
            text = text[: max_chars - 3].rstrip() + "..."
        return text


@dataclass(slots=True)
class Run:
    """Ranked results produced by one search system, keyed by query id."""

    name: str
    rankings: dict[str, list[str]]

    def ranking(self, query_id: str, depth: int | None = None) -> list[str]:
        ranked = self.rankings.get(query_id, [])
        return ranked if depth is None else ranked[:depth]


@dataclass(slots=True)
class Dataset:
    """Queries, the product catalog, and optional gold relevance labels."""

    queries: dict[str, Query]
    products: dict[str, Product]
    qrels: Qrels = field(default_factory=dict)

    def gold_label(self, query_id: str, product_id: str) -> int | None:
        return self.qrels.get(query_id, {}).get(product_id)
