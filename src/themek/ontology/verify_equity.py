"""지분구조 적재 검증 — 측정 가능한 게이트 산출."""
from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from themek.ontology.core.models import Node, Edge

# 게이트 임계값
MIN_COVERAGE = 0.85        # 회사 중 지분 엣지 보유 비율
OVERSTAKE_TOLERANCE = 100.5  # is_largest 그룹 지분율 합 상한(반올림 여유)


def verify_equity(session: Session) -> dict:
    companies = session.execute(
        select(Node).where(Node.kind == "company",
                           ~Node.id.like("company:ext:%"))
    ).scalars().all()
    universe = [c for c in companies if c.attrs.get("dart_code")]
    total = len(universe)

    owns = session.execute(
        select(Edge).where(Edge.predicate == "OWNS_STAKE_IN")
    ).scalars().all()
    with_ownership = {c.id for c in universe} & {
        e.object_id for e in owns} | (
        {c.id for c in universe} & {e.subject_id for e in owns})

    person_nodes = session.execute(
        select(func.count()).select_from(Node).where(Node.kind == "person")
    ).scalar_one()
    ext_nodes = session.execute(
        select(func.count()).select_from(Node).where(
            Node.id.like("company:ext:%"))
    ).scalar_one()

    # is_largest 그룹 지분율 합이 상한 초과인 회사 카운트(최신 period 기준)
    by_company: dict[str, dict[str, float]] = {}
    for e in owns:
        if not e.qualifier.get("is_largest"):
            continue
        pct = e.qualifier.get("stake_pct")
        if pct is None:
            continue
        by_company.setdefault(e.object_id, {})
        key = e.period or ""
        by_company[e.object_id].setdefault(key, 0.0)
        by_company[e.object_id][key] += pct
    overstake = 0
    for comp, per_period in by_company.items():
        latest = max(per_period.keys()) if per_period else None
        if latest is not None and per_period[latest] > OVERSTAKE_TOLERANCE:
            overstake += 1

    null_pct = sum(1 for e in owns if e.qualifier.get("stake_pct") is None)
    coverage = (len(with_ownership) / total) if total else 0.0
    ok = (coverage >= MIN_COVERAGE and overstake == 0)
    return {
        "companies_total": total,
        "companies_with_ownership": len(with_ownership),
        "coverage": round(coverage, 4),
        "owns_edges": len(owns),
        "person_nodes": person_nodes,
        "external_company_nodes": ext_nodes,
        "null_stake_pct_edges": null_pct,
        "overstake_companies": overstake,
        "ok": ok,
    }
