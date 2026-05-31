"""graph-ready 코어 ORM. 프로퍼티그래프(Node/Edge) + 정형 fact(FinancialFact)."""
from __future__ import annotations

from datetime import datetime as _dt

from sqlalchemy import (
    String, Float, Numeric, ForeignKey, Enum as SQLEnum, JSON,
    DateTime, UniqueConstraint, Index, func, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from themek.db.engine import Base

NODE_KINDS = (
    "company", "stock", "sector", "region", "segment",
    "customer", "period", "metric", "group",
)
PREDICATES = (
    "HAS_SEGMENT", "SELLS_TO", "EXPOSED_TO", "IN_SECTOR",
    "ISSUES_STOCK", "BELONGS_TO_GROUP", "SUB_SECTOR_OF",
)
SOURCE_TYPES = ("dart_api", "dart_report", "social", "llm", "manual")
METHODS = ("api", "llm", "manual")
FISCAL_PERIODS = ("FY", "Q1", "H1", "Q3")
FS_DIVS = ("CFS", "OFS")
METRIC_KEYS = (
    "revenue", "operating_income", "net_income",
    "assets", "liabilities", "equity",
)


class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    kind: Mapped[str] = mapped_column(SQLEnum(*NODE_KINDS, name="node_kind"),
                                      nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    attrs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Edge(Base):
    __tablename__ = "edges"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subject_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("nodes.id"), nullable=False, index=True)
    predicate: Mapped[str] = mapped_column(
        SQLEnum(*PREDICATES, name="edge_predicate"), nullable=False, index=True)
    object_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("nodes.id"), nullable=False, index=True)
    period: Mapped[str | None] = mapped_column(String(16))
    qualifier: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_type: Mapped[str] = mapped_column(
        SQLEnum(*SOURCE_TYPES, name="source_type"), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512))
    method: Mapped[str] = mapped_column(SQLEnum(*METHODS, name="method"),
                                        nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    extracted_at: Mapped[_dt] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp())

    # many-to-one → UOW가 Node를 Edge보다 먼저 INSERT하도록 보장
    subject_node: Mapped[Node] = relationship("Node", foreign_keys=[subject_id])
    object_node: Mapped[Node] = relationship("Node", foreign_keys=[object_id])

    __table_args__ = (
        Index(
            "ux_edge_spo",
            text("subject_id"), text("predicate"), text("object_id"),
            text("coalesce(period, '')"),
            unique=True,
        ),
    )


class FinancialFact(Base):
    __tablename__ = "financial_facts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("nodes.id"), nullable=False, index=True)
    bsns_year: Mapped[str] = mapped_column(String(4), nullable=False)
    fiscal_period: Mapped[str] = mapped_column(
        SQLEnum(*FISCAL_PERIODS, name="fiscal_period"), nullable=False)
    fs_div: Mapped[str] = mapped_column(SQLEnum(*FS_DIVS, name="fs_div"),
                                        nullable=False)
    metric_key: Mapped[str] = mapped_column(
        SQLEnum(*METRIC_KEYS, name="metric_key"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(22, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(4), nullable=False, default="KRW")
    source_type: Mapped[str] = mapped_column(
        SQLEnum(*SOURCE_TYPES, name="source_type"), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512))
    method: Mapped[str] = mapped_column(SQLEnum(*METHODS, name="method"),
                                        nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    company: Mapped[Node] = relationship("Node", foreign_keys=[company_id])

    __table_args__ = (
        UniqueConstraint("company_id", "bsns_year", "fiscal_period",
                         "fs_div", "metric_key", name="ux_financial_fact"),
    )


class ConceptAlias(Base):
    __tablename__ = "concept_aliases"
    alias_norm: Mapped[str] = mapped_column(String(256), primary_key=True)
    node_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("nodes.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    node: Mapped[Node] = relationship("Node", foreign_keys=[node_id])
