"""DartClient 단위 + 실 fixture 통합 테스트.

T0 정찰(2026-05-25)로 실 응답을 fixture로 저장하여 cassette playback 흉내.
실 API 호출 0회, 응답 구조는 실 DART OpenAPI 응답을 기준으로 한다.
"""
from __future__ import annotations
import json
import zipfile
from io import BytesIO
from pathlib import Path
import httpx
import pytest
from themek.dart.client import (
    DartClient, DartApiError, DartAuthError, DartRateLimitError,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dart_cassettes"
REAL_CORP_ZIP = FIXTURE_DIR / "corp_code_zip_success.bin"
REAL_LIST_JSON = FIXTURE_DIR / "list_json_samsung_2023.json"
REAL_DOC_ZIP = FIXTURE_DIR / "document_zip_samsung_2023.bin"


def _fake_response(status_code: int, *, content: bytes = b"", json_body=None,
                   text: str = "") -> httpx.Response:
    if json_body is not None:
        return httpx.Response(
            status_code=status_code, json=json_body,
            request=httpx.Request("GET", "https://opendart.fss.or.kr/api/x"),
        )
    return httpx.Response(
        status_code=status_code,
        content=content or text.encode("utf-8"),
        request=httpx.Request("GET", "https://opendart.fss.or.kr/api/x"),
    )


def _make_corpcode_zip() -> bytes:
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<result>"
        "<list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>"
        "<stock_code>005930</stock_code><modify_date>20240101</modify_date></list>"
        "</result>"
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", xml.encode("utf-8"))
    return buf.getvalue()


def test_client_init_requires_api_key():
    with pytest.raises(DartAuthError):
        DartClient(api_key="")


def test_client_init_ok_with_key():
    c = DartClient(api_key="xyz")
    assert c is not None


def test_fetch_corp_code_zip_returns_bytes(monkeypatch):
    zip_bytes = _make_corpcode_zip()

    def fake_get(self, url, **kwargs):
        assert "corpCode.xml" in url
        assert kwargs["params"]["crtfc_key"] == "key"
        return _fake_response(200, content=zip_bytes)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="key")
    data = client.fetch_corp_code_zip()
    assert isinstance(data, bytes)
    assert data[:2] == b"PK"
    assert len(data) > 50


def test_list_periodic_reports_returns_dict(monkeypatch):
    payload = {
        "status": "000",
        "message": "정상",
        "list": [
            {
                "rcept_no": "20240314000123",
                "report_nm": "사업보고서 (2023.12)",
                "rcept_dt": "20240314",
            },
        ],
    }

    def fake_get(self, url, **kwargs):
        assert "list.json" in url
        assert kwargs["params"]["corp_code"] == "00126380"
        assert kwargs["params"]["bgn_de"] == "20240101"
        assert kwargs["params"]["end_de"] == "20240701"
        assert kwargs["params"]["pblntf_ty"] == "A"
        return _fake_response(200, json_body=payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="key")
    result = client.list_periodic_reports(
        corp_code="00126380", bgn_de="20240101", end_de="20240701",
    )
    assert result["status"] == "000"
    assert any("사업보고서" in r["report_nm"] for r in result["list"])


def test_list_periodic_reports_accepts_status_013_no_data(monkeypatch):
    """DART는 데이터 없음 시 status=013을 반환 — 정상 흐름."""
    payload = {"status": "013", "message": "조회된 데이터가 없습니다.", "list": []}

    def fake_get(self, url, **kwargs):
        return _fake_response(200, json_body=payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="key")
    result = client.list_periodic_reports(
        corp_code="00000000", bgn_de="19990101", end_de="19990201",
    )
    assert result["status"] == "013"


def test_fetch_document_zip_returns_bytes(monkeypatch):
    """document.xml 응답은 zip bytes."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("01_cover.html", b"<html>cover</html>")
        z.writestr("02_II_business_content.html", b"<html>body</html>")
    doc_zip = buf.getvalue()

    def fake_get(self, url, **kwargs):
        assert "document.xml" in url
        assert kwargs["params"]["rcept_no"] == "20240314000123"
        return _fake_response(200, content=doc_zip)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="key")
    data = client.fetch_document_zip(rcept_no="20240314000123")
    assert data[:2] == b"PK"


def test_client_raises_auth_error_on_401(monkeypatch):
    def fake_get(self, url, **kwargs):
        return _fake_response(401, text="invalid key")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="bad")
    with pytest.raises(DartAuthError):
        client.fetch_corp_code_zip()


def test_client_raises_auth_error_on_403(monkeypatch):
    def fake_get(self, url, **kwargs):
        return _fake_response(403, text="forbidden")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="bad")
    with pytest.raises(DartAuthError):
        client.fetch_corp_code_zip()


def test_client_raises_rate_limit_on_429(monkeypatch):
    def fake_get(self, url, **kwargs):
        return _fake_response(429, text="rate")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="x")
    with pytest.raises(DartRateLimitError):
        client.fetch_corp_code_zip()


def test_client_raises_api_error_on_5xx(monkeypatch):
    def fake_get(self, url, **kwargs):
        return _fake_response(503, text="down")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="x")
    with pytest.raises(DartApiError):
        client.fetch_corp_code_zip()


def test_client_raises_api_error_on_4xx_non_auth(monkeypatch):
    def fake_get(self, url, **kwargs):
        return _fake_response(400, text="bad request")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="x")
    with pytest.raises(DartApiError):
        client.fetch_corp_code_zip()


# ---------- 실 fixture playback ----------

@pytest.mark.skipif(
    not REAL_CORP_ZIP.exists(),
    reason="실 corpCode.zip fixture 없음",
)
def test_fetch_corp_code_zip_real_fixture(monkeypatch):
    real_bytes = REAL_CORP_ZIP.read_bytes()

    def fake_get(self, url, **kwargs):
        return _fake_response(200, content=real_bytes)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="key")
    data = client.fetch_corp_code_zip()
    assert data == real_bytes
    assert data[:2] == b"PK"


@pytest.mark.skipif(
    not REAL_LIST_JSON.exists(),
    reason="실 list.json fixture 없음",
)
def test_list_periodic_reports_real_fixture(monkeypatch):
    real_payload = json.loads(REAL_LIST_JSON.read_text(encoding="utf-8"))

    def fake_get(self, url, **kwargs):
        return _fake_response(200, json_body=real_payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="key")
    result = client.list_periodic_reports(
        corp_code="00126380", bgn_de="20240101", end_de="20240701",
    )
    assert result["status"] == "000"
    samsung_business = [
        r for r in result["list"]
        if r.get("report_nm", "").startswith("사업보고서")
    ]
    assert len(samsung_business) >= 1
    assert samsung_business[0]["rcept_no"] == "20240312000736"


@pytest.mark.skipif(
    not REAL_DOC_ZIP.exists(),
    reason="실 document.zip fixture 없음",
)
def test_fetch_document_zip_real_fixture(monkeypatch):
    real_bytes = REAL_DOC_ZIP.read_bytes()

    def fake_get(self, url, **kwargs):
        return _fake_response(200, content=real_bytes)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="key")
    data = client.fetch_document_zip(rcept_no="20240312000736")
    assert data == real_bytes
    assert data[:2] == b"PK"


def test_list_json_raises_on_non_zero_status(monkeypatch):
    """status가 000/013이 아닌 경우(예: 권한 없음 020) → DartApiError."""
    payload = {"status": "020", "message": "사용한도 초과"}

    def fake_get(self, url, **kwargs):
        return _fake_response(200, json_body=payload)

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="x")
    with pytest.raises(DartApiError):
        client.list_periodic_reports(
            corp_code="00126380", bgn_de="20240101", end_de="20240701",
        )
