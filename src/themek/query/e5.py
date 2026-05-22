"""E5 ("이 회사 뭐 만들어?") query traversal."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from themek.db.models import (
    Stock, BusinessReport, BusinessSegment, RevenueComposition,
    CustomerRelation, GeographicExposure, Region,
)


@dataclass
class SegmentSummary:
    name: str
    share_pct: Optional[float]
    description: Optional[str]


@dataclass
class CustomerSummary:
    name_raw: str
    revenue_share_pct: Optional[float]
    tier: str


@dataclass
class RegionSummary:
    region_code: str
    region_name_ko: str
    share_pct: float


@dataclass
class E5Result:
    stock_ticker: str
    stock_name: str
    corporation_dart_code: str
    corporation_name: str
    sector_name: Optional[str]
    period: Optional[str]
    segments: list[SegmentSummary] = field(default_factory=list)
    top_customers: list[CustomerSummary] = field(default_factory=list)
    top_regions: list[RegionSummary] = field(default_factory=list)
    source_report_rcept_no: Optional[str] = None
    source_report_url: Optional[str] = None


def query_e5(session: Session, *, ticker: str,
             top_n_customers: int = 5, top_n_regions: int = 5) -> E5Result:
    """ticker 1개에 대한 사업 구조 요약."""
    stock = session.get(Stock, ticker)
    if stock is None:
        raise LookupError(f"Unknown ticker: {ticker}")
    corp = stock.issued_by

    report = session.execute(
        select(BusinessReport)
        .where(BusinessReport.corporation_id == corp.dart_code)
        .order_by(BusinessReport.filing_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    result = E5Result(
        stock_ticker=stock.ticker,
        stock_name=stock.name_ko,
        corporation_dart_code=corp.dart_code,
        corporation_name=corp.name_ko,
        sector_name=corp.in_sector.name_ko if corp.in_sector else None,
        period=report.period if report else None,
        source_report_rcept_no=report.dart_rcept_no if report else None,
        source_report_url=report.url if report else None,
    )
    if report is None:
        return result

    segments_rows = session.execute(
        select(BusinessSegment, RevenueComposition.share_pct)
        .join(
            RevenueComposition,
            RevenueComposition.subject_segment_id == BusinessSegment.id,
            isouter=True,
        )
        .where(BusinessSegment.corporation_id == corp.dart_code)
        .where(
            (RevenueComposition.source_report_id == report.dart_rcept_no)
            | (RevenueComposition.id.is_(None))
        )
    ).all()
    segments_rows = sorted(
        segments_rows,
        key=lambda r: (r[1] is None, -(float(r[1]) if r[1] is not None else 0.0)),
    )
    result.segments = [
        SegmentSummary(name=seg.name_ko,
                       share_pct=float(share) if share is not None else None,
                       description=seg.description)
        for seg, share in segments_rows
    ]

    customer_rows = session.execute(
        select(CustomerRelation)
        .where(CustomerRelation.source_report_id == report.dart_rcept_no)
        .order_by(CustomerRelation.revenue_share_pct.desc().nullslast())
        .limit(top_n_customers)
    ).scalars().all()
    result.top_customers = [
        CustomerSummary(
            name_raw=c.buyer_raw or (c.buyer_corp.name_ko if c.buyer_corp else "?"),
            revenue_share_pct=float(c.revenue_share_pct) if c.revenue_share_pct is not None else None,
            tier=c.tier,
        )
        for c in customer_rows
    ]

    geo_rows = session.execute(
        select(GeographicExposure, Region)
        .join(Region, Region.code == GeographicExposure.region_id)
        .where(GeographicExposure.source_report_id == report.dart_rcept_no)
        .order_by(GeographicExposure.share_pct.desc())
        .limit(top_n_regions)
    ).all()
    result.top_regions = [
        RegionSummary(region_code=g.region_id,
                      region_name_ko=region.name_ko,
                      share_pct=float(g.share_pct))
        for g, region in geo_rows
    ]

    return result
