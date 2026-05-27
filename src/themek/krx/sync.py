"""KRX 상장사 → Stock 테이블 sync."""
from __future__ import annotations

from typing import Protocol


class _KrxClientLike(Protocol):
    def list_tickers(
        self, *, market: str, date: str | None = None,
    ) -> list[str]: ...


def fetch_listed_universe(
    client: _KrxClientLike,
    *,
    date: str | None = None,
) -> dict[str, str]:
    """KOSPI + KOSDAQ 통합. {ticker: market} 반환.

    date=None이면 최근 영업일.
    """
    out: dict[str, str] = {}
    for market in ("KOSPI", "KOSDAQ"):
        for t in client.list_tickers(market=market, date=date):
            out[t] = market
    return out
