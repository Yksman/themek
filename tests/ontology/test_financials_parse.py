"""재무 API 행 → (metric_key, 연도별 금액) 파싱 단위 테스트."""
import json
from pathlib import Path

from themek.ontology.ingest.financials import parse_financial_rows

_CASSETTE = Path("tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json")


def test_parse_maps_accounts_and_three_years():
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY")
    # 6개 metric × 3개년 = 18 fact
    assert len(facts) == 18
    rev_2024 = [f for f in facts if f["metric_key"] == "revenue"
                and f["bsns_year"] == "2024"]
    assert len(rev_2024) == 1
    assert rev_2024[0]["amount"] == 3007700000000.0
    # 전기/전전기 연도 라벨 = 2023/2022
    years = {f["bsns_year"] for f in facts if f["metric_key"] == "revenue"}
    assert years == {"2024", "2023", "2022"}


def test_parse_skips_unmapped_accounts():
    rows = [{"account_id": "ifrs-full_GrossProfit", "account_nm": "매출총이익",
             "thstrm_amount": "100", "frmtrm_amount": "90",
             "bfefrmtrm_amount": "80", "sj_div": "IS"}]
    assert parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY") == []


def test_parse_handles_blank_and_negative_amounts():
    rows = [{"account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익",
             "thstrm_amount": "-5,000", "frmtrm_amount": "",
             "bfefrmtrm_amount": "1,000", "sj_div": "IS"}]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY")
    by_year = {f["bsns_year"]: f["amount"] for f in facts}
    assert by_year["2024"] == -5000.0   # 음수·콤마 파싱
    assert "2023" not in by_year          # 빈 금액 스킵
    assert by_year["2022"] == 1000.0
