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
            q = dict(e.qualifier)
            q["buyer_raw"] = raw_label
            e.qualifier = q
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
                q = dict(existing.qualifier)
                q["buyer_raw"] = raw_label
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
            attrs = dict(cust.attrs)
            attrs["resolved"] = False
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


def merge_segments(session: Session) -> dict:
    """별칭 시드에 따라 비-canonical segment 노드의 HAS_SEGMENT 엣지를 canonical로
    재지정 + 고아 노드 제거. ConceptAlias(segment)는 normalize_alias 키 사용."""
    from themek.ontology.core.resolve import normalize_alias
    segments = session.execute(
        select(Node).where(Node.kind == "segment")
    ).scalars().all()
    merged = 0
    for seg in segments:
        alias = session.get(ConceptAlias, normalize_alias(seg.label))
        if alias is None or alias.node_id == seg.id:
            continue
        if not alias.node_id.startswith("segment:") \
                or session.get(Node, alias.node_id) is None:
            continue
        _repoint_edges(session, old_object_id=seg.id,
                       new_object_id=alias.node_id)
        session.delete(seg)
        merged += 1
    session.flush()
    return {"merged": merged}


def _repoint_subject_edges(session: Session, *, old_subject_id: str,
                           new_subject_id: str) -> int:
    """old_subject_id를 subject로 하는 엣지를 new_subject_id로 재지정.
    동일 (subject,predicate,object,period) 충돌 시 source 삭제(병합)."""
    edges = session.execute(
        select(Edge).where(Edge.subject_id == old_subject_id)
    ).scalars().all()
    moved = 0
    for e in edges:
        existing = session.execute(
            select(Edge).where(
                Edge.subject_id == new_subject_id,
                Edge.predicate == e.predicate,
                Edge.object_id == e.object_id,
                Edge.period.is_(None) if e.period is None
                else Edge.period == e.period,
            )
        ).scalars().first()
        if existing is not None and existing.id != e.id:
            session.delete(e)
        else:
            e.subject_id = new_subject_id
        moved += 1
    session.flush()
    return moved


def resolve_external_companies(session: Session) -> dict:
    """company:ext 노드를 정규화 exact(별칭 우선)로 universe company에 해소.
    매칭 시 OWNS_STAKE_IN object 재지정 + ext 노드 제거."""
    corp_index = {
        normalize_corp_name(c.name_ko): company_id(c.dart_code)
        for c in session.execute(select(Corporation)).scalars().all()
    }
    ext = session.execute(
        select(Node).where(Node.kind == "company",
                           Node.id.like("company:ext:%"))
    ).scalars().all()
    resolved = unresolved = repointed = 0
    for node in ext:
        norm = normalize_corp_name(node.label)
        target = None
        alias = session.get(ConceptAlias, norm)
        if alias is not None and alias.node_id.startswith("company:") \
                and not alias.node_id.startswith("company:ext:"):
            target = alias.node_id
        elif norm in corp_index:
            target = corp_index[norm]
        if target is None or session.get(Node, target) is None:
            unresolved += 1
            continue
        # 외부법인은 피출자(object)일 수도, 법인 최대주주(subject)일 수도 있다.
        # 양방향 엣지를 모두 universe 노드로 재지정해야 FK 위반 없이 삭제 가능.
        repointed += _repoint_edges(session, old_object_id=node.id,
                                    new_object_id=target)
        repointed += _repoint_subject_edges(session, old_subject_id=node.id,
                                             new_subject_id=target)
        session.delete(node)
        resolved += 1
    session.flush()
    return {"resolved": resolved, "unresolved": unresolved,
            "edges_repointed": repointed}


def resolve_owners(session: Session) -> dict:
    """회사 네임스페이스 person 노드를 alias 시드에 따라 canonical person으로 병합.
    OWNS_STAKE_IN subject 재지정 + 네임스페이스 노드 제거. ConceptAlias는
    normalize_alias 키. canonical 노드(`person:{slug}`)가 존재할 때만 병합."""
    from themek.ontology.core.resolve import normalize_alias
    persons = session.execute(
        select(Node).where(Node.kind == "person")
    ).scalars().all()
    merged = 0
    for p in persons:
        alias = session.get(ConceptAlias, normalize_alias(p.label))
        if alias is None or alias.node_id == p.id:
            continue
        if not alias.node_id.startswith("person:") \
                or session.get(Node, alias.node_id) is None:
            continue
        _repoint_subject_edges(session, old_subject_id=p.id,
                               new_subject_id=alias.node_id)
        session.delete(p)
        merged += 1
    session.flush()
    return {"merged": merged}
