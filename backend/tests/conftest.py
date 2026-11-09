from collections.abc import Iterator
from pathlib import Path
from typing import Any

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


DEMO_INPUTS = {"repo": "fixtures/demo-app", "branch": "main", "jira_project_key": "DEMO"}
TERMINAL_OR_PAUSED = ("awaiting_review", "completed", "failed", "cancelled")


def fixture_upload() -> list[tuple[str, tuple[str, bytes, str]]]:
    """The fixture transcript and both screenshots, as multipart files."""
    return [
        (
            "transcript_file",
            ("transcript.vtt", (FIXTURES / "transcript.vtt").read_bytes(), "text/vtt"),
        ),
        (
            "screenshots",
            ("01-login.png", (FIXTURES / "screenshots/01-login.png").read_bytes(), "image/png"),
        ),
        (
            "screenshots",
            (
                "02-dashboard.png",
                (FIXTURES / "screenshots/02-dashboard.png").read_bytes(),
                "image/png",
            ),
        ),
    ]


def start_fixture_run(client: TestClient) -> str:
    import json

    res = client.post(
        "/runs",
        data={"inputs": json.dumps(DEMO_INPUTS), "captions": json.dumps(["Login", "Dashboard"])},
        files=fixture_upload(),
    )
    assert res.status_code == 202, res.text
    run_id: str = res.json()["run_id"]
    return run_id


def wait_for(
    client: TestClient, run_id: str, statuses: tuple[str, ...] = TERMINAL_OR_PAUSED
) -> dict[str, Any]:
    import time

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        detail: dict[str, Any] = client.get(f"/runs/{run_id}").json()
        run = detail["run"]
        assert isinstance(run, dict)
        if run["status"] in statuses:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach {statuses}")
