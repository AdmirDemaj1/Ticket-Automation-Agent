import pytest

from app.providers.filters import looks_binary, should_skip

MAX = 200_000


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/react/index.js",
        "apps/web/node_modules/x/y.ts",
        "dist/bundle.js",
        "build/output.css",
        "vendor/lib.go",
        "package-lock.json",
        "frontend/pnpm-lock.yaml",
        "uv.lock",
        "public/logo.png",
        "assets/font.woff2",
        "static/app.min.js",
        "static/app.js.map",
        ".git/config",
    ],
)
def test_skips_noise(path: str) -> None:
    assert should_skip(path, 100, MAX)


@pytest.mark.parametrize(
    "path",
    ["src/pages/Login.tsx", "README.md", "package.json", "backend/app/main.py", "Dockerfile"],
)
def test_keeps_source(path: str) -> None:
    assert not should_skip(path, 100, MAX)


def test_skips_oversized_and_keeps_unknown_size() -> None:
    assert should_skip("src/big.ts", MAX + 1, MAX)
    assert not should_skip("src/big.ts", MAX, MAX)
    assert not should_skip("src/unknown.ts", None, MAX)


def test_looks_binary() -> None:
    assert looks_binary(b"\x89PNG\r\n\x1a\n\x00\x00")
    assert looks_binary(b"\xff\xfe\xfa invalid utf8 " * 10)
    assert not looks_binary("plain text, ünïcode ✓".encode())
    # multi-byte character cut at the 8 KB boundary is still text
    text = ("a" * 8191 + "é").encode()
    assert not looks_binary(text)
