"""외부(DART) 분류 데이터 → 코어 섹터 노드/엣지 (provenance method=api)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.ids import sector_id
from themek.ontology.core.models import Node
from themek.ontology.core.resolve import upsert_node, upsert_edge


def link_sectors(session: Session, client) -> int:
    """company 노드별 DART 기업개황 fetch → sector 노드 + IN_SECTOR 엣지. 멱등.

    그래프가 정본이므로 관계형 Corporation.in_sector_id는 동기화하지 않는다
    (induty_code는 sectors.fics_code FK 네임스페이스와 달라 FK 위반 위험).
    """
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
        name = (profile.get("induty") or code).strip()
        sid = sector_id(code)
        upsert_node(session, sid, "sector", name)
        upsert_edge(session, subject_id=c.id, predicate="IN_SECTOR",
                    object_id=sid, period=None, qualifier={},
                    source_type="dart_api", source_ref=None, method="api",
                    confidence=1.0)
        n += 1
    return n
