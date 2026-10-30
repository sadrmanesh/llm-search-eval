"""Shared pieces for live search connectors."""

from __future__ import annotations

import json
import logging
import random
import time
import urllib.error
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from llm_search_eval.errors import ConfigError, ConnectorError
from llm_search_eval.http import RequestTransport, urllib_request
from llm_search_eval.judges.openai_compat import HTTPResponse, Transport, urllib_transport
from llm_search_eval.models import Query, Run

log = logging.getLogger(__name__)

_RETRYABLE = frozenset({408, 429, 500, 502, 503, 504})


class SearchConnector(ABC):
    """Sends a query to a live search backend and returns ranked product ids."""

    #: Short backend name, used as the default system name.
    name: str = "search"

    @abstractmethod
    def search(self, query: Query, k: int) -> list[str]:
        """Return up to ``k`` product ids, best first."""

    def close(self) -> None:  # noqa: B027 - optional hook, intentionally empty
        """Release resources such as HTTP sessions."""


@dataclass(slots=True)
class FetchResult:
    run: Run
    failures: dict[str, str] = field(default_factory=dict)


def fetch_run(
    connector: SearchConnector,
    queries: Mapping[str, Query] | Sequence[Query],
    *,
    k: int = 10,
    name: str | None = None,
    concurrency: int = 4,
    progress: Callable[[int, int], None] | None = None,
) -> FetchResult:
    """Query the backend for every query and collect the rankings as a :class:`Run`.

    Queries that fail are left without results and reported in ``failures``,
    so one bad request does not discard a long fetch.
    """
    if k < 1:
        raise ConfigError("k must be a positive integer")
    items = list(queries.values()) if isinstance(queries, Mapping) else list(queries)
    rankings: dict[str, list[str]] = {}
    failures: dict[str, str] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(connector.search, q, k): q for q in items}
        for future in as_completed(futures):
            query = futures[future]
            done += 1
            try:
                ranked = future.result()
            except ConnectorError as exc:
                failures[query.query_id] = str(exc)
                log.warning("%s", exc)
            else:
                rankings[query.query_id] = list(dict.fromkeys(ranked))[:k]
            if progress:
                progress(done, len(items))
    ordered = {q.query_id: rankings[q.query_id] for q in items if q.query_id in rankings}
    return FetchResult(Run(name=name or connector.name, rankings=ordered), failures)


def post_json(
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    *,
    timeout: float,
    max_retries: int,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    what: str = "search request",
) -> Any:
    """POST JSON with retries on rate limits and server errors; return the decoded body."""
    send = transport or urllib_transport
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    all_headers = {"Content-Type": "application/json", **headers}
    last = ""
    for attempt in range(max_retries + 1):
        try:
            response: HTTPResponse = send(url, all_headers, body, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"network error: {exc}"
        else:
            if 200 <= response.status < 300:
                try:
                    return json.loads(response.body)
                except json.JSONDecodeError as exc:
                    raise ConnectorError(f"{what} returned invalid JSON") from exc
            last = f"HTTP {response.status}: {response.body[:300]}"
            if response.status not in _RETRYABLE:
                break
        if attempt < max_retries:
            sleep(min(10.0, 0.5 * 2**attempt) + random.uniform(0, 0.25))
    raise ConnectorError(f"{what} failed: {last}")


def request_json(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Any = None,
    *,
    timeout: float,
    max_retries: int,
    transport: RequestTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    what: str = "search request",
) -> Any:
    """Like :func:`post_json` for any HTTP method; ``payload`` ``None`` sends no body."""
    send = transport or urllib_request
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    all_headers = dict(headers)
    if body is not None:
        all_headers.setdefault("Content-Type", "application/json")
    last = ""
    for attempt in range(max_retries + 1):
        try:
            response: HTTPResponse = send(method, url, all_headers, body, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = f"network error: {exc}"
        else:
            if 200 <= response.status < 300:
                try:
                    return json.loads(response.body)
                except json.JSONDecodeError as exc:
                    raise ConnectorError(f"{what} returned invalid JSON") from exc
            last = f"HTTP {response.status}: {response.body[:300]}"
            if response.status not in _RETRYABLE:
                break
        if attempt < max_retries:
            sleep(min(10.0, 0.5 * 2**attempt) + random.uniform(0, 0.25))
    raise ConnectorError(f"{what} failed: {last}")


_MISSING = object()


def get_path(data: Any, path: str, default: Any = _MISSING) -> Any:
    """Follow a dotted path such as ``data.items`` or ``results.0.hits``.

    Integer segments index into lists. An empty path returns ``data``. Raises
    :class:`KeyError` when the path does not exist and no default is given.
    """
    current = data
    for part in [p for p in path.split(".") if p] if path else []:
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif (
            isinstance(current, list)
            and part.lstrip("-").isdigit()
            and -len(current) <= int(part) < len(current)
        ):
            current = current[int(part)]
        else:
            if default is _MISSING:
                raise KeyError(path)
            return default
    return current


def fill_template(template: Any, values: Mapping[str, Any]) -> Any:
    """Replace ``{{name}}`` placeholders in a JSON-like template.

    A string that is exactly one placeholder takes the value's own type, so
    ``"{{k}}"`` becomes an integer. Placeholders inside longer strings are
    replaced with text.
    """
    if isinstance(template, str):
        for key, value in values.items():
            marker = "{{" + key + "}}"
            if template == marker:
                return value
            template = template.replace(marker, str(value))
        return template
    if isinstance(template, list):
        return [fill_template(item, values) for item in template]
    if isinstance(template, dict):
        return {key: fill_template(item, values) for key, item in template.items()}
    return template


def to_mapping(response: Any) -> Any:
    """Turn client response objects into plain dicts where possible."""
    if isinstance(response, Mapping):
        return response
    for attr in ("body", "raw"):
        value = getattr(response, attr, None)
        if isinstance(value, Mapping):
            return value
    to_dict = getattr(response, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    raise ConnectorError(f"unexpected search response type: {type(response).__name__}")
