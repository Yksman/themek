"""CLI dart backfill {init, run, status} + dart incremental."""
from __future__ import annotations
import json
from pathlib import Path

from typer.testing import CliRunner

from themek.cli import app
from themek.dart import backfill as backfill_mod
from themek.dart import incremental as incremental_mod
from themek.dart import client as client_mod
from themek.dart.backfill import BackfillTargetSpec, BatchSummary
from themek.dart.incremental import IncrementalRunResult
from themek.db.models import BackfillTarget


runner = CliRunner()
FIXTURE_JSON = (
    Path(__file__).parent / "fixtures" / "samsung_extraction_expected.json"
)


# ──────────────────────────────────────────────────────────────────────────
# init
# ──────────────────────────────────────────────────────────────────────────


def test_cli_backfill_init_dry_run(tmp_path, monkeypatch):
    universe_file = tmp_path / "active.txt"
    universe_file.write_text("00126380\n00164742\n", encoding="utf-8")
    monkeypatch.setenv("DART_API_KEY", "test")

    result = runner.invoke(app, [
        "dart", "backfill", "init",
        "--universe-file", str(universe_file), "--periods", "2024:2025",
    ])
    assert result.exit_code == 0, result.stdout
    assert "예상 처리: 4 target" in result.stdout
    assert "예상 DART 호출" in result.stdout
    assert "예상 LLM 비용" in result.stdout


def test_cli_backfill_init_confirm_creates_rows(
    tmp_path, monkeypatch, fresh_db,
):
    universe_file = tmp_path / "active.txt"
    universe_file.write_text("00126380\n", encoding="utf-8")
    monkeypatch.setenv("DART_API_KEY", "test")

    result = runner.invoke(app, [
        "dart", "backfill", "init",
        "--universe-file", str(universe_file), "--periods", "2024:2025",
        "--confirm",
    ])
    assert result.exit_code == 0, result.stdout
    assert "inserted=2" in result.stdout

    from sqlalchemy import select, func
    from themek.db.engine import make_engine, make_session_factory
    Session = make_session_factory(make_engine())
    with Session() as s:
        n = s.scalar(select(func.count()).select_from(BackfillTarget))
        assert n == 2


# ──────────────────────────────────────────────────────────────────────────
# run
# ──────────────────────────────────────────────────────────────────────────


def test_cli_backfill_run_summary_output(
    tmp_path, monkeypatch, fresh_db,
):
    """run_batch을 monkeypatch로 가짜 summary로 대체 — CLI 출력만 검증."""
    monkeypatch.setenv("DART_API_KEY", "test")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))

    def fake_run_batch(**kwargs):
        return BatchSummary(
            processed=3, done=2, skipped=1, failed=0,
            pending_remaining=5, budget_remaining=37994,
        )

    monkeypatch.setattr("themek.cli.run_batch", fake_run_batch, raising=False)
    # Cli imports run_batch lazily inside command; patch module instead
    monkeypatch.setattr(backfill_mod, "run_batch", fake_run_batch)

    result = runner.invoke(app, ["dart", "backfill", "run", "--max-targets", "3"])
    assert result.exit_code == 0, result.stdout
    assert "processed=3" in result.stdout
    assert "done=2" in result.stdout
    assert "pending_remaining=5" in result.stdout
    assert "budget_remaining=" in result.stdout


def test_cli_backfill_run_budget_exceeded_exit_6(
    tmp_path, monkeypatch, fresh_db,
):
    """run_batch이 RateBudgetExceeded 발생 → CLI exit code 6."""
    from themek.dart.rate_budget import RateBudgetExceeded
    monkeypatch.setenv("DART_API_KEY", "test")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))

    def boom(**kwargs):
        raise RateBudgetExceeded("daily_cap=0 used=0 requested=1")

    monkeypatch.setattr(backfill_mod, "run_batch", boom)

    result = runner.invoke(app, ["dart", "backfill", "run"])
    assert result.exit_code == 6
    combined = result.stdout + (result.stderr or "")
    assert "Budget exceeded" in combined


# ──────────────────────────────────────────────────────────────────────────
# status
# ──────────────────────────────────────────────────────────────────────────


def test_cli_backfill_status_basic(tmp_path, monkeypatch, fresh_db):
    """status 기본 출력: 5 라인 + Total LLM cost."""
    monkeypatch.setenv("DART_API_KEY", "test")

    from themek.db.engine import make_engine, make_session_factory
    Session = make_session_factory(make_engine())
    with Session() as s:
        s.add(BackfillTarget(
            corp_code="00000001", period="2025", status="done",
            escalation_level="regex", input_chars=10000,
            cost_estimate_usd=0.14,
        ))
        s.add(BackfillTarget(
            corp_code="00000002", period="2025", status="pending",
        ))
        s.commit()

    result = runner.invoke(app, ["dart", "backfill", "status"])
    assert result.exit_code == 0, result.stdout
    assert "BackfillTarget summary" in result.stdout
    assert "pending" in result.stdout
    assert "done" in result.stdout
    assert "Total LLM cost" in result.stdout


def test_cli_backfill_status_verbose(tmp_path, monkeypatch, fresh_db):
    """--verbose: escalation distribution + Top 10 by cost."""
    monkeypatch.setenv("DART_API_KEY", "test")

    from themek.db.engine import make_engine, make_session_factory
    Session = make_session_factory(make_engine())
    with Session() as s:
        s.add(BackfillTarget(
            corp_code="00000001", period="2025", status="done",
            escalation_level="regex", input_chars=10000,
            cost_estimate_usd=0.14,
        ))
        s.add(BackfillTarget(
            corp_code="00000002", period="2025", status="done",
            escalation_level="full_text", input_chars=80000,
            cost_estimate_usd=0.77,
        ))
        s.commit()

    result = runner.invoke(app, ["dart", "backfill", "status", "--verbose"])
    assert result.exit_code == 0, result.stdout
    assert "Escalation distribution" in result.stdout
    assert "Top 10 by cost" in result.stdout
    # 비용 합계 정확성 (0.14 + 0.77 = 0.91)
    assert "0.91" in result.stdout


# ──────────────────────────────────────────────────────────────────────────
# incremental
# ──────────────────────────────────────────────────────────────────────────


def test_cli_dart_incremental_outputs_metrics(
    tmp_path, monkeypatch, fresh_db,
):
    universe_file = tmp_path / "active.txt"
    universe_file.write_text("00126380\n", encoding="utf-8")
    monkeypatch.setenv("DART_API_KEY", "test")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))

    captured = {}

    def fake_run_incremental(**kwargs):
        captured.update(kwargs)
        return IncrementalRunResult(
            scanned=10, in_universe=1, already_ingested=0,
            to_ingest=1, ingested=1, failed=[],
        )

    monkeypatch.setattr(incremental_mod, "run_incremental", fake_run_incremental)

    result = runner.invoke(app, [
        "dart", "incremental",
        "--universe-file", str(universe_file),
    ])
    assert result.exit_code == 0, result.stdout
    assert "scanned=10" in result.stdout
    assert "in_universe=1" in result.stdout
    assert "ingested=1" in result.stdout

    # since=yesterday default
    from datetime import date, timedelta
    assert captured["since"] == date.today() - timedelta(days=1)
    assert captured["until"] == date.today()
    # universe loaded from active.txt
    assert captured["universe"] == {"00126380"}


# ──────────────────────────────────────────────────────────────────────────
# backfill init --from-stocks
# ──────────────────────────────────────────────────────────────────────────


def test_backfill_init_from_stocks_uses_stock_table(monkeypatch, fresh_db):
    """--from-stocks는 Stock 테이블에서 universe를 가져온다."""
    from datetime import date

    from sqlalchemy import select, func
    from typer.testing import CliRunner

    from themek.cli import app
    from themek.db.models import BackfillTarget, Corporation, Stock
    from themek.db.engine import make_engine, make_session_factory

    monkeypatch.setenv("DART_API_KEY", "test")
    Session = make_session_factory(make_engine())
    with Session() as s:
        s.add_all([
            Corporation(dart_code="00126380", name_ko="삼성전자"),
            Corporation(dart_code="00164742", name_ko="현대자동차"),
        ])
        s.flush()
        s.add_all([
            Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
                  share_class="common", issued_by_id="00126380",
                  last_seen_at=date(2026, 5, 27)),
            Stock(ticker="005380", name_ko="현대자동차", market="KOSPI",
                  share_class="common", issued_by_id="00164742",
                  last_seen_at=date(2026, 5, 27)),
        ])
        s.commit()

    runner = CliRunner()
    result = runner.invoke(app, [
        "dart", "backfill", "init",
        "--from-stocks", "--periods", "2023", "--confirm",
    ])
    assert result.exit_code == 0, result.stdout

    with Session() as s:
        targets = s.scalars(select(BackfillTarget)).all()
        assert {(t.corp_code, t.period) for t in targets} == {
            ("00126380", "2023"),
            ("00164742", "2023"),
        }


def test_backfill_init_from_stocks_dry_run_no_db_change(db_session, mocker):
    from datetime import date

    from sqlalchemy import select
    from typer.testing import CliRunner

    from themek.cli import app
    from themek.db.models import BackfillTarget, Corporation, Stock

    db_session.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
    db_session.flush()
    db_session.add(Stock(
        ticker="005930", name_ko="삼성전자", market="KOSPI",
        share_class="common", issued_by_id="00126380",
        last_seen_at=date(2026, 5, 27),
    ))
    db_session.commit()

    runner = CliRunner()
    result = runner.invoke(app, [
        "dart", "backfill", "init",
        "--from-stocks", "--periods", "2023",
    ])
    assert result.exit_code == 0
    assert "dry-run" in result.stdout.lower()
    assert db_session.scalars(select(BackfillTarget)).all() == []


def test_backfill_init_rejects_both_universe_sources():
    """--from-stocks와 --universe-file 동시 사용은 거부."""
    from typer.testing import CliRunner

    from themek.cli import app

    runner = CliRunner()
    result = runner.invoke(app, [
        "dart", "backfill", "init",
        "--from-stocks", "--universe-file", "data/universe/active.txt",
        "--periods", "2023",
    ])
    assert result.exit_code != 0
    assert "동시" in result.stdout or "동시" in (result.stderr or "")
