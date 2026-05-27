"""krx/sync.py: fetch_listed_universe 통합 + sync_listed_stocks DB 반영."""
from __future__ import annotations

from datetime import date

import pytest

from themek.krx.sync import fetch_listed_universe


class FakeKrxClient:
    def __init__(self, by_market: dict[str, list[str]]):
        self._by_market = by_market
        self.calls: list[tuple[str, str | None]] = []

    def list_tickers(self, *, market: str, date: str | None = None) -> list[str]:
        self.calls.append((market, date))
        return self._by_market.get(market, [])


def test_fetch_listed_universe_merges_kospi_kosdaq():
    """KOSPI+KOSDAQ을 각각 호출해 ticker → market 매핑으로 합친다."""
    client = FakeKrxClient({
        "KOSPI": ["005930", "000660"],
        "KOSDAQ": ["247540", "035720"],
    })
    result = fetch_listed_universe(client)
    assert result == {
        "005930": "KOSPI",
        "000660": "KOSPI",
        "247540": "KOSDAQ",
        "035720": "KOSDAQ",
    }
    assert [c[0] for c in client.calls] == ["KOSPI", "KOSDAQ"]


def test_fetch_listed_universe_passes_date():
    client = FakeKrxClient({"KOSPI": [], "KOSDAQ": []})
    fetch_listed_universe(client, date="20240515")
    assert client.calls == [("KOSPI", "20240515"), ("KOSDAQ", "20240515")]


def test_fetch_listed_universe_kospi_kosdaq_overlap_kosdaq_wins():
    """동일 ticker가 양쪽 호출에 반환되면 마지막(KOSDAQ)이 우선 — 현실에선 거의 없는 케이스지만 deterministic 동작 보장."""
    client = FakeKrxClient({
        "KOSPI": ["005930"],
        "KOSDAQ": ["005930"],
    })
    result = fetch_listed_universe(client)
    assert result == {"005930": "KOSDAQ"}


from sqlalchemy import select

from themek.db.models import Stock, Corporation


def _save_corp_master(cache, rows):
    cache.save_corp_master(rows)


def test_sync_listed_stocks_inserts_new_with_corp_link(
    db_session, tmp_path,
):
    """첫 sync — Stock + Corporation upsert + last_seen_at=today."""
    from themek.dart.cache import DartCache
    from themek.krx.sync import sync_listed_stocks

    cache = DartCache(base_dir=tmp_path)
    _save_corp_master(cache, [
        {"corp_code": "00126380", "corp_name": "삼성전자",
         "stock_code": "005930", "modify_date": "20240312"},
        {"corp_code": "01160363", "corp_name": "에코프로비엠",
         "stock_code": "247540", "modify_date": "20240312"},
    ])
    client = FakeKrxClient({
        "KOSPI": ["005930"],
        "KOSDAQ": ["247540"],
    })

    r = sync_listed_stocks(
        db_session, krx_client=client, cache=cache,
        today=date(2026, 5, 27),
    )

    stocks = {s.ticker: s for s in db_session.scalars(select(Stock)).all()}
    assert set(stocks.keys()) == {"005930", "247540"}
    assert stocks["005930"].market == "KOSPI"
    assert stocks["005930"].name_ko == "삼성전자"
    assert stocks["005930"].issued_by_id == "00126380"
    assert stocks["005930"].last_seen_at == date(2026, 5, 27)
    assert stocks["005930"].delisted_at is None
    assert set(r.added) == {"005930", "247540"}
    assert r.delisted == []
    assert r.updated == []
    assert r.unlinked == []


def test_sync_listed_stocks_marks_delisted(db_session, tmp_path):
    """기존 Stock이 KRX에 없으면 delisted_at=today set."""
    from themek.dart.cache import DartCache
    from themek.krx.sync import sync_listed_stocks

    cache = DartCache(base_dir=tmp_path)
    _save_corp_master(cache, [
        {"corp_code": "00126380", "corp_name": "삼성전자",
         "stock_code": "005930", "modify_date": "20240312"},
        {"corp_code": "00009999", "corp_name": "구상장사",
         "stock_code": "888888", "modify_date": "20100101"},
    ])
    db_session.add(Corporation(dart_code="00009999", name_ko="구상장사"))
    db_session.flush()
    db_session.add(Stock(
        ticker="888888", name_ko="구상장사", market="KOSPI",
        share_class="common", issued_by_id="00009999",
        last_seen_at=date(2026, 5, 20),
    ))
    db_session.commit()

    client = FakeKrxClient({"KOSPI": ["005930"], "KOSDAQ": []})
    r = sync_listed_stocks(
        db_session, krx_client=client, cache=cache,
        today=date(2026, 5, 27),
    )

    delisted = db_session.get(Stock, "888888")
    assert delisted.delisted_at == date(2026, 5, 27)
    assert r.delisted == ["888888"]


def test_sync_listed_stocks_unlinked_when_corp_master_missing(
    db_session, tmp_path,
):
    """pykrx ticker가 corp_master에 없으면 unlinked로 두고 skip (error 아님)."""
    from themek.dart.cache import DartCache
    from themek.krx.sync import sync_listed_stocks

    cache = DartCache(base_dir=tmp_path)
    _save_corp_master(cache, [])
    client = FakeKrxClient({"KOSPI": ["005930"], "KOSDAQ": []})
    r = sync_listed_stocks(
        db_session, krx_client=client, cache=cache,
        today=date(2026, 5, 27),
    )
    assert r.unlinked == ["005930"]
    assert r.added == []


def test_sync_listed_stocks_relisting_clears_delisted_at(
    db_session, tmp_path,
):
    """delisted_at=set인 Stock이 다시 KRX에 나타나면 None으로 복원."""
    from themek.dart.cache import DartCache
    from themek.krx.sync import sync_listed_stocks

    cache = DartCache(base_dir=tmp_path)
    _save_corp_master(cache, [
        {"corp_code": "00009999", "corp_name": "재상장사",
         "stock_code": "005930", "modify_date": "20240312"},
    ])
    db_session.add(Corporation(dart_code="00009999", name_ko="재상장사"))
    db_session.flush()
    db_session.add(Stock(
        ticker="005930", name_ko="재상장사", market="KOSPI",
        share_class="common", issued_by_id="00009999",
        delisted_at=date(2026, 1, 1), last_seen_at=date(2025, 12, 31),
    ))
    db_session.commit()

    client = FakeKrxClient({"KOSPI": ["005930"], "KOSDAQ": []})
    r = sync_listed_stocks(
        db_session, krx_client=client, cache=cache,
        today=date(2026, 5, 27),
    )
    stock = db_session.get(Stock, "005930")
    assert stock.delisted_at is None
    assert stock.last_seen_at == date(2026, 5, 27)
    assert "005930" in r.updated
