"""vault.render — frontmatter·wikilink·파일명 안전화 + 노드 렌더 단위 테스트."""
from themek.vault.model import (
    CompanyNode, SegmentNode, CustomerNode, RegionNode, SectorNode,
    SegmentLine, CustomerLine, RegionLine, ReportLine, VaultGraph,
)
from themek.vault.render import (
    safe_filename, customer_slug, wikilink, frontmatter,
    render_company, render_segment, render_customer, render_region,
    render_sector, render_index, render_qa_report,
)
from themek.vault.qa import Issue, detect_issues


def test_safe_filename_strips_obsidian_unsafe_chars():
    assert safe_filename("CJ CGV") == "CJ CGV"
    assert safe_filename("스마트폰/네트워크") == "스마트폰 네트워크"
    assert safe_filename('A:B*C?"D<E>F|G') == "A B C D E F G"
    assert safe_filename("HD현대마린솔루션") == "HD현대마린솔루션"


def test_customer_slug_short_name_unchanged():
    assert customer_slug("Apple Inc.") == "Apple Inc."


def test_customer_slug_long_name_truncated_with_hash_suffix():
    raw = "세계 유수의 Mobile 및 Computing 관련 전자 업체 (DRAM 수요처)"
    slug = customer_slug(raw, max_len=20)
    assert len(slug) <= 20 + 1 + 6  # 본문 + 공백 + 6자 해시
    # 같은 원문은 항상 같은 slug (안정적)
    assert slug == customer_slug(raw, max_len=20)
    # 다른 원문은 다른 해시
    assert customer_slug(raw, max_len=20) != customer_slug(raw + "x", max_len=20)


def test_wikilink_plain_and_aliased():
    assert wikilink("삼성전자") == "[[삼성전자]]"
    assert wikilink("slug123", "전체 표시명") == "[[slug123|전체 표시명]]"
    # 동일하면 별칭 생략
    assert wikilink("삼성전자", "삼성전자") == "[[삼성전자]]"
    # display의 파이프/대괄호 제거
    assert wikilink("s", "a|b]c") == "[[s|a b c]]"


def test_frontmatter_serializes_valid_yaml_types():
    fm = frontmatter({
        "type": "company", "dart_code": "00126380", "issue_count": 3,
        "resolved": False, "periods": ["2022", "2023"],
    })
    assert fm.startswith("---\n") and fm.rstrip().endswith("---")
    assert 'type: "company"' in fm
    assert "issue_count: 3" in fm
    assert "resolved: false" in fm
    assert 'periods: ["2022", "2023"]' in fm


def test_frontmatter_escapes_quotes():
    fm = frontmatter({"name": 'A "quoted" name'})
    assert r'name: "A \"quoted\" name"' in fm


def _sample_company():
    return CompanyNode(
        dart_code="00126380", name_ko="삼성전자", name_en="Samsung",
        ticker="005930", market="KOSPI", sector_name="반도체", periods=["2023"],
        reports=[ReportLine("20240314000001", "2023", "사업보고서", "http://dart/1")],
        segments=[SegmentLine("메모리반도체", 42.5), SegmentLine("DX 부문", None)],
        customers=[CustomerLine("Apple Inc.", "1차", 18.0, False),
                   CustomerLine("주요 글로벌 IT 고객사 (비공개)", "unknown", None, False)],
        regions=[RegionLine("US", "미주", 35.0)],
    )


def test_render_company_path_and_frontmatter():
    path, text = render_company(_sample_company(), [])
    assert path == "companies/삼성전자.md"
    assert 'type: "company"' in text
    assert 'dart_code: "00126380"' in text
    assert "issue_count: 0" in text
    assert "[[메모리반도체]]" in text
    assert "[[미주]]" in text
    # 매출비중 없는 세그먼트도 렌더
    assert "DX 부문" in text


def test_render_company_links_segments_and_customers():
    path, text = render_company(_sample_company(), [])
    assert "[[Apple Inc.]]" in text
    # 설명문 고객도 링크 (긴 이름은 slug 별칭)
    assert "주요 글로벌 IT 고객사 (비공개)" in text


def test_render_company_embeds_issue_section():
    issues = [Issue("삼성전자", "geo_duplicate", "warn", "지역 '미주' 2회 중복: 35%, 31.1%")]
    path, text = render_company(_sample_company(), issues)
    assert "issue_count: 1" in text
    assert "geo_duplicate" in text
    assert "미주" in text


def test_render_customer_descriptive_tagged_and_named_by():
    node = CustomerNode(raw="주요 글로벌 IT 고객사 (비공개)", kind="descriptive",
                        resolved=False, named_by=["삼성전자", "현대자동차"])
    path, text = render_customer(node)
    assert path.startswith("customers/")
    assert 'kind: "descriptive"' in text
    assert "resolved: false" in text
    assert '"unresolved/descriptive"' in text
    assert "[[삼성전자]]" in text and "[[현대자동차]]" in text


def test_render_segment_lists_companies():
    node = SegmentNode(name_ko="메모리반도체", companies=["삼성전자", "SK하이닉스"])
    path, text = render_segment(node)
    assert path == "segments/메모리반도체.md"
    assert "[[삼성전자]]" in text and "[[SK하이닉스]]" in text


def test_render_region_and_sector():
    rpath, rtext = render_region(RegionNode("US", "미주", [("삼성전자", 35.0)]))
    assert rpath == "regions/미주.md"
    assert "[[삼성전자]]" in rtext and "35" in rtext
    spath, stext = render_sector(SectorNode("G2520", "반도체", None, ["삼성전자"]))
    assert spath == "sectors/반도체.md"
    assert "[[삼성전자]]" in stext


def test_render_index_and_qa_report():
    graph = VaultGraph(
        companies=[_sample_company()],
        customers=[
            CustomerNode(raw="Apple Inc.", kind="entity", resolved=False,
                         named_by=["삼성전자"]),
            CustomerNode(raw="주요 글로벌 IT 고객사 (비공개)", kind="descriptive",
                         resolved=False, named_by=["삼성전자"]),
        ],
    )
    issues = detect_issues(graph)
    ipath, itext = render_index(graph, issues)
    assert ipath == "_index.md"
    assert "[[삼성전자]]" in itext
    qpath, qtext = render_qa_report(graph, issues)
    assert qpath == "_qa-report.md"
    # 미주 단일이라 geo_duplicate 없음; low_segment 아님(2개). 미연결 고객 요약 존재
    assert "unresolved_customer" in qtext or "미연결" in qtext
