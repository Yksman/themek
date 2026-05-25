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
