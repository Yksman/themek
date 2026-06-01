from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.equity import ingest_largest_shareholders

_ROWS = [
    {"nm": "이재용", "relate": "최대주주 본인", "trmend_posesn_stock_co": "12345678",
     "trmend_posesn_stock_qota_rt": "1.63"},
    {"nm": "삼성생명보험(주)", "relate": "계열회사", "trmend_posesn_stock_co": "50000000",
     "trmend_posesn_stock_qota_rt": "8.51"},
]


def _company(session):
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})


def test_ingest_creates_person_and_company_holders(ontology_session):
    session = ontology_session
    _company(session)
    n = ingest_largest_shareholders(session, corp_code="00126380",
                                    bsns_year="2023", rows=_ROWS, source_ref="r1")
    session.flush()
    assert n == 2
    person = session.get(Node, "person:00126380:이재용")
    assert person is not None and person.kind == "person"
    extco = session.get(Node, "company:ext:삼성생명보험-주")
    assert extco is not None and extco.kind == "company"
    edges = session.query(Edge).filter_by(predicate="OWNS_STAKE_IN",
                                          object_id="company:00126380").all()
    assert len(edges) == 2
    owner = next(e for e in edges if e.subject_id == "person:00126380:이재용")
    assert owner.period == "2023"
    assert owner.qualifier["stake_pct"] == 1.63
    assert owner.qualifier["is_largest"] is True
    assert owner.qualifier["relation"] == "최대주주 본인"
    assert owner.qualifier["shares"] == 12345678


def test_ingest_keeps_max_stake_across_stock_kinds(ontology_session):
    # 한 holder가 보통주/우선주 여러 행으로 오면 의결권(보통주=최대 지분율) 행을 채택.
    session = ontology_session
    _company(session)
    rows = [
        {"nm": "삼성생명보험㈜", "relate": "최대주주 본인", "stock_knd": "보통주",
         "trmend_posesn_stock_co": "508157148", "trmend_posesn_stock_qota_rt": "8.51"},
        {"nm": "삼성생명보험㈜", "relate": "최대주주 본인", "stock_knd": "우선주",
         "trmend_posesn_stock_co": "1000", "trmend_posesn_stock_qota_rt": "0.01"},
    ]
    n = ingest_largest_shareholders(session, corp_code="00126380",
                                    bsns_year="2024", rows=rows, source_ref="r1")
    session.flush()
    assert n == 1  # 한 holder, 한 엣지
    e = session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").one()
    assert e.qualifier["stake_pct"] == 8.51  # 우선주 0.01이 덮어쓰지 않음
    assert e.qualifier["is_largest"] is True


def test_ingest_skips_summary_rows(ontology_session):
    # "계/소계/합계/총계" 합계행은 주주가 아니므로 적재 제외.
    session = ontology_session
    _company(session)
    rows = [
        {"nm": "이재용", "relate": "최대주주 본인", "trmend_posesn_stock_co": "100",
         "trmend_posesn_stock_qota_rt": "1.5"},
        {"nm": "계", "relate": "", "trmend_posesn_stock_co": "200",
         "trmend_posesn_stock_qota_rt": "3.0"},
    ]
    n = ingest_largest_shareholders(session, corp_code="00126380",
                                    bsns_year="2024", rows=rows, source_ref="r1")
    session.flush()
    assert n == 1
    assert session.get(Node, "person:00126380:계") is None


def test_ingest_is_idempotent(ontology_session):
    session = ontology_session
    _company(session)
    ingest_largest_shareholders(session, corp_code="00126380",
                                bsns_year="2023", rows=_ROWS, source_ref="r1")
    session.flush()
    ingest_largest_shareholders(session, corp_code="00126380",
                                bsns_year="2023", rows=_ROWS, source_ref="r1")
    session.flush()
    assert session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").count() == 2
