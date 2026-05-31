"""pipeline 헬퍼 단위 테스트."""
import json
from pathlib import Path

from themek.ontology.core.models import Node, FinancialFact
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.pipeline import (
    derive_financial_years, company_report_years, ingest_financials_all,
    run_pipeline,
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


def test_company_report_years_is_per_company(ontology_session):
    s = ontology_session
    _edge(s, "company:A", "segment:a", "2023")
    _edge(s, "company:A", "segment:a2", "2022")
    _edge(s, "company:B", "segment:b", "2025")
    s.commit()
    assert company_report_years(s, "company:A") == ["2022", "2023"]
    assert company_report_years(s, "company:B") == ["2025"]
    assert company_report_years(s, "company:none") == []


def test_ingest_financials_all_uses_per_company_years_by_default(ontology_session):
    s = ontology_session
    # A는 2023만, B는 2025만 제출 → 각자 자기 연도만 호출 (cross-product 아님)
    upsert_node(s, "company:00000001", "company", "에이", {"dart_code": "00000001"})
    upsert_node(s, "segment:sa", "segment", "sa")
    upsert_edge(s, subject_id="company:00000001", predicate="HAS_SEGMENT",
                object_id="segment:sa", period="2023", qualifier={},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    upsert_node(s, "company:00000002", "company", "비", {"dart_code": "00000002"})
    upsert_node(s, "segment:sb", "segment", "sb")
    upsert_edge(s, subject_id="company:00000002", predicate="HAS_SEGMENT",
                object_id="segment:sb", period="2025", qualifier={},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    s.commit()
    client = _FakeClient([])  # 빈 응답이어도 호출 인자만 검증
    ingest_financials_all(s, client)  # years 미지정 → 회사별
    years_by_corp = {}
    for corp, yr, rc, fs in client.calls:
        years_by_corp.setdefault(corp, set()).add(yr)
    assert years_by_corp["00000001"] == {"2023"}   # A는 2023만
    assert years_by_corp["00000002"] == {"2025"}   # B는 2025만 (2023 호출 안 함)


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


def _seed_company_with_edges(s):
    upsert_node(s, "company:00126380", "company", "삼성전자", {"dart_code": "00126380"})
    upsert_node(s, "segment:메모리", "segment", "메모리")
    upsert_edge(s, subject_id="company:00126380", predicate="HAS_SEGMENT",
                object_id="segment:메모리", period="2024", qualifier={"share_pct": 50.0},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    s.commit()


def test_run_pipeline_skips_sync_and_structure(tmp_path, ontology_session):
    s = ontology_session
    _seed_company_with_edges(s)
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    client = _FakeClient(rows)
    result = run_pipeline(
        s, client, cache=None,
        skip_sync=True, skip_structure=True,
        skip_financials=False, skip_export=False,
        since=None, until=None, universe=set(), rate_budget=None, extractor=None,
        out_vault=tmp_path / "vault", out_graph=tmp_path / "graph",
    )
    assert "sync" in result.skipped and "structure" in result.skipped
    assert "financials" in result.ran and "export" in result.ran
    # 재무: 도출 연도 2024 사용
    assert result.financials["facts"] > 0
    # export 산출물
    assert (tmp_path / "vault" / "companies" / "삼성전자.md").exists()
    assert (tmp_path / "graph" / "nodes.json").exists()
    assert result.export["nodes"] > 0


def test_run_pipeline_financials_skipped_when_no_years(tmp_path, ontology_session):
    s = ontology_session
    # 엣지 없음 → 도출 연도 0 → financials는 ran이지만 facts 0
    upsert_node(s, "company:00126380", "company", "삼성전자", {"dart_code": "00126380"})
    s.commit()
    client = _FakeClient([])
    result = run_pipeline(
        s, client, cache=None, skip_sync=True, skip_structure=True,
        skip_financials=False, skip_export=True,
        since=None, until=None, universe=set(), rate_budget=None, extractor=None,
        out_vault=tmp_path / "v", out_graph=tmp_path / "g",
    )
    assert result.financials["facts"] == 0
    assert result.financials.get("years") == []


def test_rebuild_financials_purges_and_reingests(ontology_session):
    from themek.ontology.core.models import Node, Edge, FinancialFact
    from themek.ontology.core.resolve import upsert_node
    from themek.ontology.pipeline import rebuild_financials

    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    # company_report_years가 2024를 반환하도록 엣지 1건(period=2024)
    s.add(Node(id="segment:x", kind="segment", label="x"))
    s.add(Edge(subject_id="company:00126380", predicate="HAS_SEGMENT",
               object_id="segment:x", period="2024", qualifier={},
               source_type="llm", method="llm", confidence=0.9))
    # 오염된(stale) 기존 fact — purge로 사라져야 함
    s.add(FinancialFact(company_id="company:00126380", bsns_year="1999",
                        fiscal_period="FY", fs_div="CFS", metric_key="assets",
                        amount=1, currency="KRW", source_type="dart_api",
                        method="api", confidence=1.0))
    s.commit()

    class _FakeClient:
        def fetch_financials(self, *, corp_code, bsns_year, reprt_code, fs_div):
            if fs_div != "CFS":
                return []
            return [{"account_id": "ifrs-full_Revenue", "account_nm": "매출액",
                     "sj_div": "IS", "thstrm_amount": "500",
                     "frmtrm_amount": "400", "bfefrmtrm_amount": "300"},
                    {"account_id": "ifrs-full_Assets", "account_nm": "자산총계",
                     "sj_div": "BS", "thstrm_amount": "900",
                     "frmtrm_amount": "800", "bfefrmtrm_amount": "700"}]

    res = rebuild_financials(s, _FakeClient())
    s.commit()

    assert res["deleted"] == 1                      # stale fact 제거
    assert res["facts"] > 0                          # 재적재됨
    # stale(1999) fact 사라짐
    assert s.query(FinancialFact).filter_by(bsns_year="1999").count() == 0
    # stock(assets)은 당기만 → 2024만 존재
    assets_years = {f.bsns_year for f in
                    s.query(FinancialFact).filter_by(metric_key="assets").all()}
    assert assets_years == {"2024"}
    assert isinstance(res["issues"], list)


def test_run_pipeline_all_skipped(tmp_path, ontology_session):
    s = ontology_session
    result = run_pipeline(
        s, client=None, cache=None,
        skip_sync=True, skip_structure=True, skip_financials=True, skip_export=True,
        since=None, until=None, universe=set(), rate_budget=None, extractor=None,
        out_vault=tmp_path / "v", out_graph=tmp_path / "g",
    )
    assert result.ran == []
    assert set(result.skipped) == {"sync", "structure", "financials", "export"}
