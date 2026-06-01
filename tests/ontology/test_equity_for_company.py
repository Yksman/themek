from themek.ontology.core.models import Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.equity import ingest_equity_for_company


class _FakeClient:
    def fetch_largest_shareholders(self, *, corp_code, bsns_year, reprt_code):
        return [{"nm": "이재용", "relate": "최대주주 본인",
                 "trmend_posesn_stock_co": "100", "trmend_posesn_stock_qota_rt": "1.6"}]

    def fetch_other_corp_investments(self, *, corp_code, bsns_year, reprt_code):
        return [{"inv_prm": "삼성디스플레이(주)", "invstmnt_purps": "지배",
                 "trmend_blce_qy": "100", "trmend_blce_qota_rt": "84.8"}]


def test_ingest_equity_for_company_loads_both_sides(ontology_session):
    session = ontology_session
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    n = ingest_equity_for_company(session, _FakeClient(), corp_code="00126380",
                                  bsns_year="2023")
    session.flush()
    assert n == 2
    inbound = session.query(Edge).filter_by(
        predicate="OWNS_STAKE_IN", object_id="company:00126380").count()
    outbound = session.query(Edge).filter_by(
        predicate="OWNS_STAKE_IN", subject_id="company:00126380").count()
    assert inbound == 1 and outbound == 1
