"""전역 안정 노드 ID 스킴: `{kind}:{natural_key|slug}`.

자연키가 있는 종류(company/stock/sector/region/metric)는 키 그대로,
개념 종류(segment/customer)는 정규화 slug(+장문 해시)를 쓴다.
"""
from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")
_UNSAFE = re.compile(r"[^0-9a-z가-힣]+")
_SLUG_MAX = 48


def slug(s: str) -> str:
    """소문자 + 공백/특수문자를 하이픈으로. 한글 보존."""
    base = _WS.sub(" ", s.strip()).lower()
    base = _UNSAFE.sub("-", base).strip("-")
    if len(base) <= _SLUG_MAX:
        return base
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()[:6]
    return f"{base[:_SLUG_MAX - 7].strip('-')}-{h}"


def company_id(dart_code: str) -> str:
    return f"company:{dart_code}"


def stock_id(ticker: str) -> str:
    return f"stock:{ticker}"


def sector_id(fics_code: str) -> str:
    return f"sector:{fics_code}"


def region_id(code: str) -> str:
    return f"region:{code}"


def metric_id(key: str) -> str:
    return f"metric:{key}"


def period_id(bsns_year: str, fiscal_period: str) -> str:
    return f"period:{bsns_year}{fiscal_period}"


def segment_id(name_ko: str) -> str:
    return f"segment:{slug(name_ko)}"


def customer_id(raw: str) -> str:
    return f"customer:{slug(raw)}"
