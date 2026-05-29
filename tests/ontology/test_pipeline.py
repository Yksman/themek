"""pipeline 헬퍼 단위 테스트."""
import json
from pathlib import Path

from themek.ontology.core.models import Node, FinancialFact
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.pipeline import (
    derive_financial_years, ingest_financials_all,
)

_CASSETTE = Path("tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json")


def _edge(s, subj, obj, period):
    upsert_node(s, subj, "company", subj)
    upsert_node(s, obj, "segment", obj)
    upsert_edge(s, subject_id=subj, predicate="HAS_SEGMENT", object_id=obj,
                period=period, qualifier={}, source_type="llm",
                source_ref="r", method="llm", confidence=0.9)


def test_derive_financial_years_distinct_4digit_sorted(ontology_session):
    s = ontology_session
    _edge(s, "company:1", "segment:a", "2023")
    _edge(s, "company:1", "segment:b", "2024")
    _edge(s, "company:2", "segment:c", "2023")     # 중복 연도
    _edge(s, "company:2", "segment:d", None)        # null 제외
    _edge(s, "company:2", "segment:e", "2024Q1")    # 비-4자리 제외
    s.commit()
    assert derive_financial_years(s) == ["2023", "2024"]


def test_derive_financial_years_empty(ontology_session):
    assert derive_financial_years(ontology_session) == []


class _FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def fetch_financials(self, *, corp_code, bsns_year, reprt_code, fs_div):
        self.calls.append((corp_code, bsns_year, reprt_code, fs_div))
        return self.rows if fs_div == "CFS" else []


def test_ingest_financials_all_iterates_companies_years_reprtcodes(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자", {"dart_code": "00126380"})
    upsert_node(s, "company:00164742", "company", "현대차", {"dart_code": "00164742"})
    upsert_node(s, "segment:x", "segment", "x")  # company 아닌 노드는 무시
    s.commit()
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    client = _FakeClient(rows)
    stats = ingest_financials_all(s, client, years=["2024"])
    s.commit()
    assert stats["companies"] == 2
    # 회사2 × reprt4 = 8 CFS 호출 (+OFS는 CFS 있으면 안 함)
    assert len([c for c in client.calls if c[3] == "CFS"]) == 8
    # 각 호출 18 fact(6 metric×3년) → 단, 같은 (company,year,fp,fs,metric) UNIQUE라
    # 4개 reprt_code가 fiscal_period(FY/H1/Q1/Q3)로 구분되어 중복 안 됨.
    assert s.query(FinancialFact).count() > 0
    assert stats["facts"] > 0
    assert stats["failed"] == []


def test_ingest_financials_all_collects_failures(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자", {"dart_code": "00126380"})
    s.commit()

    class _BoomClient:
        def fetch_financials(self, **kw):
            raise RuntimeError("boom")

    stats = ingest_financials_all(s, _BoomClient(), years=["2024"])
    assert stats["companies"] == 1
    assert len(stats["failed"]) >= 1
    assert stats["facts"] == 0
