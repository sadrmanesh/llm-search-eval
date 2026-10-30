"""Relevance judge backed by any OpenAI-compatible chat completions endpoint.

Works with OpenAI, Azure OpenAI compatible gateways, OpenRouter, vLLM, Ollama,
LM Studio, and other servers that implement ``POST /chat/completions``. Uses only
the standard library so the package has no runtime dependencies.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from llm_search_eval.errors import ConfigError, JudgeError
from llm_search_eval.judges.base import Judge, Judgment, TokenUsage, register_judge
from llm_search_eval.judges.prompts import PROMPT_VERSION, build_messages
from llm_search_eval.models import MAX_RELEVANCE, MIN_RELEVANCE, Product, Query

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    status: int
    body: str


#: ``(url, headers, payload, timeout) -> HTTPResponse``; injectable for testing.
Transport = Callable[[str, dict[str, str], bytes, float], HTTPResponse]


def urllib_transport(
    url: str, headers: dict[str, str], payload: bytes, timeout: float
) -> HTTPResponse:
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return HTTPResponse(resp.status, resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return HTTPResponse(exc.code, exc.read().decode("utf-8", errors="replace"))


_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
_BARE_GRADE = re.compile(r"^\s*([0-3])\s*$")


def parse_judgment(content: str) -> Judgment:
    """Extract a :class:`Judgment` from a model reply.

    Accepts plain JSON, JSON wrapped in prose or Markdown code fences, and a bare
    digit. Raises :class:`JudgeError` for anything else.
    """
    bare = _BARE_GRADE.match(content)
    if bare:
        return Judgment(int(bare.group(1)))
    match = _JSON_OBJECT.search(content)
    if not match:
        raise JudgeError(f"judge reply contains no JSON object: {content[:200]!r}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeError(f"judge reply is not valid JSON: {content[:200]!r}") from exc
    raw = data.get("relevance", data.get("score", data.get("grade")))
    try:
        number = float(raw)
    except (TypeError, ValueError) as exc:
        raise JudgeError(f"judge reply has no numeric relevance: {content[:200]!r}") from exc
    if not number.is_integer() or not MIN_RELEVANCE <= number <= MAX_RELEVANCE:
        raise JudgeError(f"judge relevance out of range: {raw!r}")
    return Judgment(int(number), str(data.get("reason", "")).strip())


@register_judge("openai")
class OpenAICompatibleJudge(Judge):
    """LLM-as-judge over the OpenAI chat completions protocol.

    Configuration falls back to the ``OPENAI_BASE_URL`` and ``OPENAI_API_KEY``
    environment variables (the key variable name is configurable).
    """

    name = "openai"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        temperature: float = 0.0,
        timeout: float = 60.0,
        max_retries: int = 4,
        json_mode: bool = True,
        max_product_chars: int = 2000,
        extra_headers: dict[str, str] | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = model
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip(
            "/"
        )
        self.api_key = api_key if api_key is not None else os.environ.get(api_key_env)
        if not self.api_key and _requires_key(self.base_url):
            raise ConfigError(
                f"no API key: set {api_key_env} or pass api_key (local servers do not need one)"
            )
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.json_mode = json_mode
        self.max_product_chars = max_product_chars
        self.extra_headers = dict(extra_headers or {})
        self._transport = transport or urllib_transport
        self._sleep = sleep

    @property
    def fingerprint(self) -> str:
        return f"openai:{self.base_url}:{self.model}:t={self.temperature}:{PROMPT_VERSION}"

    @property
    def label(self) -> str:
        return f"openai:{self.model}"

    def _payload(self, query: Query, product: Product) -> dict[str, Any]:
        return self._chat_payload(build_messages(query, product, self.max_product_chars))

    def _chat_payload(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def judge(self, query: Query, product: Product) -> Judgment:
        content, usage = self.complete(
            build_messages(query, product, self.max_product_chars),
            what=f"{query.query_id}/{product.product_id}",
        )
        return replace(parse_judgment(content), usage=usage)

    def complete(
        self, messages: list[dict[str, Any]], *, what: str = "request"
    ) -> tuple[str, TokenUsage | None]:
        """Send ``messages`` and return the reply text and token usage.

        Retries rate limits, server errors and network failures with backoff.
        Other judges (for example the pairwise judge) reuse this method.
        """
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = json.dumps(self._chat_payload(messages), ensure_ascii=False).encode("utf-8")

        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                response = self._transport(url, headers, body, self.timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = f"network error: {exc}"
            else:
                if response.status == 200:
                    return _message_content(response.body, self.model)
                last_error = f"HTTP {response.status}: {response.body[:300]}"
                if response.status not in _RETRYABLE_STATUS:
                    break
            if attempt < self.max_retries:
                self._sleep(min(30.0, 2**attempt) + random.uniform(0, 0.5))
        raise JudgeError(f"judge request failed for {what}: {last_error}")


def _requires_key(base_url: str) -> bool:
    return not re.match(
        r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:\d+)?(/|$)", base_url
    )


def _message_content(body: str, model: str) -> tuple[str, TokenUsage | None]:
    try:
        data = json.loads(body)
        content = data["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise JudgeError(f"unexpected chat completions response: {body[:300]!r}") from exc
    if not isinstance(content, str):
        raise JudgeError("chat completions response has no text content")
    return content, _parse_usage(data, model)


def _parse_usage(data: Any, model: str) -> TokenUsage | None:
    """Read the ``usage`` block. The billed model name wins over the requested one."""
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None
    try:
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    except (TypeError, ValueError):
        return None
    billed = data.get("model")
    return TokenUsage(
        model=billed if isinstance(billed, str) and billed else model,
        prompt_tokens=prompt,
        completion_tokens=completion,
    )
