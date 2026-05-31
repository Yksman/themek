"""외부법인 → universe, 오너 시드 병합 엔티티 해소 테스트."""
from themek.db.corp_models import Corporation
from themek.ontology.core.models import Node, Edge, ConceptAlias
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.ingest.resolution import (
    resolve_external_companies, resolve_owners)


def _owns(session, subj, obj, period="2023", q=None):
    upsert_edge(session, subject_id=subj, predicate="OWNS_STAKE_IN",
                object_id=obj, period=period, qualifier=q or {},
                source_type="dart_api", source_ref=None, method="api",
                confidence=1.0)


def test_resolve_external_company_to_universe(ontology_session):
    session = ontology_session
    session.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_node(session, "company:00100", "company", "출자모회사",
                {"dart_code": "00100"})
    upsert_node(session, "company:ext:삼성전자-주", "company", "삼성전자(주)",
                {"external": True})
    _owns(session, "company:00100", "company:ext:삼성전자-주",
          q={"stake_pct": 30.0})
    session.flush()
    res = resolve_external_companies(session)
    session.flush()
    assert res["resolved"] == 1
    assert session.get(Node, "company:ext:삼성전자-주") is None
    e = session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").one()
    assert e.object_id == "company:00126380"


def test_resolve_owner_seed_merge(ontology_session):
    session = ontology_session
    upsert_node(session, "person:이재용", "person", "이재용")
    session.add(ConceptAlias(alias_norm="이재용", node_id="person:이재용",
                             source="manual", confidence=1.0))
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_node(session, "person:00126380:이재용", "person", "이재용")
    _owns(session, "person:00126380:이재용", "company:00126380",
          q={"stake_pct": 1.6})
    session.flush()
    res = resolve_owners(session)
    session.flush()
    assert res["merged"] == 1
    assert session.get(Node, "person:00126380:이재용") is None
    e = session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").one()
    assert e.subject_id == "person:이재용"
