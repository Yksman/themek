"""CLI `themek vault build` 통합 테스트. 테스트 DB(conftest temp)에 커밋 후 실행."""
from datetime import date

from typer.testing import CliRunner

from themek.cli import app
from themek.db.engine import make_engine, make_session_factory
from themek.db.models import (
    Corporation, Stock, Sector, Region, BusinessReport, BusinessSegment,
    RevenueComposition, CustomerRelation, GeographicExposure,
)

runner = CliRunner()


def _seed_committed():
    s = make_session_factory(make_engine())()
    s.add(Sector(fics_code="G2520", name_ko="반도체"))
    s.add(Region(code="US", name_ko="미주"))
    s.add(Corporation(dart_code="00126380", name_ko="삼성전자", in_sector_id="G2520"))
    s.add(Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
                share_class="common", issued_by_id="00126380"))
    s.flush()
    s.add(BusinessReport(dart_rcept_no="20240314000001", corporation_id="00126380",
                         report_type="사업보고서", period="2023",
                         filing_date=date(2024, 3, 14)))
    s.add(BusinessSegment(id="seg-mem", corporation_id="00126380", name_ko="메모리반도체"))
    s.flush()
    s.add(RevenueComposition(id="rc1", subject_segment_id="seg-mem", period="2023",
                             share_pct=42.5, source_report_id="20240314000001"))
    s.add(CustomerRelation(id="cr1", seller_id="00126380", buyer_raw="Apple Inc.",
                           resolved=False, period="2023", tier="1차",
                           source_report_id="20240314000001"))
    s.add(GeographicExposure(id="ge1", subject_corp_id="00126380", region_id="US",
                             period="2023", share_pct=35,
                             source_report_id="20240314000001"))
    s.commit()
    s.close()


def test_vault_build_cli(tmp_path, fresh_db):
    _seed_committed()
    out = tmp_path / "vault"
    result = runner.invoke(app, ["vault", "build", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "vault built" in result.output
    assert "1 companies" in result.output
    assert (out / "_index.md").exists()
    assert (out / "_qa-report.md").exists()
    assert (out / "companies" / "삼성전자.md").exists()
