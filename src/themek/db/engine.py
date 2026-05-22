from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from themek.config import get_settings


class Base(DeclarativeBase):
    pass


# SQLite는 기본적으로 FK 강제 안 함. PRAGMA로 켜야 CHECK constraint와 함께 정상 동작.
@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        # 비-SQLite 드라이버는 무시
        pass


def make_engine():
    settings = get_settings()
    return create_engine(settings.postgres_dsn, echo=False, future=True)


def make_session_factory(engine=None):
    eng = engine or make_engine()
    return sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
