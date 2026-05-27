"""aggregate_runs — mean/stdev + token total + union 진단."""
import pytest
from themek.llm.claude_cli import CallResult
from themek.eval.e5 import EvalResult, AggregatedResult, aggregate_runs


def _r(seg_r, seg_p, cust_r, cust_p, reg_r, reg_p, mae, *,
       missed_segs=None, extra_segs=None) -> EvalResult:
    return EvalResult(
        segment_recall=seg_r, segment_precision=seg_p,
        customer_recall=cust_r, customer_precision=cust_p,
        region_recall=reg_r, region_precision=reg_p,
        share_pct_mae=mae,
        missed_segments=list(missed_segs or []),
        extra_segments=list(extra_segs or []),
    )


def _u(input_t, output_t, cost, ms) -> CallResult:
    return CallResult(text="", input_tokens=input_t, output_tokens=output_t,
                      cost_usd=cost, duration_ms=ms, raw_payload={})


def test_aggregate_n3_basic_means():
    runs = [
        _r(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0),
        _r(0.8, 1.0, 1.0, 0.75, 1.0, 1.0, 0.85),
        _r(1.0, 0.857, 1.0, 1.0, 1.0, 1.0, 0.30),
    ]
    usages = [_u(12000, 600, 0.04, 30000),
              _u(13000, 620, 0.042, 31000),
              _u(12500, 610, 0.041, 30500)]
    agg = aggregate_runs(runs, usages)
    assert isinstance(agg, AggregatedResult)
    assert agg.segment_recall_mean == pytest.approx((1.0 + 0.8 + 1.0) / 3)
    assert agg.segment_precision_mean == pytest.approx((1.0 + 1.0 + 0.857) / 3)
    assert agg.share_pct_mae_mean == pytest.approx((0.0 + 0.85 + 0.30) / 3)
    assert agg.total_input_tokens == 37500
    assert agg.total_output_tokens == 1830
    assert abs(agg.total_cost_usd - 0.123) < 1e-6
    assert agg.total_duration_ms == 91500
    # stdev > 0
    assert agg.segment_recall_stdev > 0


def test_aggregate_n1_stdev_is_none():
    runs = [_r(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0)]
    usages = [_u(100, 50, 0.001, 1000)]
    agg = aggregate_runs(runs, usages)
    assert agg.segment_recall_mean == 1.0
    assert agg.segment_recall_stdev is None
    assert agg.share_pct_mae_stdev is None


def test_aggregate_skips_none_metric_in_mean():
    runs = [
        _r(1.0, None, 1.0, 1.0, 1.0, 1.0, 0.0),
        _r(1.0, None, 1.0, 1.0, 1.0, 1.0, 0.0),
    ]
    usages = [_u(100, 10, 0.001, 1000), _u(100, 10, 0.001, 1000)]
    agg = aggregate_runs(runs, usages)
    assert agg.segment_precision_mean is None
    assert agg.segment_precision_stdev is None
    assert agg.segment_recall_mean == 1.0


def test_aggregate_unions_missed_and_extra_across_runs():
    runs = [
        _r(0.5, 0.5, None, None, None, None, None,
           missed_segs=["Harman"], extra_segs=["환각A"]),
        _r(0.5, 0.5, None, None, None, None, None,
           missed_segs=["Harman", "VD/DA"], extra_segs=["환각B"]),
    ]
    usages = [_u(100, 10, 0.001, 1000), _u(100, 10, 0.001, 1000)]
    agg = aggregate_runs(runs, usages)
    assert sorted(agg.missed_segments_union) == ["Harman", "VD/DA"]
    assert sorted(agg.extra_segments_union) == ["환각A", "환각B"]


def test_aggregate_requires_matching_run_usage_lengths():
    with pytest.raises(ValueError):
        aggregate_runs([_r(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0)], [])


from themek.eval.e5 import format_aggregated_result_text


def test_format_aggregated_displays_means_and_totals():
    runs = [
        _r(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0),
        _r(0.833, 1.0, 1.0, 0.75, 1.0, 1.0, 0.85,
           missed_segs=["Harman"], extra_segs=["환각"]),
        _r(1.0, 0.857, 1.0, 1.0, 1.0, 1.0, 0.30),
    ]
    usages = [_u(12000, 600, 0.04, 30000),
              _u(13000, 620, 0.042, 31000),
              _u(12500, 610, 0.041, 30500)]
    agg = aggregate_runs(runs, usages)
    metadata = {"ticker": "005930", "name_ko": "삼성전자", "period": "2023"}
    section_log = "regex matched: overview, products, revenue\nllm fallback: not called"
    text = format_aggregated_result_text(
        agg, metadata=metadata,
        ground_truth_path="data/eval/ground_truth/samsung_e5_2023.json",
        html_path="data/dart/raw/2024XXX/business.html",
        section_log=section_log,
    )
    assert "삼성전자" in text
    assert "(N=3)" in text
    assert "Token usage" in text
    assert "37,500" in text or "37500" in text
    assert "$0.12" in text
    assert "Section filter:" in text
    assert "Harman" in text       # union missed
    assert "환각" in text         # union extra
