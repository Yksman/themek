"""create core graph tables (nodes, edges, financial_facts, concept_aliases)

Revision ID: 0004a_core_tables
Revises: 0004_stock_lifecycle
Create Date: 2026-05-31 00:00:00.000000

코어 그래프 테이블은 그동안 Base.metadata.create_all로만 생성되어 어떤 마이그레이션에도
없었다. 그 결과 0005(edges 인덱스)·0007(financial_facts ALTER)이 alembic만으로 만든 fresh
DB에서 'no such table' 로 실패했다. 본 마이그레이션이 0005 이전에 코어 테이블을 만들어 체인을
자립적으로 만든다. models.py와 동일하게 정의하되, ux_edge_spo는 0005, metric_key 확장은 0007이
담당하므로 여기서는 제외(metric_key는 원본 6값).

기존 실 DB는 이미 head(0007)라 본 조상 마이그레이션을 재실행하지 않는다(영향 없음).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004a_core_tables"
down_revision: Union[str, Sequence[str], None] = "0004_stock_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NODE_KINDS = ("company", "stock", "sector", "region", "segment",
               "customer", "period", "metric", "group")
_PREDICATES = ("HAS_SEGMENT", "SELLS_TO", "EXPOSED_TO", "IN_SECTOR",
               "ISSUES_STOCK", "BELONGS_TO_GROUP", "SUB_SECTOR_OF")
_SOURCE_TYPES = ("dart_api", "dart_report", "social", "llm", "manual")
_METHODS = ("api", "llm", "manual")
_FISCAL_PERIODS = ("FY", "Q1", "H1", "Q3")
_FS_DIVS = ("CFS", "OFS")
_METRIC_KEYS = ("revenue", "operating_income", "net_income",
                "assets", "liabilities", "equity")


def upgrade() -> None:
    op.create_table(
        "nodes",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("kind", sa.Enum(*_NODE_KINDS, name="node_kind"),
                  nullable=False),
        sa.Column("label", sa.String(length=256), nullable=False),
        sa.Column("attrs", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nodes_kind", "nodes", ["kind"])

    op.create_table(
        "edges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subject_id", sa.String(length=96), nullable=False),
        sa.Column("predicate", sa.Enum(*_PREDICATES, name="edge_predicate"),
                  nullable=False),
        sa.Column("object_id", sa.String(length=96), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=True),
        sa.Column("qualifier", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.Enum(*_SOURCE_TYPES, name="source_type"),
                  nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=True),
        sa.Column("method", sa.Enum(*_METHODS, name="method"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(),
                  server_default=sa.func.current_timestamp(), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["nodes.id"]),
        sa.ForeignKeyConstraint(["object_id"], ["nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_edges_subject_id", "edges", ["subject_id"])
    op.create_index("ix_edges_predicate", "edges", ["predicate"])
    op.create_index("ix_edges_object_id", "edges", ["object_id"])

    op.create_table(
        "financial_facts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.String(length=96), nullable=False),
        sa.Column("bsns_year", sa.String(length=4), nullable=False),
        sa.Column("fiscal_period",
                  sa.Enum(*_FISCAL_PERIODS, name="fiscal_period"),
                  nullable=False),
        sa.Column("fs_div", sa.Enum(*_FS_DIVS, name="fs_div"), nullable=False),
        sa.Column("metric_key", sa.Enum(*_METRIC_KEYS, name="metric_key"),
                  nullable=False),
        sa.Column("amount", sa.Numeric(precision=22, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=4), nullable=False),
        sa.Column("source_type", sa.Enum(*_SOURCE_TYPES, name="source_type"),
                  nullable=False),
        sa.Column("source_ref", sa.String(length=512), nullable=True),
        sa.Column("method", sa.Enum(*_METHODS, name="method"), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["nodes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "bsns_year", "fiscal_period",
                            "fs_div", "metric_key", name="ux_financial_fact"),
    )
    op.create_index("ix_financial_facts_company_id", "financial_facts",
                    ["company_id"])

    op.create_table(
        "concept_aliases",
        sa.Column("alias_norm", sa.String(length=256), nullable=False),
        sa.Column("node_id", sa.String(length=96), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"]),
        sa.PrimaryKeyConstraint("alias_norm"),
    )


def downgrade() -> None:
    op.drop_table("concept_aliases")
    op.drop_index("ix_financial_facts_company_id", table_name="financial_facts")
    op.drop_table("financial_facts")
    op.drop_index("ix_edges_object_id", table_name="edges")
    op.drop_index("ix_edges_predicate", table_name="edges")
    op.drop_index("ix_edges_subject_id", table_name="edges")
    op.drop_table("edges")
    op.drop_index("ix_nodes_kind", table_name="nodes")
    op.drop_table("nodes")
