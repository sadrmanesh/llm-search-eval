"""Post or update a pull request comment with the evaluation summary.

The comment carries a hidden marker, so later runs edit the same comment
instead of adding a new one each time. Only the standard library is used.

The token needs permission to write pull request comments. In a workflow that
means ``permissions: pull-requests: write``. Pull requests from forks get a
read-only token on the ``pull_request`` event; then the request fails with 403
and :func:`upsert_comment` reports that without raising, so the build does not
fail because of a missing comment.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_search_eval.errors import LLMSearchEvalError
from llm_search_eval.http import RequestTransport, urllib_request

#: GitHub rejects issue comments longer than this.
MAX_COMMENT_CHARS = 65_536
DEFAULT_API_URL = "https://api.github.com"
DEFAULT_COMMENT_ID = "report"
_PAGE_SIZE = 100
_MAX_PAGES = 30
_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class GitHubError(LLMSearchEvalError):
    """The GitHub API returned an error."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def marker(comment_id: str = DEFAULT_COMMENT_ID) -> str:
    if not _ID.match(comment_id):
        raise LLMSearchEvalError(
            f"invalid comment id {comment_id!r}; use letters, digits, '.', '_' or '-'"
        )
    return f"<!-- llm-search-eval:{comment_id} -->"


def build_body(text: str, comment_id: str = DEFAULT_COMMENT_ID, footer: str = "") -> str:
    """Comment text with the marker and an optional footer, cut to GitHub's limit."""
    head = marker(comment_id) + "\n"
    tail = f"\n\n{footer}" if footer else ""
    note = "\n\n_The report was cut to fit in a comment; see the job summary for the rest._"
    text = text.strip()
    room = MAX_COMMENT_CHARS - len(head) - len(tail)
    if len(text) > room:
        cut = text[: room - len(note)]
        # Do not leave half a table row behind.
        cut = cut[: cut.rfind("\n")] if "\n" in cut else cut
        text = cut + note
    return head + text + tail


@dataclass(frozen=True, slots=True)
class PullRequestContext:
    repository: str
    number: int
    api_url: str = DEFAULT_API_URL


def context_from_env(env: Mapping[str, str] | None = None) -> PullRequestContext | None:
    """Repository and pull request number of the current GitHub Actions run.

    Returns ``None`` outside a pull request (for example on a push).
    """
    env = os.environ if env is None else env
    repository = env.get("GITHUB_REPOSITORY", "")
    api_url = env.get("GITHUB_API_URL") or DEFAULT_API_URL
    event_path = env.get("GITHUB_EVENT_PATH", "")
    number: Any = None
    if event_path and Path(event_path).is_file():
        try:
            event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            event = {}
        if isinstance(event, dict):
            pr = event.get("pull_request") or {}
            issue = event.get("issue") or {}
            if isinstance(pr, dict) and pr.get("number"):
                number = pr["number"]
            elif isinstance(issue, dict) and issue.get("pull_request") and issue.get("number"):
                number = issue["number"]
    if not number:
        match = re.match(r"^refs/pull/(\d+)/", env.get("GITHUB_REF", ""))
        number = match.group(1) if match else None
    if not repository or not number:
        return None
    return PullRequestContext(repository, int(number), api_url.rstrip("/"))


def run_url(env: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if env is None else env
    server, repo, run_id = (
        env.get("GITHUB_SERVER_URL"),
        env.get("GITHUB_REPOSITORY"),
        env.get("GITHUB_RUN_ID"),
    )
    if server and repo and run_id:
        return f"{server.rstrip('/')}/{repo}/actions/runs/{run_id}"
    return None


@dataclass(frozen=True, slots=True)
class CommentResult:
    """What :func:`upsert_comment` did: ``created``, ``updated`` or ``skipped``."""

    action: str
    url: str | None = None
    comment_id: int | None = None
    reason: str | None = None


class GitHubClient:
    def __init__(
        self,
        token: str,
        api_url: str = DEFAULT_API_URL,
        *,
        timeout: float = 30.0,
        transport: RequestTransport | None = None,
    ) -> None:
        if not token:
            raise LLMSearchEvalError("a GitHub token is required to post comments")
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or urllib_request

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "llm-search-eval",
        }
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            response = self.transport(method, self.api_url + path, headers, body, self.timeout)
        except OSError as exc:
            raise GitHubError(f"GitHub request failed: {exc}") from exc
        if not 200 <= response.status < 300:
            message = response.body[:300]
            with contextlib.suppress(json.JSONDecodeError, AttributeError):
                message = json.loads(response.body).get("message", message)
            raise GitHubError(
                f"GitHub {method} {path} returned HTTP {response.status}: {message}",
                response.status,
            )
        if not response.body.strip():
            return None
        try:
            return json.loads(response.body)
        except json.JSONDecodeError as exc:
            raise GitHubError(f"GitHub {method} {path} returned invalid JSON") from exc

    def find_comment(self, repository: str, number: int, tag: str) -> dict[str, Any] | None:
        for page in range(1, _MAX_PAGES + 1):
            path = f"/repos/{repository}/issues/{number}/comments?per_page={_PAGE_SIZE}&page={page}"
            comments = self.request("GET", path) or []
            for comment in comments:
                if isinstance(comment, dict) and tag in str(comment.get("body") or ""):
                    return comment
            if len(comments) < _PAGE_SIZE:
                break
        return None


def upsert_comment(
    client: GitHubClient,
    context: PullRequestContext,
    text: str,
    *,
    comment_id: str = DEFAULT_COMMENT_ID,
    footer: str = "",
) -> CommentResult:
    """Create the report comment, or update the one an earlier run left.

    Permission errors (401, 403 and 404) give a ``skipped`` result with the
    reason instead of raising; other API errors raise :class:`GitHubError`.
    """
    tag = marker(comment_id)
    body = build_body(text, comment_id, footer)
    try:
        existing = client.find_comment(context.repository, context.number, tag)
        if existing is not None:
            data = client.request(
                "PATCH",
                f"/repos/{context.repository}/issues/comments/{existing['id']}",
                {"body": body},
            )
            action = "updated"
        else:
            data = client.request(
                "POST",
                f"/repos/{context.repository}/issues/{context.number}/comments",
                {"body": body},
            )
            action = "created"
    except GitHubError as exc:
        if exc.status in (401, 403, 404):
            return CommentResult(
                "skipped",
                reason=f"{exc}. The token needs 'pull-requests: write'; pull requests "
                "from forks only get a read-only token.",
            )
        raise
    data = data if isinstance(data, dict) else {}
    return CommentResult(action, data.get("html_url"), data.get("id"))
