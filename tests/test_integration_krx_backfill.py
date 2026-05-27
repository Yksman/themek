"""통합 smoke: pykrx mock → Stock sync → BackfillTarget enroll → backfill init from-stocks."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from themek.cli import app
from themek.db.models import BackfillTarget, Stock, Corporation


@pytest.fixture
def fake_krx_50(mocker):
    """KRX mock — KOSPI 30 + KOSDAQ 20 = 50개 ticker."""
    kospi = [f"{100000 + i:06d}" for i in range(30)]
    kosdaq = [f"{200000 + i:06d}" for i in range(20)]

    class _Fake:
        def list_tickers(self, *, market, date=None):
            return {"KOSPI": kospi, "KOSDAQ": kosdaq}.get(market, [])

    mocker.patch("themek.cli.KrxClient", return_value=_Fake())
    return kospi, kosdaq


@pytest.fixture
def fake_corp_master_50(tmp_path, mocker):
    """50개 ticker가 모두 corp_master에 있는 상태."""
    from themek.dart.cache import DartCache
    cache = DartCache(base_dir=tmp_path)
    rows = []
    for i in range(30):
        rows.append({
            "corp_code": f"{1000000 + i:08d}",
            "corp_name": f"KOSPI종목_{i}",
            "stock_code": f"{100000 + i:06d}",
            "modify_date": "20240312",
        })
    for i in range(20):
        rows.append({
            "corp_code": f"{2000000 + i:08d}",
            "corp_name": f"KOSDAQ종목_{i}",
            "stock_code": f"{200000 + i:06d}",
            "modify_date": "20240312",
        })
    cache.save_corp_master(rows)
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(None, cache),
    )
    return cache


def test_full_flow_sync_then_enroll_then_init_from_stocks(
    fake_krx_50, fake_corp_master_50, fresh_db,
):
    """krx sync-listed --auto-enroll → backfill init --from-stocks."""
    from themek.db.engine import make_engine, make_session_factory
    runner = CliRunner()

    # Step 1: sync-listed --auto-enroll --periods 2023:2024
    r1 = runner.invoke(app, [
        "krx", "sync-listed",
        "--auto-enroll", "--periods", "2023:2024",
    ])
    assert r1.exit_code == 0, r1.stdout
    assert "added=50" in r1.stdout

    Session = make_session_factory(make_engine())
    with Session() as s:
        stocks = s.scalars(select(Stock)).all()
        assert len(stocks) == 50

        targets = s.scalars(select(BackfillTarget)).all()
        assert len(targets) == 100  # 50 corps × 2 years
        assert all(t.status == "pending" for t in targets)

    # Step 2: backfill init --from-stocks (idempotent — 중복 skip)
    r2 = runner.invoke(app, [
        "dart", "backfill", "init",
        "--from-stocks", "--periods", "2023:2024", "--confirm",
    ])
    assert r2.exit_code == 0, r2.stdout
    assert "skipped (already exists)=100" in r2.stdout

    # Step 3: backfill init --from-stocks --periods 2025 (신규 1년)
    r3 = runner.invoke(app, [
        "dart", "backfill", "init",
        "--from-stocks", "--periods", "2025", "--confirm",
    ])
    assert r3.exit_code == 0
    with Session() as s:
        targets_after = s.scalars(select(BackfillTarget)).all()
        assert len(targets_after) == 150  # +50 for 2025


def test_relisting_round_trip(fake_corp_master_50, fresh_db, mocker):
    """상장폐지 → 다음 sync에서 다시 listed → delisted_at 복원."""
    from themek.db.engine import make_engine, make_session_factory
    runner = CliRunner()

    # Day 1: 50개 sync
    class _Fake1:
        def list_tickers(self, *, market, date=None):
            return {
                "KOSPI": [f"{100000 + i:06d}" for i in range(30)],
                "KOSDAQ": [f"{200000 + i:06d}" for i in range(20)],
            }.get(market, [])

    mocker.patch("themek.cli.KrxClient", return_value=_Fake1())
    r1 = runner.invoke(app, ["krx", "sync-listed"])
    assert r1.exit_code == 0
    assert "added=50" in r1.stdout

    # Day 2: KOSPI 1개 빠짐 → delisted
    class _Fake2:
        def list_tickers(self, *, market, date=None):
            return {
                "KOSPI": [f"{100000 + i:06d}" for i in range(29)],
                "KOSDAQ": [f"{200000 + i:06d}" for i in range(20)],
            }.get(market, [])

    mocker.patch("themek.cli.KrxClient", return_value=_Fake2())
    r2 = runner.invoke(app, ["krx", "sync-listed"])
    assert r2.exit_code == 0
    assert "delisted=1" in r2.stdout

    # Day 3: 다시 50개 → 복원
    mocker.patch("themek.cli.KrxClient", return_value=_Fake1())
    r3 = runner.invoke(app, ["krx", "sync-listed"])
    assert r3.exit_code == 0
    # updated=50 (모두 last_seen_at 갱신, 1개는 delisted_at 복원)
    assert "updated=50" in r3.stdout

    Session = make_session_factory(make_engine())
    with Session() as s:
        delisted_now = s.scalars(
            select(Stock).where(Stock.delisted_at.isnot(None))
        ).all()
        assert len(delisted_now) == 0
