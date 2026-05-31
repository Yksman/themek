"""온톨로지 경량 무결성 가드 — 순수 조회. 부작용 없음."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from themek.ontology.core.models import Edge, FinancialFact, Node

_STOCK = ("assets", "liabilities", "equity")
_INTERIM = ("Q1", "H1", "Q3")


@dataclass
class Issue:
    code: str
    severity: str  # "error" | "warn" | "info"
    message: str
    subject: str | None = None


def check_integrity(session: Session) -> list[Issue]:
    issues: list[Issue] = []

    # 1. interim_bs_equals_fy (error) — 분기 BS가 FY와 정확히 동일 = 1.1 버그 시그니처
    rows = session.execute(
        select(FinancialFact.company_id, FinancialFact.bsns_year,
               FinancialFact.metric_key, FinancialFact.fiscal_period,
               FinancialFact.fs_div, FinancialFact.amount)
        .where(FinancialFact.metric_key.in_(_STOCK))
    ).all()
    fy = {(c, y, m, d): a for (c, y, m, p, d, a) in rows if p == "FY"}
    for c, y, m, p, d, a in rows:
        if p in _INTERIM and fy.get((c, y, m, d)) == a:
            issues.append(Issue("interim_bs_equals_fy", "error",
                                 f"{c} {y} {m} {p}=={d} matches FY ({a})", c))

    # 2. duplicate_edge (error)
    dups = session.execute(
        select(Edge.subject_id, Edge.predicate, Edge.object_id, Edge.period,
               func.count().label("c"))
        .group_by(Edge.subject_id, Edge.predicate, Edge.object_id, Edge.period)
        .having(func.count() > 1)
    ).all()
    for sid, pred, oid, period, c in dups:
        issues.append(Issue("duplicate_edge", "error",
                             f"{sid} -{pred}-> {oid} @{period} x{c}", sid))

    # 3. orphan_fact (warn)
    orphans = session.execute(
        select(FinancialFact.company_id).distinct()
        .where(FinancialFact.company_id.not_in(select(Node.id)))
    ).scalars().all()
    for cid in orphans:
        issues.append(Issue("orphan_fact", "warn",
                             f"fact company_id {cid} not in nodes", cid))

    # 4. negative_or_zero_equity (info)
    negs = session.execute(
        select(FinancialFact.company_id, FinancialFact.bsns_year,
               FinancialFact.fiscal_period)
        .where(FinancialFact.metric_key == "equity", FinancialFact.amount <= 0)
    ).all()
    for cid, yr, fp in negs:
        issues.append(Issue("negative_or_zero_equity", "info",
                             f"{cid} {yr}{fp} equity<=0", cid))

    return issues
