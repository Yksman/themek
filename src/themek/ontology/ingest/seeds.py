"""코어 그래프 기본 시드 (sector·region·company·stock 노드 + 구조 엣지)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from themek.ontology.core.ids import company_id, stock_id, sector_id, region_id
from themek.ontology.core.resolve import upsert_node, upsert_edge

_SECTORS = [("G2520", "반도체"), ("G2570", "자동차 및 부품"), ("G2030", "산업기계")]
_REGIONS = [("KR", "국내"), ("US", "미주"), ("EU", "유럽"),
            ("CN", "중국"), ("JP", "일본"), ("ROW", "기타")]
_COMPANIES = [
    ("00126380", "삼성전자", "G2520", "005930", "KOSPI"),
    ("00164742", "현대자동차", "G2570", "005380", "KOSPI"),
    ("01261644", "레인보우로보틱스", "G2030", "277810", "KOSDAQ"),
]


def seed_core(session: Session) -> None:
    for fics, name in _SECTORS:
        upsert_node(session, sector_id(fics), "sector", name)
    for code, name in _REGIONS:
        upsert_node(session, region_id(code), "region", name)
    for dart, name, fics, ticker, market in _COMPANIES:
        cid, sid = company_id(dart), stock_id(ticker)
        upsert_node(session, cid, "company", name, {"dart_code": dart})
        upsert_node(session, sid, "stock", name,
                    {"ticker": ticker, "market": market})
        upsert_edge(session, subject_id=cid, predicate="IN_SECTOR",
                    object_id=sector_id(fics), period=None, qualifier={},
                    source_type="manual", source_ref=None, method="manual",
                    confidence=1.0)
        upsert_edge(session, subject_id=cid, predicate="ISSUES_STOCK",
                    object_id=sid, period=None, qualifier={},
                    source_type="manual", source_ref=None, method="manual",
                    confidence=1.0)
