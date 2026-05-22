import pytest
from pydantic import ValidationError
from themek.llm.schemas import (
    BusinessExtraction, SegmentItem, CustomerItem, GeographicItem,
)


def test_business_extraction_full_payload():
    payload = {
        "segments": [
            {"name_ko": "메모리반도체", "share_pct": 42.5,
             "products": ["DRAM", "NAND"]},
            {"name_ko": "스마트폰", "share_pct": 38.0, "products": ["갤럭시"]},
        ],
        "customers": [
            {"name_raw": "Apple Inc.", "revenue_share_pct": 18.0, "tier": "1차"},
        ],
        "geographic": [
            {"region_code": "KR", "share_pct": 30.0},
            {"region_code": "US", "share_pct": 35.0},
            {"region_code": "CN", "share_pct": 20.0},
            {"region_code": "EU", "share_pct": 10.0},
            {"region_code": "ROW", "share_pct": 5.0},
        ],
        "period": "2023",
    }
    extraction = BusinessExtraction.model_validate(payload)
    assert len(extraction.segments) == 2
    assert extraction.segments[0].share_pct == 42.5
    assert extraction.customers[0].tier == "1차"
    assert sum(g.share_pct for g in extraction.geographic) == 100.0


def test_business_extraction_optional_fields():
    payload = {"segments": [], "customers": [], "geographic": [], "period": "2024Q1"}
    extraction = BusinessExtraction.model_validate(payload)
    assert extraction.segments == []


def test_customer_tier_validation():
    with pytest.raises(ValidationError):
        CustomerItem(name_raw="X", tier="invalid_tier")


def test_segment_optional_share():
    s = SegmentItem(name_ko="X")
    assert s.share_pct is None
    assert s.products == []


def test_geographic_region_validation():
    with pytest.raises(ValidationError):
        GeographicItem(region_code="XX", share_pct=10.0)
