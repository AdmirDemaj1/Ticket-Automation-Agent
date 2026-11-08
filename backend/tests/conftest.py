from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import REPO_ROOT, Settings, load_settings
from app.main import create_app

FIXTURES = REPO_ROOT / "fixtures"
ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "CODE_PROVIDER",
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
    "GITLAB_BASE_URL",
    "JIRA_PROVIDER",
    "JIRA_BASE_URL",
    "JIRA_EMAIL",
    "JIRA_API_TOKEN",
    "DATA_DIR",
    "FIXTURES_DIR",
)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never read the developer's real .env or environment."""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(data_dir=tmp_path / "data", fixtures_dir=FIXTURES)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c
