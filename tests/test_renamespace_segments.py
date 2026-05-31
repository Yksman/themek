"""scripts/renamespace_segments.py 백필 단위 테스트 (분리·멱등·정합·alias 보존)."""
import importlib.util
import pathlib

from themek.ontology.core.models import ConceptAlias, Edge, Node
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.validate import check_integrity

_SCRIPT = (pathlib.Path(__file__).parent.parent
           / "scripts" / "renamespace_segments.py")
_spec = importlib.util.spec_from_file_location("renamespace_segments", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
renamespace_segments = _mod.renamespace_segments


def _setup_shared_global(s):
    upsert_node(s, "company:dartA", "company", "A회사", {"dart_code": "dartA"})
    upsert_node(s, "company:dartB", "company", "B회사", {"dart_code": "dartB"})
    upsert_node(s, "segment:기타", "segment", "기타")
    for comp in ("company:dartA", "company:dartB"):
        upsert_edge(s, subject_id=comp, predicate="HAS_SEGMENT",
                    object_id="segment:기타", period="2023", qualifier={},
                    source_type="llm", source_ref="r", method="llm",
                    confidence=0.9)
    s.commit()


def test_renamespace_splits(ontology_session):
    s = ontology_session
    _setup_shared_global(s)
    renamespace_segments(s)
    s.commit()
    # 회사별 별도 노드 생성
    assert s.get(Node, "segment:dartA:기타") is not None
    assert s.get(Node, "segment:dartB:기타") is not None
    # 각 회사 엣지가 자기 회사키 노드를 가리킴
    ea = s.query(Edge).filter_by(subject_id="company:dartA",
                                 predicate="HAS_SEGMENT").one()
    eb = s.query(Edge).filter_by(subject_id="company:dartB",
                                 predicate="HAS_SEGMENT").one()
    assert ea.object_id == "segment:dartA:기타"
    assert eb.object_id == "segment:dartB:기타"
    # 참조 0 된 전역 노드 제거
    assert s.get(Node, "segment:기타") is None


def test_renamespace_idempotent(ontology_session):
    s = ontology_session
    _setup_shared_global(s)
    renamespace_segments(s)
    s.commit()
    n1 = s.query(Node).count()
    e1 = s.query(Edge).count()
    summary2 = renamespace_segments(s)
    s.commit()
    assert summary2["repointed"] == 0
    assert s.query(Node).count() == n1
    assert s.query(Edge).count() == e1


def test_renamespace_integrity_clean(ontology_session):
    s = ontology_session
    _setup_shared_global(s)
    renamespace_segments(s)
    s.commit()
    errors = [i for i in check_integrity(s) if i.severity == "error"]
    assert errors == []


def test_renamespace_preserves_alias_target(ontology_session):
    s = ontology_session
    upsert_node(s, "company:dartA", "company", "A회사", {"dart_code": "dartA"})
    # alias canonical 타깃인 전역 노드 — 의도된 교차회사 병합용, 보존돼야 함
    upsert_node(s, "segment:메모리", "segment", "메모리")
    s.add(ConceptAlias(alias_norm="메모리", node_id="segment:메모리",
                       source="manual", confidence=1.0))
    upsert_edge(s, subject_id="company:dartA", predicate="HAS_SEGMENT",
                object_id="segment:메모리", period="2023", qualifier={},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    s.commit()
    renamespace_segments(s)
    s.commit()
    # 전역 alias 타깃 노드·엣지 보존
    assert s.get(Node, "segment:메모리") is not None
    e = s.query(Edge).filter_by(subject_id="company:dartA",
                                predicate="HAS_SEGMENT").one()
    assert e.object_id == "segment:메모리"
