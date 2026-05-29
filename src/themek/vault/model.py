"""DB → 내부 그래프 모델. 노드/엣지 dataclass + 정규화/분류 + build_graph."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.db.models import (
    Corporation, Stock, BusinessReport, BusinessSegment,
    RevenueComposition, CustomerRelation, GeographicExposure, Region,
)

_WS = re.compile(r"\s+")
_DESCRIPTIVE_TOKENS = (
    "수요처", "업체", "제조업체", "생산업체", "고객사", "비공개",
    "메이커", "디바이스", "수요", "거래처",
)
_DESCRIPTIVE_LEN = 20


def normalize_name(s: str) -> str:
    """dedupe 키용 정규화: trim + 공백 단일화 + 소문자."""
    return _WS.sub(" ", s.strip()).lower()


def classify_customer(raw: str) -> str:
    """buyer_raw를 'entity'(실회사 후보) | 'descriptive'(설명문)로 분류."""
    t = raw.strip()
    if len(t) > _DESCRIPTIVE_LEN:
        return "descriptive"
    if any(tok in t for tok in _DESCRIPTIVE_TOKENS):
        return "descriptive"
    if "," in t or "/" in t:
        return "descriptive"
    return "entity"


@dataclass
class SegmentLine:
    name_ko: str
    share_pct: float | None


@dataclass
class CustomerLine:
    raw: str
    tier: str
    revenue_share_pct: float | None
    resolved: bool


@dataclass
class RegionLine:
    code: str
    name_ko: str
    share_pct: float


@dataclass
class ReportLine:
    rcept_no: str
    period: str
    report_type: str
    url: str | None


@dataclass
class CompanyNode:
    dart_code: str
    name_ko: str
    name_en: str | None
    ticker: str | None
    market: str | None
    sector_name: str | None
    periods: list[str]
    reports: list[ReportLine] = field(default_factory=list)
    segments: list[SegmentLine] = field(default_factory=list)
    customers: list[CustomerLine] = field(default_factory=list)
    regions: list[RegionLine] = field(default_factory=list)


@dataclass
class SegmentNode:
    name_ko: str
    companies: list[str] = field(default_factory=list)


@dataclass
class CustomerNode:
    raw: str
    kind: str
    resolved: bool
    named_by: list[str] = field(default_factory=list)


@dataclass
class RegionNode:
    code: str
    name_ko: str
    companies: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class SectorNode:
    fics_code: str
    name_ko: str
    parent_name: str | None
    companies: list[str] = field(default_factory=list)


@dataclass
class VaultGraph:
    companies: list[CompanyNode] = field(default_factory=list)
    segments: list[SegmentNode] = field(default_factory=list)
    customers: list[CustomerNode] = field(default_factory=list)
    regions: list[RegionNode] = field(default_factory=list)
    sectors: list[SectorNode] = field(default_factory=list)


def _collapse_segments(rows) -> list[SegmentLine]:
    """(BusinessSegment, share_pct) 행들을 세그먼트당 1줄로. 같은 세그먼트 다중 share면 max."""
    best: dict[str, tuple[str, float | None]] = {}
    for seg, share in rows:
        share_f = float(share) if share is not None else None
        cur = best.get(seg.id)
        if cur is None:
            best[seg.id] = (seg.name_ko, share_f)
        else:
            name, cur_share = cur
            if share_f is not None and (cur_share is None or share_f > cur_share):
                best[seg.id] = (name, share_f)
    return [SegmentLine(name_ko=n, share_pct=sh) for (n, sh) in best.values()]


def build_graph(session: Session) -> VaultGraph:
    """현재 DB에서 '보고서가 적재된 회사'를 진입점으로 VaultGraph를 구성."""
    corp_ids = sorted(session.execute(
        select(BusinessReport.corporation_id).distinct()
    ).scalars().all())

    companies: list[CompanyNode] = []
    seg_map: dict[str, SegmentNode] = {}
    cust_map: dict[str, CustomerNode] = {}
    region_map: dict[str, RegionNode] = {}
    sector_map: dict[str, SectorNode] = {}

    for corp_id in corp_ids:
        corp = session.get(Corporation, corp_id)
        if corp is None:
            continue

        stock = session.execute(
            select(Stock).where(Stock.issued_by_id == corp_id)
            .order_by(Stock.share_class, Stock.ticker)
        ).scalars().first()

        reports = session.execute(
            select(BusinessReport).where(BusinessReport.corporation_id == corp_id)
            .order_by(BusinessReport.filing_date.desc())
        ).scalars().all()
        report_lines = [
            ReportLine(rcept_no=r.dart_rcept_no, period=r.period,
                       report_type=r.report_type, url=r.url)
            for r in reports
        ]
        periods = sorted({r.period for r in reports})

        seg_rows = session.execute(
            select(BusinessSegment, RevenueComposition.share_pct)
            .join(RevenueComposition,
                  RevenueComposition.subject_segment_id == BusinessSegment.id,
                  isouter=True)
            .where(BusinessSegment.corporation_id == corp_id)
        ).all()
        seg_lines = sorted(
            _collapse_segments(seg_rows),
            key=lambda sl: (sl.share_pct is None, -(sl.share_pct or 0.0), sl.name_ko),
        )

        cust_rows = session.execute(
            select(CustomerRelation).where(CustomerRelation.seller_id == corp_id)
            .order_by(CustomerRelation.id)
        ).scalars().all()
        cust_lines = [
            CustomerLine(
                raw=(c.buyer_raw or (c.buyer_corp.name_ko if c.buyer_corp else "?")),
                tier=c.tier,
                revenue_share_pct=(float(c.revenue_share_pct)
                                   if c.revenue_share_pct is not None else None),
                resolved=c.resolved,
            )
            for c in cust_rows
        ]

        geo_rows = session.execute(
            select(GeographicExposure, Region)
            .join(Region, Region.code == GeographicExposure.region_id)
            .where(GeographicExposure.subject_corp_id == corp_id)
            .order_by(GeographicExposure.share_pct.desc())
        ).all()
        region_lines = [
            RegionLine(code=g.region_id, name_ko=region.name_ko,
                       share_pct=float(g.share_pct))
            for g, region in geo_rows
        ]

        companies.append(CompanyNode(
            dart_code=corp.dart_code, name_ko=corp.name_ko, name_en=corp.name_en,
            ticker=(stock.ticker if stock else None),
            market=(stock.market if stock else None),
            sector_name=(corp.in_sector.name_ko if corp.in_sector else None),
            periods=periods, reports=report_lines,
            segments=seg_lines, customers=cust_lines, regions=region_lines,
        ))

        for sl in seg_lines:
            sn = seg_map.setdefault(normalize_name(sl.name_ko),
                                    SegmentNode(name_ko=sl.name_ko))
            if corp.name_ko not in sn.companies:
                sn.companies.append(corp.name_ko)
        for cl in cust_lines:
            cn = cust_map.setdefault(
                normalize_name(cl.raw),
                CustomerNode(raw=cl.raw, kind=classify_customer(cl.raw),
                             resolved=cl.resolved),
            )
            if corp.name_ko not in cn.named_by:
                cn.named_by.append(corp.name_ko)
        for rl in region_lines:
            rn = region_map.setdefault(rl.code,
                                       RegionNode(code=rl.code, name_ko=rl.name_ko))
            rn.companies.append((corp.name_ko, rl.share_pct))
        if corp.in_sector is not None:
            sec = corp.in_sector
            secn = sector_map.setdefault(
                sec.fics_code,
                SectorNode(fics_code=sec.fics_code, name_ko=sec.name_ko,
                           parent_name=(sec.parent_sector.name_ko
                                        if sec.parent_sector else None)),
            )
            if corp.name_ko not in secn.companies:
                secn.companies.append(corp.name_ko)

    return VaultGraph(
        companies=companies,
        segments=sorted(seg_map.values(), key=lambda n: n.name_ko),
        customers=sorted(cust_map.values(), key=lambda n: n.raw),
        regions=sorted(region_map.values(), key=lambda n: n.code),
        sectors=sorted(sector_map.values(), key=lambda n: n.fics_code),
    )
