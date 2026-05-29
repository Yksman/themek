"""vault.qa — 데이터 품질 검출 단위 테스트. VaultGraph dataclass를 직접 구성."""
from themek.vault.model import (
    VaultGraph, CompanyNode, CustomerNode, RegionLine, SegmentLine,
)
from themek.vault.qa import detect_issues


def _company(**kw):
    base = dict(dart_code="X", name_ko="회사", name_en=None, ticker=None,
                market=None, sector_name=None, periods=["2023"])
    base.update(kw)
    return CompanyNode(**base)


def test_detects_geo_duplicate():
    c = _company(regions=[RegionLine("US", "미주", 35.0),
                          RegionLine("US", "미주", 31.1)],
                 segments=[SegmentLine("a", 50.0), SegmentLine("b", 50.0)],
                 customers=[1])  # customers non-empty to avoid missing flag
    issues = detect_issues(VaultGraph(companies=[c]))
    kinds = [i.kind for i in issues if i.company == "회사"]
    assert "geo_duplicate" in kinds


def test_detects_revenue_sum_anomaly():
    c = _company(segments=[SegmentLine("DX", 60.4), SegmentLine("메모리", 42.5),
                           SegmentLine("DS", 32.6)],
                 regions=[RegionLine("US", "미주", 50.0)], customers=[1])
    issues = detect_issues(VaultGraph(companies=[c]))
    sums = [i for i in issues if i.kind == "revenue_sum_anomaly"]
    assert len(sums) == 1
    assert "135.5" in sums[0].detail


def test_detects_low_segment_count():
    c = _company(segments=[SegmentLine("only", 100.0)],
                 regions=[RegionLine("US", "미주", 100.0)], customers=[1])
    issues = detect_issues(VaultGraph(companies=[c]))
    assert any(i.kind == "low_segment_count" for i in issues)


def test_detects_missing_geo_and_customer():
    c = _company(segments=[SegmentLine("a", 50.0), SegmentLine("b", 50.0)],
                 regions=[], customers=[])
    kinds = {i.kind for i in detect_issues(VaultGraph(companies=[c]))}
    assert "missing_geo" in kinds
    assert "missing_customer" in kinds


def test_detects_segment_no_revenue():
    c = _company(segments=[SegmentLine("a", 50.0), SegmentLine("b", None)],
                 regions=[RegionLine("US", "미주", 50.0)], customers=[1])
    assert any(i.kind == "segment_no_revenue" for i in detect_issues(VaultGraph(companies=[c])))


def test_unresolved_customer_summary_counts_kinds():
    graph = VaultGraph(
        companies=[],
        customers=[
            CustomerNode(raw="Apple Inc.", kind="entity", resolved=False, named_by=["A"]),
            CustomerNode(raw="설명문 고객사", kind="descriptive", resolved=False, named_by=["A"]),
        ],
    )
    issues = detect_issues(graph)
    u = [i for i in issues if i.kind == "unresolved_customer"]
    assert len(u) == 1
    assert "entity 1" in u[0].detail and "descriptive 1" in u[0].detail


def test_clean_company_has_no_warn_issues():
    c = _company(segments=[SegmentLine("a", 50.0), SegmentLine("b", 50.0)],
                 regions=[RegionLine("US", "미주", 60.0), RegionLine("CN", "중국", 40.0)],
                 customers=[1])
    warns = [i for i in detect_issues(VaultGraph(companies=[c])) if i.severity == "warn"]
    assert warns == []
