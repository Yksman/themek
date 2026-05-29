"""CLI: themek krx sync-listed."""
from __future__ import annotations

from datetime import date

import pytest
from typer.testing import CliRunner

from themek.cli import app


runner = CliRunner()


@pytest.fixture
def fake_listed(mocker):
    """KrxClient를 mock해서 KOSPI 2 + KOSDAQ 1 종목 반환."""

    class _Fake:
        def list_tickers(self, *, market, date=None):
            return {
                "KOSPI": ["005930", "000660"],
                "KOSDAQ": ["247540"],
            }.get(market, [])

    mocker.patch("themek.cli.KrxClient", return_value=_Fake())
    return _Fake


@pytest.fixture
def fake_corp_master(db_session, tmp_path, mocker):
    """corp_master.json 3건 — KOSPI 2 + KOSDAQ 1."""
    from themek.dart.cache import DartCache
    cache = DartCache(base_dir=tmp_path)
    cache.save_corp_master([
        {"corp_code": "00126380", "corp_name": "삼성전자",
         "stock_code": "005930", "modify_date": "20240312"},
        {"corp_code": "00164779", "corp_name": "SK하이닉스",
         "stock_code": "000660", "modify_date": "20240312"},
        {"corp_code": "01160363", "corp_name": "에코프로비엠",
         "stock_code": "247540", "modify_date": "20240312"},
    ])
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(None, cache),
    )
    return cache


def test_krx_sync_listed_dry_run(fake_listed, fake_corp_master):
    """--dry-run은 listed count만 출력하고 DB 미변경."""
    result = runner.invoke(app, ["krx", "sync-listed", "--dry-run"])
    assert result.exit_code == 0
    assert "3" in result.stdout  # 2 KOSPI + 1 KOSDAQ


def test_krx_sync_listed_actual_run_inserts_stocks(
    fake_listed, fake_corp_master, db_session,
):
    """실 sync — Stock 3 row 추가."""
    from sqlalchemy import select

    from themek.db.corp_models import Stock

    result = runner.invoke(app, ["krx", "sync-listed"])
    assert result.exit_code == 0, result.stdout
    assert "added=3" in result.stdout

    stocks = db_session.scalars(select(Stock)).all()
    assert {s.ticker for s in stocks} == {"005930", "000660", "247540"}


def test_krx_sync_listed_auto_enroll_creates_backfill_targets(
    fake_listed, fake_corp_master, db_session,
):
    """--auto-enroll --periods 2023 시 신규 ticker마다 BackfillTarget pending."""
    from sqlalchemy import select

    from themek.db.corp_models import BackfillTarget

    result = runner.invoke(app, [
        "krx", "sync-listed",
        "--auto-enroll", "--periods", "2023:2024",
    ])
    assert result.exit_code == 0, result.stdout
    assert "auto-enrolled" in result.stdout

    targets = db_session.scalars(select(BackfillTarget)).all()
    assert len(targets) == 6  # 3 corps × 2 years
    for t in targets:
        assert t.status == "pending"
