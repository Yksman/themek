"""1개 사업보고서를 ingestion하는 오케스트레이션."""
from __future__ import annotations
import uuid
from datetime import date
from typing import Callable, Optional
from sqlalchemy.orm import Session
from themek.db.models import (
    BusinessReport, BusinessSegment, RevenueComposition,
    CustomerRelation, GeographicExposure,
)
from themek.llm.schemas import BusinessExtraction


def _default_extractor(text: str, period_hint: str) -> BusinessExtraction:
    from themek.llm.claude_cli import call_claude, extract_json_block
    from themek.llm.prompts import build_business_extraction_prompt
    prompt = build_business_extraction_prompt(text, period_hint=period_hint)
    raw = call_claude(prompt)
    payload = extract_json_block(raw)
    return BusinessExtraction.model_validate(payload)


def ingest_business_report(
    session: Session,
    *,
    dart_rcept_no: str,
    corporation_id: str,
    report_type: str,
    period: str,
    filing_date: date,
    raw_text_excerpt: str,
    url: Optional[str] = None,
    extractor: Callable[[str, str], BusinessExtraction] = _default_extractor,
) -> None:
    """사업보고서 1건을 ingest. 이미 존재하면 no-op (R4: idempotency)."""
    existing = session.get(BusinessReport, dart_rcept_no)
    if existing is not None:
        return

    extraction = extractor(raw_text_excerpt, period)

    report = BusinessReport(
        dart_rcept_no=dart_rcept_no,
        corporation_id=corporation_id,
        report_type=report_type,
        period=period,
        filing_date=filing_date,
        url=url,
    )
    session.add(report)
    session.flush()

    for seg_item in extraction.segments:
        seg = BusinessSegment(
            id=str(uuid.uuid4()),
            corporation_id=corporation_id,
            name_ko=seg_item.name_ko,
            description=seg_item.description,
        )
        session.add(seg)
        session.flush()
        if seg_item.share_pct is not None:
            session.add(RevenueComposition(
                id=str(uuid.uuid4()),
                subject_corp_id=None,
                subject_segment_id=seg.id,
                period=period,
                share_pct=seg_item.share_pct,
                source_report_id=report.dart_rcept_no,
            ))

    for cust in extraction.customers:
        session.add(CustomerRelation(
            id=str(uuid.uuid4()),
            seller_id=corporation_id,
            buyer_corp_id=None,
            buyer_raw=cust.name_raw,
            resolved=False,
            period=period,
            revenue_share_pct=cust.revenue_share_pct,
            tier=cust.tier,
            source_report_id=report.dart_rcept_no,
        ))

    for geo in extraction.geographic:
        session.add(GeographicExposure(
            id=str(uuid.uuid4()),
            subject_corp_id=corporation_id,
            subject_segment_id=None,
            region_id=geo.region_code,
            period=period,
            share_pct=geo.share_pct,
            source_report_id=report.dart_rcept_no,
        ))
