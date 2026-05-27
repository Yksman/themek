from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_dsn: str = Field(...)
    log_level: str = Field(default="INFO")
    claude_cli_bin: str = Field(default="claude")
    claude_cli_timeout_sec: int = Field(default=120)
    dart_api_key: str = Field(default="")
    dart_cache_dir: Path = Field(default=Path("data/dart"))
    dart_rate_per_min: int = Field(default=60)
    dart_http_timeout_sec: int = Field(default=60)


def get_settings() -> Settings:
    return Settings()
