"""expand node_kind(person) + edge_predicate(OWNS_STAKE_IN)

Revision ID: 0008_equity_ownership
Revises: 0007_expand_metrics
Create Date: 2026-06-01 00:00:00.000000

SQLite는 CHECK 제약을 in-place ALTER 못 함 → batch_alter_table로 테이블 재생성.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_equity_ownership"
down_revision: Union[str, Sequence[str], None] = "0007_expand_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KIND_OLD = ("company", "stock", "sector", "region", "segment",
             "customer", "period", "metric", "group")
_KIND_NEW = _KIND_OLD + ("person",)
_PRED_OLD = ("HAS_SEGMENT", "SELLS_TO", "EXPOSED_TO", "IN_SECTOR",
             "ISSUES_STOCK", "BELONGS_TO_GROUP", "SUB_SECTOR_OF")
_PRED_NEW = _PRED_OLD + ("OWNS_STAKE_IN",)


def upgrade() -> None:
    # nodes는 edges/financial_facts/concept_aliases의 FK 부모 → batch 재생성 시
    # DROP TABLE nodes가 FK 강제에 걸린다. SQLite FK 강제는 마이그레이션 트랜잭션
    # 밖에서 env.py가 끈다(render_as_batch + foreign_keys=OFF).
    with op.batch_alter_table("nodes") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*_KIND_OLD, name="node_kind"),
            type_=sa.Enum(*_KIND_NEW, name="node_kind"),
            existing_nullable=False,
        )
    with op.batch_alter_table("edges") as batch:
        batch.alter_column(
            "predicate",
            existing_type=sa.Enum(*_PRED_OLD, name="edge_predicate"),
            type_=sa.Enum(*_PRED_NEW, name="edge_predicate"),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("edges") as batch:
        batch.alter_column(
            "predicate",
            existing_type=sa.Enum(*_PRED_NEW, name="edge_predicate"),
            type_=sa.Enum(*_PRED_OLD, name="edge_predicate"),
            existing_nullable=False,
        )
    with op.batch_alter_table("nodes") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*_KIND_NEW, name="node_kind"),
            type_=sa.Enum(*_KIND_OLD, name="node_kind"),
            existing_nullable=False,
        )
