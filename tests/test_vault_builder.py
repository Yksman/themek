"""vault.builder — DB→파일 통합 + 멱등성 테스트."""
from datetime import date

from themek.db.models import (
    Corporation, Stock, Sector, Region, BusinessReport, BusinessSegment,
    RevenueComposition, CustomerRelation, GeographicExposure,
)
from themek.vault.builder import build_vault


def _seed(s):
    s.add(Sector(fics_code="G2520", name_ko="반도체"))
    s.add(Region(code="US", name_ko="미주"))
    s.add(Corporation(dart_code="00126380", name_ko="삼성전자",
                      in_sector_id="G2520"))
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


def test_build_vault_creates_expected_tree(tmp_path, db_session):
    _seed(db_session)
    stats = build_vault(db_session, tmp_path)
    assert stats["companies"] == 1
    assert (tmp_path / "_index.md").exists()
    assert (tmp_path / "_qa-report.md").exists()
    assert (tmp_path / "companies" / "삼성전자.md").exists()
    assert (tmp_path / "segments" / "메모리반도체.md").exists()
    assert (tmp_path / "regions" / "미주.md").exists()
    assert (tmp_path / "sectors" / "반도체.md").exists()
    assert list((tmp_path / "customers").glob("*.md"))


def test_build_vault_idempotent_same_output(tmp_path, db_session):
    _seed(db_session)
    build_vault(db_session, tmp_path)
    first = (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8")
    build_vault(db_session, tmp_path)  # 재실행
    second = (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8")
    assert first == second


def test_build_vault_clears_stale_generated_files(tmp_path, db_session):
    _seed(db_session)
    build_vault(db_session, tmp_path)
    stale = tmp_path / "companies" / "삭제될회사.md"
    stale.write_text("stale", encoding="utf-8")
    build_vault(db_session, tmp_path)  # 재생성
    assert not stale.exists()  # 생성 폴더는 비우고 재기록


def test_build_vault_preserves_obsidian_dir(tmp_path, db_session):
    _seed(db_session)
    obs = tmp_path / ".obsidian"
    obs.mkdir(parents=True)
    (obs / "app.json").write_text("{}", encoding="utf-8")
    build_vault(db_session, tmp_path)
    assert (obs / "app.json").exists()  # 사용자 설정 보존
