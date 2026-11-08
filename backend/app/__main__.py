"""Start the backend: `uv run python -m app`. Binds to 127.0.0.1 only."""

import os
import sys

import uvicorn

from app.config import ConfigError, load_settings
from app.main import create_app


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    port = int(os.environ.get("BACKEND_PORT", "8000"))
    uvicorn.run(create_app(settings), host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
