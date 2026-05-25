from themek.eval.e5 import (
    EvalResult,
    segment_metrics,
    customer_metrics,
    region_metrics,
    share_pct_mae,
)
from themek.llm.schemas import BusinessExtraction


def _ext(segments):
    return BusinessExtraction.model_validate({
        "period": "2023", "segments": segments,
        "customers": [], "geographic": [],
    })


def test_eval_result_default_construction():
    r = EvalResult()
    assert r.segment_recall is None
    assert r.segment_precision is None
    assert r.customer_recall is None
    assert r.customer_precision is None
    assert r.region_recall is None
    assert r.region_precision is None
    assert r.share_pct_mae is None
    assert r.matched_segment_count == 0
    assert r.truth_segment_count == 0
    assert r.extracted_segment_count == 0
    assert r.missed_segments == []
    assert r.extra_segments == []
    assert r.missed_customers == []
    assert r.extra_customers == []
    assert r.missed_regions == []
    assert r.extra_regions == []


def test_segment_perfect_match():
    truth = _ext([{"name_ko": "메모리", "share_pct": 20.0}])
    ext = _ext([{"name_ko": "메모리", "share_pct": 20.0}])
    recall, precision, matched, missed, extra = segment_metrics(ext, truth)
    assert recall == 1.0
    assert precision == 1.0
    assert matched == ["메모리"]
    assert missed == []
    assert extra == []


def test_segment_missing():
    truth = _ext([{"name_ko": "메모리"}, {"name_ko": "MX"}])
    ext = _ext([{"name_ko": "메모리"}])
    recall, precision, matched, missed, extra = segment_metrics(ext, truth)
    assert recall == 0.5
    assert precision == 1.0
    assert missed == ["MX"]
    assert extra == []


def test_segment_extra():
    truth = _ext([{"name_ko": "메모리"}])
    ext = _ext([{"name_ko": "메모리"}, {"name_ko": "환각"}])
    recall, precision, matched, missed, extra = segment_metrics(ext, truth)
    assert recall == 1.0
    assert precision == 0.5
    assert extra == ["환각"]


def test_segment_empty_extracted():
    truth = _ext([{"name_ko": "메모리"}])
    ext = _ext([])
    recall, precision, matched, missed, extra = segment_metrics(ext, truth)
    assert recall == 0.0
    assert precision is None  # 0/0
    assert missed == ["메모리"]


def test_segment_empty_truth():
    truth = _ext([])
    ext = _ext([{"name_ko": "환각"}])
    recall, precision, matched, missed, extra = segment_metrics(ext, truth)
    assert recall is None  # 0/0
    assert precision == 0.0
    assert extra == ["환각"]


def _cust_ext(customers):
    return BusinessExtraction.model_validate({
        "period": "2023", "segments": [],
        "customers": customers, "geographic": [],
    })


def test_customer_case_insensitive_match():
    truth = _cust_ext([{"name_raw": "Apple Inc.", "tier": "1차"}])
    ext = _cust_ext([{"name_raw": "apple inc.", "tier": "1차"}])
    recall, precision, matched, missed, extra = customer_metrics(ext, truth)
    assert recall == 1.0
    assert precision == 1.0
    assert matched == ["Apple Inc."]  # truth 표기 유지


def test_customer_missing():
    truth = _cust_ext([
        {"name_raw": "Apple Inc.", "tier": "1차"},
        {"name_raw": "삼성디스플레이", "tier": "1차"},
    ])
    ext = _cust_ext([{"name_raw": "Apple Inc.", "tier": "1차"}])
    recall, precision, _, missed, extra = customer_metrics(ext, truth)
    assert recall == 0.5
    assert missed == ["삼성디스플레이"]


def test_customer_extra():
    truth = _cust_ext([{"name_raw": "Apple Inc.", "tier": "1차"}])
    ext = _cust_ext([
        {"name_raw": "Apple Inc.", "tier": "1차"},
        {"name_raw": "환각고객사", "tier": "unknown"},
    ])
    recall, precision, _, _, extra = customer_metrics(ext, truth)
    assert recall == 1.0
    assert precision == 0.5
    assert extra == ["환각고객사"]


def test_customer_empty_both():
    truth = _cust_ext([])
    ext = _cust_ext([])
    recall, precision, _, missed, extra = customer_metrics(ext, truth)
    assert recall is None
    assert precision is None
    assert missed == []
    assert extra == []


def _geo_ext(geo):
    return BusinessExtraction.model_validate({
        "period": "2023", "segments": [],
        "customers": [], "geographic": geo,
    })


def test_region_perfect_match():
    truth = _geo_ext([
        {"region_code": "KR", "share_pct": 14.8},
        {"region_code": "ROW", "share_pct": 19.2},
    ])
    ext = _geo_ext([
        {"region_code": "KR", "share_pct": 14.8},
        {"region_code": "ROW", "share_pct": 19.2},
    ])
    recall, precision, matched, missed, extra = region_metrics(ext, truth)
    assert recall == 1.0
    assert precision == 1.0
    assert sorted(matched) == ["KR", "ROW"]


def test_region_missing_and_extra():
    truth = _geo_ext([
        {"region_code": "KR", "share_pct": 14.8},
        {"region_code": "US", "share_pct": 35.6},
    ])
    ext = _geo_ext([
        {"region_code": "KR", "share_pct": 14.8},
        {"region_code": "ROW", "share_pct": 50.0},  # 환각
    ])
    recall, precision, _, missed, extra = region_metrics(ext, truth)
    assert recall == 0.5
    assert precision == 0.5
    assert missed == ["US"]
    assert extra == ["ROW"]


def test_share_pct_mae_basic():
    truth = _ext([
        {"name_ko": "메모리", "share_pct": 20.0},
        {"name_ko": "MX", "share_pct": 40.0},
    ])
    ext = _ext([
        {"name_ko": "메모리", "share_pct": 21.5},  # +1.5
        {"name_ko": "MX", "share_pct": 35.5},      # -4.5
    ])
    mae, matched_count = share_pct_mae(ext, truth)
    assert abs(mae - 3.0) < 0.001  # (1.5+4.5)/2
    assert matched_count == 2


def test_share_pct_mae_no_matched_segments():
    truth = _ext([{"name_ko": "메모리", "share_pct": 20.0}])
    ext = _ext([{"name_ko": "환각", "share_pct": 99.0}])
    mae, matched_count = share_pct_mae(ext, truth)
    assert mae is None
    assert matched_count == 0


def test_share_pct_mae_excludes_null_truth_share():
    truth = _ext([
        {"name_ko": "메모리", "share_pct": 20.0},
        {"name_ko": "기타", "share_pct": None},
    ])
    ext = _ext([
        {"name_ko": "메모리", "share_pct": 22.0},  # +2.0
        {"name_ko": "기타", "share_pct": 5.0},
    ])
    mae, matched_count = share_pct_mae(ext, truth)
    assert mae == 2.0  # 기타는 분모/분자 둘 다 제외
    assert matched_count == 1


def test_share_pct_mae_excludes_null_extracted_share():
    truth = _ext([
        {"name_ko": "메모리", "share_pct": 20.0},
        {"name_ko": "MX", "share_pct": 40.0},
    ])
    ext = _ext([
        {"name_ko": "메모리", "share_pct": 22.0},  # +2.0
        {"name_ko": "MX", "share_pct": None},
    ])
    mae, matched_count = share_pct_mae(ext, truth)
    assert mae == 2.0
    assert matched_count == 1
