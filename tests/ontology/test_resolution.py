"""엔티티 해소: 별칭 시드 + customer/segment 배치 패스."""
import json
from pathlib import Path

from sqlalchemy import select

from themek.db.corp_models import Corporation
from themek.ontology.core.ids import company_id, customer_id, segment_id
from themek.ontology.core.models import Node, Edge, ConceptAlias
from themek.ontology.core.resolve import (
    upsert_node, upsert_edge, normalize_corp_name)
from themek.ontology.ingest.seeds import seed_aliases


def _aliases(tmp_path, data):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_seed_aliases_creates_concept_aliases(ontology_session, tmp_path):
    s = ontology_session
    upsert_node(s, company_id("00126380"), "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_node(s, segment_id("메모리반도체"), "segment", "메모리반도체")
    s.commit()
    path = _aliases(tmp_path, {
        "customers": [{"corp": "00126380", "variants": ["삼성전자(주)"]}],
        "segments": [{"canonical": "메모리반도체", "variants": ["메모리"]}],
    })
    n = seed_aliases(s, path); s.commit()
    assert n == 2
    # customer 변형 → company 노드
    from themek.ontology.core.resolve import normalize_corp_name, normalize_alias
    a1 = s.get(ConceptAlias, normalize_corp_name("삼성전자(주)"))
    assert a1.node_id == company_id("00126380")
    # segment 동의어 → canonical segment 노드
    a2 = s.get(ConceptAlias, normalize_alias("메모리"))
    assert a2.node_id == segment_id("메모리반도체")


from themek.ontology.ingest.resolution import resolve_customers


def _seller_sells_to(s, *, seller, buyer_node, period="2024"):
    upsert_edge(s, subject_id=seller, predicate="SELLS_TO",
                object_id=buyer_node, period=period, qualifier={},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)


def test_resolve_customers_repoints_and_removes_customer(ontology_session):
    s = ontology_session
    # 그래프 company + 관계형 corp + raw customer 노드
    upsert_node(s, company_id("00164742"), "company", "현대자동차",
                {"dart_code": "00164742"})
    upsert_node(s, company_id("seller1"), "company", "셀러1",
                {"dart_code": "seller1"})
    cust_id = customer_id("현대차(주)")
    upsert_node(s, cust_id, "customer", "현대차(주)")
    s.add(Corporation(dart_code="00164742", name_ko="현대자동차"))
    # 약어 "현대차"→현대자동차는 별칭으로 해소(별칭 우선 경로)
    s.add(ConceptAlias(alias_norm=normalize_corp_name("현대차"),
                       node_id=company_id("00164742"),
                       source="manual", confidence=1.0))
    s.commit()
    _seller_sells_to(s, seller=company_id("seller1"), buyer_node=cust_id)
    s.commit()

    res = resolve_customers(s); s.commit()
    assert res["resolved"] == 1
    # SELLS_TO가 company:현대차로 재지정, buyer_raw 보존
    e = s.execute(select(Edge).where(Edge.predicate == "SELLS_TO")).scalar_one()
    assert e.object_id == company_id("00164742")
    assert e.qualifier["buyer_raw"] == "현대차(주)"
    # customer 노드 제거
    assert s.get(Node, cust_id) is None


def test_resolve_customers_marks_unresolved(ontology_session):
    s = ontology_session
    upsert_node(s, company_id("s"), "company", "셀러", {"dart_code": "s"})
    cid = customer_id("이름없는해외바이어")
    upsert_node(s, cid, "customer", "이름없는해외바이어"); s.commit()
    _seller_sells_to(s, seller=company_id("s"), buyer_node=cid); s.commit()
    res = resolve_customers(s); s.commit()
    assert res["unresolved"] == 1
    assert s.get(Node, cid).attrs.get("resolved") is False


def test_resolve_customers_merges_on_conflict(ontology_session):
    """셀러가 raw customer와 (해소대상)company 둘 다 같은 period로 SELLS_TO하면 병합."""
    s = ontology_session
    upsert_node(s, company_id("00164742"), "company", "현대자동차",
                {"dart_code": "00164742"})
    upsert_node(s, company_id("seller1"), "company", "셀러1",
                {"dart_code": "seller1"})
    cust_id = customer_id("현대차")
    upsert_node(s, cust_id, "customer", "현대차")
    s.add(Corporation(dart_code="00164742", name_ko="현대자동차"))
    s.add(ConceptAlias(alias_norm=normalize_corp_name("현대차"),
                       node_id=company_id("00164742"),
                       source="manual", confidence=1.0)); s.commit()
    # 이미 company로 직접 + raw로도 SELLS_TO (동일 period)
    _seller_sells_to(s, seller=company_id("seller1"),
                     buyer_node=company_id("00164742"))
    _seller_sells_to(s, seller=company_id("seller1"), buyer_node=cust_id)
    s.commit()
    res = resolve_customers(s); s.commit()
    # 충돌 병합 → SELLS_TO(seller1→현대차) 1건만
    edges = s.execute(select(Edge).where(
        Edge.subject_id == company_id("seller1"),
        Edge.predicate == "SELLS_TO",
        Edge.object_id == company_id("00164742"))).scalars().all()
    assert len(edges) == 1
    assert s.get(Node, cust_id) is None


from themek.ontology.ingest.resolution import merge_segments
from themek.ontology.core.resolve import normalize_alias


def test_merge_segments_repoints_to_canonical(ontology_session):
    s = ontology_session
    canon = segment_id("메모리반도체")
    variant = segment_id("메모리")
    upsert_node(s, company_id("c"), "company", "회사", {"dart_code": "c"})
    upsert_node(s, canon, "segment", "메모리반도체")
    upsert_node(s, variant, "segment", "메모리")
    # 별칭: normalize_alias("메모리") → canonical
    s.add(ConceptAlias(alias_norm=normalize_alias("메모리"), node_id=canon,
                       source="manual", confidence=1.0))
    s.commit()
    upsert_edge(s, subject_id=company_id("c"), predicate="HAS_SEGMENT",
                object_id=variant, period="2024", qualifier={"share_pct": 30.0},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    s.commit()

    res = merge_segments(s); s.commit()
    assert res["merged"] == 1
    e = s.execute(select(Edge).where(Edge.predicate == "HAS_SEGMENT")).scalar_one()
    assert e.object_id == canon
    assert s.get(Node, variant) is None
