"""competency 스크리닝 함수 단위 테스트 (예시질의 end-to-end 포함)."""
from themek.ontology.core.models import FinancialFact, ConceptAlias
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.query.screen import (
    companies_with_segment_concept, primary_segment,
    consecutive_positive, screen,
)


def _company(s, dart, name):
    upsert_node(s, f"company:{dart}", "company", name, {"dart_code": dart})


def _seg(s, name):
    upsert_node(s, f"segment:{__import__('themek.ontology.core.ids', fromlist=['slug']).slug(name)}",
                "segment", name)


def _has_seg(s, dart, seg_node, share, period="2024"):
    upsert_edge(s, subject_id=f"company:{dart}", predicate="HAS_SEGMENT",
                object_id=seg_node, period=period, qualifier={"share_pct": share},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)


def _oi(s, dart, year, fp, amount):
    s.add(FinancialFact(company_id=f"company:{dart}", bsns_year=year,
                        fiscal_period=fp, fs_div="CFS",
                        metric_key="operating_income", amount=amount,
                        currency="KRW", source_type="dart_api", method="api",
                        confidence=1.0))


def _seed_hbm(s):
    from themek.ontology.core.ids import segment_id
    mem = segment_id("메모리반도체")
    _seg(s, "메모리반도체")
    s.add(ConceptAlias(alias_norm="hbm", node_id=mem, source="manual", confidence=1.0))
    # A: 메모리 주력(60%) + 2024H1·Q3·FY 흑자 → 통과
    _company(s, "00000001", "흑자메모리")
    _has_seg(s, "00000001", mem, 60.0)
    for fp, amt in [("H1", 10), ("Q3", 20), ("FY", 30)]:
        _oi(s, "00000001", "2024", fp, amt)
    # B: 메모리 주력이지만 2024H1 적자 → 탈락
    _company(s, "00000002", "적자메모리")
    _has_seg(s, "00000002", mem, 70.0)
    for fp, amt in [("H1", -5), ("Q3", 5), ("FY", 10)]:
        _oi(s, "00000002", "2024", fp, amt)
    # C: 메모리 있지만 주력 아님(자동차 80%) → companies_with_segment엔 들지만 primary 아님
    _company(s, "00000003", "비주력메모리")
    auto = segment_id("자동차")
    _seg(s, "자동차")
    _has_seg(s, "00000003", mem, 20.0)
    _has_seg(s, "00000003", auto, 80.0)
    for fp, amt in [("H1", 10), ("Q3", 10), ("FY", 10)]:
        _oi(s, "00000003", "2024", fp, amt)
    s.commit()


def test_companies_with_segment_concept_resolves_alias(ontology_session):
    s = ontology_session
    _seed_hbm(s)
    ids = companies_with_segment_concept(s, "HBM")
    assert ids == {"company:00000001", "company:00000002", "company:00000003"}


def test_primary_segment_is_max_share(ontology_session):
    s = ontology_session
    _seed_hbm(s)
    from themek.ontology.core.ids import segment_id
    assert primary_segment(s, "company:00000001", "2024") == segment_id("메모리반도체")
    assert primary_segment(s, "company:00000003", "2024") == segment_id("자동차")


def test_consecutive_positive_since(ontology_session):
    s = ontology_session
    _seed_hbm(s)
    ids = consecutive_positive(s, "operating_income", "2024H1", "CFS")
    assert "company:00000001" in ids
    assert "company:00000002" not in ids   # 2024H1 적자


def test_screen_example_query_hbm_primary_positive_since_2024H1(ontology_session):
    s = ontology_session
    _seed_hbm(s)
    # 예시질의: HBM 주력 + 영업이익 2024H1부터 연속 흑자
    result = screen(s, segment="HBM", metric="operating_income",
                    positive_since="2024H1", fs_div="CFS")
    # A만 통과 (B 적자, C 메모리 비주력)
    assert result == {"company:00000001"}
