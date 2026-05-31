"""DART 최대주주현황·타법인출자현황 → OWNS_STAKE_IN 엣지 적재 (method=api)."""
from __future__ import annotations

import re

# 법인 식별: 법인 형태 접미/접두 + 기관성 키워드
_CORP_AFFIX = re.compile(
    r"\(주\)|㈜|주식회사|유한회사|유한책임회사|합자회사|재단|"
    r"\bco\.?,?\s*ltd\.?|\bltd\.?|\binc\.?|\bcorp\.?|\bcorporation\b|\bllc\b",
    re.IGNORECASE,
)
_CORP_KEYWORD = re.compile(
    r"홀딩스|지주|투자|운용|자산운용|투신|증권|보험|은행|캐피탈|"
    r"공단|연금|펀드|파트너스|벤처스|인베스트먼트|기금|조합")
_RELATE_CORP = re.compile(r"계열회사|법인|기관")


def classify_shareholder(nm: str, relate: str) -> str:
    """주주 성명/관계로 person|company 판별. 법인 신호 우선, 기본 person."""
    name = (nm or "").strip()
    rel = (relate or "").strip()
    if _CORP_AFFIX.search(name) or _CORP_KEYWORD.search(name):
        return "company"
    if _RELATE_CORP.search(rel):
        return "company"
    return "person"


def affiliation_from_stake(stake_pct: float | None) -> str:
    """K-IFRS 지분율 기준 분류: >=50 자회사, >=20 관계회사, 그외 기타."""
    if stake_pct is None:
        return "기타"
    if stake_pct >= 50:
        return "자회사"
    if stake_pct >= 20:
        return "관계회사"
    return "기타"
