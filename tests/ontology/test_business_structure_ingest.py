"""BusinessExtraction → nodes/edges 적재 단위 테스트."""
from themek.llm.schemas import (
    BusinessExtraction, SegmentItem, CustomerItem, GeographicItem,
)
from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.business_structure import ingest_business_structure


def _extraction():
    return BusinessExtraction(
        period="2023",
        segments=[SegmentItem(name_ko="메모리반도체", share_pct=42.5),
                  SegmentItem(name_ko="DX 부문", share_pct=None)],
        customers=[CustomerItem(name_raw="Apple Inc.", revenue_share_pct=18.0,
                                tier="1차")],
        geographic=[GeographicItem(region_code="US", share_pct=35.0)],
    )


def test_ingest_creates_company_segment_customer_region_edges(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자")
    upsert_node(s, "region:US", "region", "미주")
    s.commit()
    ingest_business_structure(s, corp_code="00126380",
                              extraction=_extraction(), source_ref="r1")
    s.commit()
    # 세그먼트/고객 노드 생성
    assert s.get(Node, "segment:메모리반도체") is not None
    assert s.get(Node, "customer:apple-inc") is not None
    # HAS_SEGMENT 엣지 share_pct qualifier
    seg_edge = s.query(Edge).filter_by(predicate="HAS_SEGMENT",
                                       object_id="segment:메모리반도체").one()
    assert seg_edge.qualifier["share_pct"] == 42.5
    assert seg_edge.period == "2023"
    # SELLS_TO + EXPOSED_TO
    assert s.query(Edge).filter_by(predicate="SELLS_TO",
                                   object_id="customer:apple-inc").count() == 1
    assert s.query(Edge).filter_by(predicate="EXPOSED_TO",
                                   object_id="region:US").one().qualifier["share_pct"] == 35.0


def test_ingest_idempotent(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자")
    upsert_node(s, "region:US", "region", "미주")
    s.commit()
    for _ in range(2):
        ingest_business_structure(s, corp_code="00126380",
                                  extraction=_extraction(), source_ref="r1")
        s.commit()
    assert s.query(Edge).filter_by(predicate="HAS_SEGMENT").count() == 2  # 2 세그먼트
    assert s.query(Edge).filter_by(predicate="SELLS_TO").count() == 1
