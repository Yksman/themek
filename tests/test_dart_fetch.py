"""fetch.py 단위 + 통합 테스트.

T0 정찰(2026-05-25) 후 재작성:
- DART zip은 HTML이 아닌 DART 전용 XML(dart4.xsd)을 담는다
- extract는 zip → 본 사업보고서 XML → 'II. 사업의 내용' SECTION-1 추출
"""
from __future__ import annotations
import zipfile
from io import BytesIO
from pathlib import Path
import pytest
from themek.dart.cache import DartCache
from themek.dart.fetch import (
    BusinessReportFetchError,
    extract_business_html_from_zip,
    find_business_report_rcept_no,
    fetch_business_report_html,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "dart_cassettes"
REAL_DOC_ZIP = FIXTURE_DIR / "document_zip_samsung_2023.bin"


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _make_dart_main_xml(
    *,
    chapter2_section: str = (
        '<SECTION-1 ACLASS="MANDATORY">\n'
        '<TITLE ATOC="Y" AASSOCNOTE="D-0-2-0-0" ATOCID="9">'
        'II. 사업의 내용</TITLE>\n'
        '<P>사업의 내용 본문</P>\n'
        '</SECTION-1>'
    ),
    other_chapters: bool = True,
    include_acode_11011: bool = True,
) -> bytes:
    """DART 본 사업보고서 XML 합성."""
    acode = '<DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>' \
        if include_acode_11011 else \
        '<DOCUMENT-NAME ACODE="99999">기타</DOCUMENT-NAME>'
    chap1 = (
        '<SECTION-1>'
        '<TITLE ATOC="Y" AASSOCNOTE="D-0-1-0-0" ATOCID="3">'
        'I. 회사의 개요</TITLE><P>회사 개요 본문</P>'
        '</SECTION-1>'
        if other_chapters else ''
    )
    chap3 = (
        '<SECTION-1>'
        '<TITLE ATOC="Y" AASSOCNOTE="D-0-3-0-0" ATOCID="17">'
        'III. 재무에 관한 사항</TITLE><P>재무 본문</P>'
        '</SECTION-1>'
        if other_chapters else ''
    )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<DOCUMENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:noNamespaceSchemaLocation="dart4.xsd">\n'
        + acode + '\n'
        '<COMPANY-NAME AREGCIK="00126380">삼성전자</COMPANY-NAME>\n'
        '<BODY ATOCID="285">\n'
        + chap1 + chapter2_section + chap3 +
        '</BODY>\n'
        '</DOCUMENT>'
    )
    return xml.encode("utf-8")


# ---------- extract_business_html_from_zip (synthetic XML) ----------

def test_extract_picks_business_section_by_aasocnote():
    """1차 매치: AASSOCNOTE D-0-2-0-0."""
    main_xml = _make_dart_main_xml()
    zip_bytes = _make_zip({"20240312000736.xml": main_xml})
    html = extract_business_html_from_zip(zip_bytes)
    assert html.startswith(b"<html><body>")
    assert html.endswith(b"</body></html>")
    assert "II. 사업의 내용".encode("utf-8") in html
    assert "사업의 내용 본문".encode("utf-8") in html
    # 다른 chapter는 포함 안 됨
    assert "회사 개요 본문".encode("utf-8") not in html
    assert "재무 본문".encode("utf-8") not in html


def test_extract_picks_via_title_text_fallback():
    """AASSOCNOTE가 비표준이면 TITLE 텍스트로 매치."""
    chapter2 = (
        '<SECTION-1 ACLASS="MANDATORY">\n'
        '<TITLE ATOC="Y" AASSOCNOTE="X-1-Y-Z" ATOCID="9">'
        'II. 사업의 내용</TITLE>\n'
        '<P>특수 케이스 본문</P>\n'
        '</SECTION-1>'
    )
    main_xml = _make_dart_main_xml(chapter2_section=chapter2)
    zip_bytes = _make_zip({"main.xml": main_xml})
    html = extract_business_html_from_zip(zip_bytes)
    assert "특수 케이스 본문".encode("utf-8") in html


def test_extract_picks_via_roman_unicode_title():
    """TITLE이 'Ⅱ. 사업의 내용' (유니코드 로마자)."""
    chapter2 = (
        '<SECTION-1>\n'
        '<TITLE>Ⅱ. 사업의 내용</TITLE>\n'
        '<P>유니코드 본문</P>\n'
        '</SECTION-1>'
    )
    main_xml = _make_dart_main_xml(chapter2_section=chapter2)
    zip_bytes = _make_zip({"main.xml": main_xml})
    html = extract_business_html_from_zip(zip_bytes)
    assert "유니코드 본문".encode("utf-8") in html


def test_extract_picks_main_via_acode_11011_with_attachments():
    """zip에 여러 XML이 있을 때 ACODE='11011' 사업보고서를 선택."""
    main_xml = _make_dart_main_xml()
    attachment = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<DOCUMENT><DOCUMENT-NAME ACODE="00760">감사보고서</DOCUMENT-NAME>'
        '<BODY><SECTION-1><TITLE AASSOCNOTE="D-0-2-0-0">감사 chapter II</TITLE>'
        '<P>감사 본문 (잘못된 매치 함정)</P></SECTION-1></BODY></DOCUMENT>'
    ).encode("utf-8")
    # 첨부가 더 크지만 ACODE 매치로 사업보고서가 우선
    zip_bytes = _make_zip({
        "20240312000736_00760.xml": attachment,
        "20240312000736.xml": main_xml,
    })
    html = extract_business_html_from_zip(zip_bytes)
    # 본 보고서의 chapter 2 본문이 추출됨
    assert "사업의 내용 본문".encode("utf-8") in html
    # 감사보고서 본문은 추출 안 됨
    assert "감사 본문".encode("utf-8") not in html


def test_extract_falls_back_to_largest_xml_when_no_acode():
    """ACODE 매치 실패 시 가장 큰 XML을 본 보고서로 간주."""
    big = _make_dart_main_xml(include_acode_11011=False)
    small = (
        '<DOCUMENT><DOCUMENT-NAME>기타</DOCUMENT-NAME>'
        '<BODY><SECTION-1><TITLE AASSOCNOTE="D-0-2-0-0">II. 사업의 내용</TITLE>'
        '<P>small 본문</P></SECTION-1></BODY></DOCUMENT>'
    ).encode("utf-8")
    zip_bytes = _make_zip({"small.xml": small, "big.xml": big})
    html = extract_business_html_from_zip(zip_bytes)
    # big에서 추출되어야 함
    assert "사업의 내용 본문".encode("utf-8") in html
    assert "small 본문".encode("utf-8") not in html


def test_extract_raises_when_no_xml():
    zip_bytes = _make_zip({"readme.txt": b"hello"})
    with pytest.raises(BusinessReportFetchError, match=".xml"):
        extract_business_html_from_zip(zip_bytes)


def test_extract_raises_when_no_business_section():
    """본 XML이 있어도 chapter 2가 없으면 실패."""
    xml = (
        '<DOCUMENT><DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>'
        '<BODY>'
        '<SECTION-1><TITLE AASSOCNOTE="D-0-1-0-0">I. 회사의 개요</TITLE></SECTION-1>'
        '<SECTION-1><TITLE AASSOCNOTE="D-0-3-0-0">III. 재무</TITLE></SECTION-1>'
        '</BODY></DOCUMENT>'
    ).encode("utf-8")
    zip_bytes = _make_zip({"main.xml": xml})
    with pytest.raises(BusinessReportFetchError, match="사업의 내용"):
        extract_business_html_from_zip(zip_bytes)


# ---------- extract: 실 DART fixture ----------

@pytest.mark.skipif(
    not REAL_DOC_ZIP.exists(),
    reason="실 DART document.zip fixture 없음 (T0 정찰 미실행)",
)
def test_extract_on_real_samsung_2023_zip():
    """삼성전자 2023 실 보고서 zip → 추출된 본문에 알려진 키워드 포함."""
    html = extract_business_html_from_zip(REAL_DOC_ZIP.read_bytes())
    text = html.decode("utf-8", errors="replace")
    assert "<html><body>" in text
    # SECTION-1 TITLE이 II. 사업의 내용
    assert "II. 사업의 내용" in text
    # 실제 삼성 사업보고서에 등장하는 키워드
    assert "사업의 개요" in text
    # 다른 chapter는 누락
    assert "III. 재무에 관한 사항" not in text


@pytest.mark.skipif(
    not REAL_DOC_ZIP.exists(),
    reason="실 DART document.zip fixture 없음",
)
def test_extract_real_zip_produces_sufficient_text():
    """추출된 HTML이 BeautifulSoup pipeline을 거쳐 충분한 본문 텍스트 산출."""
    from themek.dart.parser import extract_business_content
    html = extract_business_html_from_zip(REAL_DOC_ZIP.read_bytes())
    text = extract_business_content(html.decode("utf-8"))
    # 사업의 내용 섹션은 보통 수만 자 — 1만 자 이상 보수적 임계
    assert len(text) > 10_000
    # 삼성전자 사업보고서 키워드
    assert "DRAM" in text or "반도체" in text
    assert "사업의 개요" in text


# ---------- find_business_report_rcept_no ----------

class _FakeListClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def list_periodic_reports(self, **kwargs):
        self.calls.append(kwargs)
        return self.payload


def test_find_rcept_no_picks_matching_year():
    payload = {"status": "000", "list": [
        {"rcept_no": "20240312000736",
         "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240312"},
        {"rcept_no": "20230315000456",
         "report_nm": "사업보고서 (2022.12)", "rcept_dt": "20230315"},
    ]}
    client = _FakeListClient(payload)
    rcept = find_business_report_rcept_no(
        client, corp_code="00126380", year=2023,
    )
    assert rcept == "20240312000736"
    assert client.calls[0]["bgn_de"] == "20240101"
    assert client.calls[0]["end_de"] == "20240701"


def test_find_rcept_no_returns_latest_when_multiple_in_same_year():
    payload = {"status": "000", "list": [
        {"rcept_no": "20240501000001",
         "report_nm": "사업보고서 (2023.12) (정정)", "rcept_dt": "20240501"},
        {"rcept_no": "20240312000736",
         "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240312"},
    ]}
    rcept = find_business_report_rcept_no(
        _FakeListClient(payload), corp_code="00126380", year=2023,
    )
    assert rcept == "20240501000001"


def test_find_rcept_no_raises_when_no_match():
    payload = {"status": "000", "list": [
        {"rcept_no": "20230315000456",
         "report_nm": "사업보고서 (2022.12)", "rcept_dt": "20230315"},
    ]}
    with pytest.raises(BusinessReportFetchError, match="사업보고서 없음"):
        find_business_report_rcept_no(
            _FakeListClient(payload), corp_code="00126380", year=2023,
        )


def test_find_rcept_no_ignores_non_business_reports():
    payload = {"status": "000", "list": [
        {"rcept_no": "20240814000001",
         "report_nm": "반기보고서 (2024.06)", "rcept_dt": "20240814"},
        {"rcept_no": "20240312000736",
         "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240312"},
    ]}
    rcept = find_business_report_rcept_no(
        _FakeListClient(payload), corp_code="00126380", year=2023,
    )
    assert rcept == "20240312000736"


def test_find_rcept_no_handles_empty_list():
    payload = {"status": "013", "list": []}
    with pytest.raises(BusinessReportFetchError):
        find_business_report_rcept_no(
            _FakeListClient(payload), corp_code="00000000", year=2023,
        )


# ---------- fetch_business_report_html orchestration ----------

class _SpyClient:
    def __init__(self, list_payload, doc_zip):
        self.list_payload = list_payload
        self.doc_zip = doc_zip
        self.list_calls = 0
        self.doc_calls = 0

    def list_periodic_reports(self, **kwargs):
        self.list_calls += 1
        return self.list_payload

    def fetch_document_zip(self, *, rcept_no):
        self.doc_calls += 1
        return self.doc_zip


def test_fetch_cache_miss_fetches_and_saves(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    main_xml = _make_dart_main_xml()
    doc_zip = _make_zip({"20240312000736.xml": main_xml})
    client = _SpyClient(
        list_payload={"status": "000", "list": [
            {"rcept_no": "20240312000736",
             "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240312"},
        ]},
        doc_zip=doc_zip,
    )
    html_path, rcept_no = fetch_business_report_html(
        client, cache, ticker="005930", year=2023, corp_code="00126380",
    )
    assert rcept_no == "20240312000736"
    body = html_path.read_bytes()
    assert b"<html><body>" in body
    assert "사업의 내용 본문".encode("utf-8") in body
    assert client.list_calls == 1
    assert client.doc_calls == 1
    assert (tmp_path / "dart" / "raw" / "20240312000736"
            / "document.zip").exists()


def test_fetch_cache_hit_skips_document_api(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    cache.save_business_html(
        "20240312000736",
        "<html>cached</html>".encode("utf-8"),
    )
    client = _SpyClient(
        list_payload={"status": "000", "list": [
            {"rcept_no": "20240312000736",
             "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240312"},
        ]},
        doc_zip=b"",
    )
    html_path, rcept_no = fetch_business_report_html(
        client, cache, ticker="005930", year=2023, corp_code="00126380",
    )
    assert html_path.read_bytes() == b"<html>cached</html>"
    assert client.list_calls == 1
    assert client.doc_calls == 0


def test_fetch_propagates_extract_error(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    # zip에 XML 0개 → extract 실패
    doc_zip = _make_zip({"readme.txt": b"hello"})
    client = _SpyClient(
        list_payload={"status": "000", "list": [
            {"rcept_no": "20240312000736",
             "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240312"},
        ]},
        doc_zip=doc_zip,
    )
    with pytest.raises(BusinessReportFetchError):
        fetch_business_report_html(
            client, cache, ticker="005930", year=2023, corp_code="00126380",
        )


@pytest.mark.skipif(
    not REAL_DOC_ZIP.exists(),
    reason="실 DART fixture 없음",
)
def test_fetch_with_real_zip(tmp_path):
    """실 fixture(삼성 2023 zip)로 cache miss flow end-to-end."""
    cache = DartCache(base_dir=tmp_path / "dart")
    real_zip = REAL_DOC_ZIP.read_bytes()
    client = _SpyClient(
        list_payload={"status": "000", "list": [
            {"rcept_no": "20240312000736",
             "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240312"},
        ]},
        doc_zip=real_zip,
    )
    html_path, rcept_no = fetch_business_report_html(
        client, cache, ticker="005930", year=2023, corp_code="00126380",
    )
    assert rcept_no == "20240312000736"
    body = html_path.read_bytes()
    assert b"<html><body>" in body
    # 실 본문 검증
    assert "사업의 개요".encode("utf-8") in body
    # raw zip이 cache에 저장됨
    raw_zip_path = (tmp_path / "dart" / "raw" / "20240312000736"
                    / "document.zip")
    assert raw_zip_path.exists()
    assert raw_zip_path.stat().st_size == len(real_zip)
