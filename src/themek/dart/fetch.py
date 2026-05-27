"""DART 사업보고서 본문 fetch 오케스트레이션.

T0 정찰(2026-05-25) 결과: DART document.xml zip은 HTML이 아닌 **DART 전용 XML**을
담는다 (`dart4.xsd`). zip 내에 본 사업보고서 XML 1개 + 첨부 보고서 XML 0~N개.

본 보고서 XML 식별:
- 1차: `<DOCUMENT-NAME ACODE="11011">사업보고서</DOCUMENT-NAME>` 매치
- 2차 fallback: zip 내 .xml 중 최대 크기

"II. 사업의 내용" 섹션 추출 (본 XML 안에서):
- 1차: `<SECTION-1>` 노드 중 `<TITLE>` 자식의 `AASSOCNOTE` 속성이 'D-*-2-0-0' (chapter 2)
- 2차 fallback: `<TITLE>` 텍스트가 '사업의 내용' 포함 + 'II' or 'Ⅱ' 시작
"""
from __future__ import annotations
import zipfile
from io import BytesIO
from pathlib import Path
from lxml import etree
from themek.dart.cache import DartCache


class BusinessReportFetchError(RuntimeError):
    pass


_BUSINESS_REPORT_ACODE = b'ACODE="11011"'


def _select_main_report_xml(zip_bytes: bytes) -> bytes:
    """zip 내 .xml 파일 중 본 사업보고서 XML을 반환.

    1차: DOCUMENT-NAME ACODE="11011"(사업보고서) 매치
    2차 fallback: 가장 큰 .xml
    """
    with zipfile.ZipFile(BytesIO(zip_bytes)) as z:
        xml_names = [n for n in z.namelist() if n.lower().endswith(".xml")]
        if not xml_names:
            raise BusinessReportFetchError(
                f"zip에 .xml 파일 없음 (namelist={z.namelist()})"
            )
        # 1차: ACODE 매치
        for n in xml_names:
            data = z.read(n)
            head = data[:4096]
            if _BUSINESS_REPORT_ACODE in head and (
                "사업보고서".encode("utf-8") in head
            ):
                return data
        # 2차: 최대 크기
        biggest = max(xml_names, key=lambda n: z.getinfo(n).file_size)
        return z.read(biggest)


def _extract_business_section_xml(xml_bytes: bytes) -> bytes:
    """DART 본 XML에서 'II. 사업의 내용' SECTION-1을 찾아 그 sub-tree를 bytes로."""
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(xml_bytes, parser=parser)
    if root is None:
        raise BusinessReportFetchError("XML parse 실패 (root None)")

    candidate_section = None
    text_fallback = None
    for section in root.iter("SECTION-1"):
        title = section.find("TITLE")
        if title is None:
            continue
        aan = title.get("AASSOCNOTE", "")
        # 1차: chapter 2 식별자 D-*-2-0-0
        if aan.startswith("D-") and aan.endswith("-2-0-0"):
            candidate_section = section
            break
        # 2차: TITLE 텍스트 매치
        txt = (title.text or "").strip()
        if "사업의 내용" in txt and ("II" in txt or "Ⅱ" in txt):
            text_fallback = section

    if candidate_section is None:
        candidate_section = text_fallback
    if candidate_section is None:
        raise BusinessReportFetchError(
            "본 XML에서 'II. 사업의 내용' SECTION-1을 찾지 못함"
        )
    return etree.tostring(candidate_section, encoding="utf-8")


def extract_business_html_from_zip(zip_bytes: bytes) -> bytes:
    """DART document.xml zip → '사업의 내용' 본문을 HTML로 wrap한 bytes.

    실 응답 구조 (T0 정찰):
        zip
          ├─ <rcept_no>.xml           — 본 사업보고서 (사업의 내용 포함)
          ├─ <rcept_no>_00760.xml     — 감사보고서
          └─ <rcept_no>_00761.xml     — 별도 감사보고서

    반환값은 BeautifulSoup이 처리할 수 있도록 `<html><body>...</body></html>`로 감싼
    bytes — 기존 parser.extract_business_content 파이프라인과 호환.
    """
    main_xml = _select_main_report_xml(zip_bytes)
    section_xml = _extract_business_section_xml(main_xml)
    return b"<html><body>" + section_xml + b"</body></html>"


def find_business_report_rcept_no(client, *, corp_code: str, year: int) -> str:
    """list.json 조회 → report_nm이 '사업보고서' + (year.12) 매치 → 가장 최근 rcept_dt.

    사업보고서는 다음 해 3월경에 공시되므로 bgn_de/end_de를 year+1로 설정.
    """
    bgn_de = f"{year + 1}0101"
    end_de = f"{year + 1}0701"
    payload = client.list_periodic_reports(
        corp_code=corp_code, bgn_de=bgn_de, end_de=end_de,
    )
    year_token = f"({year}.12)"
    candidates = [
        r for r in payload.get("list", [])
        if r.get("report_nm", "").startswith("사업보고서")
        and year_token in r.get("report_nm", "")
    ]
    if not candidates:
        raise BusinessReportFetchError(
            f"corp_code={corp_code} year={year} 사업보고서 없음 (DART)"
        )
    candidates.sort(key=lambda r: r.get("rcept_dt", ""), reverse=True)
    return candidates[0]["rcept_no"]


def fetch_business_report_html(
    client,
    cache: DartCache,
    *,
    ticker: str,
    year: int,
    corp_code: str,
) -> tuple[Path, str]:
    """주 entry point. (ticker, year, corp_code) → (html_path, rcept_no).

    1. list.json으로 rcept_no 탐색
    2. cache hit이면 그대로 사용 (DART API 0회 추가 호출)
    3. cache miss면 document.xml zip fetch → XML 추출 → cache 저장
    """
    rcept_no = find_business_report_rcept_no(
        client, corp_code=corp_code, year=year,
    )
    if cache.has_business_html(rcept_no):
        return cache.get_business_html_path(rcept_no), rcept_no
    zip_bytes = client.fetch_document_zip(rcept_no=rcept_no)
    cache.save_raw_zip(rcept_no, zip_bytes)
    html_bytes = extract_business_html_from_zip(zip_bytes)
    path = cache.save_business_html(rcept_no, html_bytes)
    return path, rcept_no
