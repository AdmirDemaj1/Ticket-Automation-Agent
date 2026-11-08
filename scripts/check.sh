#!/usr/bin/env bash
# Run every linter, type checker and test suite. Same steps as CI.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== backend"
(
  cd backend
  uv sync --frozen --quiet
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy app tests
  uv run pytest -q
)

echo "== frontend"
(
  cd frontend
  pnpm install --frozen-lockfile --silent
  pnpm format:check
  pnpm lint
  pnpm typecheck
  pnpm test
  pnpm build
)
echo "All checks passed."
