"""코어 그래프 기본 시드 (sector·region·company·stock 노드 + 구조 엣지)."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from themek.ontology.core.ids import (
    company_id, stock_id, sector_id, region_id, segment_id)
from themek.ontology.core.models import ConceptAlias, Node
from themek.ontology.core.resolve import (
    upsert_node, upsert_edge, normalize_corp_name, normalize_alias)

_DEFAULT_ALIASES = Path("data/ontology/aliases.json")

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


def _upsert_alias(session: Session, alias_norm: str, node_id: str) -> bool:
    """target 노드가 그래프에 존재할 때만 alias upsert. 적재(또는 갱신) 시 True.

    ConceptAlias.node_id는 nodes.id FK라 존재하지 않는 노드를 가리키면 FK 위반.
    큐레이션 aliases.json이 미적재 corp/segment를 참조해도 안전하게 건너뛴다."""
    if session.get(Node, node_id) is None:
        return False
    row = session.get(ConceptAlias, alias_norm)
    if row is None:
        session.add(ConceptAlias(alias_norm=alias_norm, node_id=node_id,
                                 source="manual", confidence=1.0))
    else:
        row.node_id = node_id
    return True


def seed_aliases(session: Session, path: Path = _DEFAULT_ALIASES) -> int:
    """JSON 별칭을 ConceptAlias로 적재. customer 변형은 normalize_corp_name,
    segment 동의어는 normalize_alias 키로 저장. upsert(멱등).
    target 노드가 그래프에 없는 변형은 건너뛴다. 적재 수 반환."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    n = 0
    for entry in data.get("customers", []):
        target = company_id(entry["corp"])
        for variant in entry["variants"]:
            if _upsert_alias(session, normalize_corp_name(variant), target):
                n += 1
    for entry in data.get("segments", []):
        target = segment_id(entry["canonical"])
        for variant in entry["variants"]:
            if _upsert_alias(session, normalize_alias(variant), target):
                n += 1
    return n
