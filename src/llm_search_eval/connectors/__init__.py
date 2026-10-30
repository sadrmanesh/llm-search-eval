"""Live search connectors that turn a search backend into a :class:`~llm_search_eval.Run`.

All connectors work over plain HTTP with the standard library. Official
clients can be passed in when installed through the ``elasticsearch``,
``opensearch`` or ``algolia`` extras. :class:`HTTPJSONConnector` covers any
other JSON search API.
"""

from __future__ import annotations

from llm_search_eval.connectors.algolia import AlgoliaConnector
from llm_search_eval.connectors.base import FetchResult, SearchConnector, fetch_run
from llm_search_eval.connectors.elasticsearch import (
    ElasticsearchConnector,
    OpenSearchConnector,
)
from llm_search_eval.connectors.http_json import HTTPJSONConnector
from llm_search_eval.connectors.meilisearch import MeilisearchConnector
from llm_search_eval.connectors.typesense import TypesenseConnector

__all__ = [
    "AlgoliaConnector",
    "ElasticsearchConnector",
    "FetchResult",
    "HTTPJSONConnector",
    "MeilisearchConnector",
    "OpenSearchConnector",
    "SearchConnector",
    "TypesenseConnector",
    "fetch_run",
]
