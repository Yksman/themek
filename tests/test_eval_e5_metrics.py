from themek.eval.e5 import EvalResult


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
