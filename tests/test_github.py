import json

import pytest

from llm_search_eval.cli import main
from llm_search_eval.errors import LLMSearchEvalError
from llm_search_eval.github import (
    MAX_COMMENT_CHARS,
    GitHubClient,
    GitHubError,
    PullRequestContext,
    build_body,
    context_from_env,
    marker,
    run_url,
    upsert_comment,
)
from llm_search_eval.judges.openai_compat import HTTPResponse

CTX = PullRequestContext("octo/shop", 7)


class FakeGitHub:
    """In-memory issue comments API."""

    def __init__(self, comments=None, fail=None):
        self.comments = list(comments or [])
        self.fail = fail
        self.calls = []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url))
        assert headers["Authorization"] == "Bearer t0ken"
        if self.fail:
            return HTTPResponse(self.fail, json.dumps({"message": "Resource not accessible"}))
        payload = json.loads(body) if body else None
        if method == "GET":
            page = int(url.rsplit("page=", 1)[1])
            chunk = self.comments[(page - 1) * 100 : page * 100]
            return HTTPResponse(200, json.dumps(chunk))
        if method == "POST":
            comment = {"id": 1000 + len(self.comments), "body": payload["body"]}
            comment["html_url"] = f"https://github.com/octo/shop/pull/7#c{comment['id']}"
            self.comments.append(comment)
            return HTTPResponse(201, json.dumps(comment))
        if method == "PATCH":
            cid = int(url.rsplit("/", 1)[1])
            comment = next(c for c in self.comments if c["id"] == cid)
            comment["body"] = payload["body"]
            return HTTPResponse(200, json.dumps({**comment, "html_url": "u"}))
        raise AssertionError(method)


def client(fake):
    return GitHubClient("t0ken", transport=fake)


def test_marker_and_body():
    assert marker("nightly") == "<!-- llm-search-eval:nightly -->"
    with pytest.raises(LLMSearchEvalError, match="invalid comment id"):
        marker("bad id")
    body = build_body("# Report\n", footer="[run](x)")
    assert body.startswith("<!-- llm-search-eval:report -->\n# Report")
    assert body.endswith("[run](x)")
    long = "\n".join(f"| row {i} | value |" for i in range(10_000))
    cut = build_body(long, footer="end")
    assert len(cut) <= MAX_COMMENT_CHARS
    assert "was cut to fit" in cut
    assert cut.endswith("end")
    assert "| row 9999" not in cut


def test_create_then_update_same_comment():
    others = [{"id": i, "body": "looks good"} for i in range(150)]
    fake = FakeGitHub(others)
    first = upsert_comment(client(fake), CTX, "nDCG 0.5")
    assert first.action == "created"
    assert [m for m, _ in fake.calls] == ["GET", "GET", "POST"]
    second = upsert_comment(client(fake), CTX, "nDCG 0.6")
    assert second.action == "updated"
    assert len(fake.comments) == 151
    assert fake.comments[-1]["body"].endswith("nDCG 0.6")
    other_id = upsert_comment(client(fake), CTX, "x", comment_id="nightly")
    assert other_id.action == "created"


def test_permission_errors_are_skipped():
    result = upsert_comment(client(FakeGitHub(fail=403)), CTX, "x")
    assert result.action == "skipped"
    assert "pull-requests: write" in result.reason
    with pytest.raises(GitHubError, match="HTTP 422") as info:
        upsert_comment(client(FakeGitHub(fail=422)), CTX, "x")
    assert info.value.status == 422


def test_client_needs_token():
    with pytest.raises(LLMSearchEvalError, match="token"):
        GitHubClient("")


def test_context_from_env(tmp_path):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 42}}))
    env = {"GITHUB_REPOSITORY": "octo/shop", "GITHUB_EVENT_PATH": str(event)}
    assert context_from_env(env) == PullRequestContext("octo/shop", 42)
    event.write_text(json.dumps({"issue": {"number": 5, "pull_request": {}}}))
    assert context_from_env(env) is None  # an empty pull_request object is not a PR link
    event.write_text(json.dumps({"issue": {"number": 5, "pull_request": {"url": "u"}}}))
    assert context_from_env(env).number == 5
    event.write_text("{}")
    assert context_from_env(env) is None
    env["GITHUB_REF"] = "refs/pull/9/merge"
    env["GITHUB_API_URL"] = "https://ghe.example/api/v3/"
    assert context_from_env(env) == PullRequestContext("octo/shop", 9, "https://ghe.example/api/v3")
    assert context_from_env({}) is None


def test_run_url():
    env = {
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "o/r",
        "GITHUB_RUN_ID": "3",
    }
    assert run_url(env) == "https://github.com/o/r/actions/runs/3"
    assert run_url({}) is None


def test_cli_comment(tmp_path, monkeypatch, capsys):
    for name in ("GITHUB_REPOSITORY", "GITHUB_EVENT_PATH", "GITHUB_REF", "GITHUB_RUN_ID"):
        monkeypatch.delenv(name, raising=False)
    report = tmp_path / "report.md"
    report.write_text("# Search evaluation report\n", encoding="utf-8")
    gate = tmp_path / "gate.md"
    gate.write_text("## Gate passed\n", encoding="utf-8")

    assert main(["comment", str(gate), str(report), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.index("Gate passed") < out.index("Search evaluation report")

    assert main(["comment", str(report)]) == 0
    assert "not a pull request" in capsys.readouterr().err
    assert main(["comment", str(report), "--strict"]) == 2

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert main(["comment", str(report), "--repo", "o/r", "--pr", "1"]) == 0
    assert "GITHUB_TOKEN" in capsys.readouterr().err

    fake = FakeGitHub()
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    monkeypatch.setattr("llm_search_eval.github.urllib_request", fake)
    assert main(["comment", str(report), "--repo", "o/r", "--pr", "1"]) == 0
    assert "created comment" in capsys.readouterr().out
    assert main(["comment", str(tmp_path / "missing.md")]) == 2
