"""DART fnlttSinglAcntAll 응답 → financial_facts 적재.

응답 1행 = 한 계정의 3개년(당기/전기/전전기) 금액. account_id(IFRS 표준ID)
우선, account_nm fallback으로 KPI metric_key에 매핑한다.
"""
from __future__ import annotations

# account_id → metric_key (우선)
_ID_MAP = {
    "ifrs-full_Revenue": "revenue",
    "ifrs_Revenue": "revenue",
    "dart_OperatingIncomeLoss": "operating_income",
    "ifrs-full_ProfitLossFromOperatingActivities": "operating_income",
    "ifrs-full_ProfitLoss": "net_income",
    "ifrs-full_Assets": "assets",
    "ifrs-full_Liabilities": "liabilities",
    "ifrs-full_Equity": "equity",
    "ifrs-full_BasicEarningsLossPerShare": "eps",
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": "cf_operating",
    "ifrs-full_CashFlowsFromUsedInInvestingActivities": "cf_investing",
    "ifrs-full_CashFlowsFromUsedInFinancingActivities": "cf_financing",
}
# account_nm → metric_key (fallback)
_NM_MAP = {
    "매출액": "revenue", "수익(매출액)": "revenue", "영업수익": "revenue",
    "영업이익": "operating_income", "영업이익(손실)": "operating_income",
    "당기순이익": "net_income", "당기순이익(손실)": "net_income",
    "자산총계": "assets", "부채총계": "liabilities", "자본총계": "equity",
    "기본주당이익(손실)": "eps", "기본주당순이익": "eps",
    "영업활동현금흐름": "cf_operating", "영업활동으로인한현금흐름": "cf_operating",
    "투자활동현금흐름": "cf_investing", "투자활동으로인한현금흐름": "cf_investing",
    "재무활동현금흐름": "cf_financing", "재무활동으로인한현금흐름": "cf_financing",
}
# 각 metric은 해당 재무제표(sj_div)에서만 유효. fnlttSinglAcntAll은 한 응답에
# BS(재무상태표)·IS/CIS(손익)·SCE(자본변동표)·CF(현금흐름표)를 모두 담는데,
# 예) account_id 'ifrs-full_Equity'(자본총계)는 BS의 총계 1행 외에 SCE에 구성요소로
# 여러 번 등장한다. sj_div로 제한하지 않으면 SCE 구성요소(비지배지분 등)가 총계를
# 덮어써 값이 오염된다.
_BS = frozenset({"BS"})
_PL = frozenset({"IS", "CIS"})
_METRIC_SJ = {
    "revenue": _PL, "operating_income": _PL, "net_income": _PL,
    "assets": _BS, "liabilities": _BS, "equity": _BS,
    "eps": _PL,
    "cf_operating": frozenset({"CF"}),
    "cf_investing": frozenset({"CF"}),
    "cf_financing": frozenset({"CF"}),
    "shares_outstanding": frozenset({"BS"}),  # 파싱 경로 미사용(별도 fetch) — 방어값
}
_FLOW = frozenset({"revenue", "operating_income", "net_income",
                   "eps", "cf_operating", "cf_investing", "cf_financing"})
_STOCK = frozenset({"assets", "liabilities", "equity"})


def _to_amount(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _metric_of(row: dict) -> str | None:
    key = _ID_MAP.get((row.get("account_id") or "").strip())
    if not key:
        key = _NM_MAP.get((row.get("account_nm") or "").strip())
    if not key:
        return None
    # 해당 재무제표(sj_div)에서 온 행만 유효 — SCE/CF 오염 차단.
    if (row.get("sj_div") or "").strip() not in _METRIC_SJ[key]:
        return None
    return key


def parse_financial_rows(rows: list[dict], *, bsns_year: str,
                         fiscal_period: str) -> list[dict]:
    """행들을 [{company-agnostic fact dict}] 로 평탄화.

    flow 지표(매출/이익)는 당기/전기/전전기 3개년 전개 — 비교열이 '전기 동기'라 의미상 맞다.
    stock 지표(자산/부채/자본)는 당기(thstrm)만 적재 — 분기보고서의 비교열(frmtrm)은
    '직전 사업연도 말' 스냅샷이라 interim period로 라벨링하면 오염된다(연말값으로 덮어씀).
    """
    yr = int(bsns_year)
    flow_years = {
        "thstrm_amount": str(yr),
        "frmtrm_amount": str(yr - 1),
        "bfefrmtrm_amount": str(yr - 2),
    }
    facts: list[dict] = []
    for row in rows:
        metric = _metric_of(row)
        if metric is None:
            continue
        if metric in _STOCK:
            amount = _to_amount(row.get("thstrm_amount"))
            if amount is not None:
                facts.append({"metric_key": metric, "bsns_year": str(yr),
                              "fiscal_period": fiscal_period, "amount": amount})
            continue
        for field, year_label in flow_years.items():
            amount = _to_amount(row.get(field))
            if amount is None:
                continue
            facts.append({"metric_key": metric, "bsns_year": year_label,
                          "fiscal_period": fiscal_period, "amount": amount})
    return facts


from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from themek.ontology.core.ids import period_id, metric_id  # noqa: E402
from themek.ontology.core.models import FinancialFact, METRIC_KEYS  # noqa: E402
from themek.ontology.core.resolve import upsert_node  # noqa: E402

# reprt_code → fiscal_period 라벨
_REPRT_PERIOD = {"11011": "FY", "11012": "H1", "11013": "Q1", "11014": "Q3"}
_METRIC_LABEL = {
    "revenue": "매출액", "operating_income": "영업이익", "net_income": "당기순이익",
    "assets": "자산총계", "liabilities": "부채총계", "equity": "자본총계",
    "eps": "기본주당순이익", "cf_operating": "영업활동현금흐름",
    "cf_investing": "투자활동현금흐름", "cf_financing": "재무활동현금흐름",
    "shares_outstanding": "발행주식수",
}


def _ensure_metric_nodes(session: Session) -> None:
    for key in METRIC_KEYS:
        upsert_node(session, metric_id(key), "metric", _METRIC_LABEL[key])


def _ensure_period_node(session: Session, bsns_year: str,
                        fiscal_period: str) -> None:
    upsert_node(session, period_id(bsns_year, fiscal_period), "period",
                f"{bsns_year} {fiscal_period}")


def _upsert_fact(session: Session, company_id: str, fs_div: str, f: dict) -> None:
    existing = session.execute(
        select(FinancialFact).where(
            FinancialFact.company_id == company_id,
            FinancialFact.bsns_year == f["bsns_year"],
            FinancialFact.fiscal_period == f["fiscal_period"],
            FinancialFact.fs_div == fs_div,
            FinancialFact.metric_key == f["metric_key"],
        )
    ).scalars().first()
    if existing is None:
        session.add(FinancialFact(
            company_id=company_id, bsns_year=f["bsns_year"],
            fiscal_period=f["fiscal_period"], fs_div=fs_div,
            metric_key=f["metric_key"], amount=f["amount"], currency="KRW",
            source_type="dart_api", source_ref=None, method="api", confidence=1.0))
    else:
        existing.amount = f["amount"]


def ingest_financials_for_company(session: Session, client, *, corp_code: str,
                                  bsns_year: str, reprt_code: str) -> int:
    """회사 1건 재무 적재. CFS→OFS fallback. 적재한 fact 수 반환."""
    from themek.ontology.core.ids import company_id as _cid
    fiscal_period = _REPRT_PERIOD[reprt_code]
    company_node_id = _cid(corp_code)

    rows = client.fetch_financials(corp_code=corp_code, bsns_year=bsns_year,
                                   reprt_code=reprt_code, fs_div="CFS")
    fs_div = "CFS"
    if not rows:
        rows = client.fetch_financials(corp_code=corp_code, bsns_year=bsns_year,
                                       reprt_code=reprt_code, fs_div="OFS")
        fs_div = "OFS"
    if not rows:
        return 0

    facts = parse_financial_rows(rows, bsns_year=bsns_year,
                                 fiscal_period=fiscal_period)
    if not facts:
        return 0

    _ensure_metric_nodes(session)
    periods_seen = {(f["bsns_year"], f["fiscal_period"]) for f in facts}
    for yr, fp in periods_seen:
        _ensure_period_node(session, yr, fp)
    for f in facts:
        _upsert_fact(session, company_node_id, fs_div, f)
    return len(facts)


def ingest_shares_for_company(session: Session, client, *, corp_code: str,
                              bsns_year: str, reprt_code: str) -> int:
    """발행주식수(보통주 총수) → shares_outstanding fact. stock 지표(당기만). 멱등.

    fs_div는 연결/별도 무관 개념이라 관습적으로 'CFS' 고정(unique 키 충족용).
    """
    from themek.ontology.core.ids import company_id as _cid
    fiscal_period = _REPRT_PERIOD[reprt_code]
    rows = client.fetch_shares(corp_code=corp_code, bsns_year=bsns_year,
                               reprt_code=reprt_code)
    common = next((r for r in rows
                   if (r.get("se") or "").strip().startswith("보통")), None)
    if common is None:
        return 0
    amount = _to_amount(common.get("istc_totqy"))
    if amount is None:
        return 0
    _ensure_metric_nodes(session)
    _ensure_period_node(session, bsns_year, fiscal_period)
    _upsert_fact(session, _cid(corp_code), "CFS",
                 {"metric_key": "shares_outstanding", "bsns_year": bsns_year,
                  "fiscal_period": fiscal_period, "amount": amount})
    return 1
