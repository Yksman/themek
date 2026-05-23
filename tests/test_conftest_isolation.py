"""conftest의 테스트 DB 격리가 깨지지 않도록 지키는 메타 테스트.

만약 누가 conftest.py를 다시 production DSN을 사용하도록 바꾸면 이 테스트들이
즉시 빨갛게 떠야 한다 (이전에 pytest가 production themek.db를 통째로 날린
사고가 있었음 — T15/conftest reset 변경의 부작용).
"""
from __future__ import annotations
import os
from pathlib import Path
from themek.config import get_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_DB_PATH = PROJECT_ROOT / "themek.db"


def test_settings_postgres_dsn_is_not_production_db():
    """현재 프로세스가 보는 POSTGRES_DSN이 production ./themek.db가 아니어야 함."""
    settings = get_settings()
    assert settings.postgres_dsn != "sqlite:///./themek.db", (
        "conftest 격리가 깨졌습니다. POSTGRES_DSN이 production DB를 가리킵니다."
    )


def test_engine_fixture_url_differs_from_production(engine):
    """engine fixture의 실제 URL이 production DB 파일과 다른 경로여야 함."""
    db_url_path = str(engine.url).removeprefix("sqlite:///")
    test_db_abs = os.path.abspath(db_url_path)
    prod_db_abs = str(PRODUCTION_DB_PATH)
    assert test_db_abs != prod_db_abs, (
        f"engine fixture가 production DB를 가리킵니다: {test_db_abs}"
    )


def test_engine_fixture_points_to_tempdir(engine):
    """engine fixture는 임시 디렉토리(`themek_pytest_*`)를 써야 함."""
    db_url = str(engine.url)
    assert "themek_pytest_" in db_url, (
        f"engine fixture가 임시 테스트 디렉토리를 사용하지 않습니다: {db_url}"
    )


def test_db_session_writes_do_not_touch_production(db_session):
    """db_session으로 한 INSERT가 production themek.db에 영향을 주지 않아야 함.

    production DB의 mtime이 fixture 동작 전후 동일한지 확인.
    """
    if not PRODUCTION_DB_PATH.exists():
        # production DB가 없으면 검증할 게 없음 — vacuous pass
        return
    mtime_before = PRODUCTION_DB_PATH.stat().st_mtime

    from themek.db.models import Region
    db_session.add(Region(code="ZZ", name_ko="테스트지역", name_en="Test"))
    db_session.flush()

    mtime_after = PRODUCTION_DB_PATH.stat().st_mtime
    assert mtime_before == mtime_after, (
        "db_session 쓰기가 production themek.db를 변경했습니다."
    )
