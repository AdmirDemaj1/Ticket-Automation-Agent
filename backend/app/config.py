"""Settings from the repo-root `.env` (or the process environment).

Secrets are `SecretStr` so they never show up in reprs or logs. They are never sent to the
browser, stored in the database, or placed in graph state.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(Exception):
    """Raised with a human-readable message when the configuration is unusable."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LLM
    llm_provider: Literal["anthropic", "fake"] = "fake"
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    # Server-side refusal fallback (beta). Turn off for models that don't support it.
    anthropic_refusal_fallback: bool = True
    max_llm_tokens_per_run: int = Field(default=300_000, gt=0)

    # Code source
    code_provider: Literal["github", "gitlab", "fake"] = "fake"
    github_token: SecretStr | None = None
    gitlab_base_url: str = "https://gitlab.com"
    gitlab_token: SecretStr | None = None

    # Jira
    jira_provider: Literal["jira", "fake"] = "fake"
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_api_token: SecretStr | None = None

    # Limits
    max_code_files: int = Field(default=60, gt=0)
    max_file_bytes: int = Field(default=200_000, gt=0)
    max_screenshots: int = Field(default=10, gt=0)
    max_screenshot_bytes: int = Field(default=8_000_000, gt=0)
    max_total_code_bytes: int = Field(default=400_000, gt=0)
    max_transcript_bytes: int = Field(default=2_000_000, gt=0)

    # Local paths and server
    data_dir: Path = REPO_ROOT / "data"
    fixtures_dir: Path = REPO_ROOT / "fixtures"
    frontend_origin: str = "http://localhost:5173"
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check_provider_credentials(self) -> Self:
        missing: list[str] = []
        if self.llm_provider == "anthropic" and not _has(self.anthropic_api_key):
            missing.append("ANTHROPIC_API_KEY (required when LLM_PROVIDER=anthropic)")
        if self.code_provider == "github" and not _has(self.github_token):
            missing.append("GITHUB_TOKEN (required when CODE_PROVIDER=github)")
        if self.code_provider == "gitlab" and not _has(self.gitlab_token):
            missing.append("GITLAB_TOKEN (required when CODE_PROVIDER=gitlab)")
        if self.jira_provider == "jira":
            if not self.jira_base_url:
                missing.append("JIRA_BASE_URL (required when JIRA_PROVIDER=jira)")
            if not self.jira_email:
                missing.append("JIRA_EMAIL (required when JIRA_PROVIDER=jira)")
            if not _has(self.jira_api_token):
                missing.append("JIRA_API_TOKEN (required when JIRA_PROVIDER=jira)")
        if missing:
            raise ValueError("missing settings: " + "; ".join(missing))
        return self

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def checkpoint_path(self) -> Path:
        return self.data_dir / "checkpoints.db"

    @property
    def fake_llm_dir(self) -> Path:
        return self.fixtures_dir / "llm"


def _has(secret: SecretStr | None) -> bool:
    return secret is not None and bool(secret.get_secret_value().strip())


def load_settings(**overrides: object) -> Settings:
    """Build settings, turning validation errors into one readable ConfigError.

    The message lists setting names and problems only, never values.
    """
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as e:
        lines: list[str] = []
        for err in e.errors(include_input=False, include_url=False):
            loc = ".".join(str(p) for p in err["loc"]).upper()
            msg = err["msg"].removeprefix("Value error, ")
            if msg.startswith("missing settings: "):
                lines.extend(f"  - {m}" for m in msg.removeprefix("missing settings: ").split("; "))
            else:
                lines.append(f"  - {loc + ': ' if loc else ''}{msg}")
        raise ConfigError(
            "Invalid configuration. Fix your .env (see .env.example):\n" + "\n".join(lines)
        ) from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
