"""Prompt templates for LLM relevance grading."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from llm_search_eval.models import RELEVANCE_SCALE, Product, Query

#: Bump when the prompt changes. Reports and cache entries record it next to
#: :data:`PROMPT_HASH`, which changes on any edit to the template text even
#: when the version is not bumped.
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


USER_PROMPT_TEMPLATE = """\
Query language: {language}
Search query: {query}

Product:
{product}"""


def prompt_hash(*templates: str) -> str:
    """First 12 hex characters of the SHA-256 of the templates, joined by a unit separator."""
    return hashlib.sha256("\x1f".join(templates).encode("utf-8")).hexdigest()[:12]


def system_prompt() -> str:
    scale = "\n".join(f"{grade} = {meaning}" for grade, meaning in RELEVANCE_SCALE.items())
    return SYSTEM_PROMPT.format(scale=scale)


def user_prompt(query: Query, product: Product, max_product_chars: int = 2000) -> str:
    language = _LANGUAGE_NAMES.get(query.lang or "", query.lang or "unknown")
    return USER_PROMPT_TEMPLATE.format(
        language=language, query=query.text, product=product.to_text(max_product_chars)
    )


#: Hash of the rendered system prompt and the user prompt template.
PROMPT_HASH = prompt_hash(system_prompt(), USER_PROMPT_TEMPLATE)


def build_messages(query: Query, product: Product, max_product_chars: int = 2000) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user_prompt(query, product, max_product_chars)},
    ]


#: Bump when the pairwise prompt changes. :data:`PAIRWISE_PROMPT_HASH` is
#: recorded with it.
PAIRWISE_PROMPT_VERSION = "pairwise-v1"

PAIRWISE_SYSTEM_PROMPT = """\
You are an expert search quality rater for an online store. You see a shopper's
search query and two ranked result lists, A and B, from two search engines.
Decide which list serves the shopper better.

Guidelines:
- Judge the shopper's intent, not keyword overlap. Synonyms, transliterations,
  and translations between Persian and English count as matches.
- Top positions matter most: a relevant first result outweighs several relevant
  results further down.
- Products that break hard constraints in the query (brand, size, color,
  compatibility, price range) count against a list.
- The order in which the lists are shown is random. Do not prefer A or B for
  its position, and do not prefer a list for being longer.
- Answer "tie" when the lists are about equally useful.

Respond with a single JSON object and nothing else:
{"winner": "A" | "B" | "tie", "reason": "<one short sentence in English>"}"""


PAIRWISE_USER_PROMPT_TEMPLATE = """\
Query language: {language}
Search query: {query}

Results A:
{first}

Results B:
{second}"""


def _result_list(products: Sequence[Product], max_product_chars: int) -> str:
    if not products:
        return "(no results)"
    blocks = []
    for rank, product in enumerate(products, start=1):
        text = product.to_text(max_product_chars).replace("\n", "; ")
        blocks.append(f"{rank}. {text}")
    return "\n".join(blocks)


def pairwise_user_prompt(
    query: Query,
    first: Sequence[Product],
    second: Sequence[Product],
    max_product_chars: int = 400,
) -> str:
    language = _LANGUAGE_NAMES.get(query.lang or "", query.lang or "unknown")
    return PAIRWISE_USER_PROMPT_TEMPLATE.format(
        language=language,
        query=query.text,
        first=_result_list(first, max_product_chars),
        second=_result_list(second, max_product_chars),
    )


def build_pairwise_messages(
    query: Query,
    first: Sequence[Product],
    second: Sequence[Product],
    max_product_chars: int = 400,
) -> list[dict]:
    return [
        {"role": "system", "content": PAIRWISE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": pairwise_user_prompt(query, first, second, max_product_chars),
        },
    ]


#: Hash of the pairwise system prompt and the pairwise user prompt template.
PAIRWISE_PROMPT_HASH = prompt_hash(PAIRWISE_SYSTEM_PROMPT, PAIRWISE_USER_PROMPT_TEMPLATE)
