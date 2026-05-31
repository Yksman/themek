"""themek equity ingest CLI smoke (DartClient monkeypatched)."""
from typer.testing import CliRunner

from themek.cli import app
from themek.db.engine import make_session_factory
from themek.ontology.core.models import Edge, Node
from themek.ontology.core.resolve import upsert_node

runner = CliRunner()


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    def fetch_largest_shareholders(self, *, corp_code, bsns_year, reprt_code):
        return [{"nm": "오너", "relate": "본인", "trmend_posesn_stock_co": "10",
                 "trmend_posesn_stock_qota_rt": "5.0"}]

    def fetch_other_corp_investments(self, *, corp_code, bsns_year, reprt_code):
        return []


def test_equity_ingest_cmd(monkeypatch, engine, fresh_db):
    import themek.cli as cli
    monkeypatch.setattr(cli, "DartClient", _FakeClient)

    # 보고회사 노드를 시드 (OWNS_STAKE_IN의 object_id 대상)
    with make_session_factory(engine)() as s:
        upsert_node(s, "company:00126380", "company", "삼성전자",
                    {"dart_code": "00126380"})
        s.commit()

    res = runner.invoke(app, ["equity", "ingest", "--corp", "00126380",
                              "--years", "2023"])
    assert res.exit_code == 0, res.output
    assert "ingested" in res.output

    with make_session_factory(engine)() as s:
        assert s.query(Edge).filter_by(predicate="OWNS_STAKE_IN").count() >= 1
        assert s.get(Node, "company:00126380") is not None
