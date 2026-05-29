"""Layer A: initial backfill 오케스트레이터.

핵심 함수:
- run_one_target: 1 BackfillTarget을 ingest. 에러 차등 + 비용 캡처 + purge-zip.
- enumerate_targets: active.txt + periods → 단순 곱.
- run_batch: pending row를 순서대로 처리. budget/max_targets/stale reset 처리.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import httpx
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from themek.config import get_settings
from themek.db.models import BackfillTarget, Corporation
from themek.dart.cache import DartCache
from themek.dart.rate_budget import RateBudget, RateBudgetExceeded
from themek.dart.fetch import (
    fetch_business_report_html, BusinessReportFetchError,
)
from themek.dart.parser import extract_business_sections
from themek.dart.universe import load_universe
from themek.ingest.business_report import ingest_business_report
from themek.llm.claude_cli import ClaudeRateLimitError

MAX_ATTEMPTS = 3

# C4: 비용 추정 단가 (대략) — input_chars 기준 토큰 비례.
# claude opus 4.x: input $15/M, output $75/M. 사업보고서 1 char ≈ 0.5 token.
# 종합 단가 ~$8.7/M input char + 고정 output. 보수적으로 $0.000009 / char + $0.05 base.
COST_PER_CHAR_USD = 9e-6
COST_BASE_USD = 0.05


@dataclass
class RunTargetResult:
    status: str
    rcept_no: Optional[str] = None
    error: Optional[str] = None
    escalation_level: Optional[str] = None
    input_chars: Optional[int] = None
    cost_estimate_usd: Optional[float] = None


@dataclass
class BackfillTargetSpec:
    corp_code: str
    period: str


@dataclass
class BatchSummary:
    processed: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    pending_remaining: int = 0
    budget_remaining: int = 0
    rate_limit_hits: int = 0
    rate_limit_waits: int = 0


def _is_no_report_error(e: Exception) -> bool:
    return isinstance(e, BusinessReportFetchError) and "사업보고서 없음" in str(e)


def _is_retryable(e: Exception) -> bool:
    """C5: fetch/network 계열만 retry. LLM/schema는 즉시 failed."""
    if isinstance(e, BusinessReportFetchError) and not _is_no_report_error(e):
        return True
    if isinstance(e, (httpx.TimeoutException, httpx.HTTPError)):
        return True
    return False


def _ensure_corporation(session: Session, *, corp_code: str,
                        cache: DartCache) -> None:
    existing = session.get(Corporation, corp_code)
    if existing is not None:
        return
    name_ko = corp_code
    rows = cache.load_corp_master()
    if rows is not None:
        for r in rows:
            if r.get("corp_code") == corp_code:
                name_ko = r.get("corp_name") or corp_code
                break
    session.add(Corporation(dart_code=corp_code, name_ko=name_ko))
    session.flush()


def run_one_target(
    *,
    target: BackfillTarget,
    session: Session,
    client,
    cache: DartCache,
    rate_budget: RateBudget,
    extractor: Callable,
    fetcher: Optional[Callable] = None,
    purge_zip: bool = False,
) -> RunTargetResult:
    """1개 BackfillTarget을 ingest.

    예외는 status 반영 + 정상 return. RateBudgetExceeded는 re-raise.
    """
    fetcher = fetcher or fetch_business_report_html

    target.status = "in_progress"
    target.attempts += 1
    target.last_attempt_at = datetime.utcnow()
    session.commit()

    # Phase 1: fetch (DART 호출)
    try:
        rate_budget.consume(1)
        html_path, rcept_no = fetcher(
            client, cache,
            ticker="",
            year=int(target.period),
            corp_code=target.corp_code,
        )
    except RateBudgetExceeded:
        raise
    except Exception as e:
        if _is_no_report_error(e):
            target.status = "skipped"
            target.last_error = str(e)[:500]
            session.commit()
            return RunTargetResult(status="skipped", error=str(e))
        target.last_error = str(e)[:500]
        if _is_retryable(e) and target.attempts < MAX_ATTEMPTS:
            target.status = "pending"
        else:
            target.status = "failed"
        session.commit()
        return RunTargetResult(status=target.status, error=str(e))

    # Phase 2: extract + ingest (LLM 호출). SAVEPOINT으로 부분 ingest 격리.
    sp = session.begin_nested()
    try:
        html_text = html_path.read_text(encoding="utf-8")
        text, resolution = extract_business_sections(html_text)
        escalation = resolution.escalation_level
        input_chars = resolution.output_chars
        cost = round(COST_BASE_USD + input_chars * COST_PER_CHAR_USD, 4)

        _ensure_corporation(session, corp_code=target.corp_code, cache=cache)
        ingest_kwargs = dict(
            dart_rcept_no=rcept_no,
            corporation_id=target.corp_code,
            report_type="사업보고서",
            period=target.period,
            filing_date=date.today(),
            raw_text_excerpt=text,
            escalation_level=escalation,
        )
        if extractor is not None:
            ingest_kwargs["extractor"] = extractor
        ingest_business_report(session, **ingest_kwargs)

        target.rcept_no = rcept_no
        target.status = "done"
        target.last_error = None
        target.escalation_level = escalation
        target.input_chars = input_chars
        target.cost_estimate_usd = cost
        sp.commit()
        session.commit()

        # C7: 디스크 절약 — document.zip 삭제
        if purge_zip:
            zip_path = cache.raw_dir / rcept_no / "document.zip"
            if zip_path.exists():
                zip_path.unlink()

        return RunTargetResult(
            status="done", rcept_no=rcept_no,
            escalation_level=escalation, input_chars=input_chars,
            cost_estimate_usd=cost,
        )
    except ClaudeRateLimitError:
        sp.rollback()
        raise
    except Exception as e:
        # C5: LLM/extract/schema 에러는 retry 무의미 — 즉시 failed
        sp.rollback()
        target.last_error = str(e)[:500]
        target.status = "failed"
        session.commit()
        return RunTargetResult(status="failed", error=str(e))


def _parse_periods(periods: str) -> list[str]:
    if ":" in periods:
        a, b = periods.split(":")
        return [str(y) for y in range(int(a), int(b) + 1)]
    if "," in periods:
        return [p.strip() for p in periods.split(",")]
    return [periods.strip()]


def enumerate_targets_from_corps(
    *,
    corp_codes: list[str],
    periods: str,
) -> list[BackfillTargetSpec]:
    """corp_code list + periods → BackfillTargetSpec 곱.

    universe source가 file이든 Stock 테이블이든 상위에서 결정한 뒤 호출.
    """
    period_list = _parse_periods(periods)
    return [BackfillTargetSpec(c, p) for c in corp_codes for p in period_list]


def enumerate_targets(
    *,
    universe_file: Path,
    periods: str,
) -> list[BackfillTargetSpec]:
    """active.txt + periods → 단순 곱."""
    corps = load_universe(universe_file)
    return enumerate_targets_from_corps(corp_codes=corps, periods=periods)


def run_batch(
    *,
    session: Session,
    client,
    cache: DartCache,
    rate_budget: RateBudget,
    extractor: Callable,
    fetcher: Optional[Callable] = None,
    max_targets: int = 500,
    reset_stale_minutes: int = 180,
    purge_zip: bool = False,
) -> BatchSummary:
    # stale in_progress reset
    cutoff = datetime.utcnow() - timedelta(minutes=reset_stale_minutes)
    session.execute(
        update(BackfillTarget)
        .where(BackfillTarget.status == "in_progress")
        .where(BackfillTarget.last_attempt_at < cutoff)
        .values(status="pending")
    )
    session.commit()

    settings = get_settings()
    summary = BatchSummary()
    wait_iter = 0
    while summary.processed < max_targets:
        # Budget pre-check: don't even touch the next target if no budget
        if rate_budget.remaining() < 1:
            break
        target = session.scalar(
            select(BackfillTarget)
            .where(BackfillTarget.status == "pending")
            .order_by(BackfillTarget.id)
            .limit(1)
        )
        if target is None:
            break
        try:
            r = run_one_target(
                target=target, session=session,
                client=client, cache=cache, rate_budget=rate_budget,
                extractor=extractor, fetcher=fetcher, purge_zip=purge_zip,
            )
        except ClaudeRateLimitError:
            target.status = "pending"
            target.last_error = "rate limit (auto-recovery in progress)"
            session.commit()
            summary.rate_limit_hits += 1
            if not settings.themek_wait_for_quota:
                break
            if wait_iter >= settings.themek_wait_for_quota_max_iterations:
                break
            wait_iter += 1
            summary.rate_limit_waits += 1
            time.sleep(settings.themek_wait_for_quota_sec)
            continue
        except RateBudgetExceeded:
            break
        summary.processed += 1
        if r.status == "done":
            summary.done += 1
        elif r.status == "skipped":
            summary.skipped += 1
        elif r.status == "failed":
            summary.failed += 1

    summary.pending_remaining = session.scalar(
        select(func.count())
        .select_from(BackfillTarget)
        .where(BackfillTarget.status == "pending")
    ) or 0
    summary.budget_remaining = rate_budget.remaining()
    return summary
