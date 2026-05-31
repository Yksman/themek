"""check_integrity — 오염 시그니처 탐지 단위 테스트."""
from themek.ontology.core.models import Node, Edge, FinancialFact
from themek.ontology.validate import check_integrity


def _fact(s, *, cid, yr, fp, mk, amt, fsd="CFS"):
    s.add(FinancialFact(company_id=cid, bsns_year=yr, fiscal_period=fp,
                        fs_div=fsd, metric_key=mk, amount=amt, currency="KRW",
                        source_type="dart_api", method="api", confidence=1.0))


def test_clean_data_has_no_errors(ontology_session):
    s = ontology_session
    s.add(Node(id="company:1", kind="company", label="A")); s.commit()
    _fact(s, cid="company:1", yr="2024", fp="FY", mk="assets", amt=100)
    _fact(s, cid="company:1", yr="2024", fp="Q1", mk="assets", amt=95)  # 다름 → OK
    s.commit()
    issues = check_integrity(s)
    assert [i for i in issues if i.severity == "error"] == []


def test_interim_bs_equals_fy_flagged(ontology_session):
    s = ontology_session
    s.add(Node(id="company:1", kind="company", label="A")); s.commit()
    _fact(s, cid="company:1", yr="2024", fp="FY", mk="assets", amt=100)
    _fact(s, cid="company:1", yr="2024", fp="H1", mk="assets", amt=100)  # FY와 동일
    s.commit()
    codes = [i.code for i in check_integrity(s)]
    assert "interim_bs_equals_fy" in codes


def test_duplicate_edge_flagged(ontology_session):
    s = ontology_session
    s.add(Node(id="company:1", kind="company", label="A"))
    s.add(Node(id="segment:x", kind="segment", label="x")); s.commit()
    # ORM UNIQUE 추가 전이므로 직접 2건 insert 가능(Task 3에서 차단됨).
    # 여기선 중복 탐지 로직만 검증하기 위해 동일 키 2건을 강제 구성.
    for _ in range(2):
        s.add(Edge(subject_id="company:1", predicate="HAS_SEGMENT",
                   object_id="segment:x", period="2024", qualifier={},
                   source_type="llm", method="llm", confidence=0.9))
    try:
        s.commit()
    except Exception:
        s.rollback()
        return  # UNIQUE 제약이 이미 있으면(Task 3 이후) 중복 insert 자체가 막힘 — 정상
    codes = [i.code for i in check_integrity(s)]
    assert "duplicate_edge" in codes
