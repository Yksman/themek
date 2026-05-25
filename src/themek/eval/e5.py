"""E5 evaluation harness — 추출 결과를 ground truth와 비교한다.

Spec: docs/superpowers/specs/2026-05-23-e5-eval-harness-design.md
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


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
