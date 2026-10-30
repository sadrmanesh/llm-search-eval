"""Meilisearch connector over the REST search API."""

from __future__ import annotations

import os
import urllib.parse
from collections.abc import Mapping
from typing import Any

from llm_search_eval.connectors.base import SearchConnector, post_json
from llm_search_eval.errors import ConfigError, ConnectorError
from llm_search_eval.judges.openai_compat import Transport
from llm_search_eval.models import Query

DEFAULT_URL = "http://localhost:7700"


class MeilisearchConnector(SearchConnector):
    """Ranks products with a Meilisearch index.

    ``params`` are extra search parameters sent with every query, for example
    ``{"filter": "in_stock = true"}`` or ``{"locales": ["pes"]}``. Product ids
    come from ``id_field`` (default ``id``). The API key is read from
    ``MEILI_API_KEY`` or ``MEILISEARCH_API_KEY`` when not given; use a
    search-only key. A local server without a master key needs no key.
    """

    name = "meilisearch"

    def __init__(
        self,
        url: str | None = None,
        index: str = "products",
        *,
        api_key: str | None = None,
        params: Mapping[str, Any] | None = None,
        id_field: str = "id",
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: Transport | None = None,
    ) -> None:
        if not index:
            raise ConfigError("meilisearch connector needs an index")
        self.url = (url or os.environ.get("MEILI_URL") or DEFAULT_URL).rstrip("/")
        self.index = index
        self.api_key = (
            api_key or os.environ.get("MEILI_API_KEY") or os.environ.get("MEILISEARCH_API_KEY")
        )
        self.params = dict(params or {})
        self.id_field = id_field
        self.timeout = timeout
        self.max_retries = max_retries
        self.transport = transport

    def build_body(self, query: Query, k: int) -> dict[str, Any]:
        body: dict[str, Any] = {"attributesToRetrieve": [self.id_field], **self.params}
        body["q"] = query.text
        body["limit"] = k
        body.pop("offset", None)
        return body

    def search(self, query: Query, k: int) -> list[str]:
        url = f"{self.url}/indexes/{urllib.parse.quote(self.index, safe='')}/search"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = post_json(
            url,
            self.build_body(query, k),
            headers,
            timeout=self.timeout,
            max_retries=self.max_retries,
            transport=self.transport,
            what=f"meilisearch search for query {query.query_id!r}",
        )
        hits = data.get("hits") if isinstance(data, Mapping) else None
        if not isinstance(hits, list):
            raise ConnectorError(f"meilisearch response for query {query.query_id!r} has no hits")
        return [str(h[self.id_field]) for h in hits if h.get(self.id_field) is not None]
