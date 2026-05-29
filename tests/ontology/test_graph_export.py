"""graph export — nodes.json/edges.json + financial_facts measurement 엣지."""
import json

from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.core.models import FinancialFact
from themek.ontology.projection.graph_export import export_graph


def _seed(s):
    upsert_node(s, "company:00126380", "company", "삼성전자")
    upsert_node(s, "segment:메모리반도체", "segment", "메모리반도체")
    upsert_node(s, "metric:operating_income", "metric", "영업이익")
    upsert_node(s, "period:2024FY", "period", "2024 FY")
    upsert_edge(s, subject_id="company:00126380", predicate="HAS_SEGMENT",
                object_id="segment:메모리반도체", period="2023",
                qualifier={"share_pct": 42.5}, source_type="llm",
                source_ref="r1", method="llm", confidence=0.9)
    s.add(FinancialFact(company_id="company:00126380", bsns_year="2024",
                        fiscal_period="FY", fs_div="CFS",
                        metric_key="operating_income", amount=326700000000.0,
                        currency="KRW", source_type="dart_api", method="api",
                        confidence=1.0))
    s.commit()


def test_export_graph_writes_nodes_and_edges(tmp_path, ontology_session):
    s = ontology_session
    _seed(s)
    export_graph(s, tmp_path)
    nodes = json.loads((tmp_path / "nodes.json").read_text(encoding="utf-8"))
    edges = json.loads((tmp_path / "edges.json").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in nodes}
    assert "company:00126380" in node_ids and "metric:operating_income" in node_ids
    # HAS_SEGMENT 엣지 + financial measurement 엣지(REPORTS)
    preds = {e["predicate"] for e in edges}
    assert "HAS_SEGMENT" in preds and "REPORTS" in preds
    # 깨진 참조 없음: 모든 엣지 endpoint가 노드에 존재
    for e in edges:
        assert e["subject_id"] in node_ids
        assert e["object_id"] in node_ids


def test_financial_measurement_edge_carries_amount(tmp_path, ontology_session):
    s = ontology_session
    _seed(s)
    export_graph(s, tmp_path)
    edges = json.loads((tmp_path / "edges.json").read_text(encoding="utf-8"))
    rep = [e for e in edges if e["predicate"] == "REPORTS"][0]
    assert rep["object_id"] == "metric:operating_income"
    assert rep["qualifier"]["amount"] == 326700000000.0
    assert rep["qualifier"]["fs_div"] == "CFS"
    assert rep["period"] == "2024FY"
