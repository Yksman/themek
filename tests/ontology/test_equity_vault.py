"""지분구조(OWNS_STAKE_IN) → 회사 노트 섹션 + people/ 노트 백링크 투영 테스트."""
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.projection.vault import build_vault


def _setup(session):
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_node(session, "person:이재용", "person", "이재용")
    upsert_node(session, "company:ext:삼성디스플레이-주", "company",
                "삼성디스플레이(주)", {"external": True})
    upsert_edge(session, subject_id="person:이재용", predicate="OWNS_STAKE_IN",
                object_id="company:00126380", period="2023",
                qualifier={"stake_pct": 1.63, "is_largest": True,
                           "relation": "최대주주 본인"},
                source_type="dart_api", source_ref=None, method="api",
                confidence=1.0)
    upsert_edge(session, subject_id="company:00126380",
                predicate="OWNS_STAKE_IN", object_id="company:ext:삼성디스플레이-주",
                period="2023",
                qualifier={"stake_pct": 84.78, "affiliation_type": "자회사"},
                source_type="dart_api", source_ref=None, method="api",
                confidence=1.0)


def test_company_note_has_ownership_section(ontology_session, tmp_path):
    session = ontology_session
    _setup(session)
    session.flush()
    build_vault(session, tmp_path)
    note = (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8")
    assert "## 지분구조" in note
    assert "[[이재용]]" in note
    assert "1.63%" in note
    assert "[[삼성디스플레이(주)]]" in note or "삼성디스플레이" in note
    assert "84.78%" in note


def test_person_note_created_with_backlink(ontology_session, tmp_path):
    session = ontology_session
    _setup(session)
    session.flush()
    build_vault(session, tmp_path)
    pnote = tmp_path / "people" / "이재용.md"
    assert pnote.exists()
    body = pnote.read_text(encoding="utf-8")
    assert "[[삼성전자]]" in body
