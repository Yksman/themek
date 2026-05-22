import json
from datetime import date
from pathlib import Path
import pytest
from themek.query.e5 import query_e5, E5Result
from themek.seeds import seed_basic
from themek.ingest.business_report import ingest_business_report
from themek.llm.schemas import BusinessExtraction


FIXTURE_JSON = Path(__file__).parent / "fixtures" / "samsung_extraction_expected.json"


def _stub(text, period_hint):
    return BusinessExtraction.model_validate(
        json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    )


def _setup(db_session):
    seed_basic(db_session)
    db_session.commit()
    ingest_business_report(
        db_session,
        dart_rcept_no="20240314000123",
        corporation_id="00126380",
        report_type="사업보고서",
        period="2023",
        filing_date=date(2024, 3, 14),
        raw_text_excerpt="…",
        url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123",
        extractor=_stub,
    )
    db_session.commit()


def test_query_e5_returns_structured_result(db_session):
    _setup(db_session)
    result: E5Result = query_e5(db_session, ticker="005930")
    assert result.stock_name == "삼성전자"
    assert result.corporation_name == "삼성전자"
    assert result.sector_name == "반도체"
    assert len(result.segments) == 3
    top_seg = result.segments[0]
    assert top_seg.name == "메모리반도체"
    assert top_seg.share_pct == 42.5
    assert len(result.top_customers) >= 1
    assert any(c.name_raw == "Apple Inc." for c in result.top_customers)
    assert len(result.top_regions) == 5
    assert result.source_report_rcept_no == "20240314000123"
    assert result.period == "2023"


def test_query_e5_raises_on_unknown_ticker(db_session):
    seed_basic(db_session)
    db_session.commit()
    with pytest.raises(LookupError, match="999999"):
        query_e5(db_session, ticker="999999")


def test_query_e5_returns_none_summary_when_no_report(db_session):
    seed_basic(db_session)
    db_session.commit()
    result = query_e5(db_session, ticker="005930")
    assert result.stock_name == "삼성전자"
    assert result.segments == []
    assert result.top_customers == []
    assert result.top_regions == []
    assert result.source_report_rcept_no is None
