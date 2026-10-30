"""Live search connectors that turn a search backend into a :class:`~llm_search_eval.Run`.

All connectors work over plain HTTP with the standard library. Official
clients can be passed in when installed through the ``elasticsearch``,
``opensearch`` or ``algolia`` extras.
"""

from __future__ import annotations

from llm_search_eval.connectors.algolia import AlgoliaConnector
from llm_search_eval.connectors.base import FetchResult, SearchConnector, fetch_run
from llm_search_eval.connectors.elasticsearch import (
    ElasticsearchConnector,
    OpenSearchConnector,
)

__all__ = [
    "AlgoliaConnector",
    "ElasticsearchConnector",
    "FetchResult",
    "OpenSearchConnector",
    "SearchConnector",
    "fetch_run",
]
