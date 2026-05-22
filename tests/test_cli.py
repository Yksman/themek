from pathlib import Path
from typer.testing import CliRunner
from themek.cli import app


runner = CliRunner()
FIXTURE_JSON = Path(__file__).parent / "fixtures" / "samsung_extraction_expected.json"


def test_cli_seed_command(engine, fresh_db):
    result = runner.invoke(app, ["seed"])
    assert result.exit_code == 0, result.stdout
    assert "Seeded" in result.stdout


def test_cli_query_e5_no_report(engine, fresh_db):
    runner.invoke(app, ["seed"])
    result = runner.invoke(app, ["query", "e5", "--ticker", "005930"])
    assert result.exit_code == 0, result.stdout
    assert "삼성전자" in result.stdout
    assert "ingest되지 않았" in result.stdout


def test_cli_query_e5_unknown_ticker(engine, fresh_db):
    runner.invoke(app, ["seed"])
    result = runner.invoke(app, ["query", "e5", "--ticker", "999999"])
    assert result.exit_code != 0
    assert "999999" in (result.stdout + result.stderr)


def test_cli_ingest_with_stub(engine, fresh_db, monkeypatch, tmp_path):
    runner.invoke(app, ["seed"])

    raw_html = tmp_path / "report.html"
    raw_html.write_text("<html><body><p>샘플 본문</p></body></html>", encoding="utf-8")

    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(FIXTURE_JSON))

    result = runner.invoke(app, [
        "ingest",
        "--rcept-no", "20240314000123",
        "--corp", "00126380",
        "--report-type", "사업보고서",
        "--period", "2023",
        "--filing-date", "2024-03-14",
        "--html-file", str(raw_html),
        "--url", "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123",
    ])
    assert result.exit_code == 0, result.stdout

    result = runner.invoke(app, ["query", "e5", "--ticker", "005930"])
    assert result.exit_code == 0
    assert "메모리반도체" in result.stdout
    assert "20240314000123" in result.stdout
