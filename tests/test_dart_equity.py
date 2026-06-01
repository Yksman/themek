"""DART 최대주주/타법인출자 fetch 단위 테스트 (httpx transport mock)."""
import json
from pathlib import Path

import httpx

from themek.dart.client import DartClient

_HYSLR = Path("tests/fixtures/dart_cassettes/hyslrSttus_sample.json")
_OTR = Path("tests/fixtures/dart_cassettes/otrCprInvstmntSttus_sample.json")


def _client_with(payload: dict, capture: dict | None = None) -> DartClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["params"] = dict(request.url.params)
            capture["url"] = str(request.url)
        return httpx.Response(200, json=payload)
    c = DartClient(api_key="dummy")
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_fetch_largest_shareholders_rows_and_params():
    cap = {}
    c = _client_with(json.loads(_HYSLR.read_text(encoding="utf-8")), cap)
    rows = c.fetch_largest_shareholders(corp_code="00126380", bsns_year="2023",
                                        reprt_code="11011")
    assert len(rows) == 2
    assert rows[0]["nm"] == "이재용"
    assert "hyslrSttus.json" in cap["url"]
    assert cap["params"]["corp_code"] == "00126380"


def test_fetch_largest_shareholders_empty_status():
    c = _client_with({"status": "013", "message": "데이타 없음"})
    assert c.fetch_largest_shareholders(corp_code="x", bsns_year="2023",
                                        reprt_code="11011") == []


def test_fetch_other_corp_investments_rows():
    c = _client_with(json.loads(_OTR.read_text(encoding="utf-8")))
    rows = c.fetch_other_corp_investments(corp_code="00126380",
                                          bsns_year="2023", reprt_code="11011")
    assert len(rows) == 2
    assert rows[0]["inv_prm"] == "삼성디스플레이(주)"


def test_fetch_other_corp_investments_empty_status():
    c = _client_with({"status": "020", "message": "사용한도 초과"})
    assert c.fetch_other_corp_investments(corp_code="x", bsns_year="2023",
                                          reprt_code="11011") == []
