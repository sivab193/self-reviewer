from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Any, Protocol

import httpx


class TokenProvider(Protocol):
    def __call__(self) -> str: ...


class GitHubError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self, token_provider: TokenProvider, base_url: str = "https://api.github.com"):
        self._token_provider = token_provider
        self._client = httpx.Client(base_url=base_url, timeout=30.0, headers={
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "aayvu-reviewer/0.1",
        })
        self._login: str | None = None

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._token_provider()}"
        for attempt in range(4):
            response = self._client.request(method, path, headers=headers, **kwargs)
            if response.status_code not in {429, 502, 503, 504} and not (
                response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0"
            ):
                break
            if attempt == 3:
                break
            reset = int(response.headers.get("X-RateLimit-Reset", "0"))
            time.sleep(min(30, max(1, reset - int(time.time()))) if reset else 2 ** attempt)
        if response.is_error:
            raise GitHubError(f"GitHub {method} {path} failed ({response.status_code}): {response.text[:500]}")
        return response

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        params = dict(params or {})
        params["per_page"] = 100
        page = 1
        while True:
            params["page"] = page
            items = self._request("GET", path, params=params).json()
            if not isinstance(items, list):
                raise GitHubError("expected paginated list")
            yield from items
            if len(items) < 100:
                return
            page += 1

    def open_pulls(self, repository: str, base: str) -> list[dict]:
        return list(self.paginate(f"/repos/{repository}/pulls", {"state": "open", "base": base}))

    def current_login(self) -> str:
        if self._login is None:
            self._login = str(self._request("GET", "/user").json()["login"])
        return self._login

    def pull(self, repository: str, number: int) -> dict:
        return self._request("GET", f"/repos/{repository}/pulls/{number}").json()

    def pull_files(self, repository: str, number: int) -> list[dict]:
        return list(self.paginate(f"/repos/{repository}/pulls/{number}/files"))

    def issue_comments(self, repository: str, number: int) -> list[dict]:
        return list(self.paginate(f"/repos/{repository}/issues/{number}/comments"))

    def create_review(self, repository: str, number: int, commit_id: str, comments: list[dict]) -> dict:
        return self._request("POST", f"/repos/{repository}/pulls/{number}/reviews",
                             json={"commit_id": commit_id, "event": "COMMENT", "body": "Aayvu local-model review", "comments": comments}).json()

    def create_comment(self, repository: str, number: int, body: str) -> dict:
        return self._request("POST", f"/repos/{repository}/issues/{number}/comments", json={"body": body}).json()

    def update_comment(self, repository: str, comment_id: int, body: str) -> dict:
        return self._request("PATCH", f"/repos/{repository}/issues/comments/{comment_id}", json={"body": body}).json()

