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
# 명백한 개인 신호: 임원·가족. "계열회사 임원"처럼 corp 키워드와 섞여도 개인으로 본다.
# ("본인"/"특수관계인"은 법인·개인 모두에 쓰여 신호로 부적합 → 제외.)
_RELATE_PERSON = re.compile(r"임원|배우자|자녀|친인척|형제자매|형제|친족")
# 최대주주현황 표의 합계/소계 행(주주가 아님) — 적재 제외.
_SUMMARY_NAMES = frozenset({"계", "소계", "합계", "총계"})


def classify_shareholder(nm: str, relate: str) -> str:
    """주주 성명/관계로 person|company 판별. 이름의 법인 접미/키워드 최우선,
    그다음 관계의 개인 신호(임원·가족), 그다음 관계의 법인 신호, 기본 person."""
    name = (nm or "").strip()
    rel = (relate or "").strip()
    if _CORP_AFFIX.search(name) or _CORP_KEYWORD.search(name):
        return "company"
    if _RELATE_PERSON.search(rel):
        return "person"
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
    period=bsns_year(4자리). 멱등. 적재 엣지(=고유 holder) 수 반환.

    한 holder가 주식종류별(보통주/우선주)로 여러 행에 나뉘므로, 엣지 키
    (subject,object,period)가 같아 마지막 행이 앞 행을 덮어쓰는 문제가 있다.
    의결권 지분(보통주)이 헤드라인 지분율이므로 holder별 **최대 stake_pct 행**만
    채택한다. 표의 합계/소계 행(`_SUMMARY_NAMES`)은 주주가 아니므로 제외한다."""
    held = company_id(corp_code)
    best: dict[str, dict] = {}
    for row in rows:
        name = (row.get("nm") or "").strip()
        if not name or name in _SUMMARY_NAMES:
            continue
        relate = (row.get("relate") or "").strip()
        kind = classify_shareholder(name, relate)
        hid = (person_id(name, corp_code) if kind == "person"
               else external_company_id(name))
        pct = _to_pct(row.get("trmend_posesn_stock_qota_rt"))
        cur = best.get(hid)
        cur_pct = cur["pct"] if cur is not None else None
        if cur is None or (pct is not None and (cur_pct is None or pct > cur_pct)):
            best[hid] = {"name": name, "kind": kind, "relate": relate,
                         "pct": pct,
                         "shares": _to_int(row.get("trmend_posesn_stock_co"))}
    for hid, b in best.items():
        if b["kind"] == "person":
            upsert_node(session, hid, "person", b["name"])
        else:
            upsert_node(session, hid, "company", b["name"], {"external": True})
        q = {
            "stake_pct": b["pct"],
            "shares": b["shares"],
            "relation": b["relate"] or None,
            "is_largest": bool(_IS_LARGEST.search(b["relate"])),
        }
        upsert_edge(session, subject_id=hid, predicate="OWNS_STAKE_IN",
                    object_id=held, period=bsns_year, qualifier=q,
                    source_type="dart_api", source_ref=source_ref,
                    method="api", confidence=1.0)
    return len(best)


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


def ingest_equity_for_company(session: Session, client, *, corp_code: str,
                              bsns_year: str, reprt_code: str = "11011") -> int:
    """회사 1건 지분구조 적재(사업보고서 기준). 최대주주 + 타법인출자 엣지 수 합 반환."""
    source_ref = f"dart:{corp_code}:{bsns_year}:{reprt_code}"
    sh = client.fetch_largest_shareholders(
        corp_code=corp_code, bsns_year=bsns_year, reprt_code=reprt_code)
    inv = client.fetch_other_corp_investments(
        corp_code=corp_code, bsns_year=bsns_year, reprt_code=reprt_code)
    n = ingest_largest_shareholders(session, corp_code=corp_code,
                                    bsns_year=bsns_year, rows=sh,
                                    source_ref=source_ref)
    n += ingest_other_corp_investments(session, corp_code=corp_code,
                                       bsns_year=bsns_year, rows=inv,
                                       source_ref=source_ref)
    return n
