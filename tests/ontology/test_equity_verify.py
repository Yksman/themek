from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.verify_equity import verify_equity


def _company(session, code):
    upsert_node(session, f"company:{code}", "company", code, {"dart_code": code})


def _owns(session, subj, obj, pct, is_largest=False, period="2023"):
    upsert_edge(session, subject_id=subj, predicate="OWNS_STAKE_IN",
                object_id=obj, period=period,
                qualifier={"stake_pct": pct, "is_largest": is_largest},
                source_type="dart_api", source_ref=None, method="api",
                confidence=1.0)


def test_verify_reports_coverage_and_checks(ontology_session):
    session = ontology_session
    _company(session, "A")
    _company(session, "B")  # 엣지 없음 → 커버리지 1/2
    upsert_node(session, "person:o", "person", "오너")
    _owns(session, "person:o", "company:A", 40.0, True)
    session.flush()
    rep = verify_equity(session)
    assert rep["companies_total"] == 2
    assert rep["companies_with_ownership"] == 1
    assert rep["coverage"] == 0.5
    assert rep["owns_edges"] == 1
    assert rep["person_nodes"] == 1
    assert rep["overstake_companies"] == 0  # 40 <= 100
    assert isinstance(rep["ok"], bool)


def test_verify_flags_overstake(ontology_session):
    session = ontology_session
    _company(session, "A")
    upsert_node(session, "person:x", "person", "엑스")
    upsert_node(session, "person:y", "person", "와이")
    _owns(session, "person:x", "company:A", 70.0, True)
    _owns(session, "person:y", "company:A", 60.0, True)  # 본인그룹 합 130 > 100
    session.flush()
    rep = verify_equity(session)
    assert rep["overstake_companies"] == 1
