"""BackfillTarget model + 비용 컬럼 + UNIQUE constraint."""
import pytest
from sqlalchemy import select

from themek.db.corp_models import BackfillTarget


def test_backfill_target_creates(db_session):
    t = BackfillTarget(corp_code="00126380", period="2025", status="pending")
    db_session.add(t)
    db_session.commit()
    row = db_session.scalar(
        select(BackfillTarget).where(BackfillTarget.corp_code == "00126380")
    )
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.escalation_level is None
    assert row.input_chars is None
    assert row.cost_estimate_usd is None


def test_backfill_target_unique_corp_period(db_session):
    db_session.add(BackfillTarget(
        corp_code="00126380", period="2025", status="pending",
    ))
    db_session.commit()
    db_session.add(BackfillTarget(
        corp_code="00126380", period="2025", status="pending",
    ))
    with pytest.raises(Exception):
        db_session.commit()


def test_backfill_target_cost_columns_updatable(db_session):
    """ingest 완료 후 컬럼 채워질 수 있다."""
    t = BackfillTarget(
        corp_code="00126380", period="2025", status="done",
        escalation_level="regex", input_chars=38000,
        cost_estimate_usd=0.33,
    )
    db_session.add(t)
    db_session.commit()
    row = db_session.scalar(select(BackfillTarget))
    assert row.escalation_level == "regex"
    assert row.input_chars == 38000
    assert float(row.cost_estimate_usd) == 0.33
