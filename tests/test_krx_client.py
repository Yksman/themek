"""KrxClient: pykrx 의존성 격리 wrapper."""
from __future__ import annotations

import pytest

from themek.krx.client import KrxClient


def test_krx_client_list_tickers_calls_pykrx(mocker):
    """KrxClient.list_tickers는 pykrx.stock.get_market_ticker_list로 위임한다."""
    fake = mocker.patch(
        "themek.krx.client.stock.get_market_ticker_list",
        return_value=["005930", "000660"],
    )
    client = KrxClient()
    result = client.list_tickers(market="KOSPI")
    assert result == ["005930", "000660"]
    fake.assert_called_once_with(market="KOSPI")


def test_krx_client_list_tickers_with_date(mocker):
    fake = mocker.patch(
        "themek.krx.client.stock.get_market_ticker_list",
        return_value=["005930"],
    )
    client = KrxClient()
    result = client.list_tickers(market="KOSDAQ", date="20240515")
    assert result == ["005930"]
    fake.assert_called_once_with("20240515", market="KOSDAQ")


def test_krx_client_rejects_invalid_market():
    client = KrxClient()
    with pytest.raises(ValueError, match="market"):
        client.list_tickers(market="INVALID")
