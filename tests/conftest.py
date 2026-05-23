"""pytest 공통 fixture.

테스트 격리 정책:
- pytest 시작 즉시 POSTGRES_DSN을 임시 파일로 override해서 production
  ./themek.db를 절대 건드리지 않도록 강제한다. themek 코드를 import하기
  전에 이 작업을 해야 Settings()가 새 환경변수를 읽는다.
"""
import os
import tempfile
from pathlib import Path

# --- 격리 가드: themek import 전에 환경변수 set ---
_TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="themek_pytest_"))
_TEST_DB_PATH = _TEST_DB_DIR / "test.db"
os.environ["POSTGRES_DSN"] = f"sqlite:///{_TEST_DB_PATH}"
# --- 격리 가드 끝 ---

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from themek.db.engine import Base
import themek.db.models  # noqa: F401 — 모든 모델 등록


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(f"sqlite:///{_TEST_DB_PATH}", future=True)
    yield eng


@pytest.fixture
def db_session(engine):
    # 매 테스트 시작 시 schema reset (테스트 간 state 누수 방지)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    connection = engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    yield session
    session.close()
    try:
        trans.rollback()
    except Exception:
        pass
    connection.close()


@pytest.fixture
def fresh_db(engine):
    """CLI/integration 테스트 전 모든 테이블 비우기."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
