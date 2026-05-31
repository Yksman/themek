"""link_sectors — DART induty_code → IN_SECTOR 엣지 + sector 노드 (KSIC 명칭 매핑)."""
import json

from sqlalchemy import select

from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.ingest.classification import link_sectors


class _FakeClient:
    def __init__(self, profiles):
        self.profiles = profiles  # {corp_code: {"induty_code": ..}}

    def fetch_company_profile(self, *, corp_code):
        return self.profiles.get(corp_code, {})


def _ksic(tmp_path, mapping):
    p = tmp_path / "ksic.json"
    p.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return p


def test_link_sectors_uses_ksic_name_and_dedups(ontology_session, tmp_path):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    # 기존 수동 seed IN_SECTOR (이중분류 모사)
    upsert_node(s, "sector:G2520", "sector", "반도체")
    upsert_edge(s, subject_id="company:00126380", predicate="IN_SECTOR",
                object_id="sector:G2520", period=None, qualifier={},
                source_type="manual", source_ref=None, method="manual",
                confidence=1.0)
    s.commit()
    ksic = _ksic(tmp_path, {"264": "통신 및 방송 장비 제조업"})
    client = _FakeClient({"00126380": {"induty_code": "264"}})

    n = link_sectors(s, client, ksic_path=ksic); s.commit()
    assert n == 1
    node = s.get(Node, "sector:264")
    assert node.label == "통신 및 방송 장비 제조업"     # KSIC 명칭
    assert node.attrs["induty_code"] == "264"
    # 이중분류 정리: 이 회사 IN_SECTOR는 1개(264)만
    edges = s.execute(select(Edge).where(
        Edge.subject_id == "company:00126380",
        Edge.predicate == "IN_SECTOR")).scalars().all()
    assert len(edges) == 1 and edges[0].object_id == "sector:264"

    link_sectors(s, client, ksic_path=ksic); s.commit()   # 멱등
    assert s.query(Edge).filter_by(predicate="IN_SECTOR").count() == 1


def test_link_sectors_code_fallback_when_unmapped(ontology_session, tmp_path):
    s = ontology_session
    upsert_node(s, "company:1", "company", "A", {"dart_code": "1"})
    s.commit()
    ksic = _ksic(tmp_path, {})   # 빈 매핑
    client = _FakeClient({"1": {"induty_code": "99999"}})
    link_sectors(s, client, ksic_path=ksic); s.commit()
    assert s.get(Node, "sector:99999").label == "KSIC 99999"


def test_link_sectors_skips_when_no_induty(ontology_session, tmp_path):
    s = ontology_session
    upsert_node(s, "company:1", "company", "A", {"dart_code": "1"})
    s.commit()
    ksic = _ksic(tmp_path, {})
    assert link_sectors(s, _FakeClient({"1": {}}), ksic_path=ksic) == 0
