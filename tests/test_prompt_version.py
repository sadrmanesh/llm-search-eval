"""Judge prompt versions and hashes in fingerprints, caches, and reports."""

from __future__ import annotations

import json
import re

from llm_search_eval import EvaluationConfig, evaluate
from llm_search_eval.html_report import render_html
from llm_search_eval.judges import JudgmentCache, MockJudge, OpenAICompatibleJudge, prompts
from llm_search_eval.judges.cache import cache_key
from llm_search_eval.judges.openai_compat import HTTPResponse
from llm_search_eval.judges.pairwise import MockPairwiseJudge, OpenAIPairwiseJudge
from llm_search_eval.judges.panel import JudgePanel
from llm_search_eval.models import Product, Query, Run
from llm_search_eval.pairwise import PairwiseCache
from llm_search_eval.report import render_markdown, write_reports

HASH = re.compile(r"^[0-9a-f]{12}$")


def reply(content: str):
    def transport(url, headers, payload, timeout):
        body = {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }
        return HTTPResponse(200, json.dumps(body))

    return transport


def openai_judge(**kwargs) -> OpenAICompatibleJudge:
    kwargs.setdefault("api_key", "k")
    kwargs.setdefault("model", "gpt-test")
    kwargs.setdefault("transport", reply('{"relevance": 3, "reason": "match"}'))
    return OpenAICompatibleJudge(sleep=lambda _: None, **kwargs)


def test_prompt_hashes_are_stable_and_track_the_template_text():
    assert HASH.match(prompts.PROMPT_HASH)
    assert HASH.match(prompts.PAIRWISE_PROMPT_HASH)
    assert prompts.PROMPT_HASH != prompts.PAIRWISE_PROMPT_HASH
    expected = prompts.prompt_hash(prompts.system_prompt(), prompts.USER_PROMPT_TEMPLATE)
    assert expected == prompts.PROMPT_HASH
    edited = prompts.prompt_hash(prompts.system_prompt() + " ", prompts.USER_PROMPT_TEMPLATE)
    assert edited != prompts.PROMPT_HASH


def test_user_prompt_text_is_unchanged_by_the_template_constant():
    query = Query("q", "red {shoes}", "fa")
    product = Product("p", "Red shoes")
    text = prompts.user_prompt(query, product)
    assert text == (
        "Query language: Persian (Farsi)\nSearch query: red {shoes}\n\n"
        f"Product:\n{product.to_text(2000)}"
    )
    pairwise = prompts.pairwise_user_prompt(query, [product], [])
    assert pairwise.endswith("Results A:\n1. Title: Red shoes\n\nResults B:\n(no results)")


def test_judge_info_names_provider_model_and_prompt():
    judge = openai_judge(base_url="http://localhost:11434/v1")
    assert judge.info == {
        "judge": "openai:gpt-test",
        "provider": "localhost:11434",
        "model": "gpt-test",
        "prompt_version": prompts.PROMPT_VERSION,
        "prompt_hash": prompts.PROMPT_HASH,
    }
    assert judge.fingerprint.endswith(f":{prompts.PROMPT_VERSION}:{prompts.PROMPT_HASH}")
    assert MockJudge().info["provider"] == "mock"
    assert MockJudge().info["prompt_hash"] is None

    pairwise = OpenAIPairwiseJudge(client=openai_judge())
    assert pairwise.info["provider"] == "api.openai.com"
    assert pairwise.info["prompt_version"] == prompts.PAIRWISE_PROMPT_VERSION
    assert pairwise.info["prompt_hash"] == prompts.PAIRWISE_PROMPT_HASH
    assert pairwise.fingerprint.endswith(prompts.PAIRWISE_PROMPT_HASH)

    panel = JudgePanel([openai_judge(), MockJudge()])
    members = panel.info["members"]
    assert [m["judge"] for m in members] == panel.labels
    assert members[0]["prompt_hash"] == prompts.PROMPT_HASH


def test_cached_judgments_from_another_prompt_are_not_reused(tmp_path, monkeypatch):
    path = tmp_path / "cache.jsonl"
    query, product = Query("q1", "red shoes", "en"), Product("p1", "Red shoes")
    old = openai_judge()
    cache = JudgmentCache(path)
    cache.put(cache_key(old.fingerprint, query, product), old.judge(query, product), judge=old.info)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["judge"]["prompt_version"] == prompts.PROMPT_VERSION
    assert record["judge"]["prompt_hash"] == prompts.PROMPT_HASH
    assert record["judge"]["model"] == "gpt-test"

    reloaded = JudgmentCache(path)
    assert reloaded.get(cache_key(openai_judge().fingerprint, query, product)) is not None
    import llm_search_eval.judges.openai_compat as compat

    monkeypatch.setattr(compat, "PROMPT_HASH", "0123456789ab")
    assert reloaded.get(cache_key(openai_judge().fingerprint, query, product)) is None
    monkeypatch.setattr(compat, "PROMPT_VERSION", "relevance-v2")
    assert reloaded.get(cache_key(openai_judge().fingerprint, query, product)) is None


def test_reports_record_the_judge_and_pairwise_prompt(tmp_path, tiny_dataset):
    runs = [
        Run("a", {"q1": ["a", "b"], "q2": ["d"]}),
        Run("b", {"q1": ["c", "a"], "q2": ["c"]}),
    ]
    judge = JudgePanel([openai_judge(), MockJudge()])
    pairwise_cache = PairwiseCache(tmp_path / "pairwise.jsonl")
    cache = JudgmentCache(tmp_path / "judgments.jsonl")
    report = evaluate(
        tiny_dataset,
        runs,
        EvaluationConfig(),
        judge=judge,
        cache=cache,
        pairwise_judge=OpenAIPairwiseJudge(client=openai_judge(transport=reply('{"winner": "A"}'))),
        pairwise_cache=pairwise_cache,
    )
    data = report.to_dict()
    judging = data["judging"]
    assert judging["provider"] == "panel"
    assert [m["prompt_hash"] for m in judging["panel"]["judges"]] == [prompts.PROMPT_HASH, None]
    pw = data["pairwise"]
    assert pw["prompt_version"] == prompts.PAIRWISE_PROMPT_VERSION
    assert pw["prompt_hash"] == prompts.PAIRWISE_PROMPT_HASH
    assert pw["model"] == "gpt-test"
    assert pw["comparisons"][0]["prompt_hash"] == prompts.PAIRWISE_PROMPT_HASH

    md = render_markdown(report)
    assert f"`{prompts.PROMPT_HASH}`" in md
    assert (
        f"Model `gpt-test`, provider `api.openai.com`, prompt `{prompts.PAIRWISE_PROMPT_VERSION}`"
        in md
    )
    html = render_html(report)
    assert "Prompt hash" in html
    assert prompts.PAIRWISE_PROMPT_HASH in html

    write_reports(report, tmp_path / "out", formats=("json",))
    saved = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert saved["judging"]["panel"]["judges"][0]["prompt_version"] == prompts.PROMPT_VERSION
    for line in (tmp_path / "judgments.jsonl").read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["judge"]["members"][0]["prompt_hash"] == prompts.PROMPT_HASH
    lines = (tmp_path / "pairwise.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines
    assert all(
        json.loads(line)["judge"]["prompt_hash"] == prompts.PAIRWISE_PROMPT_HASH for line in lines
    )


def test_mock_pairwise_has_no_prompt():
    info = MockPairwiseJudge().info
    assert info["provider"] == "mock"
    assert info["prompt_version"] is None
