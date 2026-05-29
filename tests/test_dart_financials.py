"""DART fetch_financials 단위 테스트 (httpx transport mock)."""
import json
from pathlib import Path

import httpx

from themek.dart.client import DartClient, DartApiError

_CASSETTE = Path("tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json")


def _client_with(payload: dict, capture: dict | None = None) -> DartClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["params"] = dict(request.url.params)
        return httpx.Response(200, json=payload)
    c = DartClient(api_key="dummy")
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_fetch_financials_returns_rows_and_passes_params():
    payload = json.loads(_CASSETTE.read_text(encoding="utf-8"))
    cap = {}
    c = _client_with(payload, cap)
    rows = c.fetch_financials(corp_code="00126380", bsns_year="2024",
                              reprt_code="11011", fs_div="CFS")
    assert len(rows) == 6
    assert cap["params"]["corp_code"] == "00126380"
    assert cap["params"]["reprt_code"] == "11011"
    assert cap["params"]["fs_div"] == "CFS"


def test_fetch_financials_empty_status_returns_empty():
    c = _client_with({"status": "013", "message": "조회된 데이타가 없습니다."})
    rows = c.fetch_financials(corp_code="00000000", bsns_year="2024",
                              reprt_code="11011", fs_div="CFS")
    assert rows == []
