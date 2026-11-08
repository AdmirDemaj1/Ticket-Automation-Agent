import pytest
from pydantic import SecretStr

from app.config import ConfigError, load_settings


def test_defaults_use_fake_providers_and_need_no_accounts() -> None:
    s = load_settings()
    assert s.code_provider == "fake"
    assert s.jira_provider == "fake"
    assert s.anthropic_model == "claude-opus-5-5"


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"CODE_PROVIDER": "github"}, ["GITHUB_TOKEN"]),
        ({"CODE_PROVIDER": "gitlab"}, ["GITLAB_TOKEN"]),
        ({"JIRA_PROVIDER": "jira"}, ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]),
        ({"CODE_PROVIDER": "github", "GITHUB_TOKEN": "   "}, ["GITHUB_TOKEN"]),
    ],
)
def test_missing_credentials_fail_with_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: list[str]
) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ConfigError) as exc:
        load_settings()
    message = str(exc.value)
    assert "Invalid configuration" in message
    for name in expected:
        assert name in message


def test_valid_real_provider_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_PROVIDER", "gitlab")
    monkeypatch.setenv("GITLAB_TOKEN", "glpat-secret-value")
    monkeypatch.setenv("JIRA_PROVIDER", "jira")
    monkeypatch.setenv("JIRA_BASE_URL", "https://example.atlassian.net")
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_API_TOKEN", "jira-secret-value")
    s = load_settings()
    assert isinstance(s.gitlab_token, SecretStr)
    assert "glpat-secret-value" not in repr(s)
    assert "jira-secret-value" not in repr(s)


def test_invalid_values_never_echo_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODE_PROVIDER", "bitbucket")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-should-not-appear")
    with pytest.raises(ConfigError) as exc:
        load_settings()
    assert "CODE_PROVIDER" in str(exc.value)
    assert "ghp-should-not-appear" not in str(exc.value)
    assert "bitbucket" not in str(exc.value)
