import json
from datetime import date
from pathlib import Path
from themek.ingest.business_report import ingest_business_report
from themek.db.models import (
    BusinessReport, BusinessSegment,
    RevenueComposition, CustomerRelation, GeographicExposure,
)
from themek.seeds import seed_basic
from themek.llm.schemas import BusinessExtraction


FIXTURE_JSON = (Path(__file__).parent / "fixtures"
                / "samsung_extraction_expected.json")


def _stub_extractor(text, period_hint):
    return BusinessExtraction.model_validate(
        json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    )


def test_ingest_creates_report_and_segments(db_session):
    seed_basic(db_session)
    db_session.commit()
    ingest_business_report(
        db_session,
        dart_rcept_no="20240314000123",
        corporation_id="00126380",
        report_type="사업보고서",
        period="2023",
        filing_date=date(2024, 3, 14),
        raw_text_excerpt="...irrelevant for stub...",
        url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123",
        extractor=_stub_extractor,
    )
    db_session.commit()

    report = db_session.get(BusinessReport, "20240314000123")
    assert report is not None
    assert report.corporation_id == "00126380"

    segments = db_session.query(BusinessSegment).filter_by(
        corporation_id="00126380"
    ).all()
    assert len(segments) == 3
    assert {s.name_ko for s in segments} == {"메모리반도체", "스마트폰/네트워크", "디스플레이"}

    revenue = db_session.query(RevenueComposition).filter_by(
        source_report_id="20240314000123"
    ).all()
    assert len(revenue) == 3

    customers = db_session.query(CustomerRelation).filter_by(
        source_report_id="20240314000123"
    ).all()
    assert len(customers) == 2
    apple = next(c for c in customers if c.buyer_raw == "Apple Inc.")
    assert float(apple.revenue_share_pct) == 18.0
    assert apple.resolved is False

    geographic = db_session.query(GeographicExposure).filter_by(
        source_report_id="20240314000123"
    ).all()
    assert len(geographic) == 6
    assert {g.region_id for g in geographic} == {"KR", "US", "CN", "EU", "JP", "ROW"}


def test_ingest_is_idempotent(db_session):
    seed_basic(db_session)
    db_session.commit()
    for _ in range(2):
        ingest_business_report(
            db_session,
            dart_rcept_no="20240314000123",
            corporation_id="00126380",
            report_type="사업보고서",
            period="2023",
            filing_date=date(2024, 3, 14),
            raw_text_excerpt="...",
            extractor=_stub_extractor,
        )
        db_session.commit()
    assert db_session.query(BusinessReport).count() == 1
    assert db_session.query(BusinessSegment).filter_by(
        corporation_id="00126380"
    ).count() == 3
    assert db_session.query(RevenueComposition).count() == 3
