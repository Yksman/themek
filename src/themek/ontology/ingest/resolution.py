"""엔티티 해소 배치 패스 — customer→company, segment 병합. 재실행 안전."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.db.corp_models import Corporation
from themek.ontology.core.ids import company_id
from themek.ontology.core.models import Node, Edge, ConceptAlias
from themek.ontology.core.resolve import normalize_corp_name


def _repoint_edges(session: Session, *, old_object_id: str,
                   new_object_id: str, raw_label: str | None = None) -> int:
    """old_object_id를 object로 하는 엣지를 new_object_id로 재지정.
    동일 (subject,predicate,object,period) 기존 엣지와 충돌 시 병합 후 source 삭제."""
    edges = session.execute(
        select(Edge).where(Edge.object_id == old_object_id)
    ).scalars().all()
    moved = 0
    for e in edges:
        if raw_label is not None and "buyer_raw" not in e.qualifier:
            q = dict(e.qualifier); q["buyer_raw"] = raw_label; e.qualifier = q
        existing = session.execute(
            select(Edge).where(
                Edge.subject_id == e.subject_id,
                Edge.predicate == e.predicate,
                Edge.object_id == new_object_id,
                Edge.period.is_(None) if e.period is None
                else Edge.period == e.period,
            )
        ).scalars().first()
        if existing is not None and existing.id != e.id:
            if raw_label is not None and "buyer_raw" not in existing.qualifier:
                q = dict(existing.qualifier); q["buyer_raw"] = raw_label
                existing.qualifier = q
            session.delete(e)
        else:
            e.object_id = new_object_id
        moved += 1
    session.flush()
    return moved


def resolve_customers(session: Session) -> dict:
    """customer 노드를 정규화 exact(별칭 우선)로 company에 해소.
    매칭 시 SELLS_TO를 company로 재지정 + customer 제거, 미매칭은 resolved=false 표식."""
    corp_index = {
        normalize_corp_name(c.name_ko): company_id(c.dart_code)
        for c in session.execute(select(Corporation)).scalars().all()
    }
    customers = session.execute(
        select(Node).where(Node.kind == "customer")
    ).scalars().all()
    resolved = unresolved = repointed = 0
    for cust in customers:
        norm = normalize_corp_name(cust.label)
        target = None
        alias = session.get(ConceptAlias, norm)
        if alias is not None and alias.node_id.startswith("company:"):
            target = alias.node_id
        elif norm in corp_index:
            target = corp_index[norm]
        # 그래프에 존재하는 company로만 해소
        if target is None or session.get(Node, target) is None:
            attrs = dict(cust.attrs); attrs["resolved"] = False
            cust.attrs = attrs
            unresolved += 1
            continue
        repointed += _repoint_edges(session, old_object_id=cust.id,
                                    new_object_id=target, raw_label=cust.label)
        session.delete(cust)
        resolved += 1
    session.flush()
    return {"resolved": resolved, "unresolved": unresolved,
            "edges_repointed": repointed}
