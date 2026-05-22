"""SQLAlchemy declarative models for themek ontology."""
from __future__ import annotations
from typing import Optional
from datetime import date as _date
from sqlalchemy import (
    String, ForeignKey, Enum as SQLEnum,
    Date, Numeric, Boolean, Text, CheckConstraint,
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


class Region(Base):
    __tablename__ = "regions"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(64), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(64))


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


class BusinessSegment(Base):
    __tablename__ = "business_segments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    corporation_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("corporations.dart_code"), nullable=False
    )
    corporation: Mapped[Corporation] = relationship()
    name_ko: Mapped[str] = mapped_column(String(256), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(256))
    description: Mapped[Optional[str]] = mapped_column(Text)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(256), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(256))
    category: Mapped[Optional[str]] = mapped_column(String(128))


class RevenueComposition(Base):
    __tablename__ = "revenue_compositions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_corp_id: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("corporations.dart_code")
    )
    subject_segment_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("business_segments.id")
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    share_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    absolute_value: Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    source_report_id: Mapped[str] = mapped_column(
        String(14), ForeignKey("business_reports.dart_rcept_no"), nullable=False
    )
    source_report: Mapped[BusinessReport] = relationship()

    __table_args__ = (
        CheckConstraint(
            "(subject_corp_id IS NOT NULL) <> (subject_segment_id IS NOT NULL)",
            name="rc_subject_exactly_one",
        ),
    )


class CustomerRelation(Base):
    __tablename__ = "customer_relations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    seller_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("corporations.dart_code"), nullable=False
    )
    seller: Mapped[Corporation] = relationship(foreign_keys=[seller_id])
    buyer_corp_id: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("corporations.dart_code")
    )
    buyer_corp: Mapped[Optional[Corporation]] = relationship(foreign_keys=[buyer_corp_id])
    buyer_raw: Mapped[Optional[str]] = mapped_column(String(256))
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    revenue_share_pct: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    tier: Mapped[str] = mapped_column(
        SQLEnum("1차", "2차", "unknown", name="customer_tier_enum"),
        nullable=False, default="unknown",
    )
    source_report_id: Mapped[str] = mapped_column(
        String(14), ForeignKey("business_reports.dart_rcept_no"), nullable=False
    )
    source_report: Mapped[BusinessReport] = relationship()

    __table_args__ = (
        CheckConstraint(
            "(buyer_corp_id IS NOT NULL) OR (buyer_raw IS NOT NULL)",
            name="cr_buyer_present",
        ),
    )


class GeographicExposure(Base):
    __tablename__ = "geographic_exposures"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_corp_id: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("corporations.dart_code")
    )
    subject_segment_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("business_segments.id")
    )
    region_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("regions.code"), nullable=False
    )
    region: Mapped[Region] = relationship()
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    share_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    source_report_id: Mapped[str] = mapped_column(
        String(14), ForeignKey("business_reports.dart_rcept_no"), nullable=False
    )
    source_report: Mapped[BusinessReport] = relationship()

    __table_args__ = (
        CheckConstraint(
            "(subject_corp_id IS NOT NULL) <> (subject_segment_id IS NOT NULL)",
            name="ge_subject_exactly_one",
        ),
    )
