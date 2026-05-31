"""LLM BusinessExtraction → 코어 nodes/edges 적재 (provenance method=llm)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from themek.llm.schemas import BusinessExtraction
from themek.ontology.core.ids import (
    company_id, segment_id, customer_id, region_id,
)
from themek.ontology.core.models import Node
from themek.ontology.core.resolve import upsert_node, upsert_edge


def ingest_business_structure(session: Session, *, corp_code: str,
                              extraction: BusinessExtraction,
                              source_ref: str) -> None:
    """추출 결과를 HAS_SEGMENT/SELLS_TO/EXPOSED_TO 엣지로 적재. 멱등."""
    subj = company_id(corp_code)
    period = extraction.period

    def _edge(predicate, obj, qualifier, confidence=0.9):
        upsert_edge(session, subject_id=subj, predicate=predicate, object_id=obj,
                    period=period, qualifier=qualifier, source_type="llm",
                    source_ref=source_ref, method="llm", confidence=confidence)

    for seg in extraction.segments:
        # 회사 네임스페이스 키로 동명 일반 세그먼트의 우발 병합 방지(C2)
        oid = segment_id(seg.name_ko, company_key=corp_code)
        upsert_node(session, oid, "segment", seg.name_ko,
                    {"company": corp_code, "name": seg.name_ko})
        q = {} if seg.share_pct is None else {"share_pct": float(seg.share_pct)}
        _edge("HAS_SEGMENT", oid, q)

    for cust in extraction.customers:
        oid = customer_id(cust.name_raw)
        upsert_node(session, oid, "customer", cust.name_raw)
        q = {"tier": cust.tier}
        if cust.revenue_share_pct is not None:
            q["share_pct"] = float(cust.revenue_share_pct)
        _edge("SELLS_TO", oid, q)

    for geo in extraction.geographic:
        oid = region_id(geo.region_code)
        if session.get(Node, oid) is None:
            upsert_node(session, oid, "region", geo.region_code)
        _edge("EXPOSED_TO", oid, {"share_pct": float(geo.share_pct)})
