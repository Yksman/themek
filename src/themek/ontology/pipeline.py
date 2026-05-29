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
