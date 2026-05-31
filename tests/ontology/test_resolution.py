"""엔티티 해소: 별칭 시드 + customer/segment 배치 패스."""
import json
from pathlib import Path

from sqlalchemy import select

from themek.db.corp_models import Corporation
from themek.ontology.core.ids import company_id, customer_id, segment_id
from themek.ontology.core.models import Node, Edge, ConceptAlias
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.ingest.seeds import seed_aliases


def _aliases(tmp_path, data):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_seed_aliases_creates_concept_aliases(ontology_session, tmp_path):
    s = ontology_session
    upsert_node(s, company_id("00126380"), "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_node(s, segment_id("메모리반도체"), "segment", "메모리반도체")
    s.commit()
    path = _aliases(tmp_path, {
        "customers": [{"corp": "00126380", "variants": ["삼성전자(주)"]}],
        "segments": [{"canonical": "메모리반도체", "variants": ["메모리"]}],
    })
    n = seed_aliases(s, path); s.commit()
    assert n == 2
    # customer 변형 → company 노드
    from themek.ontology.core.resolve import normalize_corp_name, normalize_alias
    a1 = s.get(ConceptAlias, normalize_corp_name("삼성전자(주)"))
    assert a1.node_id == company_id("00126380")
    # segment 동의어 → canonical segment 노드
    a2 = s.get(ConceptAlias, normalize_alias("메모리"))
    assert a2.node_id == segment_id("메모리반도체")
