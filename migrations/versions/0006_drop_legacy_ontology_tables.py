"""drop legacy relational ontology tables (replaced by graph-core)

Revision ID: 0006_drop_legacy
Revises: 0005_edge_unique
Create Date: 2026-05-31 00:00:00.000000

구 db/models.py의 온톨로지 테이블(business_segments/customer_relations/
geographic_exposures/revenue_compositions)과 미사용 products는 graph-core(nodes/
edges/financial_facts)로 대체되어 코드 미참조 상태다. 일방향 cleanup —
downgrade는 빈 스텁만 재생성하지 않고 명시적으로 미복원한다(데이터/스키마 모두 폐기).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0006_drop_legacy"
down_revision: Union[str, Sequence[str], None] = "0005_edge_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY = [
    "revenue_compositions",
    "geographic_exposures",
    "customer_relations",
    "business_segments",
    "products",
]


def upgrade() -> None:
    for t in _LEGACY:
        op.execute(f"DROP TABLE IF EXISTS {t}")


def downgrade() -> None:
    # 일방향 cleanup: 폐기된 레거시 테이블은 복원하지 않는다.
    raise NotImplementedError(
        "0006 is a one-way cleanup of dead legacy ontology tables")
