"""CLI: query screen 통합 (시드 후 실행)."""
from typer.testing import CliRunner

from themek.cli import app
from themek.db.engine import make_engine, make_session_factory
from themek.ontology.core.models import FinancialFact, ConceptAlias
from themek.ontology.core.ids import segment_id
from themek.ontology.core.resolve import upsert_node, upsert_edge

runner = CliRunner()


def _seed_committed():
    s = make_session_factory(make_engine())()
    mem = segment_id("메모리반도체")
    upsert_node(s, mem, "segment", "메모리반도체")
    s.add(ConceptAlias(alias_norm="hbm", node_id=mem, source="manual", confidence=1.0))
    upsert_node(s, "company:00000001", "company", "흑자메모리", {"dart_code": "00000001"})
    upsert_edge(s, subject_id="company:00000001", predicate="HAS_SEGMENT",
                object_id=mem, period="2024", qualifier={"share_pct": 60.0},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    for fp, amt in [("H1", 10), ("Q3", 20), ("FY", 30)]:
        s.add(FinancialFact(company_id="company:00000001", bsns_year="2024",
                            fiscal_period=fp, fs_div="CFS",
                            metric_key="operating_income", amount=amt,
                            currency="KRW", source_type="dart_api", method="api",
                            confidence=1.0))
    s.commit(); s.close()


def test_query_screen_cli(ontology_fresh_db):
    _seed_committed()
    result = runner.invoke(app, ["query", "screen", "--segment", "HBM",
                                 "--metric", "operating_income",
                                 "--positive-since", "2024H1"])
    assert result.exit_code == 0, result.output
    assert "흑자메모리" in result.output or "company:00000001" in result.output
