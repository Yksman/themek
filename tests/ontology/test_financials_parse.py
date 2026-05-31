"""재무 API 행 → (metric_key, 연도별 금액) 파싱 단위 테스트."""
import json
from pathlib import Path

from themek.ontology.ingest.financials import parse_financial_rows

_CASSETTE = Path("tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json")


def test_parse_maps_accounts_flow_3yr_stock_1yr():
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY")
    # flow 3종 × 3개년(9) + stock 3종 × 당기만(3) = 12
    assert len(facts) == 12
    rev_2024 = [f for f in facts if f["metric_key"] == "revenue"
                and f["bsns_year"] == "2024"]
    assert len(rev_2024) == 1
    assert rev_2024[0]["amount"] == 3007700000000.0
    # flow(revenue)는 3개년 라벨 유지
    assert {f["bsns_year"] for f in facts if f["metric_key"] == "revenue"} \
        == {"2024", "2023", "2022"}
    # stock(assets)는 당기(2024)만
    assert {f["bsns_year"] for f in facts if f["metric_key"] == "assets"} == {"2024"}


def test_parse_stock_metric_thstrm_only_in_interim():
    """분기보고서의 비교열(frmtrm=직전 연말)은 적재하지 않는다 — stock은 당기만."""
    rows = [
        {"account_id": "ifrs-full_Assets", "account_nm": "자산총계", "sj_div": "BS",
         "thstrm_amount": "100", "frmtrm_amount": "90", "bfefrmtrm_amount": "80"},
        {"account_id": "ifrs-full_Revenue", "account_nm": "매출액", "sj_div": "IS",
         "thstrm_amount": "50", "frmtrm_amount": "40", "bfefrmtrm_amount": "30"},
    ]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="Q1")
    assets = [f for f in facts if f["metric_key"] == "assets"]
    assert len(assets) == 1 and assets[0]["bsns_year"] == "2024" \
        and assets[0]["amount"] == 100.0
    # flow는 3개년 그대로
    rev = {f["bsns_year"]: f["amount"] for f in facts if f["metric_key"] == "revenue"}
    assert rev == {"2024": 50.0, "2023": 40.0, "2022": 30.0}


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


def test_parse_equity_only_from_bs_not_sce():
    """자본총계는 BS에서만. SCE(자본변동표)의 동일 account_id 구성요소는 무시."""
    rows = [
        {"account_id": "ifrs-full_Equity", "account_nm": "자본총계", "sj_div": "BS",
         "thstrm_amount": "363677865000000", "frmtrm_amount": "", "bfefrmtrm_amount": ""},
        {"account_id": "ifrs-full_Equity", "account_nm": "자본총계", "sj_div": "SCE",
         "thstrm_amount": "10444090000000", "frmtrm_amount": "", "bfefrmtrm_amount": ""},
        {"account_id": "ifrs-full_Equity", "account_nm": "기말자본", "sj_div": "SCE",
         "thstrm_amount": "897514000000", "frmtrm_amount": "", "bfefrmtrm_amount": ""},
    ]
    facts = parse_financial_rows(rows, bsns_year="2023", fiscal_period="FY")
    eq = [f for f in facts if f["metric_key"] == "equity" and f["bsns_year"] == "2023"]
    assert len(eq) == 1
    assert eq[0]["amount"] == 363677865000000.0


def test_parse_income_metric_only_from_is_cis_not_cf():
    """당기순이익은 IS/CIS에서만. CF(현금흐름표) 시작점의 동일 account는 무시."""
    rows = [
        {"account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익", "sj_div": "CIS",
         "thstrm_amount": "100", "frmtrm_amount": "", "bfefrmtrm_amount": ""},
        {"account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익", "sj_div": "CF",
         "thstrm_amount": "999", "frmtrm_amount": "", "bfefrmtrm_amount": ""},
    ]
    facts = parse_financial_rows(rows, bsns_year="2023", fiscal_period="FY")
    ni = [f for f in facts if f["metric_key"] == "net_income" and f["bsns_year"] == "2023"]
    assert len(ni) == 1
    assert ni[0]["amount"] == 100.0


def test_parse_eps_from_is_flow_expansion():
    rows = [{"account_id": "ifrs-full_BasicEarningsLossPerShare",
             "account_nm": "기본주당이익(손실)", "sj_div": "CIS",
             "thstrm_amount": "8057", "frmtrm_amount": "6461",
             "bfefrmtrm_amount": "5777"}]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY")
    eps = {f["bsns_year"]: f["amount"] for f in facts if f["metric_key"] == "eps"}
    assert eps == {"2024": 8057.0, "2023": 6461.0, "2022": 5777.0}


def test_parse_cashflow_only_from_cf_statement():
    rows = [
        {"account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities",
         "account_nm": "영업활동현금흐름", "sj_div": "CF",
         "thstrm_amount": "100", "frmtrm_amount": "90", "bfefrmtrm_amount": "80"},
        # 같은 account가 다른 표(BS)에 잘못 오면 무시되어야 함
        {"account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities",
         "account_nm": "영업활동현금흐름", "sj_div": "BS",
         "thstrm_amount": "999", "frmtrm_amount": "", "bfefrmtrm_amount": ""},
    ]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY")
    cfo = [f for f in facts if f["metric_key"] == "cf_operating"]
    assert {f["bsns_year"]: f["amount"] for f in cfo} == \
        {"2024": 100.0, "2023": 90.0, "2022": 80.0}
