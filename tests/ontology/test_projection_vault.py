"""코어 → vault markdown 투영 통합 + 멱등 + 재무 시계열 테스트."""
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.core.models import FinancialFact
from themek.ontology.projection.vault import build_vault, _render_qa_report
from themek.ontology.validate import Issue, check_integrity


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


# ---------------------------------------------------------------------------
# C9 — _qa-report.md emit
# ---------------------------------------------------------------------------

def test_qa_report_empty():
    out = _render_qa_report([])
    assert 'type: "qa-report"' in out
    assert "무결성 이슈 없음" in out


def test_qa_report_mixed_severity():
    issues = [
        Issue("duplicate_edge", "error", "a -X-> b @2023 x2", "company:a"),
        Issue("orphan_fact", "warn", "fact c not in nodes", "company:c"),
        Issue("negative_or_zero_equity", "info", "company:d 2023FY equity<=0",
              "company:d"),
    ]
    out = _render_qa_report(issues)
    # 카운트 문자열
    assert "error: 1" in out
    assert "warn: 1" in out
    assert "info: 1" in out
    # 그룹 헤더 순서: error < warn < info
    assert out.index("## error") < out.index("## warn")
    assert out.index("## warn") < out.index("## info")
    # 각 그룹 표 헤더 정확히 1회씩 (총 3회)
    assert out.count("| code | subject | message |") == 3


def test_build_vault_emits_qa_report(tmp_path, ontology_session):
    s = ontology_session
    _seed(s)
    stats = build_vault(s, tmp_path)
    assert (tmp_path / "_qa-report.md").exists() is True
    assert "issues" in stats
    assert stats["issues"] == len(check_integrity(s))


# ---------------------------------------------------------------------------
# C12 — 신규 metric(EPS·현금흐름·발행주식수) 렌더
# ---------------------------------------------------------------------------

def test_render_cashflow_and_eps():
    import re
    from themek.ontology.projection.vault import _render_financials
    fin = {
        ("2024", "FY"): {
            "revenue": 3007700000000.0,
            "operating_income": 326700000000.0,
            "cf_operating": 1000000000000.0,
            "cf_investing": -500000000000.0,
            "cf_financing": -200000000000.0,
            "eps": 5000.0,
            "shares_outstanding": 5969782550.0,
        }
    }
    out = "\n".join(_render_financials(fin))
    # gate2: 현금흐름 헤더 1회 + 세 라벨 각 1행 + 억 포맷
    assert out.count("## 현금흐름") == 1
    assert "영업활동현금흐름" in out
    assert "투자활동현금흐름" in out
    assert "재무활동현금흐름" in out
    assert "억" in out
    # gate3: eps — 원/주 라벨 + 천단위+원
    assert "원/주" in out
    assert re.search(r"[\d,]+원", out)
    # gate4: shares — 주 단위 + 천단위
    assert re.search(r"[\d,]+주", out)
    # gate5: 단위 격리 — ## 재무 블록에 eps/shares/원/주 미포함
    fin_block = out.split("## 재무", 1)[1].split("##", 1)[0]
    assert "원/주" not in fin_block
    assert "eps" not in fin_block
    assert "shares" not in fin_block
    # gate7: 인라인 필드
    assert re.search(r"eps_\d{4}(Q1|H1|Q3|FY)::", out)


def test_metric_omitted_when_absent():
    from themek.ontology.projection.vault import _render_financials
    fin = {("2024", "FY"): {"revenue": 3007700000000.0,
                            "operating_income": 326700000000.0}}
    out = "\n".join(_render_financials(fin))
    # gate6: 소표 헤더 부재
    assert "## 현금흐름" not in out
    assert "원/주" not in out
    assert "## 발행주식수" not in out
    # 인라인에 eps/cf/shares 부재
    assert "eps_" not in out
    assert "cf_operating_" not in out
    assert "shares_outstanding_" not in out


# ---------------------------------------------------------------------------
# C10 — 회사 frontmatter 보강
# ---------------------------------------------------------------------------

def _fm(tmp_path, note_name):
    return (tmp_path / "companies" / f"{note_name}.md").read_text(
        encoding="utf-8").split("---")[1]


def test_frontmatter_full(tmp_path, ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_node(s, "stock:005930", "stock", "삼성전자",
                {"ticker": "005930", "market": "KOSPI"})
    upsert_node(s, "sector:G2520", "sector", "반도체")
    upsert_node(s, "segment:메모리", "segment", "메모리")
    upsert_node(s, "customer:apple", "customer", "Apple")
    upsert_edge(s, subject_id="company:00126380", predicate="ISSUES_STOCK",
                object_id="stock:005930", period=None, qualifier={},
                source_type="manual", source_ref=None, method="manual",
                confidence=1.0)
    upsert_edge(s, subject_id="company:00126380", predicate="IN_SECTOR",
                object_id="sector:G2520", period=None, qualifier={},
                source_type="manual", source_ref=None, method="manual",
                confidence=1.0)
    upsert_edge(s, subject_id="company:00126380", predicate="HAS_SEGMENT",
                object_id="segment:메모리", period="2023", qualifier={},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    upsert_edge(s, subject_id="company:00126380", predicate="SELLS_TO",
                object_id="customer:apple", period="2023", qualifier={},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    for yr in ("2022", "2023"):
        s.add(FinancialFact(company_id="company:00126380", bsns_year=yr,
                            fiscal_period="FY", fs_div="CFS", metric_key="revenue",
                            amount=1000.0, currency="KRW",
                            source_type="dart_api", method="api", confidence=1.0))
    s.commit()
    build_vault(s, tmp_path)
    fm = _fm(tmp_path, "삼성전자")
    for k in ("ticker", "market", "sector", "periods", "report_count",
              "segment_count", "customer_count", "issue_count"):
        assert f"{k}:" in fm, f"missing key {k}"
    assert 'ticker: "005930"' in fm
    assert 'market: "KOSPI"' in fm
    assert 'sector: "반도체"' in fm
    assert "periods: [2022FY, 2023FY]" in fm
    assert "report_count: 2" in fm
    assert "segment_count: 1" in fm
    assert "customer_count: 1" in fm


def test_frontmatter_empty_company_defaults(tmp_path, ontology_session):
    s = ontology_session
    upsert_node(s, "company:empty", "company", "빈회사", {"dart_code": "empty"})
    s.commit()
    build_vault(s, tmp_path)
    fm = _fm(tmp_path, "빈회사")
    assert 'ticker: ""' in fm
    assert 'market: ""' in fm
    assert "periods: []" in fm
    assert "report_count: 0" in fm
    assert "segment_count: 0" in fm
    assert "customer_count: 0" in fm
    assert "issue_count: 0" in fm


def test_frontmatter_issue_count(tmp_path, ontology_session):
    s = ontology_session
    # 회사 A: interim BS(assets Q1) == FY → interim_bs_equals_fy 이슈(subject==A)
    upsert_node(s, "company:A", "company", "에이회사", {"dart_code": "A"})
    upsert_node(s, "company:B", "company", "비회사", {"dart_code": "B"})
    for fp in ("FY", "Q1"):
        s.add(FinancialFact(company_id="company:A", bsns_year="2024",
                            fiscal_period=fp, fs_div="CFS", metric_key="assets",
                            amount=1000.0, currency="KRW",
                            source_type="dart_api", method="api", confidence=1.0))
    s.commit()
    issues = check_integrity(s)
    a_issues = [i for i in issues if i.subject == "company:A"]
    assert len(a_issues) >= 1
    build_vault(s, tmp_path)
    fm_a = _fm(tmp_path, "에이회사")
    fm_b = _fm(tmp_path, "비회사")
    assert f"issue_count: {len(a_issues)}" in fm_a
    assert "issue_count: 0" in fm_b


def test_frontmatter_yaml_escape():
    from themek.ontology.projection.vault import _yaml_str
    r = _yaml_str('a"b')
    inner = r[1:-1]
    # escape된 \" 제거 후 raw " 가 남지 않아야 함
    assert '"' not in inner.replace('\\"', '')
