"""GitHub code provider: REST API with a fine-grained personal access token, read-only.

Endpoints used (all GET):
- `/user/repos`                                   repository picker
- `/repos/{repo}/branches`                        branch picker
- `/repos/{repo}/git/ref/heads/{branch}`          branch -> commit
- `/repos/{repo}/git/commits/{sha}`               commit -> root tree
- `/repos/{repo}/git/trees/{sha}[?recursive=1]`   file tree
- `/repos/{repo}/contents/{path}?ref=`            raw file content

GitHub's code search is not used (default branch only, strict rate limit). Search is local,
over the files fetched within the budget. Every request goes through a hook that refuses any
method other than GET, so the provider cannot write even if it were asked to.
"""

import logging
import re
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.providers.base import FileEntry, ProviderError, Repo
from app.providers.filters import SKIP_DIRS, looks_binary, should_skip

log = logging.getLogger("app.github")

API_VERSION = "2022-11-28"
USER_AGENT = "meeting-to-jira-local"
MAX_PAGES = 10  # 1000 repos or branches is plenty for a picker
MAX_TREE_REQUESTS = 300  # cap for walking a truncated tree one directory at a time
_REPO_ID = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_NEXT_LINK = re.compile(r'<([^>]+)>;\s*rel="next"')


class ReadOnlyViolation(RuntimeError):
    """A non-GET request was attempted. This is a bug, never a user error."""


class _Transient(Exception):
    """A response worth retrying (5xx, or 429 / secondary rate limit)."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code}")
        self.response = response


async def _only_get(request: httpx.Request) -> None:
    if request.method != "GET":
        raise ReadOnlyViolation(
            f"refused {request.method} {request.url.path}: provider is read-only"
        )


class GitHubCodeProvider:
    def __init__(
        self,
        token: str,
        api_url: str = "https://api.github.com",
        max_file_bytes: int = 200_000,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_wait: float = 1.0,
    ) -> None:
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._max_file_bytes = max_file_bytes
        self._transport = transport
        self._retry_wait = retry_wait

    # ---------- CodeProvider ----------

    async def list_repos(self) -> list[Repo]:
        async with self._client() as client:
            items = await self._paginate(
                client, "/user/repos", {"per_page": "100", "sort": "pushed"}, "repositories"
            )
        return [
            Repo(id=r["full_name"], name=r["full_name"], default_branch=r.get("default_branch"))
            for r in items
            if not r.get("archived")
        ]

    async def list_branches(self, repo: str) -> list[str]:
        _check_repo(repo)
        async with self._client() as client:
            items = await self._paginate(
                client, f"/repos/{repo}/branches", {"per_page": "100"}, f"branches of {repo}"
            )
        return [b["name"] for b in items]

    async def list_tree(self, repo: str, ref: str) -> list[FileEntry]:
        _check_repo(repo)
        async with self._client() as client:
            tree_sha = await self._root_tree(client, repo, ref)
            data = await self._get_json(
                client, f"/repos/{repo}/git/trees/{tree_sha}", {"recursive": "1"}, repo
            )
            if data.get("truncated"):
                log.warning("tree of %s is truncated; walking it one directory at a time", repo)
                raw = await self._walk_tree(client, repo, tree_sha)
            else:
                raw = data.get("tree", [])
        entries = []
        for item in raw:
            # blobs only: skips directories, submodules ("commit") and symlinks (mode 120000)
            if item.get("type") != "blob" or item.get("mode") == "120000":
                continue
            path, size = item["path"], item.get("size")
            if not should_skip(path, size, self._max_file_bytes):
                entries.append(FileEntry(path=path, size=size))
        return sorted(entries, key=lambda e: e.path)

    async def get_file(self, repo: str, ref: str, path: str, max_bytes: int) -> str | None:
        _check_repo(repo)
        if path.startswith("/") or ".." in path.split("/"):
            return None
        url = f"/repos/{repo}/contents/{quote(path, safe='/')}"
        headers = {"Accept": "application/vnd.github.raw+json"}
        async with self._client() as client:
            data = await self._send(
                client,
                url,
                {"ref": ref},
                repo,
                headers=headers,
                max_bytes=max_bytes,
                missing_ok=True,
            )
        if data is None or len(data) > max_bytes or looks_binary(data):
            return None
        return data.decode("utf-8", errors="replace")

    # ---------- internals ----------

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(
            base_url=self._api_url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": USER_AGENT,
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=self._transport,
            event_hooks={"request": [_only_get]},
            follow_redirects=True,
        ) as client:
            yield client

    async def _root_tree(self, client: httpx.AsyncClient, repo: str, ref: str) -> str:
        # git/ref takes branch names with slashes as-is (e.g. heads/feature/login).
        ref_data = await self._get_json(
            client, f"/repos/{repo}/git/ref/heads/{quote(ref, safe='/')}", None, f"branch {ref!r}"
        )
        commit_sha = ref_data["object"]["sha"]
        commit = await self._get_json(client, f"/repos/{repo}/git/commits/{commit_sha}", None, repo)
        tree_sha: str = commit["tree"]["sha"]
        return tree_sha

    async def _walk_tree(
        self, client: httpx.AsyncClient, repo: str, root_sha: str
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        queue: deque[tuple[str, str]] = deque([("", root_sha)])
        requests = 0
        while queue and requests < MAX_TREE_REQUESTS:
            prefix, sha = queue.popleft()
            requests += 1
            data = await self._get_json(client, f"/repos/{repo}/git/trees/{sha}", None, repo)
            for item in data.get("tree", []):
                path = f"{prefix}{item['path']}"
                if item.get("type") == "tree":
                    if item["path"] not in SKIP_DIRS:
                        queue.append((f"{path}/", item["sha"]))
                else:
                    out.append({**item, "path": path})
        if queue:
            log.warning("stopped walking the tree of %s after %d requests", repo, requests)
        return out

    async def _paginate(
        self, client: httpx.AsyncClient, url: str, params: dict[str, str], what: str
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        next_params: dict[str, str] | None = params
        for _ in range(MAX_PAGES):
            if next_url is None:
                break
            response = await self._request(client, next_url, next_params, what)
            items.extend(response.json())
            match = _NEXT_LINK.search(response.headers.get("link", ""))
            next_url = match.group(1) if match else None
            next_params = None  # the next link already carries the query string
        return items

    async def _get_json(
        self, client: httpx.AsyncClient, url: str, params: dict[str, str] | None, what: str
    ) -> Any:
        return (await self._request(client, url, params, what)).json()

    async def _send(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str],
        what: str,
        *,
        headers: dict[str, str],
        max_bytes: int,
        missing_ok: bool,
    ) -> bytes | None:
        """GET a body, reading at most max_bytes + 1 bytes of it."""

        async def once() -> bytes | None:
            async with client.stream("GET", url, params=params, headers=headers) as response:
                if missing_ok and response.status_code == 404:
                    return None
                if response.status_code >= 400:
                    await response.aread()
                    self._raise_for(response, what)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        break
                return bytes(body)

        return await self._with_retries(once, what)

    async def _request(
        self, client: httpx.AsyncClient, url: str, params: dict[str, str] | None, what: str
    ) -> httpx.Response:
        async def once() -> httpx.Response:
            response = await client.get(url, params=params)
            if response.status_code >= 400:
                self._raise_for(response, what)
            return response

        return await self._with_retries(once, what)

    async def _with_retries[T](self, call: Callable[[], Awaitable[T]], what: str) -> T:
        """3 tries with exponential backoff for 5xx, 429 and network errors."""
        try:
            async for attempt in self._retrying():
                with attempt:
                    return await call()
        except _Transient as e:
            raise ProviderError(
                f"GitHub returned HTTP {e.response.status_code} for {what} after 3 tries"
            ) from e
        except httpx.TransportError as e:
            raise ProviderError(f"Could not reach GitHub ({type(e).__name__})") from e
        raise AssertionError("unreachable")  # pragma: no cover

    def _retrying(self) -> AsyncRetrying:
        return AsyncRetrying(
            retry=retry_if_exception_type((_Transient, httpx.TransportError)),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=self._retry_wait, max=10 * self._retry_wait),
            reraise=True,
        )

    def _raise_for(self, response: httpx.Response, what: str) -> None:
        status = response.status_code
        remaining = response.headers.get("x-ratelimit-remaining")
        if status == 401:
            raise ProviderError("GitHub rejected GITHUB_TOKEN (expired or wrong token)")
        if status in (403, 429) and remaining == "0":
            raise ProviderError(f"GitHub rate limit reached; it resets at {_reset_time(response)}")
        if status == 429 or (status == 403 and "retry-after" in response.headers):
            raise _Transient(response)  # secondary rate limit: back off and retry
        if status == 403:
            raise ProviderError(
                f"GitHub refused access to {what}. The token needs 'Contents: Read-only' "
                "on this repository."
            )
        if status == 404:
            raise ProviderError(
                f"GitHub could not find {what}, or the token has no access to it. "
                "Fine-grained tokens see only the repositories selected for them."
            )
        if status == 409:
            raise ProviderError(f"{what}: the repository is empty")
        if status >= 500:
            raise _Transient(response)
        raise ProviderError(f"GitHub returned HTTP {status} for {what}")


def _check_repo(repo: str) -> None:
    if not _REPO_ID.match(repo):
        raise ProviderError(f"Invalid repository {repo!r}; expected owner/name")


def _reset_time(response: httpx.Response) -> str:
    try:
        reset = datetime.fromtimestamp(int(response.headers["x-ratelimit-reset"]), tz=UTC)
    except (KeyError, ValueError):
        return "a later time"
    return reset.astimezone().strftime("%H:%M")
