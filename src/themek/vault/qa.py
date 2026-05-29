"""데이터 품질 검사 — VaultGraph를 받아 Issue 리스트를 반환하는 순수 함수."""
from __future__ import annotations

from dataclasses import dataclass

from themek.vault.model import VaultGraph

_SUM_LOW = 90.0
_SUM_HIGH = 110.0


@dataclass
class Issue:
    company: str   # 회사 name_ko, 전역 이슈는 ""
    kind: str
    severity: str  # error | warn | info
    detail: str


def detect_issues(graph: VaultGraph) -> list[Issue]:
    issues: list[Issue] = []

    for c in graph.companies:
        # geo_duplicate: 같은 지역명이 2회+ 노출
        by_region: dict[str, list[float]] = {}
        for r in c.regions:
            by_region.setdefault(r.name_ko, []).append(r.share_pct)
        for name, shares in by_region.items():
            if len(shares) > 1:
                pretty = ", ".join(f"{s:g}%" for s in shares)
                issues.append(Issue(c.name_ko, "geo_duplicate", "warn",
                                    f"지역 '{name}' {len(shares)}회 중복: {pretty}"))

        # revenue_sum_anomaly: 세그먼트 share 합이 100에서 크게 벗어남(중첩 가능)
        present = [s.share_pct for s in c.segments if s.share_pct is not None]
        if present:
            total = sum(present)
            if total > _SUM_HIGH or total < _SUM_LOW:
                issues.append(Issue(c.name_ko, "revenue_sum_anomaly", "warn",
                    f"세그먼트 매출비중 합 {total:.1f}% "
                    f"(세그먼트 {len(c.segments)}개; 중첩 구조 가능)"))

        # low_segment_count
        if len(c.segments) <= 1:
            issues.append(Issue(c.name_ko, "low_segment_count", "warn",
                                f"세그먼트 {len(c.segments)}개 (추출 빈약 가능)"))

        # segment_no_revenue
        for s in c.segments:
            if s.share_pct is None:
                issues.append(Issue(c.name_ko, "segment_no_revenue", "info",
                                    f"세그먼트 '{s.name_ko}' 매출비중 없음"))

        # missing_*
        if not c.regions:
            issues.append(Issue(c.name_ko, "missing_geo", "info", "지역 노출 0건"))
        if not c.customers:
            issues.append(Issue(c.name_ko, "missing_customer", "info", "고객사 0건"))

    # 전역: 미연결 고객 요약
    unresolved = [n for n in graph.customers if not n.resolved]
    if unresolved:
        ent = sum(1 for n in unresolved if n.kind == "entity")
        desc = sum(1 for n in unresolved if n.kind == "descriptive")
        issues.append(Issue("", "unresolved_customer", "info",
            f"미연결 고객사 {len(unresolved)}건 (entity {ent}, descriptive {desc})"))

    return issues
