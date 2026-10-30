"""Algolia connector.

Uses the Algolia Search REST API with the standard library by default. A
``SearchClientSync`` from ``algoliasearch`` (the ``algolia`` extra) can be
passed as ``client`` instead.
"""

from __future__ import annotations

import os
import urllib.parse
from collections.abc import Mapping
from typing import Any

from llm_search_eval.connectors.base import SearchConnector, post_json, to_mapping
from llm_search_eval.errors import ConfigError, ConnectorError
from llm_search_eval.judges.openai_compat import Transport
from llm_search_eval.models import Query


class AlgoliaConnector(SearchConnector):
    """Ranks products with an Algolia index.

    ``params`` are extra search parameters sent with every query, for example
    ``{"filters": "in_stock:true"}`` or ``{"analytics": False}``. Product ids
    come from ``objectID`` unless ``id_field`` names another attribute. Use a
    search-only API key.
    """

    name = "algolia"

    def __init__(
        self,
        app_id: str | None = None,
        index: str = "products",
        *,
        api_key: str | None = None,
        params: Mapping[str, Any] | None = None,
        id_field: str = "objectID",
        host: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        client: Any = None,
        transport: Transport | None = None,
    ) -> None:
        self.app_id = app_id or os.environ.get("ALGOLIA_APP_ID", "")
        self.api_key = api_key or os.environ.get("ALGOLIA_API_KEY", "")
        if client is None and not (self.app_id and self.api_key):
            raise ConfigError(
                "algolia connector needs an application id and API key "
                "(or ALGOLIA_APP_ID and ALGOLIA_API_KEY), or a client"
            )
        if not index:
            raise ConfigError("algolia connector needs an index")
        self.index = index
        self.params = dict(params or {})
        self.id_field = id_field
        self.host = (host or f"https://{self.app_id}-dsn.algolia.net").rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.client = client
        self.transport = transport

    def build_params(self, query: Query, k: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "query": query.text,
            "hitsPerPage": k,
            "attributesToRetrieve": [self.id_field],
            "attributesToHighlight": [],
            "attributesToSnippet": [],
        }
        if query.lang:
            params["queryLanguages"] = [query.lang]
        params.update(self.params)
        params["query"] = query.text
        params["hitsPerPage"] = k
        return params

    def search(self, query: Query, k: int) -> list[str]:
        params = self.build_params(query, k)
        if self.client is not None:
            try:
                raw = self.client.search_single_index(index_name=self.index, search_params=params)
            except Exception as exc:
                raise ConnectorError(
                    f"algolia search failed for query {query.query_id!r}: {exc}"
                ) from exc
            data = to_mapping(raw)
        else:
            url = f"{self.host}/1/indexes/{urllib.parse.quote(self.index, safe='')}/query"
            headers = {
                "X-Algolia-Application-Id": self.app_id,
                "X-Algolia-API-Key": self.api_key,
            }
            data = post_json(
                url,
                params,
                headers,
                timeout=self.timeout,
                max_retries=self.max_retries,
                transport=self.transport,
                what=f"algolia search for query {query.query_id!r}",
            )
        return self.parse_hits(data, query)

    def parse_hits(self, data: Any, query: Query) -> list[str]:
        hits = data.get("hits") if isinstance(data, Mapping) else None
        if not isinstance(hits, list):
            raise ConnectorError(f"algolia response for query {query.query_id!r} has no hits")
        ids: list[str] = []
        for hit in hits:
            value = hit.get(self.id_field)
            if value is None and self.id_field == "objectID":
                value = hit.get("object_id")
            if value is not None:
                ids.append(str(value))
        return ids
