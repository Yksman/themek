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
