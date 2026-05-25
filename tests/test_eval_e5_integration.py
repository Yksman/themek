from themek.llm.schemas import BusinessExtraction
from themek.eval.e5 import evaluate_e5, EvalResult


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
