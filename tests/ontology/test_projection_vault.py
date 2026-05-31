"""코어 → vault markdown 투영 통합 + 멱등 + 재무 시계열 테스트."""
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.core.models import FinancialFact
from themek.ontology.projection.vault import build_vault


def _seed(s):
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380", "ticker": "005930", "market": "KOSPI"})
    upsert_node(s, "sector:G2520", "sector", "반도체")
    upsert_node(s, "segment:메모리반도체", "segment", "메모리반도체")
    upsert_node(s, "region:US", "region", "미주")
    upsert_node(s, "metric:operating_income", "metric", "영업이익")
    upsert_node(s, "period:2024FY", "period", "2024 FY")
    upsert_edge(s, subject_id="company:00126380", predicate="IN_SECTOR",
                object_id="sector:G2520", period=None, qualifier={},
                source_type="manual", source_ref=None, method="manual", confidence=1.0)
    upsert_edge(s, subject_id="company:00126380", predicate="HAS_SEGMENT",
                object_id="segment:메모리반도체", period="2023",
                qualifier={"share_pct": 42.5}, source_type="llm",
                source_ref="r1", method="llm", confidence=0.9)
    for metric, amount in [("revenue", 3007700000000.0),
                           ("operating_income", 326700000000.0),
                           ("equity", 4024000000000.0),
                           ("liabilities", 1121000000000.0)]:
        s.add(FinancialFact(company_id="company:00126380", bsns_year="2024",
                            fiscal_period="FY", fs_div="CFS", metric_key=metric,
                            amount=amount, currency="KRW", source_type="dart_api",
                            method="api", confidence=1.0))
    s.commit()


def test_build_vault_creates_company_note_with_financials(tmp_path, ontology_session):
    s = ontology_session
    _seed(s)
    stats = build_vault(s, tmp_path)
    assert stats["companies"] == 1
    note = (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8")
    assert "## 재무" in note
    assert "영업이익" in note
    # 파생비율: 영업이익률 = 326.7/3007.7 ≈ 10.9%
    assert "영업이익률" in note
    # Dataview 인라인 필드
    assert "operating_income_2024FY::" in note
    # 세그먼트 wikilink
    assert "[[메모리반도체]]" in note


def test_build_vault_idempotent(tmp_path, ontology_session):
    s = ontology_session
    _seed(s)
    build_vault(s, tmp_path)
    first = (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8")
    build_vault(s, tmp_path)
    assert (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8") == first


def test_build_vault_emits_concept_notes_and_no_dangling_links(tmp_path, ontology_session):
    import re, pathlib
    s = ontology_session
    _seed(s)
    # 긴 라벨 고객(파일명 truncate 경로) + 일반 고객
    long_name = "세계 유수의 Mobile 및 Computing 관련 전자 업체 (DRAM 수요처) 외 다수 글로벌 거래선"
    upsert_node(s, "customer:apple", "customer", "Apple")
    upsert_node(s, "customer:long", "customer", long_name)
    for oid in ("customer:apple", "customer:long"):
        upsert_edge(s, subject_id="company:00126380", predicate="SELLS_TO",
                    object_id=oid, period="2023", qualifier={}, source_type="llm",
                    source_ref="r1", method="llm", confidence=0.9)
    s.commit()
    build_vault(s, tmp_path)
    # 개념노트 생성
    assert (tmp_path / "segments" / "메모리반도체.md").exists()
    assert (tmp_path / "sectors" / "반도체.md").exists()
    assert (tmp_path / "regions" / "미주.md").exists()
    assert (tmp_path / "customers" / "Apple.md").exists()
    assert (tmp_path / "_index.md").exists()
    # 백링크: 세그먼트 노트가 회사를 역참조
    assert "삼성전자" in (tmp_path / "segments" / "메모리반도체.md").read_text(encoding="utf-8")
    # dangling 링크 0
    files = {p.stem for p in tmp_path.rglob("*.md")}
    links = set()
    for p in tmp_path.rglob("*.md"):
        for m in re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", p.read_text(encoding="utf-8")):
            links.add(m.strip())
    missing = sorted(l for l in links if l not in files and not l.startswith("_"))
    assert missing == [], f"dangling links: {missing}"
