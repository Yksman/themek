"""link_stocks — 관계형 stocks를 ISSUES_STOCK 엣지로 투영."""
from sqlalchemy import select

from themek.db.corp_models import Corporation, Stock
from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.linkage import link_stocks


def test_link_stocks_projects_and_is_idempotent(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    s.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
    s.add(Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
                share_class="common", issued_by_id="00126380"))
    s.commit()

    n = link_stocks(s); s.commit()
    assert n == 1
    edge = s.execute(
        select(Edge).where(Edge.predicate == "ISSUES_STOCK")).scalar_one()
    assert edge.object_id == "stock:005930"
    assert edge.source_type == "dart_api"
    node = s.get(Node, "stock:005930")
    assert node.attrs["market"] == "KOSPI"

    link_stocks(s); s.commit()   # 멱등 — 중복 엣지 없음
    assert s.query(Edge).filter_by(predicate="ISSUES_STOCK").count() == 1


def test_link_stocks_skips_company_without_dart_code(ontology_session):
    s = ontology_session
    upsert_node(s, "company:x", "company", "노코드", {})  # dart_code 없음
    s.commit()
    assert link_stocks(s) == 0
