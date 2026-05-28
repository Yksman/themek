"""LLM 추출 결과의 Pydantic 모델."""
from __future__ import annotations
import re
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator


CustomerTier = Literal["1차", "2차", "unknown"]
RegionCode = Literal["KR", "US", "EU", "CN", "JP", "ROW"]


def _coerce_share_pct(v):
    """문자열 share_pct를 float로 강제 변환.

    LLM 응답의 비표준 형식 처리:
    - '12.3%' / '12.3 %' → 12.3
    - '약 15' / '15.0개' → 15.0
    - 'N/A' / 비파싱 → ValueError ('숫자' 키워드 포함)
    - None / float / int → 그대로
    """
    if v is None or isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        m = re.search(r"\d+(\.\d+)?", v)
        if m is None:
            raise ValueError(f"share_pct에 숫자 없음: {v!r}")
        return float(m.group())
    raise ValueError(f"share_pct 타입 미지원: {type(v).__name__}")


class SegmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_ko: str
    share_pct: Optional[float] = Field(default=None, ge=0, le=100)
    description: Optional[str] = None
    products: list[str] = Field(default_factory=list)

    @field_validator("share_pct", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _coerce_share_pct(v)


class CustomerItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_raw: str
    revenue_share_pct: Optional[float] = Field(default=None, ge=0, le=100)
    tier: CustomerTier = "unknown"

    @field_validator("revenue_share_pct", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _coerce_share_pct(v)


class GeographicItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_code: RegionCode
    share_pct: float = Field(ge=0, le=100)

    @field_validator("share_pct", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _coerce_share_pct(v)


class BusinessExtraction(BaseModel):
    """1개 사업보고서의 사업 구조 추출 결과."""
    model_config = ConfigDict(extra="forbid")
    period: str
    segments: list[SegmentItem]
    customers: list[CustomerItem]
    geographic: list[GeographicItem]
