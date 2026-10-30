"""Elasticsearch and OpenSearch connectors.

By default the connector talks to the ``_search`` REST endpoint with the
standard library, so no extra dependency is needed. To reuse an existing
client (for example with cloud authentication already configured), pass an
``elasticsearch.Elasticsearch`` or ``opensearchpy.OpenSearch`` instance as
``client``; install them with the ``elasticsearch`` or ``opensearch`` extra.
"""

from __future__ import annotations

import base64
import copy
import os
import urllib.parse
from collections.abc import Mapping, Sequence
from typing import Any

from llm_search_eval.connectors.base import (
    SearchConnector,
    fill_template,
    post_json,
    to_mapping,
)
from llm_search_eval.errors import ConfigError, ConnectorError
from llm_search_eval.judges.openai_compat import Transport
from llm_search_eval.models import Query

DEFAULT_FIELDS = ("title^3", "brand^2", "category", "description")


class ElasticsearchConnector(SearchConnector):
    """Ranks products with an Elasticsearch index.

    The default request is a ``multi_match`` query over ``fields``. Supply
    ``query_template`` to send your production query instead; the placeholders
    ``{{query}}``, ``{{k}}``, ``{{lang}}`` and ``{{query_id}}`` are filled in
    per query. Product ids come from the document ``_id`` unless ``id_field``
    names a field in ``_source``.
    """

    name = "elasticsearch"
    _api_key_env = "ELASTICSEARCH_API_KEY"
    _password_env = "ELASTICSEARCH_PASSWORD"

    def __init__(
        self,
        url: str | None = None,
        index: str = "products",
        *,
        fields: Sequence[str] = DEFAULT_FIELDS,
        query_template: Mapping[str, Any] | None = None,
        id_field: str | None = None,
        api_key: str | None = None,
        username: str | None = None,
        password: str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        client: Any = None,
        transport: Transport | None = None,
    ) -> None:
        if client is None and not url:
            raise ConfigError(f"{self.name} connector needs a url or a client")
        if not index:
            raise ConfigError(f"{self.name} connector needs an index")
        self.url = (url or "").rstrip("/")
        self.index = index
        self.fields = list(fields)
        self.query_template = copy.deepcopy(dict(query_template)) if query_template else None
        self.id_field = id_field
        self.timeout = timeout
        self.max_retries = max_retries
        self.client = client
        self.transport = transport
        self.headers = dict(headers or {})
        api_key = api_key or os.environ.get(self._api_key_env)
        password = password or os.environ.get(self._password_env)
        if api_key and "Authorization" not in self.headers:
            self.headers["Authorization"] = f"ApiKey {api_key}"
        elif username and "Authorization" not in self.headers:
            token = base64.b64encode(f"{username}:{password or ''}".encode()).decode("ascii")
            self.headers["Authorization"] = f"Basic {token}"

    def build_body(self, query: Query, k: int) -> dict[str, Any]:
        values = {"query": query.text, "k": k, "lang": query.lang or "", "query_id": query.query_id}
        if self.query_template is not None:
            body: dict[str, Any] = fill_template(self.query_template, values)
            body.setdefault("size", k)
        else:
            body = {
                "size": k,
                "query": {
                    "multi_match": {
                        "query": query.text,
                        "fields": self.fields,
                        "type": "best_fields",
                    }
                },
            }
        if self.id_field is None:
            body.setdefault("_source", False)
        else:
            body.setdefault("_source", [self.id_field])
        return body

    def search(self, query: Query, k: int) -> list[str]:
        body = self.build_body(query, k)
        if self.client is not None:
            try:
                try:
                    raw = self.client.search(index=self.index, body=body)
                except TypeError:  # clients that dropped the ``body`` argument
                    raw = self.client.search(index=self.index, **body)
            except Exception as exc:
                raise ConnectorError(
                    f"{self.name} search failed for query {query.query_id!r}: {exc}"
                ) from exc
            data = to_mapping(raw)
        else:
            url = f"{self.url}/{urllib.parse.quote(self.index, safe=',*')}/_search"
            data = post_json(
                url,
                body,
                self.headers,
                timeout=self.timeout,
                max_retries=self.max_retries,
                transport=self.transport,
                what=f"{self.name} search for query {query.query_id!r}",
            )
        return self.parse_hits(data, query)

    def parse_hits(self, data: Any, query: Query) -> list[str]:
        try:
            hits = data["hits"]["hits"]
        except (KeyError, TypeError) as exc:
            raise ConnectorError(
                f"{self.name} response for query {query.query_id!r} has no hits.hits"
            ) from exc
        ids: list[str] = []
        for hit in hits:
            if self.id_field is None:
                value = hit.get("_id")
            else:
                value = (hit.get("_source") or {}).get(self.id_field)
                if value is None:
                    value = (hit.get("fields") or {}).get(self.id_field)
                    if isinstance(value, list):
                        value = value[0] if value else None
            if value is not None:
                ids.append(str(value))
        return ids

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()


class OpenSearchConnector(ElasticsearchConnector):
    """Ranks products with an OpenSearch index; same options as Elasticsearch."""

    name = "opensearch"
    _api_key_env = "OPENSEARCH_API_KEY"
    _password_env = "OPENSEARCH_PASSWORD"
