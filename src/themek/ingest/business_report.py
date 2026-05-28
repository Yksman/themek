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


def _make_default_extractor(
    escalation_level: Optional[str] = None,
) -> Callable[[str, str], BusinessExtraction]:
    # "regex" escalation in the parser means header classification did not
    # need LLM, but the extraction prompt itself is still substantial — use
    # the default (120s) instead of the 60s reserved for tiny header-list
    # prompts. Other levels map directly.
    effective = None if escalation_level == "regex" else escalation_level

    def extractor(text: str, period_hint: str) -> BusinessExtraction:
        from themek.llm.claude_cli import call_claude, extract_json_block
        from themek.llm.prompts import build_business_extraction_prompt
        prompt = build_business_extraction_prompt(text, period_hint=period_hint)
        raw = call_claude(prompt, escalation=effective).text
        payload = extract_json_block(raw)
        # LLM occasionally returns share_pct=null for regions whose share is
        # not disclosed; geographic.share_pct is required, so drop those rows
        # rather than failing the entire extraction.
        if isinstance(payload, dict):
            geo = payload.get("geographic")
            if isinstance(geo, list):
                payload["geographic"] = [
                    g for g in geo
                    if isinstance(g, dict) and g.get("share_pct") is not None
                ]
        return BusinessExtraction.model_validate(payload)
    return extractor


def _default_extractor(text: str, period_hint: str) -> BusinessExtraction:
    return _make_default_extractor()(text, period_hint)


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
    escalation_level: Optional[str] = None,
    extractor: Optional[Callable[[str, str], BusinessExtraction]] = None,
) -> None:
    """사업보고서 1건을 ingest. 이미 존재하면 no-op (R4: idempotency)."""
    existing = session.get(BusinessReport, dart_rcept_no)
    if existing is not None:
        return

    if extractor is None:
        extractor = _make_default_extractor(escalation_level)

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

    # Dedup: 같은 region_code로 매핑된 여러 항목은 share_pct를 합산해 1 row로.
    # (subject_corp_id, region_id, period) 조합은 ontology상 unique해야 함.
    geo_by_region: dict[str, float] = {}
    for geo in extraction.geographic:
        geo_by_region[geo.region_code] = (
            geo_by_region.get(geo.region_code, 0.0) + float(geo.share_pct)
        )
    for region_code, share_pct in geo_by_region.items():
        session.add(GeographicExposure(
            id=str(uuid.uuid4()),
            subject_corp_id=corporation_id,
            subject_segment_id=None,
            region_id=region_code,
            period=period,
            share_pct=share_pct,
            source_report_id=report.dart_rcept_no,
        ))
