import uuid
from datetime import date
from themek.db.models import (
    Stock, Corporation, Sector, Region, Group,
    BusinessReport, BusinessSegment, Product, RevenueComposition,
    CustomerRelation, GeographicExposure,
)


def test_stock_creation(db_session):
    sector = Sector(fics_code="G2520", name_ko="반도체")
    corp = Corporation(dart_code="00126380", name_ko="삼성전자", in_sector=sector)
    stock = Stock(ticker="005930", name_ko="삼성전자", share_class="common",
                  market="KOSPI", issued_by=corp)
    db_session.add_all([sector, corp, stock])
    db_session.commit()

    fetched = db_session.get(Stock, "005930")
    assert fetched.name_ko == "삼성전자"
    assert fetched.issued_by.dart_code == "00126380"
    assert fetched.issued_by.in_sector.fics_code == "G2520"


def test_region_enum(db_session):
    kr = Region(code="KR", name_ko="국내")
    db_session.add(kr)
    db_session.commit()
    assert db_session.get(Region, "KR").name_ko == "국내"


def test_corporation_belongs_to_group_optional(db_session):
    corp = Corporation(dart_code="00111111", name_ko="테스트법인")
    db_session.add(corp)
    db_session.commit()
    assert db_session.get(Corporation, "00111111").belongs_to_id is None


def test_group_can_be_assigned(db_session):
    group = Group(name_ko="삼성그룹")
    db_session.add(group)
    db_session.flush()
    corp = Corporation(dart_code="00126380", name_ko="삼성전자",
                       belongs_to=group)
    db_session.add(corp)
    db_session.commit()
    assert db_session.get(Corporation, "00126380").belongs_to.name_ko == "삼성그룹"


def test_business_report_and_segment(db_session):
    corp = Corporation(dart_code="00126380", name_ko="삼성전자")
    db_session.add(corp)
    db_session.flush()

    report = BusinessReport(
        dart_rcept_no="20240314000123",
        corporation=corp,
        report_type="사업보고서",
        period="2023",
        filing_date=date(2024, 3, 14),
        url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123",
    )
    seg = BusinessSegment(
        id=str(uuid.uuid4()),
        corporation=corp,
        name_ko="메모리반도체",
    )
    db_session.add_all([report, seg])
    db_session.commit()

    assert db_session.get(BusinessReport, "20240314000123").corporation.name_ko == "삼성전자"
    assert seg.corporation_id == "00126380"


def test_revenue_composition_links_segment(db_session):
    corp = Corporation(dart_code="00126380", name_ko="삼성전자")
    db_session.add(corp)
    db_session.flush()
    report = BusinessReport(
        dart_rcept_no="20240314000123", corporation=corp,
        report_type="사업보고서", period="2023", filing_date=date(2024, 3, 14),
    )
    seg = BusinessSegment(id=str(uuid.uuid4()), corporation=corp, name_ko="DS")
    db_session.add_all([report, seg])
    db_session.flush()

    rc = RevenueComposition(
        id=str(uuid.uuid4()),
        subject_corp_id=None, subject_segment_id=seg.id,
        period="2023", share_pct=42.5, source_report=report,
    )
    db_session.add(rc)
    db_session.commit()
    fetched = db_session.get(RevenueComposition, rc.id)
    assert float(fetched.share_pct) == 42.5
    assert fetched.subject_segment_id == seg.id


def test_customer_relation_resolved_flag(db_session):
    seller = Corporation(dart_code="00111111", name_ko="공급사")
    buyer = Corporation(dart_code="00222222", name_ko="고객사A")
    db_session.add_all([seller, buyer])
    db_session.flush()
    report = BusinessReport(
        dart_rcept_no="20240315000001", corporation=seller,
        report_type="사업보고서", period="2023", filing_date=date(2024, 3, 15),
    )
    db_session.add(report)
    db_session.flush()
    cr = CustomerRelation(
        id=str(uuid.uuid4()),
        seller=seller, buyer_corp_id=buyer.dart_code,
        buyer_raw=None, resolved=True,
        period="2023", revenue_share_pct=18.2, tier="1차",
        source_report=report,
    )
    db_session.add(cr)
    db_session.commit()
    assert cr.resolved is True
    assert cr.buyer_corp_id == "00222222"


def test_customer_relation_unresolved_buyer(db_session):
    seller = Corporation(dart_code="00333333", name_ko="공급사B")
    db_session.add(seller)
    db_session.flush()
    report = BusinessReport(
        dart_rcept_no="20240316000001", corporation=seller,
        report_type="사업보고서", period="2023", filing_date=date(2024, 3, 16),
    )
    db_session.add(report)
    db_session.flush()
    cr = CustomerRelation(
        id=str(uuid.uuid4()),
        seller=seller, buyer_corp_id=None, buyer_raw="해외 고객 (이름 비공개)",
        resolved=False, period="2023", tier="unknown",
        source_report=report,
    )
    db_session.add(cr)
    db_session.commit()
    assert cr.resolved is False
    assert cr.buyer_raw == "해외 고객 (이름 비공개)"


def test_geographic_exposure(db_session):
    corp = Corporation(dart_code="00126380", name_ko="삼성전자")
    db_session.add(corp)
    db_session.flush()
    db_session.add(Region(code="US", name_ko="미주"))
    db_session.flush()
    report = BusinessReport(
        dart_rcept_no="20240314000123", corporation=corp,
        report_type="사업보고서", period="2023", filing_date=date(2024, 3, 14),
    )
    db_session.add(report)
    db_session.flush()
    ge = GeographicExposure(
        id=str(uuid.uuid4()),
        subject_corp_id=corp.dart_code, subject_segment_id=None,
        region_id="US", period="2023", share_pct=35.0,
        source_report=report,
    )
    db_session.add(ge)
    db_session.commit()
    fetched = db_session.get(GeographicExposure, ge.id)
    assert fetched.region_id == "US"
    assert float(fetched.share_pct) == 35.0
