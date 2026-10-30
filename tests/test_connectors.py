"""Connectors are tested with fake transports and clients; no network is used."""

from __future__ import annotations

import json
import urllib.error

import pytest

from llm_search_eval.connectors import (
    AlgoliaConnector,
    ElasticsearchConnector,
    OpenSearchConnector,
    fetch_run,
)
from llm_search_eval.connectors.base import fill_template, post_json, to_mapping
from llm_search_eval.errors import ConfigError, ConnectorError
from llm_search_eval.judges.openai_compat import HTTPResponse
from llm_search_eval.models import Query

QUERY = Query("q1", "red shoes", "en")


class Transport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, json.loads(payload), timeout))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def es_hits(*ids, field=None):
    hits = [{"_id": i} if field is None else {"_id": "x", "_source": {field: i}} for i in ids]
    return HTTPResponse(200, json.dumps({"hits": {"hits": hits}}))


def test_elasticsearch_default_query_and_auth():
    transport = Transport(es_hits("p1", "p2"))
    connector = ElasticsearchConnector(
        "http://es:9200/", "shop", api_key="secret", transport=transport
    )
    assert connector.search(QUERY, 5) == ["p1", "p2"]
    url, headers, body, _ = transport.calls[0]
    assert url == "http://es:9200/shop/_search"
    assert headers["Authorization"] == "ApiKey secret"
    assert body["size"] == 5
    assert body["_source"] is False
    assert body["query"]["multi_match"]["query"] == "red shoes"


def test_elasticsearch_template_id_field_and_basic_auth(monkeypatch):
    monkeypatch.setenv("OPENSEARCH_PASSWORD", "pw")
    template = {
        "query": {"match": {"title": {"query": "{{query}}"}}},
        "size": "{{k}}",
        "post_filter": {"term": {"lang": "{{lang}}"}},
    }
    transport = Transport(es_hits("A", "B", field="sku"))
    connector = OpenSearchConnector(
        "https://os",
        "shop",
        query_template=template,
        id_field="sku",
        username="admin",
        transport=transport,
    )
    assert connector.search(QUERY, 3) == ["A", "B"]
    _, headers, body, _ = transport.calls[0]
    assert headers["Authorization"].startswith("Basic ")
    assert body["size"] == 3
    assert body["query"]["match"]["title"]["query"] == "red shoes"
    assert body["post_filter"]["term"]["lang"] == "en"
    assert body["_source"] == ["sku"]
    assert connector.name == "opensearch"


def test_elasticsearch_with_client():
    class Client:
        def __init__(self):
            self.closed = False

        def search(self, index, **kwargs):
            if "body" in kwargs:
                raise TypeError("body is not supported")
            assert kwargs["size"] == 2
            return {"hits": {"hits": [{"_id": "p9"}]}}

        def close(self):
            self.closed = True

    client = Client()
    connector = ElasticsearchConnector(index="shop", client=client)
    assert connector.search(QUERY, 2) == ["p9"]
    connector.close()
    assert client.closed


def test_elasticsearch_errors():
    with pytest.raises(ConfigError):
        ElasticsearchConnector(None, "shop")
    connector = ElasticsearchConnector(
        "http://es", "shop", transport=Transport(HTTPResponse(200, '{"took": 1}'))
    )
    with pytest.raises(ConnectorError, match=r"hits\.hits"):
        connector.search(QUERY, 1)


def test_algolia_rest_request():
    body = {"hits": [{"objectID": "p1"}, {"objectID": "p2"}, {"title": "no id"}]}
    transport = Transport(HTTPResponse(200, json.dumps(body)))
    connector = AlgoliaConnector(
        "APP", "products", api_key="key", params={"filters": "stock > 0"}, transport=transport
    )
    assert connector.search(QUERY, 10) == ["p1", "p2"]
    url, headers, payload, _ = transport.calls[0]
    assert url == "https://APP-dsn.algolia.net/1/indexes/products/query"
    assert headers["X-Algolia-Application-Id"] == "APP"
    assert headers["X-Algolia-API-Key"] == "key"
    assert payload["hitsPerPage"] == 10
    assert payload["filters"] == "stock > 0"
    assert payload["queryLanguages"] == ["en"]


def test_algolia_client_and_configuration(monkeypatch):
    class Response:
        def to_dict(self):
            return {"hits": [{"object_id": "p3"}]}

    class Client:
        def search_single_index(self, index_name, search_params):
            assert index_name == "products"
            assert search_params["query"] == "red shoes"
            return Response()

    assert AlgoliaConnector(client=Client(), index="products").search(QUERY, 5) == ["p3"]
    monkeypatch.delenv("ALGOLIA_APP_ID", raising=False)
    monkeypatch.delenv("ALGOLIA_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="application id"):
        AlgoliaConnector(index="products")
    monkeypatch.setenv("ALGOLIA_APP_ID", "APP")
    monkeypatch.setenv("ALGOLIA_API_KEY", "key")
    assert AlgoliaConnector(index="products").host == "https://APP-dsn.algolia.net"


def test_post_json_retries_then_fails():
    sleeps = []
    transport = Transport(
        HTTPResponse(503, "busy"),
        urllib.error.URLError("reset"),
        HTTPResponse(200, '{"ok": true}'),
    )
    data = post_json(
        "http://x", {}, {}, timeout=1, max_retries=2, transport=transport, sleep=sleeps.append
    )
    assert data == {"ok": True}
    assert len(sleeps) == 2
    with pytest.raises(ConnectorError, match="HTTP 401"):
        post_json(
            "http://x",
            {},
            {},
            timeout=1,
            max_retries=3,
            transport=Transport(HTTPResponse(401, "denied")),
            sleep=sleeps.append,
        )
    with pytest.raises(ConnectorError, match="invalid JSON"):
        post_json(
            "http://x",
            {},
            {},
            timeout=1,
            max_retries=0,
            transport=Transport(HTTPResponse(200, "<html>")),
        )


def test_fetch_run_collects_rankings_and_failures():
    class Fake(ElasticsearchConnector):
        def search(self, query, k):
            if query.query_id == "bad":
                raise ConnectorError("boom")
            return ["p1", "p2", "p1", "p3"]

    queries = [QUERY, Query("bad", "x"), Query("q2", "y")]
    seen = []
    result = fetch_run(
        Fake("http://es", "shop"), queries, k=2, progress=lambda d, t: seen.append((d, t))
    )
    assert result.run.name == "elasticsearch"
    assert result.run.rankings == {"q1": ["p1", "p2"], "q2": ["p1", "p2"]}
    assert result.failures == {"bad": "boom"}
    assert seen[-1] == (3, 3)
    with pytest.raises(ConfigError):
        fetch_run(Fake("http://es", "shop"), queries, k=0)


def test_helpers():
    filled = fill_template({"a": ["{{query}} now", "{{k}}"], "b": 1}, {"query": "q", "k": 3})
    assert filled == {"a": ["q now", 3], "b": 1}

    class Body:
        def __init__(self):
            self.body = {"x": 1}

    assert to_mapping(Body()) == {"x": 1}
    with pytest.raises(ConnectorError):
        to_mapping(object())
