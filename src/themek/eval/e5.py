"""E5 evaluation harness — 추출 결과를 ground truth와 비교한다.

Spec: docs/superpowers/specs/2026-05-23-e5-eval-harness-design.md
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from themek.llm.schemas import BusinessExtraction


@dataclass
class EvalResult:
    """E5 evaluation 결과 컨테이너."""
    segment_recall: Optional[float] = None
    segment_precision: Optional[float] = None
    customer_recall: Optional[float] = None
    customer_precision: Optional[float] = None
    region_recall: Optional[float] = None
    region_precision: Optional[float] = None
    share_pct_mae: Optional[float] = None
    matched_segment_count: int = 0
    truth_segment_count: int = 0
    extracted_segment_count: int = 0
    missed_segments: list[str] = field(default_factory=list)
    extra_segments: list[str] = field(default_factory=list)
    missed_customers: list[str] = field(default_factory=list)
    extra_customers: list[str] = field(default_factory=list)
    missed_regions: list[str] = field(default_factory=list)
    extra_regions: list[str] = field(default_factory=list)


def _safe_div(num: int, den: int) -> Optional[float]:
    return None if den == 0 else num / den


def segment_metrics(
    extracted: BusinessExtraction,
    truth: BusinessExtraction,
) -> tuple[Optional[float], Optional[float], list[str], list[str], list[str]]:
    """segment recall/precision + matched/missed/extra 이름 리스트.

    매칭 기준: name_ko exact match.
    Returns: (recall, precision, matched_names, missed_names, extra_names)
    """
    truth_names = [s.name_ko for s in truth.segments]
    ext_names = [s.name_ko for s in extracted.segments]
    truth_set = set(truth_names)
    ext_set = set(ext_names)
    matched = sorted(truth_set & ext_set)
    missed = sorted(truth_set - ext_set)
    extra = sorted(ext_set - truth_set)
    recall = _safe_div(len(matched), len(truth_set))
    precision = _safe_div(len(matched), len(ext_set))
    return recall, precision, matched, missed, extra


def customer_metrics(
    extracted: BusinessExtraction,
    truth: BusinessExtraction,
) -> tuple[Optional[float], Optional[float], list[str], list[str], list[str]]:
    """customer recall/precision + 진단 리스트.

    매칭 기준: name_raw case-insensitive exact.
    missed/extra 리스트는 truth/extracted의 원래 표기를 보존한다.
    """
    truth_pairs = [(c.name_raw.lower(), c.name_raw) for c in truth.customers]
    ext_pairs = [(c.name_raw.lower(), c.name_raw) for c in extracted.customers]
    truth_keys = {k for k, _ in truth_pairs}
    ext_keys = {k for k, _ in ext_pairs}
    matched_keys = truth_keys & ext_keys
    matched_names = sorted({orig for k, orig in truth_pairs if k in matched_keys})
    missed = sorted({orig for k, orig in truth_pairs if k not in matched_keys})
    extra = sorted({orig for k, orig in ext_pairs if k not in matched_keys})
    recall = _safe_div(len(matched_keys), len(truth_keys))
    precision = _safe_div(len(matched_keys), len(ext_keys))
    return recall, precision, matched_names, missed, extra


def region_metrics(
    extracted: BusinessExtraction,
    truth: BusinessExtraction,
) -> tuple[Optional[float], Optional[float], list[str], list[str], list[str]]:
    """region recall/precision + 진단 리스트. 매칭: region_code exact."""
    truth_codes = {g.region_code for g in truth.geographic}
    ext_codes = {g.region_code for g in extracted.geographic}
    matched = sorted(truth_codes & ext_codes)
    missed = sorted(truth_codes - ext_codes)
    extra = sorted(ext_codes - truth_codes)
    recall = _safe_div(len(matched), len(truth_codes))
    precision = _safe_div(len(matched), len(ext_codes))
    return recall, precision, matched, missed, extra


def share_pct_mae(
    extracted: BusinessExtraction,
    truth: BusinessExtraction,
) -> tuple[Optional[float], int]:
    """matched segment의 share_pct 평균 절대 오차.

    truth.share_pct 또는 extracted.share_pct가 null이면 그 segment는 제외.
    matched(양쪽 share_pct 모두 존재) segment가 0개이면 (None, 0) 반환.
    """
    truth_share = {s.name_ko: s.share_pct for s in truth.segments}
    ext_share = {s.name_ko: s.share_pct for s in extracted.segments}
    diffs: list[float] = []
    for name_ko, t_share in truth_share.items():
        if t_share is None:
            continue
        e_share = ext_share.get(name_ko)
        if e_share is None:
            continue
        diffs.append(abs(float(e_share) - float(t_share)))
    if not diffs:
        return None, 0
    return sum(diffs) / len(diffs), len(diffs)
