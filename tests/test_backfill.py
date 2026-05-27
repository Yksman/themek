"""backfill.run_one_target + enumerate_targets + run_batch."""
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from themek.dart.backfill import (
    BackfillTargetSpec, enumerate_targets, run_batch, run_one_target,
)
from themek.dart.cache import DartCache
from themek.dart.fetch import BusinessReportFetchError
from themek.dart.rate_budget import RateBudget, RateBudgetExceeded
from themek.db.models import BackfillTarget, Corporation
from themek.llm.schemas import BusinessExtraction, SegmentItem


# ──────────────────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────────────────


def _stub_extractor():
    def stub(text, period_hint):
        return BusinessExtraction(
            period=period_hint,
            segments=[SegmentItem(name_ko="테스트부문", share_pct=100.0)],
            customers=[],
            geographic=[],
        )
    return stub


def _tmp_cache(tmp_path) -> DartCache:
    return DartCache(base_dir=tmp_path / "cache")


def _tmp_budget(tmp_path, *, daily_cap: int = 100) -> RateBudget:
    return RateBudget(
        daily_cap=daily_cap,
        state_file=tmp_path / f"budget_{daily_cap}.json",
    )


def _make_fetcher_returning_html(html: bytes, rcept_no: str = "20260301001"):
    """Test fetcher that materializes a cached business.html and returns its path."""
    def fetcher(client, cache, *, ticker: str, year: int, corp_code: str):
        path = cache.save_business_html(rcept_no, html)
        # Also persist a fake document.zip so purge_zip test works
        cache.save_raw_zip(rcept_no, b"FAKE-ZIP-CONTENTS")
        return path, rcept_no
    return fetcher


def _make_fetcher_raising(exc):
    def fetcher(client, cache, *, ticker: str, year: int, corp_code: str):
        raise exc
    return fetcher


_VALID_HTML = (
    "<html><body>\n"
    "<h1>II. 사업의 내용</h1>\n"
    "<h2>1. 사업의 개요</h2>\n"
    + ("당사는 한국의 대표 전자제품 제조회사로 반도체, 휴대전화, 가전제품 등 다양한 제품을 생산하고 있습니다. " * 30)
    + "\n<h2>2. 주요 제품 및 서비스</h2>\n"
    + ("주요 제품은 메모리 반도체, 디스플레이, 휴대전화, TV, 생활가전 등이며 글로벌 시장에 공급한다. " * 30)
    + "\n<h2>3. 매출 실적</h2>\n"
    + ("연결 매출은 매년 증가 추세를 보이고 있으며 반도체 부문이 매출의 약 50%를 차지하고 있다. " * 30)
    + "\n</body></html>"
).encode("utf-8")


# ──────────────────────────────────────────────────────────────────────────
# run_one_target tests
# ──────────────────────────────────────────────────────────────────────────


def test_run_one_target_happy_path_captures_cost(tmp_path, db_session):
    """fetch + ingest 성공 → status=done, 비용 컬럼 채워짐."""
    target = BackfillTarget(
        corp_code="00126380", period="2025", status="pending",
    )
    db_session.add(target)
    db_session.commit()

    result = run_one_target(
        target=target, session=db_session,
        client=object(), cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
        fetcher=_make_fetcher_returning_html(_VALID_HTML),
    )
    db_session.refresh(target)
    assert result.status == "done"
    assert target.status == "done"
    assert target.attempts == 1
    assert target.rcept_no is not None
    assert target.escalation_level is not None
    assert target.input_chars and target.input_chars > 0
    assert target.cost_estimate_usd is not None and float(target.cost_estimate_usd) > 0


def test_run_one_target_no_report_skipped_no_retry(tmp_path, db_session):
    """사업보고서 미존재 → status=skipped 즉시, attempts=1."""
    target = BackfillTarget(
        corp_code="00126380", period="1999", status="pending",
    )
    db_session.add(target)
    db_session.commit()
    result = run_one_target(
        target=target, session=db_session,
        client=object(), cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
        fetcher=_make_fetcher_raising(
            BusinessReportFetchError("corp_code=00126380 year=1999 사업보고서 없음 (DART)")
        ),
    )
    assert result.status == "skipped"
    assert target.status == "skipped"
    assert target.attempts == 1
    assert "사업보고서 없음" in (target.last_error or "")


def test_run_one_target_fetch_error_retries(tmp_path, db_session):
    """zip 손상 등 fetch 에러 → retry 대상 (pending로 되돌림)."""
    target = BackfillTarget(
        corp_code="00126380", period="2025", status="pending", attempts=0,
    )
    db_session.add(target)
    db_session.commit()
    run_one_target(
        target=target, session=db_session,
        client=object(), cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
        fetcher=_make_fetcher_raising(BusinessReportFetchError("zip 손상")),
    )
    assert target.status == "pending"
    assert target.attempts == 1


def test_run_one_target_fetch_error_exhausted_failed(tmp_path, db_session):
    """fetch 에러 3회 도달 → failed."""
    target = BackfillTarget(
        corp_code="00126380", period="2025", status="pending", attempts=2,
    )
    db_session.add(target)
    db_session.commit()
    run_one_target(
        target=target, session=db_session,
        client=object(), cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
        fetcher=_make_fetcher_raising(BusinessReportFetchError("zip 손상")),
    )
    assert target.status == "failed"
    assert target.attempts == 3


def test_run_one_target_llm_error_no_retry(tmp_path, db_session):
    """C5: LLM/schema 에러는 retry 안 함 — 즉시 failed."""
    target = BackfillTarget(
        corp_code="00126380", period="2025", status="pending",
    )
    db_session.add(target)
    db_session.commit()

    def bad_extractor(text, period_hint):
        raise ValueError("schema validation 실패")

    run_one_target(
        target=target, session=db_session,
        client=object(), cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=bad_extractor,
        fetcher=_make_fetcher_returning_html(_VALID_HTML),
    )
    assert target.status == "failed"
    assert target.attempts == 1


def test_run_one_target_budget_exceeded_reraises(tmp_path, db_session):
    """RateBudgetExceeded → in_progress 유지 + 예외 re-raise."""
    target = BackfillTarget(
        corp_code="00126380", period="2025", status="pending",
    )
    db_session.add(target)
    db_session.commit()
    with pytest.raises(RateBudgetExceeded):
        run_one_target(
            target=target, session=db_session,
            client=object(), cache=_tmp_cache(tmp_path),
            rate_budget=_tmp_budget(tmp_path, daily_cap=0),
            extractor=_stub_extractor(),
            fetcher=_make_fetcher_returning_html(_VALID_HTML),
        )
    db_session.refresh(target)
    assert target.status == "in_progress"


def test_run_one_target_purge_zip(tmp_path, db_session):
    """C7: purge_zip=True → business.html 추출 후 document.zip 삭제."""
    target = BackfillTarget(
        corp_code="00126380", period="2025", status="pending",
    )
    db_session.add(target)
    db_session.commit()
    cache = _tmp_cache(tmp_path)
    run_one_target(
        target=target, session=db_session,
        client=object(), cache=cache,
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
        fetcher=_make_fetcher_returning_html(_VALID_HTML, rcept_no="20260301999"),
        purge_zip=True,
    )
    rcept_dir = cache.raw_dir / "20260301999"
    assert (rcept_dir / "business.html").exists()
    assert not (rcept_dir / "document.zip").exists()


# ──────────────────────────────────────────────────────────────────────────
# enumerate_targets tests
# ──────────────────────────────────────────────────────────────────────────


def test_enumerate_targets_from_file(tmp_path):
    universe_file = tmp_path / "active.txt"
    universe_file.write_text("00126380\n00164742\n", encoding="utf-8")
    specs = enumerate_targets(universe_file=universe_file, periods="2024:2025")
    assert len(specs) == 4
    assert {(s.corp_code, s.period) for s in specs} == {
        ("00126380", "2024"), ("00126380", "2025"),
        ("00164742", "2024"), ("00164742", "2025"),
    }


def test_enumerate_targets_single_period(tmp_path):
    universe_file = tmp_path / "active.txt"
    universe_file.write_text("00126380\n", encoding="utf-8")
    specs = enumerate_targets(universe_file=universe_file, periods="2025")
    assert specs == [BackfillTargetSpec("00126380", "2025")]


# ──────────────────────────────────────────────────────────────────────────
# run_batch tests
# ──────────────────────────────────────────────────────────────────────────


def test_run_batch_processes_until_budget(tmp_path, db_session):
    """5 pending + budget=4 → 4개 처리 후 종료."""
    for i in range(5):
        db_session.add(BackfillTarget(
            corp_code=f"0012638{i}", period="2025", status="pending",
        ))
    db_session.commit()
    summary = run_batch(
        session=db_session,
        client=object(), cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path, daily_cap=4),
        extractor=_stub_extractor(),
        fetcher=_make_fetcher_returning_html(_VALID_HTML),
        max_targets=10,
    )
    assert summary.processed == 4
    from sqlalchemy import select, func
    pending = db_session.scalar(
        select(func.count()).select_from(BackfillTarget)
        .where(BackfillTarget.status == "pending")
    )
    assert pending == 1


def test_run_batch_respects_max_targets(tmp_path, db_session):
    for i in range(5):
        db_session.add(BackfillTarget(
            corp_code=f"0012638{i}", period="2025", status="pending",
        ))
    db_session.commit()
    summary = run_batch(
        session=db_session,
        client=object(), cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path, daily_cap=100),
        extractor=_stub_extractor(),
        fetcher=_make_fetcher_returning_html(_VALID_HTML),
        max_targets=2,
    )
    assert summary.processed == 2


def test_run_batch_reset_stale_in_progress(tmp_path, db_session):
    """default 180분 초과 in_progress → pending reset."""
    stale = BackfillTarget(
        corp_code="00126380", period="2025", status="in_progress",
        last_attempt_at=datetime.utcnow() - timedelta(hours=4),
    )
    db_session.add(stale)
    db_session.commit()
    run_batch(
        session=db_session,
        client=object(), cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
        fetcher=_make_fetcher_returning_html(_VALID_HTML),
    )
    db_session.refresh(stale)
    assert stale.status == "done"


def test_enumerate_targets_from_corps_basic():
    from themek.dart.backfill import enumerate_targets_from_corps

    specs = enumerate_targets_from_corps(
        corp_codes=["00126380", "00164742"], periods="2023:2024",
    )
    assert [(s.corp_code, s.period) for s in specs] == [
        ("00126380", "2023"),
        ("00126380", "2024"),
        ("00164742", "2023"),
        ("00164742", "2024"),
    ]


def test_enumerate_targets_from_corps_single_period():
    from themek.dart.backfill import enumerate_targets_from_corps

    specs = enumerate_targets_from_corps(
        corp_codes=["00126380"], periods="2023",
    )
    assert [(s.corp_code, s.period) for s in specs] == [("00126380", "2023")]


def test_enumerate_targets_existing_universe_file_still_works(tmp_path):
    """기존 enumerate_targets는 변경 없이 동작 (backward compat)."""
    from themek.dart.backfill import enumerate_targets

    p = tmp_path / "active.txt"
    p.write_text("00126380\n", encoding="utf-8")
    specs = enumerate_targets(universe_file=p, periods="2023")
    assert len(specs) == 1
    assert specs[0].corp_code == "00126380"
