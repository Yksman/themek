"""코어 노드/엣지 시드 단위 테스트."""
from themek.ontology.core.models import Node, Edge
from themek.ontology.ingest.seeds import seed_core


def test_seed_core_creates_sector_region_company_stock_nodes(ontology_session):
    s = ontology_session
    seed_core(s)
    s.commit()
    assert s.get(Node, "sector:G2520").label == "반도체"
    assert s.get(Node, "region:US") is not None
    assert s.get(Node, "company:00126380").label == "삼성전자"
    assert s.get(Node, "stock:005930").attrs["market"] == "KOSPI"
    # IN_SECTOR / ISSUES_STOCK 엣지
    assert s.query(Edge).filter_by(predicate="IN_SECTOR",
                                   subject_id="company:00126380",
                                   object_id="sector:G2520").count() == 1
    assert s.query(Edge).filter_by(predicate="ISSUES_STOCK",
                                   subject_id="company:00126380",
                                   object_id="stock:005930").count() == 1


def test_seed_core_idempotent(ontology_session):
    s = ontology_session
    seed_core(s); s.commit()
    seed_core(s); s.commit()
    assert s.query(Node).filter_by(kind="company").count() == 3
    assert s.query(Edge).filter_by(predicate="IN_SECTOR").count() == 3
