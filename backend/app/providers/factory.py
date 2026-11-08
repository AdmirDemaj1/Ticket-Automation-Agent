"""Build providers from settings. Credentials stay inside the provider objects."""

from app.config import Settings
from app.providers.base import CodeProvider, JiraProvider, ProviderNotAvailable
from app.providers.fakes import FakeCodeProvider, FakeJiraProvider


def get_code_provider(settings: Settings) -> CodeProvider:
    if settings.code_provider == "fake":
        return FakeCodeProvider(settings.fixtures_dir / "repo", settings.max_file_bytes)
    raise ProviderNotAvailable(
        f"CODE_PROVIDER={settings.code_provider} is not implemented yet (milestone M3). "
        "Use CODE_PROVIDER=fake for now."
    )


def get_jira_provider(settings: Settings) -> JiraProvider:
    if settings.jira_provider == "fake":
        return FakeJiraProvider(settings.data_dir / "fake_jira.json")
    raise ProviderNotAvailable(
        "JIRA_PROVIDER=jira is not implemented yet (milestone M4). Use JIRA_PROVIDER=fake for now."
    )
