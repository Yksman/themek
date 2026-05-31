"""concept resolver + upsert 헬퍼 단위 테스트."""
from themek.ontology.core.models import Node, ConceptAlias
from themek.ontology.core.resolve import (
    upsert_node, upsert_edge, resolve_concept, normalize_alias,
)


def test_normalize_alias():
    assert normalize_alias("  HBM 메모리 ") == "hbm 메모리"


def test_upsert_node_is_idempotent(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자", {"ticker": "005930"})
    upsert_node(s, "company:00126380", "company", "삼성전자(갱신)", {"ticker": "005930"})
    s.commit()
    rows = s.query(Node).filter_by(id="company:00126380").all()
    assert len(rows) == 1
    assert rows[0].label == "삼성전자(갱신)"  # 라벨 갱신


def test_upsert_edge_dedupes_same_triple_period(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자")
    upsert_node(s, "segment:메모리반도체", "segment", "메모리반도체")
    s.commit()
    kw = dict(subject_id="company:00126380", predicate="HAS_SEGMENT",
              object_id="segment:메모리반도체", period="2023",
              qualifier={"share_pct": 42.5}, source_type="llm",
              source_ref="r1", method="llm", confidence=0.9)
    upsert_edge(s, **kw)
    upsert_edge(s, **{**kw, "qualifier": {"share_pct": 50.0}})  # 갱신
    s.commit()
    from themek.ontology.core.models import Edge
    edges = s.query(Edge).all()
    assert len(edges) == 1
    assert edges[0].qualifier["share_pct"] == 50.0


def test_resolve_concept_exact_then_alias(ontology_session):
    s = ontology_session
    upsert_node(s, "segment:메모리반도체", "segment", "메모리반도체")
    s.add(ConceptAlias(alias_norm="hbm", node_id="segment:메모리반도체",
                       source="manual", confidence=1.0))
    s.commit()
    # 별칭 매칭
    assert resolve_concept(s, "HBM") == "segment:메모리반도체"
    # 정확 라벨 매칭(별칭 없어도)
    assert resolve_concept(s, "메모리반도체") == "segment:메모리반도체"
    # 미해소
    assert resolve_concept(s, "존재안함") is None


from themek.ontology.core.resolve import normalize_corp_name


def test_normalize_corp_name_strips_legal_forms():
    assert normalize_corp_name("삼성전자(주)") == "삼성전자"
    assert normalize_corp_name("(주)삼성전자") == "삼성전자"
    assert normalize_corp_name("㈜삼성전자") == "삼성전자"
    assert normalize_corp_name("주식회사 삼성전자") == "삼성전자"
    assert normalize_corp_name("  Samsung  Electronics  Co., Ltd. ") \
        == "samsung electronics"
    assert normalize_corp_name("Apple Inc.") == "apple"
    # 동일 정규화로 수렴
    assert normalize_corp_name("현대자동차(주)") == normalize_corp_name("현대자동차")
