"""발행주식수(stockTotqySttus) → shares_outstanding fact 적재."""
from themek.ontology.core.models import FinancialFact
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.financials import ingest_shares_for_company


class _FakeClient:
    def fetch_shares(self, *, corp_code, bsns_year, reprt_code):
        # 보통주 발행총수 1행 + 우선주 1행
        return [
            {"se": "보통주", "istc_totqy": "5,969,782,550"},
            {"se": "우선주", "istc_totqy": "822,886,700"},
        ]


def test_ingest_shares_picks_common_total(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"}); s.commit()
    n = ingest_shares_for_company(
        s, _FakeClient(), corp_code="00126380", bsns_year="2024",
        reprt_code="11011"); s.commit()
    assert n == 1
    fact = s.query(FinancialFact).filter_by(
        metric_key="shares_outstanding").one()
    assert fact.amount == 5969782550
    assert fact.bsns_year == "2024" and fact.fiscal_period == "FY"


def test_ingest_shares_idempotent(ontology_session):
    s = ontology_session
    upsert_node(s, "company:1", "company", "A", {"dart_code": "1"}); s.commit()
    for _ in range(2):
        ingest_shares_for_company(s, _FakeClient(), corp_code="1",
                                  bsns_year="2024", reprt_code="11011")
    s.commit()
    assert s.query(FinancialFact).filter_by(
        metric_key="shares_outstanding").count() == 1
