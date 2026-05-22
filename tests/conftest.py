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
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    yield session
    session.close()
    trans.rollback()
    connection.close()


@pytest.fixture
def fresh_db(engine):
    """CLI/integration 테스트 전 모든 테이블 비우기."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
