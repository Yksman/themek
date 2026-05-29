"""1개 사업보고서를 ingestion하는 오케스트레이션.

BusinessReport(운영 메타·incremental dedup용)은 계속 기록하되, 사업 구조
(세그먼트/고객/지역)는 graph-core(nodes/edges)에 `ingest_business_structure`로
적재한다. provenance는 source_ref=dart_rcept_no 로 엣지에 부착된다.
"""
from __future__ import annotations
from datetime import date
from typing import Callable, Optional
from sqlalchemy.orm import Session
from themek.db.corp_models import BusinessReport, Corporation
from themek.llm.schemas import BusinessExtraction
from themek.ontology.core.ids import company_id
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.business_structure import ingest_business_structure


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

    # 사업 구조 → graph-core nodes/edges. 회사 노드 보장 후 적재.
    # 라벨은 corp_models.Corporation.name_ko(=corp master 캐시 보강) 우선, 없으면 dart_code.
    corp = session.get(Corporation, corporation_id)
    corp_label = corp.name_ko if corp and corp.name_ko else corporation_id
    upsert_node(session, company_id(corporation_id), "company", corp_label,
                {"dart_code": corporation_id})
    ingest_business_structure(
        session, corp_code=corporation_id, extraction=extraction,
        source_ref=dart_rcept_no,
    )
