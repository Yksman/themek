"""코어 ORM 생성·제약·조회 단위 테스트."""
import pytest
from sqlalchemy import select
from themek.ontology.core.models import (
    Node, Edge, FinancialFact, ConceptAlias,
)


def test_node_roundtrip(ontology_session):
    s = ontology_session
    s.add(Node(id="company:00126380", kind="company", label="삼성전자",
               attrs={"name_en": "Samsung", "ticker": "005930"}))
    s.commit()
    got = s.get(Node, "company:00126380")
    assert got.kind == "company"
    assert got.attrs["name_en"] == "Samsung"


def test_edge_with_qualifier_and_provenance(ontology_session):
    s = ontology_session
    s.add(Node(id="company:00126380", kind="company", label="삼성전자"))
    s.add(Node(id="segment:메모리반도체", kind="segment", label="메모리반도체"))
    s.commit()
    s.add(Edge(subject_id="company:00126380", predicate="HAS_SEGMENT",
               object_id="segment:메모리반도체", period="2023",
               qualifier={"share_pct": 42.5}, source_type="llm",
               source_ref="20240314000001", method="llm", confidence=0.9))
    s.commit()
    e = s.execute(select(Edge).where(Edge.predicate == "HAS_SEGMENT")).scalar_one()
    assert e.qualifier["share_pct"] == 42.5
    assert e.source_type == "llm"


def test_financial_fact_unique_constraint(ontology_session):
    s = ontology_session
    s.add(Node(id="company:00126380", kind="company", label="삼성전자"))
    s.commit()
    def _fact():
        return FinancialFact(
            company_id="company:00126380", bsns_year="2024", fiscal_period="FY",
            fs_div="CFS", metric_key="operating_income", amount=1000,
            currency="KRW", source_type="dart_api", method="api", confidence=1.0)
    s.add(_fact()); s.commit()
    s.add(_fact())
    with pytest.raises(Exception):
        s.commit()


def test_concept_alias_lookup(ontology_session):
    s = ontology_session
    s.add(Node(id="segment:메모리반도체", kind="segment", label="메모리반도체"))
    s.commit()
    s.add(ConceptAlias(alias_norm="hbm", node_id="segment:메모리반도체",
                       source="manual", confidence=1.0))
    s.commit()
    row = s.get(ConceptAlias, "hbm")
    assert row.node_id == "segment:메모리반도체"
