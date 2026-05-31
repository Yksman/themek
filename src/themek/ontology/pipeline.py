"""DART 통합 파이프라인 오케스트레이션 (순수 함수 + 얇은 단계 조합)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Node, Edge

_YEAR = re.compile(r"^\d{4}$")
_REPRT_CODES = ("11011", "11012", "11013", "11014")


def derive_financial_years(session: Session) -> list[str]:
    """코어 엣지 period 중 4자리 연도만 distinct·정렬 반환 (전역 — 요약/로깅용)."""
    rows = session.execute(
        select(Edge.period).where(Edge.period.is_not(None)).distinct()
    ).scalars().all()
    years = {p for p in rows if p and _YEAR.match(p)}
    return sorted(years)


def company_report_years(session: Session, company_id: str) -> list[str]:
    """해당 회사가 실제 제출한 보고서의 회계연도(4자리) — 그 회사 엣지 period 기준."""
    rows = session.execute(
        select(Edge.period).where(
            Edge.subject_id == company_id, Edge.period.is_not(None)
        ).distinct()
    ).scalars().all()
    return sorted({p for p in rows if p and _YEAR.match(p)})


def recent_fiscal_years(today: "date", n: int = 3) -> list[str]:
    """today 기준 최근 n개 회계연도(현재 역년 포함). 예: 2026 → ['2024','2025','2026'].

    엣지(사업보고서 적재)와 무관하게 항상 시도하는 '최신화 floor'. 현재 역년을 포함해
    당해 분기/반기보고서가 제출되는 즉시 잡히도록 한다(아직 미제출 연/분기는 DART가
    status 013로 빈 응답 → 멱등·무해). 회사별 제출 연도 ∪ 이 floor 가 실제 조회 대상.
    """
    y = today.year
    return sorted(str(y - i) for i in range(n))


def ingest_financials_all(session: Session, client, *,
                          years: list[str] | None = None,
                          today: "date | None" = None,
                          floor_n: int = 3) -> dict:
    """재무 적재.

    기본은 **회사별 실제 제출 회계연도(`company_report_years`) ∪ 최신화 floor**
    (`recent_fiscal_years`)를 적재한다. floor 덕분에 사업보고서가 아직 적재되지 않은
    최근 연도(당해 분기 포함)도 항상 조회 → 매일 돌리면 자가치유(self-healing)된다.
    `years`를 명시하면 그 연도를 전 회사에 강제 적용하고 floor는 끈다(테스트·수동
    override). fnlttSinglAcntAll 1콜=당기/전기/전전기 3개년이라 flow 지표는 추가로
    조회연도 -2년까지 자동 확보된다(stock 지표는 조회 당해만 적재).
    """
    from themek.ontology.ingest.financials import (
        ingest_financials_for_company, ingest_shares_for_company)

    floor = (set() if years is not None
             else set(recent_fiscal_years(today or date.today(), floor_n)))

    companies = session.execute(
        select(Node).where(Node.kind == "company")
    ).scalars().all()
    facts = 0
    failed: list[tuple[str, str]] = []
    processed = 0
    for node in companies:
        dart_code = node.attrs.get("dart_code")
        if not dart_code:
            continue
        processed += 1
        company_years = (years if years is not None else sorted(
            set(company_report_years(session, node.id)) | floor))
        for yr in company_years:
            for rc in _REPRT_CODES:
                try:
                    facts += ingest_financials_for_company(
                        session, client, corp_code=dart_code,
                        bsns_year=yr, reprt_code=rc)
                    facts += ingest_shares_for_company(
                        session, client, corp_code=dart_code,
                        bsns_year=yr, reprt_code=rc)
                except Exception as e:  # 회사별 관용
                    failed.append((dart_code, f"{yr}/{rc}: {e}"))
    return {"companies": processed, "facts": facts, "failed": failed}


def rebuild_financials(session: Session, client, *,
                       today: "date | None" = None, floor_n: int = 3) -> dict:
    """financial_facts 전체 purge 후 회사별 제출 연도 ∪ 최신화 floor로 재적재 + 무결성 검사.

    1.1 BS 오염 교정용. _upsert_fact는 덮어쓰기만 하므로(삭제 안 함) purge가 선행해야
    잘못 라벨된 기존 행이 제거된다. 멱등(재실행 안전).
    """
    from themek.ontology.core.models import FinancialFact
    from themek.ontology.validate import check_integrity

    deleted = session.query(FinancialFact).delete()
    session.flush()
    stats = ingest_financials_all(session, client, today=today, floor_n=floor_n)
    session.flush()
    issues = check_integrity(session)
    errors = [i for i in issues if i.severity == "error"]
    return {"deleted": deleted, "facts": stats["facts"],
            "failed": stats["failed"], "issues": issues, "errors": errors}


@dataclass
class PipelineResult:
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    sync: int | None = None
    structure: object | None = None
    financials: dict | None = None
    export: dict | None = None


from pathlib import Path  # noqa: E402


def run_pipeline(
    session: Session, client, *, cache,
    skip_sync: bool, skip_structure: bool, skip_financials: bool, skip_export: bool,
    since, until, universe, rate_budget, extractor,
    out_vault, out_graph,
) -> PipelineResult:
    """4단계(sync→structure→financials→export) 오케스트레이션. skip 플래그 존중."""
    from themek.dart.corp_lookup import sync_corp_master
    from themek.dart.incremental import run_incremental
    from themek.ontology.projection.vault import build_vault
    from themek.ontology.projection.graph_export import export_graph

    result = PipelineResult()

    # 1. sync
    if skip_sync:
        result.skipped.append("sync")
    else:
        result.sync = sync_corp_master(client, cache)
        result.ran.append("sync")

    # 2. structure (incremental, 자동 기간)
    if skip_structure:
        result.skipped.append("structure")
    else:
        result.structure = run_incremental(
            client=client, cache=cache, session=session, universe=universe,
            rate_budget=rate_budget, extractor=extractor, since=since, until=until)
        result.ran.append("structure")

    # 3. financials (회사별 실제 제출 회계연도 자동 적재)
    if skip_financials:
        result.skipped.append("financials")
    else:
        stats = ingest_financials_all(session, client)  # 회사별 연도
        stats["years"] = derive_financial_years(session)  # 전역 요약(표시용)
        result.financials = stats
        result.ran.append("financials")

    # 4. export (vault + graph)
    if skip_export:
        result.skipped.append("export")
    else:
        v = build_vault(session, Path(out_vault))
        g = export_graph(session, Path(out_graph))
        result.export = {"companies": v["companies"], "nodes": g["nodes"],
                         "edges": g["edges"]}
        result.ran.append("export")

    return result
