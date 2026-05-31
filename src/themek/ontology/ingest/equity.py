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


from sqlalchemy.orm import Session  # noqa: E402

from themek.ontology.core.ids import (  # noqa: E402
    company_id, person_id, external_company_id)
from themek.ontology.core.resolve import upsert_node, upsert_edge  # noqa: E402

_IS_LARGEST = re.compile(r"본인|최대주주")


def _to_pct(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", "").replace("%", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(raw) -> int | None:
    f = _to_pct(raw)
    return int(f) if f is not None else None


def ingest_largest_shareholders(session: Session, *, corp_code: str,
                                bsns_year: str, rows: list[dict],
                                source_ref: str) -> int:
    """최대주주현황 행 → holder(person|company:ext) ──OWNS_STAKE_IN──▶ 보고회사.
    period=bsns_year(4자리). 멱등. 적재 엣지 수 반환."""
    held = company_id(corp_code)
    n = 0
    for row in rows:
        name = (row.get("nm") or "").strip()
        if not name:
            continue
        relate = (row.get("relate") or "").strip()
        kind = classify_shareholder(name, relate)
        if kind == "person":
            hid = person_id(name, corp_code)
            upsert_node(session, hid, "person", name)
        else:
            hid = external_company_id(name)
            upsert_node(session, hid, "company", name, {"external": True})
        pct = _to_pct(row.get("trmend_posesn_stock_qota_rt"))
        q = {
            "stake_pct": pct,
            "shares": _to_int(row.get("trmend_posesn_stock_co")),
            "relation": relate or None,
            "is_largest": bool(_IS_LARGEST.search(relate)),
        }
        upsert_edge(session, subject_id=hid, predicate="OWNS_STAKE_IN",
                    object_id=held, period=bsns_year, qualifier=q,
                    source_type="dart_api", source_ref=source_ref,
                    method="api", confidence=1.0)
        n += 1
    return n


def ingest_other_corp_investments(session: Session, *, corp_code: str,
                                  bsns_year: str, rows: list[dict],
                                  source_ref: str) -> int:
    """타법인출자현황 행 → 보고회사 ──OWNS_STAKE_IN──▶ 피출자(company:ext).
    피출자는 항상 company:ext로 적재(resolve가 universe로 승격). 멱등. 엣지 수 반환."""
    holder = company_id(corp_code)
    n = 0
    for row in rows:
        name = (row.get("inv_prm") or "").strip()
        if not name:
            continue
        oid = external_company_id(name)
        upsert_node(session, oid, "company", name, {"external": True})
        pct = _to_pct(row.get("trmend_blce_qota_rt"))
        q = {
            "stake_pct": pct,
            "shares": _to_int(row.get("trmend_blce_qy")),
            "affiliation_type": affiliation_from_stake(pct),
            "purpose": (row.get("invstmnt_purps") or "").strip() or None,
        }
        upsert_edge(session, subject_id=holder, predicate="OWNS_STAKE_IN",
                    object_id=oid, period=bsns_year, qualifier=q,
                    source_type="dart_api", source_ref=source_ref,
                    method="api", confidence=1.0)
        n += 1
    return n
