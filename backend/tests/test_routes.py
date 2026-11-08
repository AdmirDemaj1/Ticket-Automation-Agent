import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from tests.conftest import FIXTURES


def test_config_status_never_returns_secrets(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-very-secret")
    monkeypatch.setenv("CODE_PROVIDER", "github")
    monkeypatch.setenv("GITHUB_TOKEN", "github_pat_very_secret")
    settings = load_settings(data_dir=tmp_path / "d", fixtures_dir=FIXTURES)
    with TestClient(create_app(settings)) as client:
        res = client.get("/config/status")
    assert res.status_code == 200
    body = res.json()
    assert body["llm"]["api_key_set"] is True
    assert body["code"]["provider"] == "github"
    assert "very_secret" not in res.text and "very-secret" not in res.text


def test_config_status_defaults(client: TestClient) -> None:
    body = client.get("/config/status").json()
    assert body["code"]["provider"] == "fake"
    assert body["jira"]["provider"] == "fake"
    assert body["llm"]["api_key_set"] is False


def test_code_pickers_with_fake_provider(client: TestClient) -> None:
    repos = client.get("/code/repos").json()
    assert repos[0]["id"] == "fixtures/demo-app"
    assert client.get("/code/repos/fixtures/demo-app/branches").json() == ["main"]
    res = client.get("/code/repos/nope/x/branches")
    assert res.status_code == 502
    assert "Unknown repository" in res.json()["detail"]


def test_jira_pickers_with_fake_provider(client: TestClient) -> None:
    assert client.get("/jira/projects").json() == [{"key": "DEMO", "name": "Demo project (fake)"}]
    names = [t["name"] for t in client.get("/jira/projects/DEMO/issue-types").json()]
    assert names == ["Story", "Task", "Bug", "Sub-task"]


def test_runs_list_starts_empty(client: TestClient) -> None:
    assert client.get("/runs").json() == []


def test_unimplemented_real_provider_returns_501(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("CODE_PROVIDER", "github")
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    settings = load_settings(data_dir=tmp_path / "d", fixtures_dir=FIXTURES)
    with TestClient(create_app(settings)) as client:
        res = client.get("/code/repos")
    assert res.status_code == 501
    assert "M3" in res.json()["detail"]


def test_cors_allows_only_local_frontend(client: TestClient) -> None:
    ok = client.options(
        "/healthz",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(
        "/healthz",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers
