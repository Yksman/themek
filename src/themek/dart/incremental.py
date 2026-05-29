"""Layer B: daily incremental scanner + run.

핵심 함수:
- scan_new_reports: list.json을 corp_code 없이 페이지네이션. 시간 범위 전체 정기공시.
- run_incremental: scan → 사업보고서 + universe filter + DB diff → 신규만 ingest.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import date


def scan_new_reports(
    client,
    *,
    bgn_de: str,
    end_de: str,
) -> list[dict]:
    """list.json을 corp_code 없이 페이지네이션 끝까지 전체 정기공시 수집."""
    all_rows: list[dict] = []
    page = 1
    while True:
        payload = client.list_periodic_reports(
            corp_code=None, bgn_de=bgn_de, end_de=end_de, page_no=page,
        )
        if payload.get("status") == "013":
            break
        all_rows.extend(payload.get("list", []))
        total = payload.get("total_page", 1)
        if page >= total:
            break
        page += 1
    return all_rows


@dataclass
class IncrementalRunResult:
    scanned: int = 0
    in_universe: int = 0
    already_ingested: int = 0
    to_ingest: int = 0
    ingested: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def _year_from_report_nm(report_nm: str) -> int:
    m = re.search(r"\((\d{4})\.", report_nm)
    if not m:
        raise ValueError(f"report_nm year 추출 실패: {report_nm}")
    return int(m.group(1))


def _parse_dt(rcept_dt: str) -> date:
    return date(int(rcept_dt[:4]), int(rcept_dt[4:6]), int(rcept_dt[6:8]))


def run_incremental(
    *,
    client,
    cache,
    session,
    universe: set[str],
    rate_budget,
    extractor,
    since: date,
    until: date,
    fetcher=None,
    purge_zip: bool = False,
) -> IncrementalRunResult:
    from sqlalchemy import select

    from themek.db.corp_models import BusinessReport
    from themek.ingest.business_report import ingest_business_report
    from themek.dart.fetch import fetch_business_report_html
    from themek.dart.parser import extract_business_sections
    from themek.dart.backfill import _ensure_corporation

    fetcher = fetcher or fetch_business_report_html

    rate_budget.consume(1)
    scanned = scan_new_reports(
        client, bgn_de=since.strftime("%Y%m%d"),
        end_de=until.strftime("%Y%m%d"),
    )
    result = IncrementalRunResult(scanned=len(scanned))

    candidates = [
        r for r in scanned
        if r.get("report_nm", "").startswith("사업보고서")
        and r.get("corp_code") in universe
    ]
    result.in_universe = len(candidates)
    if not candidates:
        return result

    existing = set(
        session.scalars(select(BusinessReport.dart_rcept_no)).all()
    )
    to_process = [r for r in candidates if r["rcept_no"] not in existing]
    result.already_ingested = len(candidates) - len(to_process)
    result.to_ingest = len(to_process)

    for r in to_process:
        try:
            rate_budget.consume(1)
            year = _year_from_report_nm(r["report_nm"])
            html_path, _ = fetcher(
                client, cache,
                ticker="", year=year,
                corp_code=r["corp_code"],
            )
            text, _ = extract_business_sections(
                html_path.read_text(encoding="utf-8"),
            )
            _ensure_corporation(
                session, corp_code=r["corp_code"], cache=cache,
            )
            ingest_kwargs = dict(
                dart_rcept_no=r["rcept_no"],
                corporation_id=r["corp_code"],
                report_type="사업보고서",
                period=str(year),
                filing_date=_parse_dt(r["rcept_dt"]),
                raw_text_excerpt=text,
            )
            if extractor is not None:
                ingest_kwargs["extractor"] = extractor
            ingest_business_report(session, **ingest_kwargs)
            session.commit()
            result.ingested += 1
            if purge_zip:
                zip_path = cache.raw_dir / r["rcept_no"] / "document.zip"
                if zip_path.exists():
                    zip_path.unlink()
        except Exception as e:
            session.rollback()
            result.failed.append((r["rcept_no"], str(e)))
    return result
