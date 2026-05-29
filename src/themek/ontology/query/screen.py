"""competency 스크리닝: 세그먼트 개념 · 주력 세그먼트 · 연속 흑자 · 조합.

서비스가 의존하는 안정 계약. period 비교는 (연도, 분기순서) 키로 한다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Edge, FinancialFact
from themek.ontology.core.resolve import resolve_concept

_FISCAL_ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}


def _period_key(year: str, fp: str) -> tuple[int, int]:
    return (int(year), _FISCAL_ORDER.get(fp, 0))


def _parse_period(label: str) -> tuple[str, str]:
    """'2024H1' → ('2024','H1')."""
    return label[:4], label[4:]


def companies_with_segment_concept(session: Session, concept: str) -> set[str]:
    """concept(별칭/라벨)에 해소되는 세그먼트를 가진 회사 id 집합."""
    seg_id = resolve_concept(session, concept)
    if seg_id is None:
        return set()
    rows = session.execute(
        select(Edge.subject_id).where(Edge.predicate == "HAS_SEGMENT",
                                      Edge.object_id == seg_id)
    ).scalars().all()
    return set(rows)


def primary_segment(session: Session, company_id: str,
                    period: str) -> str | None:
    """해당 회사/기간 share_pct 최대 HAS_SEGMENT object_id (주력)."""
    rows = session.execute(
        select(Edge.object_id, Edge.qualifier).where(
            Edge.predicate == "HAS_SEGMENT", Edge.subject_id == company_id,
            Edge.period == period)
    ).all()
    best, best_share = None, float("-inf")
    for obj_id, qual in rows:
        share = (qual or {}).get("share_pct")
        if share is not None and share > best_share:
            best, best_share = obj_id, share
    return best


def consecutive_positive(session: Session, metric_key: str,
                         since_period: str, fs_div: str) -> set[str]:
    """since_period(포함) 이후 기록된 모든 기간이 양수인 회사 id 집합.

    정의: period_key >= since 인 fact가 ≥1개 존재하고, 그 중 최소 amount > 0.
    (기간 연속성/누락은 deferred — 기록된 기간 기준.)
    """
    since = _period_key(*_parse_period(since_period))
    rows = session.execute(
        select(FinancialFact.company_id, FinancialFact.bsns_year,
               FinancialFact.fiscal_period, FinancialFact.amount).where(
            FinancialFact.metric_key == metric_key,
            FinancialFact.fs_div == fs_div)
    ).all()
    agg: dict[str, list[float]] = {}
    for company_id, year, fp, amount in rows:
        if _period_key(year, fp) >= since:
            agg.setdefault(company_id, []).append(float(amount))
    return {cid for cid, amts in agg.items() if amts and min(amts) > 0}


def screen(session: Session, *, segment: str, metric: str,
           positive_since: str, fs_div: str = "CFS") -> set[str]:
    """예시질의: segment가 '주력'이면서 metric이 positive_since부터 연속 양수."""
    seg_id = resolve_concept(session, segment)
    if seg_id is None:
        return set()
    period_year_fp = _parse_period(positive_since)
    # 주력 판정 기간 = positive_since 가 속한 연도의 FY (연 단위 주력)
    primary_period = period_year_fp[0]  # 주력은 연도 기준 HAS_SEGMENT.period
    candidates = companies_with_segment_concept(session, segment)
    primary_ok = {
        cid for cid in candidates
        if primary_segment(session, cid, primary_period) == seg_id
    }
    positive = consecutive_positive(session, metric, positive_since, fs_div)
    return primary_ok & positive
