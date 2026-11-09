"""A tiny fake GitHub REST API (respx) that serves a local folder as `owner/demo` @ main."""

import hashlib
import re
from pathlib import Path
from typing import Any

import httpx
import respx

API = "https://api.github.test"
REPO = "owner/demo"


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode(), usedforsecurity=False).hexdigest()


class MockGitHub:
    def __init__(self, root: Path, *, truncate: bool = False) -> None:
        self.root = root
        self.truncate = truncate
        self.router = respx.mock(base_url=API, assert_all_called=False)
        self.trees: dict[str, list[dict[str, Any]]] = {}
        self.root_tree = self._build_tree(root, "")
        self._routes()

    def _build_tree(self, folder: Path, prefix: str) -> str:
        entries: list[dict[str, Any]] = []
        for child in sorted(folder.iterdir()):
            if child.is_dir():
                sub = self._build_tree(child, f"{prefix}{child.name}/")
                entries.append({"path": child.name, "mode": "040000", "type": "tree", "sha": sub})
            else:
                entries.append(
                    {
                        "path": child.name,
                        "mode": "100644",
                        "type": "blob",
                        "sha": _sha(f"{prefix}{child.name}"),
                        "size": child.stat().st_size,
                    }
                )
        sha = _sha(f"tree:{prefix}")
        self.trees[sha] = entries
        return sha

    def _flat(self, sha: str, prefix: str = "") -> list[dict[str, Any]]:
        out = []
        for e in self.trees[sha]:
            path = f"{prefix}{e['path']}"
            out.append({**e, "path": path})
            if e["type"] == "tree":
                out.extend(self._flat(e["sha"], f"{path}/"))
        return out

    def _routes(self) -> None:
        r = self.router
        r.get("/user/repos").mock(side_effect=self._repos)
        r.get(f"/repos/{REPO}/branches").mock(
            return_value=httpx.Response(200, json=[{"name": "main"}, {"name": "feature/x"}])
        )
        r.get(url__regex=rf"/repos/{REPO}/git/ref/heads/(?P<branch>.+)$").mock(
            side_effect=self._ref
        )
        r.get(url__regex=rf"/repos/{REPO}/git/commits/c0ffee$").mock(
            return_value=httpx.Response(200, json={"tree": {"sha": self.root_tree}})
        )
        r.get(url__regex=rf"/repos/{REPO}/git/trees/(?P<sha>[0-9a-f]+)").mock(
            side_effect=self._tree
        )
        r.get(url__regex=rf"/repos/{REPO}/contents/(?P<path>[^?]+)").mock(
            side_effect=self._contents
        )

    def _repos(self, request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(
                200, json=[{"full_name": "owner/old", "default_branch": "main", "archived": True}]
            )
        return httpx.Response(
            200,
            json=[{"full_name": REPO, "default_branch": "main", "archived": False}],
            headers={"link": f'<{API}/user/repos?per_page=100&page=2>; rel="next"'},
        )

    def _ref(self, request: httpx.Request, branch: str) -> httpx.Response:
        if branch not in ("main", "feature/x"):
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, json={"object": {"sha": "c0ffee", "type": "commit"}})

    def _tree(self, request: httpx.Request, sha: str) -> httpx.Response:
        if sha not in self.trees:
            return httpx.Response(404, json={"message": "Not Found"})
        if "recursive" in request.url.params:
            if self.truncate:
                partial = self._flat(sha)[:2]
                return httpx.Response(200, json={"sha": sha, "tree": partial, "truncated": True})
            return httpx.Response(
                200, json={"sha": sha, "tree": self._flat(sha), "truncated": False}
            )
        return httpx.Response(200, json={"sha": sha, "tree": self.trees[sha], "truncated": False})

    def _contents(self, request: httpx.Request, path: str) -> httpx.Response:
        assert request.headers["accept"] == "application/vnd.github.raw+json"
        target = (self.root / httpx.URL(f"/{path}").path.lstrip("/")).resolve()
        if not target.is_relative_to(self.root.resolve()) or not target.is_file():
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, content=target.read_bytes())

    def methods(self) -> set[str]:
        return {call.request.method for call in self.router.calls}

    def paths(self) -> list[str]:
        return [call.request.url.path for call in self.router.calls]


ALLOWED_PATHS = re.compile(
    rf"^/(user/repos|repos/{REPO}/(branches|git/(ref/heads|commits|trees)/.+|contents/.+))$"
)
