"""expand node_kind(person) + edge_predicate(OWNS_STAKE_IN)

Revision ID: 0008_equity_ownership
Revises: 0007_expand_metrics
Create Date: 2026-06-01 00:00:00.000000

이 마이그레이션은 DB 스키마를 변경하지 않는 **버전 체인 전진용 no-op**이다.

근거:
- `nodes.kind` / `edges.predicate`는 SQLAlchemy `Enum`(create_constraint=False)으로
  정의되어 SQLite에선 CHECK 제약 없는 평범한 VARCHAR로 생성된다(`kind VARCHAR(8)`,
  `predicate VARCHAR(16)`). 즉 enum 허용값 집합은 DB가 아니라 models.py의
  `NODE_KINDS`/`PREDICATES` 튜플(Python 레벨)에서만 강제된다.
- 신규 값 `"person"`(6자)·`"OWNS_STAKE_IN"`(13자)은 기존 컬럼 길이(8/16) 안에 들어가므로
  ALTER가 필요 없다.
- 따라서 `batch_alter_table`로 테이블을 재생성하면 0005의 표현식 기반 unique 인덱스
  `ux_edge_spo`(`coalesce(period,'')`)가 reflect되지 못해 유실되는 부작용만 생긴다.
  이를 피하기 위해 본 리비전은 의도적으로 아무 DDL도 실행하지 않는다.
"""
from typing import Sequence, Union

revision: str = "0008_equity_ownership"
down_revision: Union[str, Sequence[str], None] = "0007_expand_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # no-op: enum 허용값은 models.py(NODE_KINDS/PREDICATES)에서 강제, DB 스키마 불변.
    pass


def downgrade() -> None:
    # no-op
    pass
