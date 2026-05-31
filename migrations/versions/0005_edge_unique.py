"""add unique index on edges (subject, predicate, object, coalesce(period))

Revision ID: 0005_edge_unique
Revises: 0004a_core_tables
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0005_edge_unique"
down_revision: Union[str, Sequence[str], None] = "0004a_core_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX ux_edge_spo ON edges "
        "(subject_id, predicate, object_id, coalesce(period, ''))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ux_edge_spo")
