"""DART 통합 파이프라인 오케스트레이션 (순수 함수 + 얇은 단계 조합)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Node, Edge

_YEAR = re.compile(r"^\d{4}$")
_REPRT_CODES = ("11011", "11012", "11013", "11014")


def derive_financial_years(session: Session) -> list[str]:
    """코어 엣지 period 중 4자리 연도만 distinct·정렬 반환."""
    rows = session.execute(
        select(Edge.period).where(Edge.period.is_not(None)).distinct()
    ).scalars().all()
    years = {p for p in rows if p and _YEAR.match(p)}
    return sorted(years)


def ingest_financials_all(session: Session, client, *, years: list[str]) -> dict:
    """DB 내 모든 company 노드 × years × 4 reprt_code 재무 적재. 회사별 실패 관용."""
    from themek.ontology.ingest.financials import ingest_financials_for_company

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
        for yr in years:
            for rc in _REPRT_CODES:
                try:
                    facts += ingest_financials_for_company(
                        session, client, corp_code=dart_code,
                        bsns_year=yr, reprt_code=rc)
                except Exception as e:  # 회사별 관용
                    failed.append((dart_code, f"{yr}/{rc}: {e}"))
    return {"companies": processed, "facts": facts, "failed": failed}


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

    # 3. financials (연도 자동 도출)
    if skip_financials:
        result.skipped.append("financials")
    else:
        years = derive_financial_years(session)
        stats = ingest_financials_all(session, client, years=years)
        stats["years"] = years
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
