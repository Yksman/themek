from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.query.equity import (
    largest_shareholders, owned_companies, stake_changes)


def _owns(session, subj, obj, period, pct, is_largest=False):
    upsert_edge(session, subject_id=subj, predicate="OWNS_STAKE_IN",
                object_id=obj, period=period,
                qualifier={"stake_pct": pct, "is_largest": is_largest},
                source_type="dart_api", source_ref=None, method="api",
                confidence=1.0)


def test_largest_shareholders_latest_period_sorted(ontology_session):
    session = ontology_session
    upsert_node(session, "company:C", "company", "씨", {"dart_code": "C"})
    upsert_node(session, "person:이씨", "person", "이씨")
    upsert_node(session, "person:박씨", "person", "박씨")
    _owns(session, "person:이씨", "company:C", "2023", 5.0, True)
    _owns(session, "person:박씨", "company:C", "2023", 8.0)
    session.flush()
    rows = largest_shareholders(session, "company:C")
    assert [r["holder_id"] for r in rows] == ["person:박씨", "person:이씨"]  # 지분율 내림차순
    assert rows[0]["stake_pct"] == 8.0


def test_owned_companies_fanout(ontology_session):
    session = ontology_session
    upsert_node(session, "person:오너", "person", "오너")
    upsert_node(session, "company:X", "company", "엑스", {"dart_code": "X"})
    upsert_node(session, "company:Y", "company", "와이", {"dart_code": "Y"})
    _owns(session, "person:오너", "company:X", "2023", 30.0)
    _owns(session, "person:오너", "company:Y", "2023", 12.0)
    session.flush()
    held = {r["company_id"] for r in owned_companies(session, "person:오너")}
    assert held == {"company:X", "company:Y"}


def test_stake_changes_year_diff(ontology_session):
    session = ontology_session
    upsert_node(session, "company:C", "company", "씨", {"dart_code": "C"})
    upsert_node(session, "person:이씨", "person", "이씨")
    _owns(session, "person:이씨", "company:C", "2022", 5.0)
    _owns(session, "person:이씨", "company:C", "2023", 7.5)
    session.flush()
    changes = stake_changes(session, "company:C")
    row = next(c for c in changes if c["holder_id"] == "person:이씨")
    assert row["from_pct"] == 5.0 and row["to_pct"] == 7.5
    assert row["delta"] == 2.5
