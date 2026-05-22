"""SQLAlchemy declarative models for themek ontology."""
from __future__ import annotations
from typing import Optional
from sqlalchemy import String, ForeignKey, Enum as SQLEnum
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
    code: Mapped[str] = mapped_column(String(8), primary_key=True)  # KR, US, EU...
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
