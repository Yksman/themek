"""관계형 운영 테이블 → 코어 그래프 엣지 투영 (provenance method=api)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.db.corp_models import Stock
from themek.ontology.core.ids import stock_id
from themek.ontology.core.models import Node
from themek.ontology.core.resolve import upsert_node, upsert_edge


def link_stocks(session: Session) -> int:
    """company 노드의 dart_code로 관계형 Stock을 찾아 ISSUES_STOCK 엣지 투영. 멱등."""
    companies = session.execute(
        select(Node).where(Node.kind == "company")
    ).scalars().all()
    n = 0
    for c in companies:
        dart_code = c.attrs.get("dart_code")
        if not dart_code:
            continue
        stocks = session.execute(
            select(Stock).where(Stock.issued_by_id == dart_code)
        ).scalars().all()
        for st in stocks:
            sid = stock_id(st.ticker)
            upsert_node(session, sid, "stock", st.name_ko,
                        {"ticker": st.ticker, "market": st.market})
            upsert_edge(session, subject_id=c.id, predicate="ISSUES_STOCK",
                        object_id=sid, period=None, qualifier={},
                        source_type="dart_api", source_ref=None, method="api",
                        confidence=1.0)
            n += 1
    return n
