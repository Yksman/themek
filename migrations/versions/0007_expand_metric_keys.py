"""expand financial_facts.metric_key enum (eps, cash flows, shares)

Revision ID: 0007_expand_metrics
Revises: 0006_drop_legacy
Create Date: 2026-05-31 00:00:00.000000

SQLite는 CHECK 제약을 in-place ALTER 못 함 → batch_alter_table로 테이블 재생성.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_expand_metrics"
down_revision: Union[str, Sequence[str], None] = "0006_drop_legacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = ("revenue", "operating_income", "net_income",
        "assets", "liabilities", "equity")
_NEW = _OLD + ("eps", "cf_operating", "cf_investing", "cf_financing",
               "shares_outstanding")


def upgrade() -> None:
    with op.batch_alter_table("financial_facts") as batch:
        batch.alter_column(
            "metric_key",
            existing_type=sa.Enum(*_OLD, name="metric_key"),
            type_=sa.Enum(*_NEW, name="metric_key"),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("financial_facts") as batch:
        batch.alter_column(
            "metric_key",
            existing_type=sa.Enum(*_NEW, name="metric_key"),
            type_=sa.Enum(*_OLD, name="metric_key"),
            existing_nullable=False,
        )
