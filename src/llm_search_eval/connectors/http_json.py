"""Generic connector for any search service that answers with JSON.

Point it at an internal search API without writing code: describe the
request with a URL and an optional JSON body template, then say where the
result list and each product id live in the response.
"""

from __future__ import annotations

import copy
import os
import re
import urllib.parse
from collections.abc import Mapping
from typing import Any

from llm_search_eval.connectors.base import SearchConnector, fill_template, get_path, request_json
from llm_search_eval.errors import ConfigError, ConnectorError
from llm_search_eval.http import RequestTransport
from llm_search_eval.models import Query

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_METHODS = frozenset({"GET", "POST", "PUT"})


def expand_env(value: str, env: Mapping[str, str] | None = None) -> str:
    """Replace ``${NAME}`` with the environment variable ``NAME``.

    Raises :class:`ConfigError` for a variable that is not set, so a missing
    secret fails fast instead of sending an empty header.
    """
    env = os.environ if env is None else env

    def lookup(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in env:
            raise ConfigError(f"environment variable {name} is not set")
        return env[name]

    return _ENV.sub(lookup, value)


class HTTPJSONConnector(SearchConnector):
    """Calls a JSON search API described by templates.

    * ``url``: may contain ``{{query}}``, ``{{k}}``, ``{{lang}}`` and
      ``{{query_id}}``; values are URL-encoded, so
      ``https://api.example.com/search?q={{query}}&size={{k}}`` works.
    * ``body``: JSON template sent with POST or PUT. A string that is exactly
      ``"{{k}}"`` becomes a number.
    * ``headers``: header values may use ``${ENV_VAR}`` for secrets.
    * ``results_path``: dotted path to the result list, for example
      ``data.items`` (empty when the response is the list itself).
    * ``id_path``: dotted path to the product id inside one result, for
      example ``id`` or ``document.sku``.
    """

    name = "http"

    def __init__(
        self,
        url: str,
        *,
        method: str = "GET",
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        results_path: str = "results",
        id_path: str = "id",
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: RequestTransport | None = None,
    ) -> None:
        if not url:
            raise ConfigError("http connector needs a url")
        self.method = method.upper()
        if self.method not in _METHODS:
            raise ConfigError(f"http connector method must be one of {', '.join(sorted(_METHODS))}")
        if body is not None and self.method == "GET":
            raise ConfigError("a request body needs --method POST or PUT")
        if not id_path:
            raise ConfigError("http connector needs an id path")
        self.url = url
        self.body = copy.deepcopy(dict(body)) if body is not None else None
        self.headers = {key: expand_env(value) for key, value in (headers or {}).items()}
        self.results_path = results_path
        self.id_path = id_path
        self.timeout = timeout
        self.max_retries = max_retries
        self.transport = transport

    def _values(self, query: Query, k: int) -> dict[str, Any]:
        return {"query": query.text, "k": k, "lang": query.lang or "", "query_id": query.query_id}

    def build_url(self, query: Query, k: int) -> str:
        url = self.url
        for key, value in self._values(query, k).items():
            url = url.replace("{{" + key + "}}", urllib.parse.quote(str(value), safe=""))
        return url

    def build_body(self, query: Query, k: int) -> Any:
        if self.body is None:
            return {} if self.method != "GET" else None
        return fill_template(self.body, self._values(query, k))

    def search(self, query: Query, k: int) -> list[str]:
        data = request_json(
            self.method,
            self.build_url(query, k),
            {"Accept": "application/json", **self.headers},
            self.build_body(query, k),
            timeout=self.timeout,
            max_retries=self.max_retries,
            transport=self.transport,
            what=f"http search for query {query.query_id!r}",
        )
        try:
            results = get_path(data, self.results_path)
        except KeyError as exc:
            raise ConnectorError(
                f"response for query {query.query_id!r} has no {self.results_path!r}"
            ) from exc
        if not isinstance(results, list):
            raise ConnectorError(
                f"{self.results_path or 'the response'} for query {query.query_id!r} is not a list"
            )
        ids: list[str] = []
        for item in results:
            value = get_path(item, self.id_path, None)
            if value is not None and not isinstance(value, Mapping | list):
                ids.append(str(value))
        return ids
