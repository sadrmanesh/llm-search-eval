from __future__ import annotations

import json
import threading

import pytest

from llm_search_eval.errors import ConfigError, JudgeError
from llm_search_eval.judges import (
    Judge,
    Judgment,
    JudgmentCache,
    MockJudge,
    OpenAICompatibleJudge,
    available_judges,
    create_judge,
    parse_judgment,
    register_judge,
)
from llm_search_eval.judges.cache import cache_key
from llm_search_eval.judges.openai_compat import HTTPResponse
from llm_search_eval.judges.prompts import PROMPT_VERSION, build_messages
from llm_search_eval.models import Product, Query

QUERY = Query("q1", "wireless noise cancelling headphones", "en")
PRODUCT = Product("p1", "Sony WH-1000XM5 Wireless Noise Cancelling Headphones", brand="Sony")


class FakeTransport:
    """Replays canned responses and records requests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.lock = threading.Lock()

    def __call__(self, url, headers, payload, timeout):
        with self.lock:
            self.requests.append((url, headers, json.loads(payload), timeout))
            item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def chat(content: str, status: int = 200) -> HTTPResponse:
    body = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]})
    return HTTPResponse(status, body)


def make_judge(transport, **kwargs) -> OpenAICompatibleJudge:
    kwargs.setdefault("api_key", "test-key")
    return OpenAICompatibleJudge(transport=transport, sleep=lambda _: None, **kwargs)


# Mock judge -------------------------------------------------------------------


def test_mock_judge_grades_by_term_coverage():
    judge = MockJudge()
    assert judge.judge(QUERY, PRODUCT).relevance == 3
    partial = Product("p2", "Wireless Mouse")
    assert judge.judge(QUERY, partial).relevance == 1
    assert judge.judge(QUERY, Product("p3", "Coffee mug")).relevance == 0
    half = Product("p4", "Noise cancelling earbuds")
    assert judge.judge(QUERY, half).relevance == 2


def test_mock_judge_handles_persian_spelling_variants():
    judge = MockJudge()
    query = Query("q", "کفش ورزشی", "fa")
    product = Product("p", "كفش ورزشي نايک")  # Arabic kaf and yeh
    assert judge.judge(query, product).relevance == 3


def test_mock_judge_is_deterministic_and_handles_empty_query():
    judge = MockJudge()
    assert judge.judge(QUERY, PRODUCT) == judge.judge(QUERY, PRODUCT)
    assert judge.judge(Query("q", "the"), PRODUCT).relevance == 0


def test_mock_judge_description_option_changes_fingerprint():
    product = Product("p", "Item", description="wireless noise cancelling headphones")
    assert MockJudge().judge(QUERY, product).relevance == 0
    assert MockJudge(include_description=True).judge(QUERY, product).relevance == 3
    assert MockJudge().fingerprint != MockJudge(include_description=True).fingerprint


# Registry ---------------------------------------------------------------------


def test_registry_lists_builtins():
    assert {"mock", "openai"} <= set(available_judges())
    assert isinstance(create_judge("mock"), MockJudge)


def test_create_judge_drops_none_options():
    assert isinstance(create_judge("mock", include_description=None), MockJudge)


def test_create_judge_errors():
    with pytest.raises(ConfigError, match="unknown judge"):
        create_judge("nope")
    with pytest.raises(ConfigError, match="cannot load"):
        create_judge("not_a_module_xyz:Judge")
    with pytest.raises(ConfigError, match="invalid options"):
        create_judge("mock", bogus=1)
    with pytest.raises(ConfigError, match="did not produce"):
        create_judge("builtins:dict")


class ConstantJudge(Judge):
    name = "constant"

    def __init__(self, grade: int = 2) -> None:
        self.grade = grade

    def judge(self, query, product):
        return Judgment(self.grade, "constant")


def test_custom_judge_by_import_path_and_decorator():
    judge = create_judge(f"{__name__}:ConstantJudge", grade=1)
    assert judge.judge(QUERY, PRODUCT).relevance == 1
    register_judge("constant-test")(ConstantJudge)
    assert create_judge("constant-test").judge(QUERY, PRODUCT).relevance == 2
    assert judge.fingerprint == "constant"


# Response parsing -------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "grade", "reason"),
    [
        ('{"relevance": 3, "reason": "exact"}', 3, "exact"),
        ('Sure!\n```json\n{"relevance": 2, "reason": "close"}\n```', 2, "close"),
        ('{"score": 1}', 1, ""),
        ('{"grade": "0"}', 0, ""),
        ("2", 2, ""),
        ('{"relevance": 3.0}', 3, ""),
    ],
)
def test_parse_judgment_accepts_common_shapes(content, grade, reason):
    assert parse_judgment(content) == Judgment(grade, reason)


@pytest.mark.parametrize(
    "content",
    ["no json here", '{"relevance": 7}', '{"relevance": "high"}', "{not json}", '{"x": 1}'],
)
def test_parse_judgment_rejects_invalid(content):
    with pytest.raises(JudgeError):
        parse_judgment(content)


# OpenAI-compatible judge ------------------------------------------------------


def test_openai_judge_builds_request():
    transport = FakeTransport([chat('{"relevance": 3, "reason": "match"}')])
    judge = make_judge(transport, model="m-1", base_url="https://llm.example/v1/")
    assert judge.judge(QUERY, PRODUCT) == Judgment(3, "match")
    url, headers, payload, _ = transport.requests[0]
    assert url == "https://llm.example/v1/chat/completions"
    assert headers["Authorization"] == "Bearer test-key"
    assert payload["model"] == "m-1"
    assert payload["temperature"] == 0.0
    assert payload["response_format"] == {"type": "json_object"}
    assert "Sony WH-1000XM5" in payload["messages"][1]["content"]


def test_openai_judge_without_json_mode():
    transport = FakeTransport([chat("1")])
    judge = make_judge(transport, json_mode=False)
    assert judge.judge(QUERY, PRODUCT).relevance == 1
    assert "response_format" not in transport.requests[0][2]


def test_openai_judge_retries_transient_errors():
    transport = FakeTransport(
        [HTTPResponse(429, "slow down"), OSError("reset"), chat('{"relevance": 2}')]
    )
    judge = make_judge(transport, max_retries=3)
    assert judge.judge(QUERY, PRODUCT).relevance == 2
    assert len(transport.requests) == 3


def test_openai_judge_gives_up_after_retries():
    transport = FakeTransport([HTTPResponse(503, "down")] * 3)
    with pytest.raises(JudgeError, match="HTTP 503"):
        make_judge(transport, max_retries=2).judge(QUERY, PRODUCT)
    assert len(transport.requests) == 3


def test_openai_judge_does_not_retry_client_errors():
    transport = FakeTransport([HTTPResponse(401, "bad key")])
    with pytest.raises(JudgeError, match="HTTP 401"):
        make_judge(transport, max_retries=5).judge(QUERY, PRODUCT)
    assert len(transport.requests) == 1


def test_openai_judge_rejects_unexpected_body():
    transport = FakeTransport([HTTPResponse(200, '{"choices": []}')])
    with pytest.raises(JudgeError, match="unexpected"):
        make_judge(transport).judge(QUERY, PRODUCT)


def test_openai_judge_requires_key_for_remote_hosts(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        OpenAICompatibleJudge()
    local = OpenAICompatibleJudge(base_url="http://localhost:11434/v1")
    assert local.api_key is None


def test_openai_judge_reads_environment(monkeypatch):
    monkeypatch.setenv("MY_KEY", "env-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    transport = FakeTransport([chat('{"relevance": 0}')])
    judge = OpenAICompatibleJudge(api_key_env="MY_KEY", transport=transport)
    judge.judge(QUERY, PRODUCT)
    url, headers, _, _ = transport.requests[0]
    assert url.startswith("https://gateway.example/v1")
    assert headers["Authorization"] == "Bearer env-key"


def test_openai_fingerprint_tracks_model_and_prompt():
    a = make_judge(FakeTransport([]), model="a")
    b = make_judge(FakeTransport([]), model="b")
    assert a.fingerprint != b.fingerprint
    assert PROMPT_VERSION in a.fingerprint


def test_prompt_mentions_language_and_scale():
    query = Query("q", "هدفون بی سیم", "fa")
    system, user = build_messages(query, PRODUCT)
    assert "3 = exact match" in system["content"]
    assert "Persian" in user["content"]
    assert "هدفون بی سیم" in user["content"]


# Cache ------------------------------------------------------------------------


def test_cache_roundtrip(tmp_path):
    path = tmp_path / "cache.jsonl"
    key = cache_key("judge-a", QUERY, PRODUCT)
    cache = JudgmentCache(path)
    assert cache.get(key) is None
    cache.put(key, Judgment(3, "great"), query_id="q1", product_id="p1")
    reloaded = JudgmentCache(path)
    assert len(reloaded) == 1
    assert reloaded.get(key) == Judgment(3, "great")


def test_cache_key_depends_on_content_and_fingerprint():
    base = cache_key("a", QUERY, PRODUCT)
    assert base == cache_key("a", QUERY, PRODUCT)
    assert base != cache_key("b", QUERY, PRODUCT)
    edited = Product("p1", PRODUCT.title, description="new")
    assert base != cache_key("a", QUERY, edited)


def test_cache_skips_corrupt_lines(tmp_path, caplog):
    path = tmp_path / "cache.jsonl"
    path.write_text('{"key": "k", "relevance": 2}\nnot json\n{"key": "x"}\n', encoding="utf-8")
    cache = JudgmentCache(path)
    assert len(cache) == 1
    assert "corrupt" in caplog.text


def test_in_memory_cache_writes_nothing(tmp_path):
    cache = JudgmentCache()
    cache.put("k", Judgment(1))
    assert cache.get("k") == Judgment(1)
    assert list(tmp_path.iterdir()) == []
