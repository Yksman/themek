"""pykrx 의존성 격리 wrapper.

pykrx는 KRX 웹사이트 스크래핑 기반이라 직접 의존하면 테스트가 네트워크에 묶인다.
이 wrapper를 통해 mocker.patch('themek.krx.client.stock....') 로 격리한다.
"""
from __future__ import annotations

from pykrx import stock

ALLOWED_MARKETS = ("KOSPI", "KOSDAQ", "KONEX", "ALL")


class KrxClient:
    """pykrx 호출 어댑터."""

    def list_tickers(
        self, *, market: str, date: str | None = None,
    ) -> list[str]:
        """KRX 종목 list. market은 KOSPI/KOSDAQ/KONEX/ALL."""
        if market not in ALLOWED_MARKETS:
            raise ValueError(
                f"market은 {ALLOWED_MARKETS} 중 하나여야 함 (got {market!r})"
            )
        if date is None:
            return stock.get_market_ticker_list(market=market)
        return stock.get_market_ticker_list(date, market=market)
