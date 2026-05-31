from themek.ontology.core.models import Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.pipeline import ingest_equity_all


class _FakeClient:
    def fetch_largest_shareholders(self, *, corp_code, bsns_year, reprt_code):
        if reprt_code != "11011":
            return []
        return [{"nm": "오너", "relate": "본인", "trmend_posesn_stock_co": "10",
                 "trmend_posesn_stock_qota_rt": "5.0"}]

    def fetch_other_corp_investments(self, *, corp_code, bsns_year, reprt_code):
        return []


def test_ingest_equity_all_iterates_companies_annual_only(ontology_session):
    session = ontology_session
    upsert_node(session, "company:A", "company", "에이", {"dart_code": "A"})
    upsert_node(session, "company:B", "company", "비", {"dart_code": "B"})
    res = ingest_equity_all(session, _FakeClient(), years=["2023"])
    session.flush()
    assert res["companies"] == 2
    assert res["edges"] == 2  # 회사당 최대주주 1행 (사업보고서 1회)
    assert session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").count() == 2


def test_ingest_equity_all_skips_companies_without_dart_code(ontology_session):
    session = ontology_session
    upsert_node(session, "company:ext:foo", "company", "외부", {"external": True})
    res = ingest_equity_all(session, _FakeClient(), years=["2023"])
    assert res["companies"] == 0
