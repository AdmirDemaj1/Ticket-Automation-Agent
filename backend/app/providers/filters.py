"""Which repository files are worth reading. Shared by every code provider."""

from pathlib import PurePosixPath

SKIP_DIRS = frozenset(
    {
        "node_modules",
        "vendor",
        "vendors",
        "third_party",
        "dist",
        "build",
        "out",
        "target",
        ".git",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".turbo",
        ".cache",
        "coverage",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".gradle",
        ".idea",
        ".vscode",
        "bin",
        "obj",
    }
)

LOCKFILES = frozenset(
    {
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lockb",
        "poetry.lock",
        "uv.lock",
        "Pipfile.lock",
        "Cargo.lock",
        "Gemfile.lock",
        "composer.lock",
        "go.sum",
        "packages.lock.json",
        "mix.lock",
        "pubspec.lock",
    }
)

BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".bmp",
        ".tiff",
        ".svgz",
        ".pdf",
        ".zip",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".jar",
        ".war",
        ".class",
        ".so",
        ".dylib",
        ".dll",
        ".exe",
        ".bin",
        ".o",
        ".a",
        ".wasm",
        ".pyc",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".eot",
        ".mp3",
        ".mp4",
        ".mov",
        ".avi",
        ".webm",
        ".wav",
        ".sqlite",
        ".db",
        ".psd",
        ".sketch",
        ".fig",
    }
)

MINIFIED_SUFFIXES = (".min.js", ".min.css", ".map")


def should_skip(path: str, size: int | None, max_bytes: int) -> bool:
    """True for build output, vendored code, lockfiles, binaries, minified and oversized files."""
    p = PurePosixPath(path)
    if any(part in SKIP_DIRS for part in p.parts[:-1]):
        return True
    name = p.name
    if name in LOCKFILES:
        return True
    lower = name.lower()
    if p.suffix.lower() in BINARY_EXTENSIONS or lower.endswith(MINIFIED_SUFFIXES):
        return True
    return size is not None and size > max_bytes


def looks_binary(data: bytes) -> bool:
    """Heuristic: NUL bytes in the first 8 KB, or not valid UTF-8."""
    head = data[:8192]
    if b"\x00" in head:
        return True
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as e:
        # A multi-byte character cut at the 8 KB boundary is fine.
        return e.start < len(head) - 4
    return False
