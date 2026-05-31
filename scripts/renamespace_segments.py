"""세그먼트 노드 회사 네임스페이스 재적재(C2) — 일회성·멱등 백필.

기존 전역 키(`segment:{slug}`)로 적재된 segment 노드의 HAS_SEGMENT 엣지를
회사 네임스페이스 노드(`segment:{dart_code}:{slug}`)로 재지정한다.
참조가 0이 된 전역 노드는 제거하되, alias canonical 타깃으로 등록된 전역
노드는 의도된 교차회사 병합을 위해 보존한다. 재실행 시 noop(멱등).

실행: `.venv/bin/python scripts/renamespace_segments.py`
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.ids import segment_id
from themek.ontology.core.models import ConceptAlias, Edge, Node
from themek.ontology.core.resolve import upsert_node


def _is_global(seg_id: str) -> bool:
    """전역 키 segment(`segment:{slug}`) 여부 — 회사키 노드는 콜론 2개."""
    return seg_id.count(":") == 1


def _repoint_one(session: Session, edge: Edge, new_object_id: str) -> None:
    """단일 엣지를 new_object_id로 재지정. 동일 키 기존 엣지와 충돌 시 병합(삭제)."""
    existing = session.execute(
        select(Edge).where(
            Edge.subject_id == edge.subject_id,
            Edge.predicate == edge.predicate,
            Edge.object_id == new_object_id,
            Edge.period.is_(None) if edge.period is None
            else Edge.period == edge.period,
        )
    ).scalars().first()
    if existing is not None and existing.id != edge.id:
        session.delete(edge)
    else:
        edge.object_id = new_object_id


def renamespace_segments(session: Session) -> dict:
    """전역 segment 노드를 회사 네임스페이스로 분리. 요약 dict 반환."""
    alias_targets = {
        a.node_id for a in session.execute(select(ConceptAlias)).scalars().all()
    }
    segments = session.execute(
        select(Node).where(Node.kind == "segment")
    ).scalars().all()
    # alias canonical 타깃 전역 노드는 의도된 병합 — 건너뜀
    global_segs = [n for n in segments
                   if _is_global(n.id) and n.id not in alias_targets]

    repointed = created = removed = 0
    for seg in global_segs:
        name = seg.attrs.get("name") or seg.label
        edges = session.execute(
            select(Edge).where(Edge.object_id == seg.id,
                               Edge.predicate == "HAS_SEGMENT")
        ).scalars().all()
        for e in edges:
            if not e.subject_id.startswith("company:"):
                continue
            dart_code = e.subject_id.split(":", 1)[1]
            new_id = segment_id(name, company_key=dart_code)
            if session.get(Node, new_id) is None:
                upsert_node(session, new_id, "segment", seg.label,
                            {"company": dart_code, "name": name})
                created += 1
            _repoint_one(session, e, new_id)
            repointed += 1
        session.flush()
        # 참조 0 된 전역 노드 제거 (alias 타깃은 이미 제외)
        still_referenced = session.execute(
            select(Edge).where(Edge.object_id == seg.id)
        ).scalars().first()
        if still_referenced is None:
            session.delete(seg)
            removed += 1
    session.flush()
    return {"repointed": repointed, "created": created, "removed": removed}


def main() -> None:
    from themek.db.engine import make_engine, make_session_factory
    session_factory = make_session_factory(make_engine())
    with session_factory() as session:
        summary = renamespace_segments(session)
        session.commit()
    print(summary)


if __name__ == "__main__":
    main()
