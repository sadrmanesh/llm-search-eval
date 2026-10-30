"""Typesense connector over the ``multi_search`` endpoint."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

from llm_search_eval.connectors.base import SearchConnector, post_json
from llm_search_eval.errors import ConfigError, ConnectorError
from llm_search_eval.judges.openai_compat import Transport
from llm_search_eval.models import Query

DEFAULT_URL = "http://localhost:8108"
#: Typesense returns at most this many hits per page.
MAX_PER_PAGE = 250


class TypesenseConnector(SearchConnector):
    """Ranks products with a Typesense collection.

    ``query_by`` lists the fields to search, for example
    ``["title", "brand", "description"]``. ``params`` are extra search
    parameters, for example ``{"filter_by": "in_stock:true"}`` or
    ``{"locale": "fa"}``. The API key is read from ``TYPESENSE_API_KEY`` when
    not given; use a search-only key.

    The search goes through ``POST /multi_search`` so long queries do not hit
    URL length limits.
    """

    name = "typesense"

    def __init__(
        self,
        url: str | None = None,
        collection: str = "products",
        *,
        query_by: Sequence[str] | str = ("title", "description"),
        api_key: str | None = None,
        params: Mapping[str, Any] | None = None,
        id_field: str = "id",
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: Transport | None = None,
    ) -> None:
        if not collection:
            raise ConfigError("typesense connector needs a collection")
        fields = query_by.split(",") if isinstance(query_by, str) else list(query_by)
        self.query_by = ",".join(f.strip() for f in fields if f.strip())
        if not self.query_by:
            raise ConfigError("typesense connector needs query_by fields")
        self.api_key = api_key or os.environ.get("TYPESENSE_API_KEY", "")
        if not self.api_key:
            raise ConfigError("typesense connector needs an API key (or TYPESENSE_API_KEY)")
        self.url = (url or os.environ.get("TYPESENSE_URL") or DEFAULT_URL).rstrip("/")
        self.collection = collection
        self.params = dict(params or {})
        self.id_field = id_field
        self.timeout = timeout
        self.max_retries = max_retries
        self.transport = transport

    def build_search(self, query: Query, k: int) -> dict[str, Any]:
        if k > MAX_PER_PAGE:
            raise ConfigError(f"typesense returns at most {MAX_PER_PAGE} results per query")
        search: dict[str, Any] = {"include_fields": self.id_field, **self.params}
        search.update(
            collection=self.collection, q=query.text, query_by=self.query_by, per_page=k, page=1
        )
        return search

    def search(self, query: Query, k: int) -> list[str]:
        data = post_json(
            f"{self.url}/multi_search",
            {"searches": [self.build_search(query, k)]},
            {"X-TYPESENSE-API-KEY": self.api_key},
            timeout=self.timeout,
            max_retries=self.max_retries,
            transport=self.transport,
            what=f"typesense search for query {query.query_id!r}",
        )
        results = data.get("results") if isinstance(data, Mapping) else None
        if not isinstance(results, list) or not results:
            raise ConnectorError(f"typesense response for query {query.query_id!r} has no results")
        result = results[0]
        if "error" in result:
            raise ConnectorError(
                f"typesense search failed for query {query.query_id!r}: "
                f"HTTP {result.get('code', '?')}: {result['error']}"
            )
        ids: list[str] = []
        for hit in result.get("hits") or []:
            value = (hit.get("document") or {}).get(self.id_field)
            if value is not None:
                ids.append(str(value))
        return ids
