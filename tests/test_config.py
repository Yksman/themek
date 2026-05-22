from themek.config import Settings


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
