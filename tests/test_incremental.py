"""incremental.scan_new_reports + run_incremental."""
from datetime import date

import pytest

from themek.dart.cache import DartCache
from themek.dart.incremental import (
    IncrementalRunResult, run_incremental, scan_new_reports,
)
from themek.dart.rate_budget import RateBudget
from themek.db.corp_models import BusinessReport, Corporation
from themek.llm.schemas import BusinessExtraction, SegmentItem


class _SpyPagedClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def list_periodic_reports(self, **kwargs):
        self.calls.append(kwargs)
        idx = kwargs.get("page_no", 1) - 1
        if idx < len(self.pages):
            return self.pages[idx]
        return {"status": "013", "list": []}


def _tmp_cache(tmp_path) -> DartCache:
    return DartCache(base_dir=tmp_path / "cache")


def _tmp_budget(tmp_path, *, daily_cap: int = 100) -> RateBudget:
    return RateBudget(
        daily_cap=daily_cap,
        state_file=tmp_path / f"budget_{daily_cap}.json",
    )


def _stub_extractor():
    def stub(text, period_hint):
        return BusinessExtraction(
            period=period_hint,
            segments=[SegmentItem(name_ko="테스트", share_pct=100.0)],
            customers=[],
            geographic=[],
        )
    return stub


_VALID_HTML = (
    "<html><body>"
    + ("사업보고서 본문입니다. " * 500)
    + "</body></html>"
).encode("utf-8")


def _make_fetcher_returning_html(html: bytes):
    def fetcher(client, cache, *, ticker, year, corp_code):
        # rcept_no will be the rcept_no from the candidate row
        # but fetcher signature doesn't have it; we just use a synthetic rcept
        rcept_no = f"FAKE{corp_code}"
        path = cache.save_business_html(rcept_no, html)
        return path, rcept_no
    return fetcher


# ──────────────────────────────────────────────────────────────────────────
# scan_new_reports tests
# ──────────────────────────────────────────────────────────────────────────


def test_scan_single_page():
    client = _SpyPagedClient([{
        "status": "000", "total_page": 1, "page_no": 1,
        "list": [
            {"rcept_no": "20260301001", "corp_code": "00126380",
             "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260301"},
            {"rcept_no": "20260301002", "corp_code": "00164742",
             "report_nm": "반기보고서 (2025.06)", "rcept_dt": "20260301"},
        ],
    }])
    rows = scan_new_reports(client, bgn_de="20260301", end_de="20260302")
    assert len(rows) == 2
    assert len(client.calls) == 1


def test_scan_multi_page():
    client = _SpyPagedClient([
        {"status": "000", "total_page": 3, "page_no": 1, "list": [{"rcept_no": "A"}]},
        {"status": "000", "total_page": 3, "page_no": 2, "list": [{"rcept_no": "B"}]},
        {"status": "000", "total_page": 3, "page_no": 3, "list": [{"rcept_no": "C"}]},
    ])
    rows = scan_new_reports(client, bgn_de="20260301", end_de="20260331")
    assert {r["rcept_no"] for r in rows} == {"A", "B", "C"}
    assert len(client.calls) == 3


def test_scan_empty_013():
    client = _SpyPagedClient([{"status": "013", "list": []}])
    assert scan_new_reports(client, bgn_de="20260101", end_de="20260102") == []


# ──────────────────────────────────────────────────────────────────────────
# run_incremental tests
# ──────────────────────────────────────────────────────────────────────────


def test_run_incremental_filters_and_ingests(tmp_path, db_session):
    """scan → 사업보고서 + universe filter + DB diff → 신규만 ingest."""
    universe = {"00126380", "00164742"}

    # 이미 ingest된 1건 (Corporation도 함께)
    db_session.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
    db_session.add(BusinessReport(
        dart_rcept_no="20260301001", corporation_id="00126380",
        report_type="사업보고서", period="2025",
        filing_date=date(2026, 3, 1),
    ))
    db_session.commit()

    client = _SpyPagedClient([{
        "status": "000", "total_page": 1, "page_no": 1,
        "list": [
            {"rcept_no": "20260301001", "corp_code": "00126380",
             "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260301"},
            {"rcept_no": "20260301002", "corp_code": "00126380",
             "report_nm": "반기보고서 (2025.06)", "rcept_dt": "20260301"},
            {"rcept_no": "20260301003", "corp_code": "99999999",
             "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260301"},
            {"rcept_no": "20260301004", "corp_code": "00164742",
             "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260301"},
        ],
    }])
    result = run_incremental(
        client=client, cache=_tmp_cache(tmp_path),
        session=db_session, universe=universe,
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
        since=date(2026, 3, 1), until=date(2026, 3, 2),
        fetcher=_make_fetcher_returning_html(_VALID_HTML),
    )
    assert result.scanned == 4
    assert result.in_universe == 2
    assert result.already_ingested == 1
    assert result.to_ingest == 1
    assert result.ingested == 1


def test_run_incremental_empty_run_zero_llm(tmp_path, db_session):
    """신규 0건 → ingest 0, LLM 0 호출."""
    client = _SpyPagedClient([{"status": "013", "list": []}])

    class _FailIfCalled:
        def __call__(self, *a, **kw):
            raise AssertionError("LLM 호출됨")

    result = run_incremental(
        client=client, cache=_tmp_cache(tmp_path),
        session=db_session, universe={"00126380"},
        rate_budget=_tmp_budget(tmp_path),
        extractor=_FailIfCalled(),
        since=date(2026, 1, 1), until=date(2026, 1, 2),
    )
    assert result.ingested == 0
    assert result.scanned == 0
