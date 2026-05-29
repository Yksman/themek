"""DART 백필 · KRX sync 서브시스템용 SQLAlchemy 모델.

온톨로지 graph-core(`themek.ontology.core.models`)와 별개로, 적재 파이프라인이
의존하는 운영 테이블(corporations/stocks/business_reports/backfill_targets)과
그 FK 대상(sectors/groups)을 보관한다. 구 `db/models.py`의 온톨로지
모델(BusinessSegment/RevenueComposition/CustomerRelation/GeographicExposure/
Region)은 코어로 대체되어 제거됐다.
"""
from __future__ import annotations
from typing import Optional
from datetime import date as _date, datetime as _datetime
from sqlalchemy import (
    String, ForeignKey, Enum as SQLEnum,
    Date, DateTime, Numeric, Text,
    Integer, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from themek.db.engine import Base


class Sector(Base):
    __tablename__ = "sectors"
    fics_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(128), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(128))
    parent_sector_id: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("sectors.fics_code")
    )

    parent_sector: Mapped[Optional["Sector"]] = relationship(remote_side=[fics_code])


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name_ko: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)


class Corporation(Base):
    __tablename__ = "corporations"
    dart_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(256), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(256))
    wikidata_qid: Mapped[Optional[str]] = mapped_column(String(32))

    in_sector_id: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("sectors.fics_code")
    )
    in_sector: Mapped[Optional[Sector]] = relationship()

    belongs_to_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("groups.id")
    )
    belongs_to: Mapped[Optional[Group]] = relationship()


class Stock(Base):
    __tablename__ = "stocks"
    ticker: Mapped[str] = mapped_column(String(6), primary_key=True)
    isin: Mapped[Optional[str]] = mapped_column(String(12))
    name_ko: Mapped[str] = mapped_column(String(256), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(256))
    share_class: Mapped[str] = mapped_column(
        SQLEnum("common", "preferred", name="share_class_enum"),
        nullable=False, default="common"
    )
    market: Mapped[str] = mapped_column(
        SQLEnum("KOSPI", "KOSDAQ", "KONEX", name="market_enum"),
        nullable=False
    )

    issued_by_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("corporations.dart_code"), nullable=False
    )
    issued_by: Mapped[Corporation] = relationship()

    # Plan #5.2: lifecycle
    delisted_at: Mapped[Optional[_date]] = mapped_column(Date)
    last_seen_at: Mapped[Optional[_date]] = mapped_column(Date)
    created_at: Mapped[Optional[_datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
    )


class BusinessReport(Base):
    __tablename__ = "business_reports"
    dart_rcept_no: Mapped[str] = mapped_column(String(14), primary_key=True)
    corporation_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("corporations.dart_code"), nullable=False
    )
    corporation: Mapped[Corporation] = relationship()
    report_type: Mapped[str] = mapped_column(
        SQLEnum("사업보고서", "반기보고서", "분기보고서", name="report_type_enum"),
        nullable=False,
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    filing_date: Mapped[_date] = mapped_column(Date, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(512))


class BackfillTarget(Base):
    __tablename__ = "backfill_targets"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(String(8), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(
            "pending", "in_progress", "done", "failed", "skipped",
            name="backfill_target_status_enum",
        ),
        nullable=False, default="pending",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[Optional[_datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    rcept_no: Mapped[Optional[str]] = mapped_column(String(14))
    # C4: 비용·품질 추적 컬럼
    escalation_level: Mapped[Optional[str]] = mapped_column(String(32))
    input_chars: Mapped[Optional[int]] = mapped_column(Integer)
    cost_estimate_usd: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    created_at: Mapped[_datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(),
    )
    updated_at: Mapped[_datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint("corp_code", "period", name="ux_backfill_corp_period"),
    )
