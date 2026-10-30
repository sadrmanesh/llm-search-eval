"""Minimal HTTP helper for requests that are not plain POSTs."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable

from llm_search_eval.judges.openai_compat import HTTPResponse

#: ``(method, url, headers, body, timeout) -> HTTPResponse``; injectable for tests.
RequestTransport = Callable[[str, str, dict[str, str], bytes | None, float], HTTPResponse]


def urllib_request(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> HTTPResponse:
    """Send one request with the standard library. HTTP errors become responses."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return HTTPResponse(resp.status, resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return HTTPResponse(exc.code, exc.read().decode("utf-8", errors="replace"))
