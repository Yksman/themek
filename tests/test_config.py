from pathlib import Path
from themek.config import Settings, get_settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "sqlite:///./x.db")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = Settings()
    assert s.postgres_dsn == "sqlite:///./x.db"
    assert s.log_level == "DEBUG"


def test_settings_defaults_for_claude_cli(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "sqlite:///./x.db")
    s = Settings()
    assert s.claude_cli_bin == "claude"
    assert s.claude_cli_timeout_sec == 120


def test_settings_loads_dart_api_key(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "test-key-xyz")
    monkeypatch.setenv("POSTGRES_DSN", "sqlite:///./x.db")
    s = get_settings()
    assert s.dart_api_key == "test-key-xyz"


def test_settings_dart_cache_dir_default(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "sqlite:///./x.db")
    monkeypatch.delenv("DART_CACHE_DIR", raising=False)
    s = get_settings()
    assert str(s.dart_cache_dir).endswith("data/dart")


def test_settings_dart_rate_and_timeout_defaults(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "sqlite:///./x.db")
    s = get_settings()
    assert s.dart_rate_per_min == 60
    assert s.dart_http_timeout_sec == 60


def test_settings_dart_cache_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("POSTGRES_DSN", "sqlite:///./x.db")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "custom_dart"))
    s = get_settings()
    assert s.dart_cache_dir == Path(str(tmp_path / "custom_dart"))
