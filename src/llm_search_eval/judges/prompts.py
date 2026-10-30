"""Prompt templates for LLM relevance grading."""

from __future__ import annotations

from llm_search_eval.models import RELEVANCE_SCALE, Product, Query

#: Bump when the prompt changes so cached judgments are invalidated.
PROMPT_VERSION = "relevance-v1"

_LANGUAGE_NAMES = {"fa": "Persian (Farsi)", "en": "English"}

SYSTEM_PROMPT = """\
You are an expert search quality rater for an online store. Given a shopper's
search query and one product from the catalog, rate how well the product
satisfies the shopper's intent.

Use this scale:
{scale}

Guidelines:
- Judge the shopper's intent, not keyword overlap. Synonyms, transliterations,
  and translations between Persian and English count as matches.
- Hard constraints in the query (brand, size, color, compatibility, price range,
  gender, quantity) must be satisfied for a grade of 3.
- Accessories for a requested product are at most 1 unless the query asks for them.
- Do not reward a product for being popular or well described.

Respond with a single JSON object and nothing else:
{{"relevance": <integer 0-3>, "reason": "<one short sentence in English>"}}"""


def system_prompt() -> str:
    scale = "\n".join(f"{grade} = {meaning}" for grade, meaning in RELEVANCE_SCALE.items())
    return SYSTEM_PROMPT.format(scale=scale)


def user_prompt(query: Query, product: Product, max_product_chars: int = 2000) -> str:
    language = _LANGUAGE_NAMES.get(query.lang or "", query.lang or "unknown")
    return (
        f"Query language: {language}\n"
        f"Search query: {query.text}\n\n"
        f"Product:\n{product.to_text(max_product_chars)}"
    )


def build_messages(query: Query, product: Product, max_product_chars: int = 2000) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user_prompt(query, product, max_product_chars)},
    ]
