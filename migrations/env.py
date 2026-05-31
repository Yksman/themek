from logging.config import fileConfig
from sqlalchemy import engine_from_config, event, pool
from alembic import context
from themek.config import get_settings
from themek.db.engine import Base

# 모든 모델을 import해야 metadata에 포함됨
import themek.db.corp_models  # noqa: F401
import themek.ontology.core.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().postgres_dsn)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite 호환을 위해 batch 모드
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    # SQLite batch 재생성(DROP/RENAME)은 FK 부모 테이블(nodes 등)에서 막힌다.
    # engine.py의 전역 connect 리스너가 PRAGMA foreign_keys=ON을 강제하므로,
    # 마이그레이션 전용 엔진에 한해 raw-connect(autocommit) 시점에 OFF로 덮어쓴다.
    # PRAGMA는 트랜잭션 내부에선 무시되므로 connect 이벤트에서 켜야 효력이 있다.
    if connectable.dialect.name == "sqlite":
        @event.listens_for(connectable, "connect")
        def _disable_fk(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=OFF")
            cur.close()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite 호환
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
