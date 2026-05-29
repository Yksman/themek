"""ingest_financials_for_company — facts upsert + 노드 보장 + fallback."""
import json
from pathlib import Path

from themek.ontology.core.models import Node, FinancialFact
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.financials import ingest_financials_for_company

_CASSETTE = Path("tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json")


class _FakeClient:
    """fetch_financials를 카세트로 대체. CFS 있으면 OFS 호출 안 됨을 추적."""
    def __init__(self, cfs_rows, ofs_rows=None):
        self.cfs_rows, self.ofs_rows = cfs_rows, ofs_rows or []
        self.calls = []

    def fetch_financials(self, *, corp_code, bsns_year, reprt_code, fs_div):
        self.calls.append(fs_div)
        return self.cfs_rows if fs_div == "CFS" else self.ofs_rows


def test_ingest_creates_facts_and_period_metric_nodes(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자"); s.commit()
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    client = _FakeClient(cfs_rows=rows)
    n = ingest_financials_for_company(
        s, client, corp_code="00126380", bsns_year="2024", reprt_code="11011")
    s.commit()
    assert n == 18
    facts = s.query(FinancialFact).filter_by(metric_key="operating_income",
                                             bsns_year="2024").all()
    assert len(facts) == 1
    assert facts[0].fs_div == "CFS"
    # period·metric 노드 보장
    assert s.get(Node, "period:2024FY") is not None
    assert s.get(Node, "metric:operating_income") is not None


def test_ingest_falls_back_to_ofs_when_cfs_empty(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00999999", "company", "단일법인"); s.commit()
    ofs = [{"account_id": "ifrs-full_Revenue", "account_nm": "매출액",
            "thstrm_amount": "100", "frmtrm_amount": "90",
            "bfefrmtrm_amount": "80", "sj_div": "IS"}]
    client = _FakeClient(cfs_rows=[], ofs_rows=ofs)
    n = ingest_financials_for_company(
        s, client, corp_code="00999999", bsns_year="2024", reprt_code="11011")
    s.commit()
    assert client.calls == ["CFS", "OFS"]   # CFS 비어서 OFS 시도
    assert n == 3
    assert s.query(FinancialFact).first().fs_div == "OFS"


def test_ingest_idempotent(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자"); s.commit()
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    client = _FakeClient(cfs_rows=rows)
    ingest_financials_for_company(s, client, corp_code="00126380",
                                  bsns_year="2024", reprt_code="11011"); s.commit()
    ingest_financials_for_company(s, client, corp_code="00126380",
                                  bsns_year="2024", reprt_code="11011"); s.commit()
    assert s.query(FinancialFact).count() == 18  # 중복 없음
