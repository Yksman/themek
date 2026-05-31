"""link_sectors — DART induty_code → IN_SECTOR 엣지 + sector 노드."""
from sqlalchemy import select

from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.classification import link_sectors


class _FakeClient:
    def __init__(self, profiles):
        self.profiles = profiles  # {corp_code: {"induty_code":..,"induty":..}}

    def fetch_company_profile(self, *, corp_code):
        return self.profiles.get(corp_code, {})


def test_link_sectors_creates_sector_and_edge(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    s.commit()
    client = _FakeClient({"00126380": {"induty_code": "264",
                                       "induty": "반도체 제조업"}})
    n = link_sectors(s, client); s.commit()
    assert n == 1
    assert s.get(Node, "sector:264").label == "반도체 제조업"
    edge = s.execute(
        select(Edge).where(Edge.predicate == "IN_SECTOR")).scalar_one()
    assert edge.object_id == "sector:264"
    assert edge.source_type == "dart_api"

    link_sectors(s, client); s.commit()   # 멱등
    assert s.query(Edge).filter_by(predicate="IN_SECTOR").count() == 1


def test_link_sectors_skips_when_no_induty(ontology_session):
    s = ontology_session
    upsert_node(s, "company:1", "company", "A", {"dart_code": "1"})
    s.commit()
    assert link_sectors(s, _FakeClient({"1": {}})) == 0
