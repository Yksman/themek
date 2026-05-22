import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from themek.config import get_settings
from themek.db.engine import Base
import themek.db.models  # noqa: F401 — 모든 모델 등록


@pytest.fixture(scope="session")
def engine():
    settings = get_settings()
    eng = create_engine(settings.postgres_dsn, future=True)
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
