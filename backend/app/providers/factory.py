"""Build providers from settings. Credentials stay inside the provider objects."""

from app.config import Settings
from app.providers.base import CodeProvider, JiraProvider, ProviderNotAvailable
from app.providers.code_github import GitHubCodeProvider
from app.providers.fakes import FakeCodeProvider, FakeJiraProvider
from app.providers.jira import JiraCloudProvider


def get_code_provider(settings: Settings) -> CodeProvider:
    if settings.code_provider == "fake":
        return FakeCodeProvider(settings.fixtures_dir / "repo", settings.max_file_bytes)
    if settings.code_provider == "github" and settings.github_token is not None:
        return GitHubCodeProvider(
            settings.github_token.get_secret_value(),
            api_url=settings.github_api_url,
            max_file_bytes=settings.max_file_bytes,
        )
    raise ProviderNotAvailable(
        f"CODE_PROVIDER={settings.code_provider} is not implemented yet. "
        "Use CODE_PROVIDER=github or fake."
    )


def get_jira_provider(settings: Settings) -> JiraProvider:
    if settings.jira_provider == "fake":
        return FakeJiraProvider(settings.data_dir / "fake_jira.json")
    # Startup validation guarantees these are set when JIRA_PROVIDER=jira.
    if settings.jira_base_url and settings.jira_email and settings.jira_api_token:
        return JiraCloudProvider(
            settings.jira_base_url,
            settings.jira_email,
            settings.jira_api_token.get_secret_value(),
        )
    raise ProviderNotAvailable("Jira is not configured; see JIRA_* in .env.example")
