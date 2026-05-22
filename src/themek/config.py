from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_dsn: str = Field(...)
    log_level: str = Field(default="INFO")
    claude_cli_bin: str = Field(default="claude")
    claude_cli_timeout_sec: int = Field(default=120)


def get_settings() -> Settings:
    return Settings()
