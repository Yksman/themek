from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.equity import ingest_other_corp_investments

_ROWS = [
    {"inv_prm": "삼성디스플레이(주)", "invstmnt_purps": "경영참여(지배)",
     "trmend_blce_qy": "100000000", "trmend_blce_qota_rt": "84.78"},
    {"inv_prm": "삼성SDI(주)", "invstmnt_purps": "일반투자",
     "trmend_blce_qy": "13000000", "trmend_blce_qota_rt": "19.58"},
]


def test_ingest_creates_outbound_ownership(ontology_session):
    session = ontology_session
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    n = ingest_other_corp_investments(session, corp_code="00126380",
                                      bsns_year="2023", rows=_ROWS,
                                      source_ref="r1")
    session.flush()
    assert n == 2
    edges = session.query(Edge).filter_by(
        predicate="OWNS_STAKE_IN", subject_id="company:00126380").all()
    assert len(edges) == 2
    sub = next(e for e in edges
               if e.object_id == "company:ext:삼성디스플레이-주")
    assert sub.qualifier["stake_pct"] == 84.78
    assert sub.qualifier["affiliation_type"] == "자회사"
    assert sub.period == "2023"
    rel = next(e for e in edges if e.object_id == "company:ext:삼성sdi-주")
    assert rel.qualifier["affiliation_type"] == "기타"  # 19.58 < 20


def test_ingest_invest_idempotent(ontology_session):
    session = ontology_session
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    ingest_other_corp_investments(session, corp_code="00126380",
                                  bsns_year="2023", rows=_ROWS, source_ref="r1")
    session.flush()
    ingest_other_corp_investments(session, corp_code="00126380",
                                  bsns_year="2023", rows=_ROWS, source_ref="r1")
    session.flush()
    assert session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").count() == 2
