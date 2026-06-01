"""지분 질의: 최대주주·지배회사·지분 시계열/변동."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Edge


def _latest_period(session: Session, company_id: str) -> str | None:
    rows = session.execute(
        select(Edge.period).where(
            Edge.predicate == "OWNS_STAKE_IN",
            Edge.object_id == company_id, Edge.period.is_not(None))
    ).scalars().all()
    return max(rows) if rows else None


def largest_shareholders(session: Session, company_id: str) -> list[dict]:
    """회사의 최신 사업연도 주주 목록(지분율 내림차순)."""
    period = _latest_period(session, company_id)
    if period is None:
        return []
    edges = session.execute(
        select(Edge).where(
            Edge.predicate == "OWNS_STAKE_IN",
            Edge.object_id == company_id, Edge.period == period)
    ).scalars().all()
    rows = [{"holder_id": e.subject_id,
             "stake_pct": e.qualifier.get("stake_pct"),
             "relation": e.qualifier.get("relation"),
             "is_largest": e.qualifier.get("is_largest", False),
             "period": e.period} for e in edges]
    rows.sort(key=lambda r: (r["stake_pct"] is None, -(r["stake_pct"] or 0)))
    return rows


def owned_companies(session: Session, holder_id: str) -> list[dict]:
    """보유자가 지분을 가진 회사 목록(최신 period 우선, object별 1건)."""
    edges = session.execute(
        select(Edge).where(Edge.predicate == "OWNS_STAKE_IN",
                           Edge.subject_id == holder_id)
    ).scalars().all()
    best: dict[str, Edge] = {}
    for e in edges:
        cur = best.get(e.object_id)
        if cur is None or (e.period or "") > (cur.period or ""):
            best[e.object_id] = e
    return [{"company_id": oid,
             "stake_pct": e.qualifier.get("stake_pct"),
             "affiliation_type": e.qualifier.get("affiliation_type"),
             "period": e.period} for oid, e in best.items()]


def stake_changes(session: Session, company_id: str) -> list[dict]:
    """holder별 직전 연도 대비 지분율 변동(append-only 엣지 연도 diff)."""
    edges = session.execute(
        select(Edge).where(Edge.predicate == "OWNS_STAKE_IN",
                           Edge.object_id == company_id,
                           Edge.period.is_not(None))
    ).scalars().all()
    by_holder: dict[str, dict[str, float | None]] = {}
    for e in edges:
        by_holder.setdefault(e.subject_id, {})[e.period] = \
            e.qualifier.get("stake_pct")
    out = []
    for holder, series in by_holder.items():
        periods = sorted(series.keys())
        if len(periods) < 2:
            continue
        frm, to = periods[-2], periods[-1]
        a, b = series[frm], series[to]
        delta = (b - a) if (a is not None and b is not None) else None
        out.append({"holder_id": holder, "from_period": frm, "to_period": to,
                    "from_pct": a, "to_pct": b, "delta": delta})
    return out
