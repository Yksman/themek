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
}
# account_nm → metric_key (fallback)
_NM_MAP = {
    "매출액": "revenue", "수익(매출액)": "revenue", "영업수익": "revenue",
    "영업이익": "operating_income", "영업이익(손실)": "operating_income",
    "당기순이익": "net_income", "당기순이익(손실)": "net_income",
    "자산총계": "assets", "부채총계": "liabilities", "자본총계": "equity",
}


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
    if key:
        return key
    return _NM_MAP.get((row.get("account_nm") or "").strip())


def parse_financial_rows(rows: list[dict], *, bsns_year: str,
                         fiscal_period: str) -> list[dict]:
    """행들을 [{company-agnostic fact dict}] 로 평탄화. 3개년 전개."""
    yr = int(bsns_year)
    year_field = {
        "thstrm_amount": str(yr),
        "frmtrm_amount": str(yr - 1),
        "bfefrmtrm_amount": str(yr - 2),
    }
    facts: list[dict] = []
    for row in rows:
        metric = _metric_of(row)
        if metric is None:
            continue
        for field, year_label in year_field.items():
            amount = _to_amount(row.get(field))
            if amount is None:
                continue
            facts.append({
                "metric_key": metric, "bsns_year": year_label,
                "fiscal_period": fiscal_period, "amount": amount,
            })
    return facts
