"""안정 노드 ID 스킴 단위 테스트."""
from themek.ontology.core.ids import (
    company_id, stock_id, sector_id, region_id, period_id,
    segment_id, customer_id, metric_id, slug,
)


def test_natural_key_ids():
    assert company_id("00126380") == "company:00126380"
    assert stock_id("005930") == "stock:005930"
    assert sector_id("G2520") == "sector:G2520"
    assert region_id("US") == "region:US"
    assert metric_id("operating_income") == "metric:operating_income"


def test_period_id_label():
    assert period_id("2025", "Q1") == "period:2025Q1"
    assert period_id("2025", "H1") == "period:2025H1"
    assert period_id("2023", "FY") == "period:2023FY"


def test_slug_normalizes_korean_and_ascii():
    assert slug("  메모리 반도체 ") == "메모리-반도체"
    assert slug("Apple Inc.") == "apple-inc"
    assert slug("DX 부문") == "dx-부문"


def test_concept_ids_use_slug():
    assert segment_id("메모리반도체") == "segment:메모리반도체"
    assert customer_id("Apple Inc.") == "customer:apple-inc"


def test_long_concept_id_is_stable_and_hashed():
    raw = "세계 유수의 Mobile 및 Computing 관련 전자 업체 (DRAM 수요처)"
    a = customer_id(raw)
    assert a == customer_id(raw)          # 안정적
    assert len(a.split(":", 1)[1]) <= 48  # slug 상한
    assert customer_id(raw) != customer_id(raw + "x")  # 다른 원문 다른 id
