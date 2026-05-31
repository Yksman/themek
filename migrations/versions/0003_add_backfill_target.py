"""add_backfill_target_table

Revision ID: 0003_backfill_target
Revises: bb34bb9167b6
Create Date: 2026-05-27 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_backfill_target"
down_revision: Union[str, Sequence[str], None] = "bb34bb9167b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backfill_targets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("corp_code", sa.String(length=8), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "in_progress", "done", "failed", "skipped",
                name="backfill_target_status_enum",
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("rcept_no", sa.String(length=14), nullable=True),
        sa.Column("escalation_level", sa.String(length=32), nullable=True),
        sa.Column("input_chars", sa.Integer(), nullable=True),
        sa.Column("cost_estimate_usd", sa.Numeric(precision=8, scale=4), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.current_timestamp(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(),
            server_default=sa.func.current_timestamp(), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("corp_code", "period", name="ux_backfill_corp_period"),
    )


def downgrade() -> None:
    op.drop_table("backfill_targets")
