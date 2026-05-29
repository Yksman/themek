"""CLI `themek pipeline run` 통합 테스트 (export만 — 네트워크 불필요)."""
from typer.testing import CliRunner

from themek.cli import app
from themek.db.engine import make_engine, make_session_factory
from themek.ontology.core.resolve import upsert_node, upsert_edge

runner = CliRunner()


def _seed_committed():
    s = make_session_factory(make_engine())()
    upsert_node(s, "company:00126380", "company", "삼성전자", {"dart_code": "00126380"})
    upsert_node(s, "segment:메모리", "segment", "메모리")
    upsert_edge(s, subject_id="company:00126380", predicate="HAS_SEGMENT",
                object_id="segment:메모리", period="2024", qualifier={"share_pct": 50.0},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    s.commit(); s.close()


def test_pipeline_run_export_only(tmp_path, ontology_fresh_db):
    _seed_committed()
    result = runner.invoke(app, [
        "pipeline", "run", "--skip-sync", "--skip-structure", "--skip-financials",
        "--out-vault", str(tmp_path / "vault"), "--out-graph", str(tmp_path / "graph"),
    ])
    assert result.exit_code == 0, result.output
    assert "export" in result.output
    assert (tmp_path / "vault" / "companies" / "삼성전자.md").exists()
    assert (tmp_path / "graph" / "nodes.json").exists()
