"""add_stock_lifecycle_columns

Revision ID: 0004_stock_lifecycle
Revises: 0003_backfill_target
Create Date: 2026-05-27 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_stock_lifecycle"
down_revision: Union[str, Sequence[str], None] = "0003_backfill_target"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("stocks") as batch:
        batch.add_column(sa.Column("delisted_at", sa.Date(), nullable=True))
        batch.add_column(sa.Column("last_seen_at", sa.Date(), nullable=True))
        batch.add_column(sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.current_timestamp(), nullable=True,
        ))


def downgrade() -> None:
    with op.batch_alter_table("stocks") as batch:
        batch.drop_column("created_at")
        batch.drop_column("last_seen_at")
        batch.drop_column("delisted_at")
