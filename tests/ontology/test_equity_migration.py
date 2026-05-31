"""0008 마이그레이션 후 person 노드 + OWNS_STAKE_IN 엣지 적재 가능."""
from themek.ontology.core.models import Node, Edge, NODE_KINDS, PREDICATES
from themek.ontology.core.resolve import upsert_node, upsert_edge


def test_constants_expanded():
    assert "person" in NODE_KINDS
    assert "OWNS_STAKE_IN" in PREDICATES


def test_can_persist_person_and_owns_edge(ontology_session):
    session = ontology_session
    upsert_node(session, "person:p1:hong", "person", "홍길동")
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_edge(session, subject_id="person:p1:hong", predicate="OWNS_STAKE_IN",
                object_id="company:00126380", period="2023",
                qualifier={"stake_pct": 1.23}, source_type="dart_api",
                source_ref=None, method="api", confidence=1.0)
    session.flush()
    e = session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").one()
    assert e.subject_id == "person:p1:hong"
    assert e.qualifier["stake_pct"] == 1.23
    assert session.get(Node, "person:p1:hong").kind == "person"
