"""외부(DART) 분류 데이터 → 코어 섹터 노드/엣지 (provenance method=api)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.ids import sector_id
from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node, upsert_edge

_DEFAULT_KSIC = Path("data/ontology/ksic.json")


@lru_cache(maxsize=8)
def _load_ksic(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def link_sectors(session: Session, client,
                 ksic_path: Path = _DEFAULT_KSIC) -> int:
    """company 노드별 DART 기업개황 fetch → sector 노드 + IN_SECTOR 엣지. 멱등.

    DART company.json은 induty_code(KSIC 코드)만 주고 명칭은 주지 않으므로
    `data/ontology/ksic.json`(코드→명칭)으로 라벨링한다. 매핑 없으면 'KSIC {code}'.
    회사당 IN_SECTOR는 1개만 유지한다(이중분류 정리): 기존 IN_SECTOR 중 이번 induty
    섹터가 아닌 엣지는 삭제. 그래프가 정본이므로 관계형 in_sector_id는 미동기화.
    """
    ksic = _load_ksic(str(ksic_path))
    companies = session.execute(
        select(Node).where(Node.kind == "company")
    ).scalars().all()
    n = 0
    for c in companies:
        dart_code = c.attrs.get("dart_code")
        if not dart_code:
            continue
        profile = client.fetch_company_profile(corp_code=dart_code)
        code = (profile.get("induty_code") or "").strip()
        if not code:
            continue
        name = ksic.get(code) or f"KSIC {code}"
        sid = sector_id(code)
        upsert_node(session, sid, "sector", name, {"induty_code": code})
        # 이중분류 정리: 이 회사의 다른 IN_SECTOR 엣지 제거
        for old in session.execute(
            select(Edge).where(Edge.subject_id == c.id,
                               Edge.predicate == "IN_SECTOR")
        ).scalars().all():
            if old.object_id != sid:
                session.delete(old)
        upsert_edge(session, subject_id=c.id, predicate="IN_SECTOR",
                    object_id=sid, period=None, qualifier={},
                    source_type="dart_api", source_ref=None, method="api",
                    confidence=1.0)
        n += 1
    return n
