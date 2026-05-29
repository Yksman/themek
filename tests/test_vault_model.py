"""vault.model — dataclass·정규화·고객 분류 단위 테스트."""
from datetime import date

from themek.db.models import (
    Corporation, Stock, Sector, Region, BusinessReport, BusinessSegment,
    RevenueComposition, CustomerRelation, GeographicExposure,
)
from themek.vault.model import normalize_name, classify_customer, build_graph


def test_normalize_name_collapses_whitespace_and_case():
    assert normalize_name("  Apple   Inc. ") == "apple inc."
    assert normalize_name("메모리반도체") == "메모리반도체"
    assert normalize_name("DX 부문") == "dx 부문"


def test_classify_customer_entity_short_propernoun():
    assert classify_customer("Apple Inc.") == "entity"
    assert classify_customer("Qualcomm") == "entity"
    assert classify_customer("Best Buy") == "entity"
    assert classify_customer("Deutsche Telekom") == "entity"


def test_classify_customer_descriptive_by_token():
    assert classify_customer("주요 글로벌 IT 고객사 (비공개)") == "descriptive"
    assert classify_customer("DRAM 수요처") == "descriptive"


def test_classify_customer_descriptive_by_length():
    raw = "세계 유수의 Mobile 및 Computing 관련 전자 업체 (DRAM 수요처)"
    assert classify_customer(raw) == "descriptive"


def test_classify_customer_descriptive_by_list_separators():
    assert classify_customer("합성수지, 플라스틱 가공업체, 가전제품 생산업체") == "descriptive"


def _seed_two_companies(s):
    """삼성(보고서 有) + 빈회사(보고서 無) 시드. 삼성·현대가 같은 'Apple Inc.' 지목."""
    sec = Sector(fics_code="G2520", name_ko="반도체")
    s.add(sec)
    s.add(Region(code="US", name_ko="미주"))
    s.add(Region(code="CN", name_ko="중국"))
    # 삼성: 보고서 있음
    s.add(Corporation(dart_code="00126380", name_ko="삼성전자",
                      name_en="Samsung", in_sector_id="G2520"))
    s.add(Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
                share_class="common", issued_by_id="00126380"))
    # 현대: 보고서 있음 (Apple 공동 지목 검증용)
    s.add(Corporation(dart_code="00164742", name_ko="현대자동차"))
    s.add(Stock(ticker="005380", name_ko="현대자동차", market="KOSPI",
                share_class="common", issued_by_id="00164742"))
    # 빈 회사: 보고서 없음 → 그래프 제외돼야 함
    s.add(Corporation(dart_code="99999999", name_ko="빈회사"))
    s.flush()

    s.add(BusinessReport(dart_rcept_no="20240314000001", corporation_id="00126380",
                         report_type="사업보고서", period="2023",
                         filing_date=date(2024, 3, 14), url="http://dart/1"))
    s.add(BusinessReport(dart_rcept_no="20240315000002", corporation_id="00164742",
                         report_type="사업보고서", period="2023",
                         filing_date=date(2024, 3, 15)))
    # 삼성 세그먼트 2개 (하나는 매출비중 有, 하나는 無)
    s.add(BusinessSegment(id="seg-mem", corporation_id="00126380", name_ko="메모리반도체"))
    s.add(BusinessSegment(id="seg-dx", corporation_id="00126380", name_ko="DX 부문"))
    s.flush()
    s.add(RevenueComposition(id="rc1", subject_segment_id="seg-mem",
                             period="2023", share_pct=42.5,
                             source_report_id="20240314000001"))
    # 삼성 고객 2건: Apple(entity) + 설명문(descriptive)
    s.add(CustomerRelation(id="cr1", seller_id="00126380", buyer_raw="Apple Inc.",
                           resolved=False, period="2023", tier="1차",
                           revenue_share_pct=18, source_report_id="20240314000001"))
    s.add(CustomerRelation(id="cr2", seller_id="00126380",
                           buyer_raw="주요 글로벌 IT 고객사 (비공개)",
                           resolved=False, period="2023", tier="unknown",
                           source_report_id="20240314000001"))
    # 현대도 Apple 지목 → named_by에 2개사
    s.add(CustomerRelation(id="cr3", seller_id="00164742", buyer_raw="Apple Inc.",
                           resolved=False, period="2023", tier="1차",
                           source_report_id="20240315000002"))
    # 삼성 지역노출 corp-level: 미주 2회(중복) + 중국 1회
    s.add(GeographicExposure(id="ge1", subject_corp_id="00126380", region_id="US",
                             period="2023", share_pct=35,
                             source_report_id="20240314000001"))
    s.add(GeographicExposure(id="ge2", subject_corp_id="00126380", region_id="US",
                             period="2023", share_pct=31.1,
                             source_report_id="20240314000001"))
    s.add(GeographicExposure(id="ge3", subject_corp_id="00126380", region_id="CN",
                             period="2023", share_pct=25.8,
                             source_report_id="20240314000001"))
    s.commit()


def test_build_graph_includes_only_companies_with_reports(db_session):
    _seed_two_companies(db_session)
    graph = build_graph(db_session)
    names = {c.name_ko for c in graph.companies}
    assert names == {"삼성전자", "현대자동차"}  # 빈회사 제외


def test_build_graph_company_fields(db_session):
    _seed_two_companies(db_session)
    graph = build_graph(db_session)
    samsung = next(c for c in graph.companies if c.name_ko == "삼성전자")
    assert samsung.ticker == "005930"
    assert samsung.market == "KOSPI"
    assert samsung.sector_name == "반도체"
    assert samsung.periods == ["2023"]
    assert len(samsung.reports) == 1
    # 세그먼트: 매출비중 有/無 둘 다 존재
    shares = {sl.name_ko: sl.share_pct for sl in samsung.segments}
    assert shares["메모리반도체"] == 42.5
    assert shares["DX 부문"] is None


def test_build_graph_dedupes_customer_node_and_aggregates_named_by(db_session):
    _seed_two_companies(db_session)
    graph = build_graph(db_session)
    apple = next(n for n in graph.customers if n.raw == "Apple Inc.")
    assert apple.kind == "entity"
    assert apple.resolved is False
    assert set(apple.named_by) == {"삼성전자", "현대자동차"}  # 공동 지목 병합


def test_build_graph_region_node_collects_company_shares(db_session):
    _seed_two_companies(db_session)
    graph = build_graph(db_session)
    us = next(n for n in graph.regions if n.code == "US")
    # 미주에 삼성이 2회 노출(중복) → 두 share 모두 수집
    samsung_shares = sorted(sh for name, sh in us.companies if name == "삼성전자")
    assert samsung_shares == [31.1, 35.0]
