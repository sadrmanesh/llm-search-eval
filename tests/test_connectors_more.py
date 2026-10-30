"""Meilisearch, Typesense and generic HTTP/JSON connectors, with fake transports."""

from __future__ import annotations

import json
import urllib.error

import pytest

from llm_search_eval.cli import main
from llm_search_eval.connectors import (
    HTTPJSONConnector,
    MeilisearchConnector,
    TypesenseConnector,
)
from llm_search_eval.connectors.base import get_path, request_json
from llm_search_eval.connectors.http_json import expand_env
from llm_search_eval.errors import ConfigError, ConnectorError
from llm_search_eval.judges.openai_compat import HTTPResponse
from llm_search_eval.models import Query

QUERY = Query("q1", "کفش قرمز", "fa")


class Post:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, json.loads(payload)))
        return self.responses.pop(0)


class Request:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, None if body is None else json.loads(body)))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok(data):
    return HTTPResponse(200, json.dumps(data))


def test_meilisearch(monkeypatch):
    monkeypatch.delenv("MEILI_URL", raising=False)
    monkeypatch.delenv("MEILI_API_KEY", raising=False)
    monkeypatch.setenv("MEILISEARCH_API_KEY", "search-key")
    transport = Post(ok({"hits": [{"sku": "p1"}, {"sku": 2}, {"title": "no id"}]}))
    connector = MeilisearchConnector(
        index="shop",
        id_field="sku",
        params={"filter": "stock > 0", "limit": 99},
        transport=transport,
    )
    assert connector.search(QUERY, 3) == ["p1", "2"]
    url, headers, body = transport.calls[0]
    assert url == "http://localhost:7700/indexes/shop/search"
    assert headers["Authorization"] == "Bearer search-key"
    assert body == {
        "attributesToRetrieve": ["sku"],
        "filter": "stock > 0",
        "limit": 3,
        "q": "کفش قرمز",
    }
    monkeypatch.delenv("MEILISEARCH_API_KEY")
    open_server = MeilisearchConnector("http://meili:7700/", "shop", transport=Post(ok({})))
    with pytest.raises(ConnectorError, match="no hits"):
        open_server.search(QUERY, 3)
    with pytest.raises(ConfigError, match="index"):
        MeilisearchConnector(index="")


def test_typesense(monkeypatch):
    monkeypatch.setenv("TYPESENSE_API_KEY", "ts-key")
    hits = [{"document": {"id": "p1"}}, {"document": {"id": "p2"}}, {"document": {}}]
    transport = Post(ok({"results": [{"hits": hits}]}))
    connector = TypesenseConnector(
        "http://ts:8108",
        "products",
        query_by=["title", " brand "],
        params={"filter_by": "in_stock:true", "per_page": 1},
        transport=transport,
    )
    assert connector.search(QUERY, 5) == ["p1", "p2"]
    url, headers, body = transport.calls[0]
    assert url == "http://ts:8108/multi_search"
    assert headers["X-TYPESENSE-API-KEY"] == "ts-key"
    search = body["searches"][0]
    assert search["query_by"] == "title,brand"
    assert search["per_page"] == 5
    assert search["filter_by"] == "in_stock:true"
    assert search["include_fields"] == "id"

    failing = TypesenseConnector(
        collection="p", transport=Post(ok({"results": [{"code": 404, "error": "Not found"}]}))
    )
    with pytest.raises(ConnectorError, match="HTTP 404: Not found"):
        failing.search(QUERY, 5)
    with pytest.raises(ConnectorError, match="no results"):
        TypesenseConnector(collection="p", transport=Post(ok({"results": []}))).search(QUERY, 5)
    with pytest.raises(ConfigError, match="at most 250"):
        connector.build_search(QUERY, 500)
    with pytest.raises(ConfigError, match="query_by"):
        TypesenseConnector(query_by=" , ")
    monkeypatch.delenv("TYPESENSE_API_KEY")
    with pytest.raises(ConfigError, match="API key"):
        TypesenseConnector()


def test_http_get_with_url_template(monkeypatch):
    monkeypatch.setenv("SEARCH_TOKEN", "abc")
    transport = Request(
        ok({"data": {"items": [{"product": {"sku": "p1"}}, {"product": {"sku": 7}}]}})
    )
    connector = HTTPJSONConnector(
        "https://api.example.com/search?q={{query}}&size={{k}}&lang={{lang}}",
        headers={"Authorization": "Bearer ${SEARCH_TOKEN}"},
        results_path="data.items",
        id_path="product.sku",
        transport=transport,
    )
    assert connector.search(QUERY, 10) == ["p1", "7"]
    method, url, headers, body = transport.calls[0]
    assert method == "GET"
    assert body is None
    assert url.startswith("https://api.example.com/search?q=%DA%A9%D9%81%D8%B4%20")
    assert url.endswith("&size=10&lang=fa")
    assert headers["Authorization"] == "Bearer abc"


def test_http_post_body_and_list_response():
    transport = Request(ok([{"id": "a"}, {"id": {"nested": 1}}, {"id": "b"}]))
    connector = HTTPJSONConnector(
        "http://search.local/query",
        method="post",
        body={"text": "{{query}}", "limit": "{{k}}"},
        results_path="",
        transport=transport,
    )
    assert connector.search(QUERY, 4) == ["a", "b"]
    method, _, headers, body = transport.calls[0]
    assert method == "POST"
    assert body == {"text": "کفش قرمز", "limit": 4}
    assert headers["Content-Type"] == "application/json"


def test_http_errors(monkeypatch):
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)
    with pytest.raises(ConfigError, match="NOT_SET_ANYWHERE"):
        HTTPJSONConnector("http://x", headers={"X-Key": "${NOT_SET_ANYWHERE}"})
    with pytest.raises(ConfigError, match="method"):
        HTTPJSONConnector("http://x", method="DELETE")
    with pytest.raises(ConfigError, match="body needs"):
        HTTPJSONConnector("http://x", body={"q": "{{query}}"})
    with pytest.raises(ConfigError, match="url"):
        HTTPJSONConnector("")
    missing = HTTPJSONConnector("http://x", transport=Request(ok({"hits": []})))
    with pytest.raises(ConnectorError, match="no 'results'"):
        missing.search(QUERY, 3)
    not_list = HTTPJSONConnector(
        "http://x", results_path="hits", transport=Request(ok({"hits": 3}))
    )
    with pytest.raises(ConnectorError, match="not a list"):
        not_list.search(QUERY, 3)


def test_request_json_retries():
    sleeps = []
    transport = Request(
        urllib.error.URLError("down"),
        HTTPResponse(503, "busy"),
        ok({"fine": True}),
    )
    data = request_json(
        "GET", "http://x", {}, timeout=1, max_retries=2, transport=transport, sleep=sleeps.append
    )
    assert data == {"fine": True}
    assert len(sleeps) == 2
    with pytest.raises(ConnectorError, match="HTTP 400"):
        request_json(
            "GET",
            "http://x",
            {},
            timeout=1,
            max_retries=3,
            transport=Request(HTTPResponse(400, "bad")),
        )
    with pytest.raises(ConnectorError, match="invalid JSON"):
        request_json(
            "GET",
            "http://x",
            {},
            timeout=1,
            max_retries=0,
            transport=Request(HTTPResponse(200, "<")),
        )


def test_get_path_and_expand_env():
    data = {"results": [{"hits": [1, 2]}], "a": {"b": None}}
    assert get_path(data, "results.0.hits") == [1, 2]
    assert get_path(data, "results.-1.hits.1") == 2
    assert get_path(data, "") is data
    assert get_path(data, "a.b") is None
    assert get_path(data, "results.5", "dflt") == "dflt"
    with pytest.raises(KeyError):
        get_path(data, "nope")
    assert expand_env("x ${A} ${A}", {"A": "1"}) == "x 1 1"


def test_cli_fetch_new_backends(tmp_path, example_dir, monkeypatch, capsys):
    queries = str(example_dir / "queries.jsonl")
    seen = {}

    def fake_search(self, query, k):
        seen[type(self).__name__] = self
        return [f"{query.query_id}-x"]

    for cls in (MeilisearchConnector, TypesenseConnector, HTTPJSONConnector):
        monkeypatch.setattr(cls, "search", fake_search)
    monkeypatch.setenv("TYPESENSE_API_KEY", "k")
    monkeypatch.setenv("SHOP_KEY", "s3cret")
    out = str(tmp_path / "run.jsonl")
    assert (
        main(["fetch", "-q", queries, "--backend", "meilisearch", "--index", "p", "-o", out]) == 0
    )
    assert main(
        ["fetch", "-q", queries, "--backend", "typesense", "--index", "p", "--query-by",
         "title,brand", "--params", '{"filter_by": "x:1"}', "-o", out]
    ) == 0  # fmt: skip
    assert seen["TypesenseConnector"].query_by == "title,brand"
    body = tmp_path / "body.json"
    body.write_text('{"q": "{{query}}", "n": "{{k}}"}', encoding="utf-8")
    assert main(
        ["fetch", "-q", queries, "--backend", "http", "--url", "http://x/s", "--method", "POST",
         "--body", str(body), "--header", "X-Key: ${SHOP_KEY}", "--results-path", "items",
         "--id-path", "sku", "-o", out]
    ) == 0  # fmt: skip
    connector = seen["HTTPJSONConnector"]
    assert connector.headers == {"X-Key": "s3cret"}
    assert connector.results_path == "items"
    assert main(["fetch", "-q", queries, "--backend", "http", "-o", out]) == 2
    assert main(["fetch", "-q", queries, "--backend", "meilisearch", "-o", out]) == 2
    assert main(
        ["fetch", "-q", queries, "--backend", "http", "--url", "u", "--header", "bad", "-o", out]
    ) == 2  # fmt: skip
    assert (
        main(["fetch", "-q", queries, "--backend", "elasticsearch", "--index", "p", "-o", out]) == 2
    )
    err = capsys.readouterr().err
    assert "--url is required" in err
    assert "--index is required" in err
