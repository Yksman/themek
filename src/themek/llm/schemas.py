"""LLM 추출 결과의 Pydantic 모델."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


CustomerTier = Literal["1차", "2차", "unknown"]
RegionCode = Literal["KR", "US", "EU", "CN", "JP", "ROW"]


class SegmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_ko: str
    share_pct: Optional[float] = Field(default=None, ge=0, le=100)
    description: Optional[str] = None
    products: list[str] = Field(default_factory=list)


class CustomerItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_raw: str
    revenue_share_pct: Optional[float] = Field(default=None, ge=0, le=100)
    tier: CustomerTier = "unknown"


class GeographicItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_code: RegionCode
    share_pct: float = Field(ge=0, le=100)


class BusinessExtraction(BaseModel):
    """1개 사업보고서의 사업 구조 추출 결과."""
    model_config = ConfigDict(extra="forbid")
    period: str
    segments: list[SegmentItem]
    customers: list[CustomerItem]
    geographic: list[GeographicItem]
