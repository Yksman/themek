from pathlib import Path

from themek.llm.schemas import BusinessExtraction
from themek.eval.e5 import (
    evaluate_e5,
    EvalResult,
    load_ground_truth,
    format_eval_result_text,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ground_truth.json"


def _full(segments, customers, geo):
    return BusinessExtraction.model_validate({
        "period": "2023", "segments": segments,
        "customers": customers, "geographic": geo,
    })


def test_evaluate_e5_perfect_match():
    payload = {
        "segments": [
            {"name_ko": "메모리", "share_pct": 20.0, "products": []},
            {"name_ko": "MX", "share_pct": 35.0, "products": []},
        ],
        "customers": [{"name_raw": "Apple Inc.", "tier": "1차"}],
        "geo": [{"region_code": "KR", "share_pct": 50.0}],
    }
    truth = _full(payload["segments"], payload["customers"], payload["geo"])
    ext = _full(payload["segments"], payload["customers"], payload["geo"])
    result = evaluate_e5(ext, truth)
    assert isinstance(result, EvalResult)
    assert result.segment_recall == 1.0
    assert result.segment_precision == 1.0
    assert result.customer_recall == 1.0
    assert result.customer_precision == 1.0
    assert result.region_recall == 1.0
    assert result.region_precision == 1.0
    assert result.share_pct_mae == 0.0
    assert result.matched_segment_count == 2
    assert result.truth_segment_count == 2
    assert result.extracted_segment_count == 2
    assert result.missed_segments == []
    assert result.extra_segments == []


def test_evaluate_e5_partial():
    truth = _full(
        [{"name_ko": "메모리", "share_pct": 20.0},
         {"name_ko": "MX", "share_pct": 40.0}],
        [{"name_raw": "Apple Inc.", "tier": "1차"}],
        [{"region_code": "KR", "share_pct": 50.0},
         {"region_code": "US", "share_pct": 50.0}],
    )
    ext = _full(
        [{"name_ko": "메모리", "share_pct": 22.0},  # +2.0
         {"name_ko": "환각", "share_pct": 10.0}],
        [],
        [{"region_code": "KR", "share_pct": 100.0}],
    )
    result = evaluate_e5(ext, truth)
    assert result.segment_recall == 0.5
    assert result.segment_precision == 0.5
    assert result.customer_recall == 0.0
    assert result.customer_precision is None
    assert result.region_recall == 0.5
    assert result.region_precision == 1.0
    assert result.share_pct_mae == 2.0
    assert result.missed_segments == ["MX"]
    assert result.extra_segments == ["환각"]
    assert result.missed_customers == ["Apple Inc."]
    assert result.missed_regions == ["US"]


def test_load_ground_truth_returns_extraction():
    extraction, metadata = load_ground_truth(FIXTURE)
    assert isinstance(extraction, BusinessExtraction)
    assert extraction.period == "2023"
    assert extraction.segments[0].name_ko == "테스트부문"
    assert metadata["ticker"] == "999999"
    assert metadata["name_ko"] == "테스트회사"


def test_load_ground_truth_file_not_found(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_ground_truth(tmp_path / "missing.json")


def test_load_ground_truth_invalid_schema(tmp_path):
    """ground truth가 BusinessExtraction 스키마를 위반하면 ValidationError."""
    import pytest
    from pydantic import ValidationError
    bad = tmp_path / "bad.json"
    bad.write_text("""
    {
      "metadata": {"ticker": "x"},
      "extraction": {
        "period": "2023",
        "segments": [],
        "customers": [],
        "geographic": [{"region_code": "XX", "share_pct": 100.0}]
      }
    }
    """, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_ground_truth(bad)


def test_format_eval_result_perfect():
    result = EvalResult(
        segment_recall=1.0, segment_precision=1.0,
        customer_recall=1.0, customer_precision=1.0,
        region_recall=1.0, region_precision=1.0,
        share_pct_mae=0.0,
        matched_segment_count=6,
        truth_segment_count=6, extracted_segment_count=6,
    )
    metadata = {"ticker": "005930", "name_ko": "삼성전자", "period": "2023"}
    text = format_eval_result_text(
        result, metadata=metadata,
        ground_truth_path="data/eval/ground_truth/samsung_e5_2023.json",
        html_path="tests/fixtures/samsung_business_report_excerpt.html",
    )
    assert "삼성전자" in text
    assert "005930" in text
    assert "period=2023" in text
    assert "Segments" in text
    assert "1.000" in text
    assert "0.00 %p" in text
    assert "matched=6" in text


def test_format_eval_result_with_missed_and_extra():
    result = EvalResult(
        segment_recall=0.833, segment_precision=0.714,
        share_pct_mae=2.45,
        matched_segment_count=5,
        truth_segment_count=6, extracted_segment_count=7,
        missed_segments=["Harman"],
        extra_segments=["반도체장비", "디지털전환솔루션"],
    )
    metadata = {"ticker": "005930", "name_ko": "삼성전자", "period": "2023"}
    text = format_eval_result_text(
        result, metadata=metadata,
        ground_truth_path="x", html_path="y",
    )
    assert "Missed" in text
    assert "Harman" in text
    assert "반도체장비" in text


def test_format_eval_result_handles_none_scores():
    result = EvalResult(
        segment_recall=None, segment_precision=None,
        customer_recall=None, customer_precision=None,
        region_recall=None, region_precision=None,
        share_pct_mae=None,
    )
    metadata = {"ticker": "x", "name_ko": "x", "period": "x"}
    text = format_eval_result_text(
        result, metadata=metadata, ground_truth_path="x", html_path="x",
    )
    assert "n/a" in text  # None은 'n/a'로 표시
