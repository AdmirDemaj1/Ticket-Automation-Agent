"""Runtime settings, read from environment variables only."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    service_token: SecretStr = Field(alias="SERVICE_TOKEN")
    api_base: str = Field(default="http://api:3000", alias="API_BASE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
