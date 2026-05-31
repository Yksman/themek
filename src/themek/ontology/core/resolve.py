"""concept resolver + 멱등 upsert 헬퍼."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Node, Edge, ConceptAlias

_WS = re.compile(r"\s+")


def normalize_alias(s: str) -> str:
    """별칭/라벨 비교용 정규화: trim + 공백 단일화 + 소문자."""
    return _WS.sub(" ", s.strip()).lower()


_CORP_AFFIX = re.compile(
    r"\(주\)|㈜|주식회사|\bco\.?,?\s*ltd\.?|\bltd\.?|\binc\.?|\bcorp\.?|"
    r"\bcorporation\b|\bcompany\b",
    re.IGNORECASE,
)


def normalize_corp_name(s: str) -> str:
    """법인명 매칭용 정규화: 법인 형태 접두/접미 제거 + 소문자 + 공백 단일화."""
    out = _CORP_AFFIX.sub(" ", s)
    out = re.sub(r"[,.]", " ", out)
    out = _WS.sub(" ", out).strip().lower()
    return out


def upsert_node(session: Session, id: str, kind: str, label: str,
                attrs: dict | None = None) -> Node:
    """id 기준 멱등 upsert. 존재하면 label/attrs 갱신."""
    node = session.get(Node, id)
    if node is None:
        node = Node(id=id, kind=kind, label=label, attrs=attrs or {})
        session.add(node)
    else:
        node.label = label
        if attrs is not None:
            node.attrs = attrs
    return node


def upsert_edge(session: Session, *, subject_id: str, predicate: str,
                object_id: str, period: str | None, qualifier: dict,
                source_type: str, source_ref: str | None, method: str,
                confidence: float) -> Edge:
    """(subject, predicate, object, period) 기준 멱등 upsert."""
    existing = session.execute(
        select(Edge).where(
            Edge.subject_id == subject_id, Edge.predicate == predicate,
            Edge.object_id == object_id,
            Edge.period.is_(period) if period is None else Edge.period == period,
        )
    ).scalars().first()
    if existing is None:
        edge = Edge(subject_id=subject_id, predicate=predicate,
                    object_id=object_id, period=period, qualifier=qualifier,
                    source_type=source_type, source_ref=source_ref,
                    method=method, confidence=confidence)
        session.add(edge)
        return edge
    existing.qualifier = qualifier
    existing.source_type = source_type
    existing.source_ref = source_ref
    existing.method = method
    existing.confidence = confidence
    return existing


def resolve_concept(session: Session, text: str) -> str | None:
    """text를 concept 노드 id로 해소: 별칭 → 정확 라벨 순. 미해소 None."""
    norm = normalize_alias(text)
    alias = session.get(ConceptAlias, norm)
    if alias is not None:
        return alias.node_id
    node = session.execute(
        select(Node).where(func_lower_label() == norm)
    ).scalars().first()
    return node.id if node is not None else None


def func_lower_label():
    from sqlalchemy import func
    return func.lower(Node.label)
