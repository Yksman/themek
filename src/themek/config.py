from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_dsn: str = Field(...)
    log_level: str = Field(default="INFO")
    claude_cli_bin: str = Field(default="claude")
    claude_cli_timeout_sec: int = Field(default=120)
    claude_cli_timeout_regex_sec: int = Field(default=60)
    claude_cli_timeout_llm_sec: int = Field(default=120)
    claude_cli_timeout_full_text_sec: int = Field(default=600)
    dart_api_key: str = Field(default="")
    dart_cache_dir: Path = Field(default=Path("data/dart"))
    dart_rate_per_min: int = Field(default=60)
    dart_http_timeout_sec: int = Field(default=60)
    claude_cli_short_retry_attempts: int = Field(default=3)
    claude_cli_short_retry_backoffs_sec: list[int] = Field(default_factory=lambda: [10, 60, 300])
    themek_wait_for_quota: bool = Field(default=False)
    themek_wait_for_quota_sec: int = Field(default=18000)
    themek_wait_for_quota_max_iterations: int = Field(default=2)
    themek_log_dir: str = Field(default="data/log")


def get_settings() -> Settings:
    return Settings()
