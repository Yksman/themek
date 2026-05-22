# E5 Walking Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자가 "이 회사 뭐 만들어? 매출 어디서 남?"(E5)에 대해 한 종목의 DART 사업보고서를 ingest해 구조화·저장한 뒤 인용·구조와 함께 답하는 end-to-end vertical slice를 완성한다.

**Architecture:** 4-layer 슬라이스. (1) Postgres에 ontology spec의 핵심 클래스(Stock, Corporation, BusinessReport, BusinessSegment, RevenueComposition, CustomerRelation, GeographicExposure 등) 일부를 구현. (2) DART 사업보고서 HTML fixture → 섹션 추출 parser. (3) Claude Code CLI(`claude -p`) subprocess를 호출하는 LLM extractor가 텍스트를 Pydantic-validated 구조화 데이터로 변환 후 DB에 저장 (idempotent). (4) typer CLI가 `query e5 --stock <ticker>` 받으면 DB traversal + Jinja template으로 자연어 답을 인용과 함께 출력.

**Tech Stack:** Python 3.12, PostgreSQL 16, SQLAlchemy 2.0, Alembic, Pydantic v2, typer, Jinja2, pytest, uv, docker-compose, Claude Code CLI (`claude -p`).

---

## Prerequisites

- Python 3.12+ (`python --version`)
- `uv` installed (`brew install uv` 또는 [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/))
- Docker + docker-compose (`docker --version`, `docker compose version`)
- Claude Code CLI 설치되어 있고 로그인됨 (`claude --version` 확인). 구독 활성 상태.
- DART OpenDART API key는 **이번 plan에선 불필요** — 사업보고서를 수동으로 1건 다운로드해서 fixture로 사용한다. 실제 API client는 후속 plan.

## Scope (in / out)

**In:**
- E5 ("이 회사 뭐 만들어?") 한 CQ를 ticker 단일 입력으로 답하기
- DART 사업보고서 1건 수동 fixture → LLM 추출 → DB 저장 → 쿼리 → 답변
- Ontology spec의 다음 클래스: `Stock`, `Corporation`, `Sector`, `Region`, `BusinessReport`, `BusinessSegment`, `Product`, `RevenueComposition`, `CustomerRelation`, `GeographicExposure`

**Out (이 plan 범위 밖):**
- 다른 CQs (E1~E4, E6~E8) — 후속 plan
- DART API client (자동 fetch) — 후속 plan
- Theme / Narrative / Membership / Activation — 후속 plan (E2·E3·E6 위해 필요)
- pgvector / 벡터 인덱스 — 후속 plan (E2·E4)
- 사용자 인터페이스(웹/UI) — 후속 plan
- 대규모 backfill — 후속 plan

## File Structure

```
themek/
├── pyproject.toml                     # uv-managed
├── .env.example                       # POSTGRES_DSN 등
├── .env                               # gitignored
├── docker-compose.yml                 # postgres 16
├── alembic.ini
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_market_entities.py
│       └── 0002_business_structure.py
├── src/themek/
│   ├── __init__.py
│   ├── config.py                      # Pydantic Settings
│   ├── db/
│   │   ├── __init__.py
│   │   ├── engine.py                  # SQLAlchemy engine + Session factory
│   │   └── models.py                  # SQLAlchemy declarative models
│   ├── dart/
│   │   ├── __init__.py
│   │   └── parser.py                  # 사업보고서 HTML → section text
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── schemas.py                 # Pydantic 추출 결과 모델
│   │   ├── prompts.py                 # 추출 prompt 템플릿
│   │   └── claude_cli.py              # `claude -p` subprocess wrapper
│   ├── ingest/
│   │   ├── __init__.py
│   │   └── business_report.py         # parser → LLM → DB 저장
│   ├── query/
│   │   ├── __init__.py
│   │   ├── e5.py                      # ticker → 구조 traversal
│   │   ├── templates/
│   │   │   └── e5_answer.txt.j2       # Jinja 템플릿
│   │   └── synthesize.py              # 구조 + 템플릿 → 자연어 답
│   ├── seeds.py                       # 샘플 Stock/Corp/Sector/Region
│   └── cli.py                         # typer entrypoint
└── tests/
    ├── conftest.py                    # DB session fixture
    ├── test_config.py
    ├── test_db_models.py
    ├── test_dart_parser.py
    ├── test_llm_schemas.py
    ├── test_claude_cli.py             # subprocess mock
    ├── test_ingest_business_report.py # mock LLM
    ├── test_query_e5.py
    ├── test_synthesize_e5.py
    ├── test_cli.py
    └── fixtures/
        ├── samsung_business_report_excerpt.html
        └── samsung_extraction_expected.json
```

---

## Task 1: 프로젝트 스캐폴드

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `docker-compose.yml`
- Create: `src/themek/__init__.py` (빈 파일)
- Create: `tests/__init__.py` (빈 파일)

- [ ] **Step 1: pyproject.toml 생성**

```toml
[project]
name = "themek"
version = "0.1.0"
description = "Korean theme stock ontology"
requires-python = ">=3.12"
dependencies = [
    "sqlalchemy>=2.0.30",
    "alembic>=1.13",
    "psycopg[binary]>=3.2",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "typer>=0.12",
    "jinja2>=3.1",
    "structlog>=24.1",
    "beautifulsoup4>=4.12",
    "lxml>=5.2",
]

[dependency-groups]
dev = [
    "pytest>=8.2",
    "pytest-mock>=3.14",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/themek"]
```

- [ ] **Step 2: .env.example 생성**

```env
# Postgres
POSTGRES_DSN=postgresql+psycopg://themek:themek@localhost:5432/themek

# Logging
LOG_LEVEL=INFO

# Claude CLI
# Claude Code must be installed and authenticated separately (claude login).
# No API key needed when using subscription.
CLAUDE_CLI_BIN=claude
CLAUDE_CLI_TIMEOUT_SEC=120
```

- [ ] **Step 3: docker-compose.yml 생성**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: themek
      POSTGRES_USER: themek
      POSTGRES_PASSWORD: themek
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "themek"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

- [ ] **Step 4: 빈 패키지 파일 생성**

```bash
mkdir -p src/themek tests
touch src/themek/__init__.py tests/__init__.py
```

- [ ] **Step 5: 의존성 설치 및 docker 기동 검증**

```bash
uv sync
docker compose up -d
docker compose ps
```

Expected: postgres 서비스가 `healthy` 상태로 표시됨.

- [ ] **Step 6: 커밋**

```bash
cp .env.example .env  # local만, gitignore됨
git add pyproject.toml .env.example docker-compose.yml src/themek/__init__.py tests/__init__.py
git commit -m "feat: scaffold Python project with Postgres compose"
```

---

## Task 2: 설정 + 로깅

**Files:**
- Create: `src/themek/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_config.py`

```python
import os
from themek.config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgresql+psycopg://x:y@z/w")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    s = Settings()
    assert s.postgres_dsn == "postgresql+psycopg://x:y@z/w"
    assert s.log_level == "DEBUG"


def test_settings_defaults_for_claude_cli(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgresql+psycopg://x:y@z/w")
    s = Settings()
    assert s.claude_cli_bin == "claude"
    assert s.claude_cli_timeout_sec == 120
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `ImportError: cannot import name 'Settings' from 'themek.config'` (모듈 없음)

- [ ] **Step 3: 최소 구현** — `src/themek/config.py`

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    postgres_dsn: str = Field(...)
    log_level: str = Field(default="INFO")
    claude_cli_bin: str = Field(default="claude")
    claude_cli_timeout_sec: int = Field(default=120)


def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/config.py tests/test_config.py
git commit -m "feat(config): add Pydantic settings with env loading"
```

---

## Task 3: DB Engine + Alembic 초기화

**Files:**
- Create: `src/themek/db/__init__.py` (빈)
- Create: `src/themek/db/engine.py`
- Create: `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`

- [ ] **Step 1: db/engine.py 작성**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from themek.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine():
    settings = get_settings()
    return create_engine(settings.postgres_dsn, echo=False, future=True)


def make_session_factory(engine=None):
    eng = engine or make_engine()
    return sessionmaker(bind=eng, expire_on_commit=False, class_=Session)
```

- [ ] **Step 2: alembic init**

```bash
mkdir -p src/themek/db
touch src/themek/db/__init__.py
uv run alembic init migrations
```

- [ ] **Step 3: alembic.ini 편집 — sqlalchemy.url 비우기**

`alembic.ini`에서 `sqlalchemy.url = driver://user:pass@localhost/dbname` 줄을 다음으로 교체:

```ini
sqlalchemy.url =
```

(env.py에서 동적으로 채울 것이라 비워둠.)

- [ ] **Step 4: migrations/env.py 편집**

`migrations/env.py`를 다음과 같이 교체:

```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from themek.config import get_settings
from themek.db.engine import Base

# 모든 모델을 import해야 metadata에 포함됨
import themek.db.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().postgres_dsn)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 5: 비어있는 models.py 생성**

```bash
touch src/themek/db/models.py
```

내용:
```python
"""SQLAlchemy declarative models. 모델은 후속 Task에서 추가됨."""
from themek.db.engine import Base  # noqa: F401
```

- [ ] **Step 6: 빈 alembic 검증**

```bash
uv run alembic current
```

Expected: 출력 없음 (아직 마이그레이션 없음). 에러 없이 종료되면 OK.

- [ ] **Step 7: 커밋**

```bash
git add src/themek/db/ alembic.ini migrations/
git commit -m "feat(db): set up SQLAlchemy engine and Alembic"
```

---

## Task 4: Schema Phase 1 — Market Entities

ontology spec의 `Stock`, `Corporation`, `Sector`, `Region`을 구현. `Group`·`Figure`는 후속 plan.

**Files:**
- Modify: `src/themek/db/models.py`
- Create: `migrations/versions/0001_market_entities.py`
- Create: `tests/conftest.py`
- Create: `tests/test_db_models.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_db_models.py`

```python
from themek.db.models import Stock, Corporation, Sector, Region


def test_stock_creation(db_session):
    sector = Sector(fics_code="G2520", name_ko="반도체")
    corp = Corporation(dart_code="00126380", name_ko="삼성전자", in_sector=sector)
    stock = Stock(ticker="005930", name_ko="삼성전자", share_class="common",
                  market="KOSPI", issued_by=corp)
    db_session.add_all([sector, corp, stock])
    db_session.commit()

    fetched = db_session.get(Stock, "005930")
    assert fetched.name_ko == "삼성전자"
    assert fetched.issued_by.dart_code == "00126380"
    assert fetched.issued_by.in_sector.fics_code == "G2520"


def test_region_enum(db_session):
    kr = Region(code="KR", name_ko="국내")
    db_session.add(kr)
    db_session.commit()
    assert db_session.get(Region, "KR").name_ko == "국내"


def test_corporation_belongs_to_group_optional(db_session):
    corp = Corporation(dart_code="00111111", name_ko="테스트법인")
    db_session.add(corp)
    db_session.commit()
    assert db_session.get(Corporation, "00111111").belongs_to_id is None
```

- [ ] **Step 2: conftest.py 작성** — `tests/conftest.py`

```python
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
```

- [ ] **Step 3: 실패 확인**

```bash
docker compose up -d
uv run pytest tests/test_db_models.py -v
```

Expected: `ImportError: cannot import name 'Stock' from 'themek.db.models'`.

- [ ] **Step 4: 모델 구현** — `src/themek/db/models.py` 교체

```python
"""SQLAlchemy declarative models for themek ontology."""
from __future__ import annotations
from typing import Optional
from sqlalchemy import String, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from themek.db.engine import Base


class Sector(Base):
    __tablename__ = "sectors"
    fics_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(128), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(128))
    parent_sector_id: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("sectors.fics_code")
    )

    parent_sector: Mapped[Optional["Sector"]] = relationship(remote_side=[fics_code])


class Region(Base):
    __tablename__ = "regions"
    code: Mapped[str] = mapped_column(String(8), primary_key=True)  # KR, US, EU...
    name_ko: Mapped[str] = mapped_column(String(64), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(64))


# Group은 후속 plan에서 본격 활용. 여기선 placeholder.
class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name_ko: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)


class Corporation(Base):
    __tablename__ = "corporations"
    dart_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(256), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(256))
    wikidata_qid: Mapped[Optional[str]] = mapped_column(String(32))

    in_sector_id: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("sectors.fics_code")
    )
    in_sector: Mapped[Optional[Sector]] = relationship()

    belongs_to_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("groups.id")
    )
    belongs_to: Mapped[Optional[Group]] = relationship()


class Stock(Base):
    __tablename__ = "stocks"
    ticker: Mapped[str] = mapped_column(String(6), primary_key=True)
    isin: Mapped[Optional[str]] = mapped_column(String(12))
    name_ko: Mapped[str] = mapped_column(String(256), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(256))
    share_class: Mapped[str] = mapped_column(
        SQLEnum("common", "preferred", name="share_class_enum"),
        nullable=False, default="common"
    )
    market: Mapped[str] = mapped_column(
        SQLEnum("KOSPI", "KOSDAQ", "KONEX", name="market_enum"),
        nullable=False
    )

    issued_by_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("corporations.dart_code"), nullable=False
    )
    issued_by: Mapped[Corporation] = relationship()
```

- [ ] **Step 5: 마이그레이션 생성**

```bash
uv run alembic revision --autogenerate -m "market entities: stock, corporation, sector, region, group"
```

Expected: `migrations/versions/<hash>_market_entities_...py` 파일 생성됨. 파일을 `migrations/versions/0001_market_entities.py`로 rename.

- [ ] **Step 6: 마이그레이션 적용**

```bash
uv run alembic upgrade head
```

Expected: `INFO  [alembic.runtime.migration] Running upgrade  -> ...` 메시지.

- [ ] **Step 7: 테스트 통과 확인**

```bash
uv run pytest tests/test_db_models.py -v
```

Expected: 3 passed.

- [ ] **Step 8: 커밋**

```bash
git add src/themek/db/models.py migrations/versions/ tests/conftest.py tests/test_db_models.py
git commit -m "feat(db): add Stock, Corporation, Sector, Region, Group models"
```

---

## Task 5: Schema Phase 2 — Business Structure

`BusinessReport`, `BusinessSegment`, `Product`, `RevenueComposition`, `CustomerRelation`, `GeographicExposure`을 추가.

**Files:**
- Modify: `src/themek/db/models.py`
- Create: `migrations/versions/0002_business_structure.py`
- Modify: `tests/test_db_models.py`

- [ ] **Step 1: 실패 테스트 작성 — 기존 파일 끝에 추가**

```python
import uuid
from datetime import date
from themek.db.models import (
    BusinessReport, BusinessSegment, Product, RevenueComposition,
    CustomerRelation, GeographicExposure,
)


def test_business_report_and_segment(db_session):
    corp = Corporation(dart_code="00126380", name_ko="삼성전자")
    db_session.add(corp)
    db_session.flush()

    report = BusinessReport(
        dart_rcept_no="20240314000123",
        corporation=corp,
        report_type="사업보고서",
        period="2023",
        filing_date=date(2024, 3, 14),
        url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123",
    )
    seg = BusinessSegment(
        id=str(uuid.uuid4()),
        corporation=corp,
        name_ko="메모리반도체",
    )
    db_session.add_all([report, seg])
    db_session.commit()

    assert db_session.get(BusinessReport, "20240314000123").corporation.name_ko == "삼성전자"
    assert seg.corporation_id == "00126380"


def test_revenue_composition_links_segment(db_session):
    corp = Corporation(dart_code="00126380", name_ko="삼성전자")
    db_session.add(corp)
    db_session.flush()
    report = BusinessReport(
        dart_rcept_no="20240314000123", corporation=corp,
        report_type="사업보고서", period="2023", filing_date=date(2024, 3, 14),
    )
    seg = BusinessSegment(id=str(uuid.uuid4()), corporation=corp, name_ko="DS")
    db_session.add_all([report, seg])
    db_session.flush()

    rc = RevenueComposition(
        id=str(uuid.uuid4()),
        subject_corp_id=None, subject_segment_id=seg.id,
        period="2023", share_pct=42.5, source_report=report,
    )
    db_session.add(rc)
    db_session.commit()
    fetched = db_session.get(RevenueComposition, rc.id)
    assert fetched.share_pct == 42.5
    assert fetched.subject_segment_id == seg.id


def test_customer_relation_resolved_flag(db_session):
    seller = Corporation(dart_code="00111111", name_ko="공급사")
    buyer = Corporation(dart_code="00222222", name_ko="고객사A")
    db_session.add_all([seller, buyer])
    db_session.flush()
    report = BusinessReport(
        dart_rcept_no="20240315000001", corporation=seller,
        report_type="사업보고서", period="2023", filing_date=date(2024, 3, 15),
    )
    db_session.add(report)
    db_session.flush()
    cr = CustomerRelation(
        id=str(uuid.uuid4()),
        seller=seller, buyer_corp_id=buyer.dart_code,
        buyer_raw=None, resolved=True,
        period="2023", revenue_share_pct=18.2, tier="1차",
        source_report=report,
    )
    db_session.add(cr)
    db_session.commit()
    assert cr.resolved is True
    assert cr.buyer_corp_id == "00222222"


def test_customer_relation_unresolved_buyer(db_session):
    seller = Corporation(dart_code="00333333", name_ko="공급사B")
    db_session.add(seller)
    db_session.flush()
    report = BusinessReport(
        dart_rcept_no="20240316000001", corporation=seller,
        report_type="사업보고서", period="2023", filing_date=date(2024, 3, 16),
    )
    db_session.add(report)
    db_session.flush()
    cr = CustomerRelation(
        id=str(uuid.uuid4()),
        seller=seller, buyer_corp_id=None, buyer_raw="해외 고객 (이름 비공개)",
        resolved=False, period="2023", tier="unknown",
        source_report=report,
    )
    db_session.add(cr)
    db_session.commit()
    assert cr.resolved is False
    assert cr.buyer_raw == "해외 고객 (이름 비공개)"
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_db_models.py -v
```

Expected: ImportError on new model names.

- [ ] **Step 3: models.py에 추가**

`src/themek/db/models.py` 끝에 추가:

```python
from datetime import date as _date
from sqlalchemy import Date, Numeric, Boolean, Text, CheckConstraint


class BusinessReport(Base):
    __tablename__ = "business_reports"
    dart_rcept_no: Mapped[str] = mapped_column(String(14), primary_key=True)
    corporation_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("corporations.dart_code"), nullable=False
    )
    corporation: Mapped[Corporation] = relationship()
    report_type: Mapped[str] = mapped_column(
        SQLEnum("사업보고서", "반기보고서", "분기보고서", name="report_type_enum"),
        nullable=False,
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False)  # "2023", "2024Q3"
    filing_date: Mapped[_date] = mapped_column(Date, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(512))


class BusinessSegment(Base):
    __tablename__ = "business_segments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    corporation_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("corporations.dart_code"), nullable=False
    )
    corporation: Mapped[Corporation] = relationship()
    name_ko: Mapped[str] = mapped_column(String(256), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(256))
    description: Mapped[Optional[str]] = mapped_column(Text)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(256), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(256))
    category: Mapped[Optional[str]] = mapped_column(String(128))


class RevenueComposition(Base):
    __tablename__ = "revenue_compositions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # subject는 Corp or Segment 둘 중 하나
    subject_corp_id: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("corporations.dart_code")
    )
    subject_segment_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("business_segments.id")
    )
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    share_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    absolute_value: Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    source_report_id: Mapped[str] = mapped_column(
        String(14), ForeignKey("business_reports.dart_rcept_no"), nullable=False
    )
    source_report: Mapped[BusinessReport] = relationship()

    __table_args__ = (
        CheckConstraint(
            "(subject_corp_id IS NOT NULL) <> (subject_segment_id IS NOT NULL)",
            name="rc_subject_exactly_one",
        ),
    )


class CustomerRelation(Base):
    __tablename__ = "customer_relations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    seller_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("corporations.dart_code"), nullable=False
    )
    seller: Mapped[Corporation] = relationship(foreign_keys=[seller_id])
    buyer_corp_id: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("corporations.dart_code")
    )
    buyer_corp: Mapped[Optional[Corporation]] = relationship(foreign_keys=[buyer_corp_id])
    buyer_raw: Mapped[Optional[str]] = mapped_column(String(256))
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    revenue_share_pct: Mapped[Optional[float]] = mapped_column(Numeric(5, 2))
    tier: Mapped[str] = mapped_column(
        SQLEnum("1차", "2차", "unknown", name="customer_tier_enum"),
        nullable=False, default="unknown",
    )
    source_report_id: Mapped[str] = mapped_column(
        String(14), ForeignKey("business_reports.dart_rcept_no"), nullable=False
    )
    source_report: Mapped[BusinessReport] = relationship()

    __table_args__ = (
        CheckConstraint(
            "(buyer_corp_id IS NOT NULL) OR (buyer_raw IS NOT NULL)",
            name="cr_buyer_present",
        ),
    )


class GeographicExposure(Base):
    __tablename__ = "geographic_exposures"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_corp_id: Mapped[Optional[str]] = mapped_column(
        String(8), ForeignKey("corporations.dart_code")
    )
    subject_segment_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("business_segments.id")
    )
    region_id: Mapped[str] = mapped_column(
        String(8), ForeignKey("regions.code"), nullable=False
    )
    region: Mapped[Region] = relationship()
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    share_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    source_report_id: Mapped[str] = mapped_column(
        String(14), ForeignKey("business_reports.dart_rcept_no"), nullable=False
    )
    source_report: Mapped[BusinessReport] = relationship()

    __table_args__ = (
        CheckConstraint(
            "(subject_corp_id IS NOT NULL) <> (subject_segment_id IS NOT NULL)",
            name="ge_subject_exactly_one",
        ),
    )
```

- [ ] **Step 4: 마이그레이션 생성 + 적용**

```bash
uv run alembic revision --autogenerate -m "business structure: report, segment, product, revenue, customer, geographic"
# 생성된 파일을 migrations/versions/0002_business_structure.py 로 rename
uv run alembic upgrade head
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest tests/test_db_models.py -v
```

Expected: 모든 테스트 (Task 4 + Task 5) passed.

- [ ] **Step 6: 커밋**

```bash
git add src/themek/db/models.py migrations/versions/0002_*.py tests/test_db_models.py
git commit -m "feat(db): add BusinessReport, Segment, Product, Revenue, Customer, Geographic"
```

---

## Task 6: Seed Data

샘플 Sector / Region / Corporation / Stock을 idempotent하게 삽입.

**Files:**
- Create: `src/themek/seeds.py`
- Create: `tests/test_seeds.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_seeds.py`

```python
from themek.seeds import seed_basic
from themek.db.models import Stock, Corporation, Sector, Region


def test_seed_basic_creates_entities(db_session):
    seed_basic(db_session)
    db_session.commit()
    assert db_session.get(Stock, "005930").name_ko == "삼성전자"
    assert db_session.get(Stock, "277810").name_ko == "레인보우로보틱스"
    assert db_session.get(Region, "KR").name_ko == "국내"
    assert db_session.get(Corporation, "00126380").name_ko == "삼성전자"


def test_seed_basic_is_idempotent(db_session):
    seed_basic(db_session)
    db_session.commit()
    seed_basic(db_session)
    db_session.commit()
    count = db_session.query(Stock).count()
    assert count == 3  # 005930, 277810, 005380 등 picked sample
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_seeds.py -v
```

Expected: ImportError.

- [ ] **Step 3: seeds 구현** — `src/themek/seeds.py`

```python
"""샘플 데이터 시드. Walking skeleton에서는 3개 종목만."""
from sqlalchemy.orm import Session
from themek.db.models import Stock, Corporation, Sector, Region

SECTORS = [
    {"fics_code": "G2520", "name_ko": "반도체", "name_en": "Semiconductors"},
    {"fics_code": "G2570", "name_ko": "자동차 및 부품", "name_en": "Auto Components"},
    {"fics_code": "G2030", "name_ko": "산업기계", "name_en": "Industrial Machinery"},
]

REGIONS = [
    {"code": "KR", "name_ko": "국내", "name_en": "Korea"},
    {"code": "US", "name_ko": "미주", "name_en": "Americas"},
    {"code": "EU", "name_ko": "유럽", "name_en": "Europe"},
    {"code": "CN", "name_ko": "중국", "name_en": "China"},
    {"code": "JP", "name_ko": "일본", "name_en": "Japan"},
    {"code": "ROW", "name_ko": "기타", "name_en": "Rest of World"},
]

CORPORATIONS = [
    {"dart_code": "00126380", "name_ko": "삼성전자", "in_sector_id": "G2520"},
    {"dart_code": "00164742", "name_ko": "현대자동차", "in_sector_id": "G2570"},
    {"dart_code": "01133360", "name_ko": "레인보우로보틱스", "in_sector_id": "G2030"},
]

STOCKS = [
    {"ticker": "005930", "name_ko": "삼성전자", "market": "KOSPI",
     "share_class": "common", "issued_by_id": "00126380"},
    {"ticker": "005380", "name_ko": "현대차", "market": "KOSPI",
     "share_class": "common", "issued_by_id": "00164742"},
    {"ticker": "277810", "name_ko": "레인보우로보틱스", "market": "KOSDAQ",
     "share_class": "common", "issued_by_id": "01133360"},
]


def _upsert(session: Session, model, data: dict, pk_field: str):
    pk = data[pk_field]
    existing = session.get(model, pk)
    if existing is None:
        session.add(model(**data))


def seed_basic(session: Session) -> None:
    for row in SECTORS:
        _upsert(session, Sector, row, "fics_code")
    for row in REGIONS:
        _upsert(session, Region, row, "code")
    session.flush()
    for row in CORPORATIONS:
        _upsert(session, Corporation, row, "dart_code")
    session.flush()
    for row in STOCKS:
        _upsert(session, Stock, row, "ticker")
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_seeds.py -v
```

Expected: 2 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/seeds.py tests/test_seeds.py
git commit -m "feat(seeds): add 3 sample stocks/corps with idempotent upsert"
```

---

## Task 7: DART 사업보고서 Fixture

이 plan에선 API client 안 만들고, 1건을 수동 다운로드해 fixture로 사용.

**Files:**
- Create: `tests/fixtures/samsung_business_report_excerpt.html`

- [ ] **Step 1: DART에서 삼성전자 2023 사업보고서 본문 발췌**

브라우저로 DART 접속:
- https://dart.fss.or.kr/
- 검색: "삼성전자 사업보고서 2023"
- 정기공시 → 사업보고서 (2024-03-14 제출, rcept_no=20240314000123 예시)
- 보고서 본문 → "II. 사업의 내용" 섹션 진입

해당 페이지의 "1. 사업의 개요" + "2. 주요 제품 및 서비스" + "3. 원재료 및 생산설비" + "4. 매출 및 수주상황" 부분의 HTML을 복사 (대략 1-3K 자 분량).

저장 경로: `tests/fixtures/samsung_business_report_excerpt.html`

(목적: 진짜 DART HTML 구조에 가까운 표·텍스트가 섞인 상태로 parser·LLM이 다룰 수 있는지 검증. 전체가 아니라 발췌만 — 100% 사실성보다 *구조 다양성*이 중요.)

- [ ] **Step 2: 파일 길이 sanity check**

```bash
wc -l tests/fixtures/samsung_business_report_excerpt.html
```

Expected: 50~500 줄 정도. 너무 짧으면 (10줄 미만) 의미 있는 추출 어려움. 너무 길면 (10000줄+) LLM token 부담.

- [ ] **Step 3: 커밋**

```bash
git add tests/fixtures/samsung_business_report_excerpt.html
git commit -m "test: add Samsung business report excerpt fixture"
```

---

## Task 8: DART Parser

HTML fixture에서 의미 있는 텍스트 섹션을 추출 (LLM에 넣기 위한 전처리).

**Files:**
- Create: `src/themek/dart/__init__.py` (빈)
- Create: `src/themek/dart/parser.py`
- Create: `tests/test_dart_parser.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_dart_parser.py`

```python
from pathlib import Path
from themek.dart.parser import extract_business_content


FIXTURE = Path(__file__).parent / "fixtures" / "samsung_business_report_excerpt.html"


def test_extract_business_content_returns_text():
    html = FIXTURE.read_text(encoding="utf-8")
    text = extract_business_content(html)
    assert isinstance(text, str)
    assert len(text) > 200  # 의미 있는 분량
    # 표 텍스트가 일부 포함되어야 함 (사업보고서엔 표가 흔함)
    assert any(token in text for token in ["매출", "사업", "제품"])


def test_extract_business_content_strips_html_tags():
    html = "<html><body><h1>제목</h1><p>내용입니다</p><table><tr><td>표</td></tr></table></body></html>"
    text = extract_business_content(html)
    assert "<" not in text
    assert "제목" in text
    assert "내용입니다" in text


def test_extract_business_content_preserves_whitespace_reasonably():
    html = "<html><body><p>줄1</p><p>줄2</p></body></html>"
    text = extract_business_content(html)
    assert "줄1" in text
    assert "줄2" in text
    # 줄간 구분이 있어야 함
    assert text.find("줄1") != text.find("줄2")
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_dart_parser.py -v
```

Expected: ImportError.

- [ ] **Step 3: parser 구현** — `src/themek/dart/parser.py`

```python
"""DART 사업보고서 HTML → 본문 텍스트 추출."""
from __future__ import annotations
from bs4 import BeautifulSoup


def extract_business_content(html: str) -> str:
    """HTML 본문에서 사람이 읽을 수 있는 텍스트를 추출.

    LLM이 처리하기 좋도록:
    - <script>, <style> 제거
    - 표(<table>)는 셀 단위로 줄바꿈 + 탭 구분
    - 블록 요소 사이 줄바꿈 유지
    """
    soup = BeautifulSoup(html, "lxml")

    # script, style 제거
    for tag in soup(["script", "style"]):
        tag.decompose()

    # 표는 셀 단위로 \t \n 변환
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if any(cells):
                rows.append("\t".join(cells))
        table.replace_with("\n".join(rows) + "\n")

    # 나머지 블록 요소는 줄바꿈 처리
    text = soup.get_text(separator="\n", strip=True)
    # 다중 빈 줄 정리
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join(lines)
```

- [ ] **Step 4: 추가 의존성 확인**

`pyproject.toml`에 `beautifulsoup4`, `lxml`이 이미 Task 1에서 포함됨. 누락 시 추가.

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest tests/test_dart_parser.py -v
```

Expected: 3 passed.

- [ ] **Step 6: 커밋**

```bash
git add src/themek/dart/__init__.py src/themek/dart/parser.py tests/test_dart_parser.py
git commit -m "feat(dart): parse business report HTML to clean text"
```

---

## Task 9: LLM Output Schemas

LLM이 반환할 구조화 데이터의 Pydantic 모델 정의.

**Files:**
- Create: `src/themek/llm/__init__.py` (빈)
- Create: `src/themek/llm/schemas.py`
- Create: `tests/test_llm_schemas.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_schemas.py`

```python
from themek.llm.schemas import (
    BusinessExtraction, SegmentItem, CustomerItem, GeographicItem,
)


def test_business_extraction_full_payload():
    payload = {
        "segments": [
            {"name_ko": "메모리반도체", "share_pct": 42.5,
             "products": ["DRAM", "NAND"]},
            {"name_ko": "스마트폰", "share_pct": 38.0, "products": ["갤럭시"]},
        ],
        "customers": [
            {"name_raw": "Apple Inc.", "revenue_share_pct": 18.0, "tier": "1차"},
        ],
        "geographic": [
            {"region_code": "KR", "share_pct": 30.0},
            {"region_code": "US", "share_pct": 35.0},
            {"region_code": "CN", "share_pct": 20.0},
            {"region_code": "EU", "share_pct": 10.0},
            {"region_code": "ROW", "share_pct": 5.0},
        ],
        "period": "2023",
    }
    extraction = BusinessExtraction.model_validate(payload)
    assert len(extraction.segments) == 2
    assert extraction.segments[0].share_pct == 42.5
    assert extraction.customers[0].tier == "1차"
    assert sum(g.share_pct for g in extraction.geographic) == 100.0


def test_business_extraction_optional_fields():
    payload = {"segments": [], "customers": [], "geographic": [], "period": "2024Q1"}
    extraction = BusinessExtraction.model_validate(payload)
    assert extraction.segments == []


def test_customer_tier_validation():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CustomerItem(name_raw="X", tier="invalid_tier")
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_llm_schemas.py -v
```

Expected: ImportError.

- [ ] **Step 3: schemas 구현** — `src/themek/llm/schemas.py`

```python
"""LLM 추출 결과의 Pydantic 모델."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


CustomerTier = Literal["1차", "2차", "unknown"]
RegionCode = Literal["KR", "US", "EU", "CN", "JP", "ROW"]


class SegmentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_ko: str
    share_pct: Optional[float] = Field(default=None, ge=0, le=100)
    description: Optional[str] = None
    products: list[str] = Field(default_factory=list)


class CustomerItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name_raw: str  # LLM이 보고서에서 그대로 본 이름 (resolve 별도)
    revenue_share_pct: Optional[float] = Field(default=None, ge=0, le=100)
    tier: CustomerTier = "unknown"


class GeographicItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region_code: RegionCode
    share_pct: float = Field(ge=0, le=100)


class BusinessExtraction(BaseModel):
    """1개 사업보고서의 사업 구조 추출 결과."""
    model_config = ConfigDict(extra="forbid")
    period: str
    segments: list[SegmentItem]
    customers: list[CustomerItem]
    geographic: list[GeographicItem]
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_llm_schemas.py -v
```

Expected: 3 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/llm/__init__.py src/themek/llm/schemas.py tests/test_llm_schemas.py
git commit -m "feat(llm): add Pydantic schemas for business extraction output"
```

---

## Task 10: LLM Prompt 템플릿

사업보고서 텍스트 → 구조화 추출 prompt.

**Files:**
- Create: `src/themek/llm/prompts.py`
- Create: `tests/test_llm_prompts.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_llm_prompts.py`

```python
from themek.llm.prompts import build_business_extraction_prompt


def test_prompt_contains_text():
    text = "이 회사의 매출은 메모리 50%, 디스플레이 30%, 기타 20%로 구성됨."
    prompt = build_business_extraction_prompt(text, period_hint="2023")
    assert "이 회사의 매출" in prompt
    assert "2023" in prompt


def test_prompt_instructs_json_only_output():
    prompt = build_business_extraction_prompt("x", period_hint="2024Q1")
    # JSON-only 출력 지시가 있어야 LLM이 raw JSON 반환
    assert "JSON" in prompt or "json" in prompt
    assert "segments" in prompt  # schema field hint


def test_prompt_lists_allowed_region_codes():
    prompt = build_business_extraction_prompt("x", period_hint="2024")
    for code in ["KR", "US", "EU", "CN", "JP", "ROW"]:
        assert code in prompt
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_llm_prompts.py -v
```

Expected: ImportError.

- [ ] **Step 3: prompts 구현** — `src/themek/llm/prompts.py`

```python
"""LLM 추출 prompt 빌더."""
from __future__ import annotations


BUSINESS_EXTRACTION_PROMPT_TEMPLATE = """\
다음은 한국 상장사의 사업보고서 본문 일부입니다 (period: {period}).
이 내용에서 사업 구조를 추출해 JSON으로만 응답하세요. 설명이나 markdown 없이 valid JSON 객체 1개만.

[추출 대상 구조]
{{
  "period": "{period}",
  "segments": [
    {{"name_ko": "사업부문명", "share_pct": 0~100 또는 null, "description": "한 줄 설명 또는 null", "products": ["주요 제품/서비스명", ...]}}
  ],
  "customers": [
    {{"name_raw": "보고서에 적힌 그대로의 고객사 이름 또는 설명", "revenue_share_pct": 0~100 또는 null, "tier": "1차" | "2차" | "unknown"}}
  ],
  "geographic": [
    {{"region_code": "KR" | "US" | "EU" | "CN" | "JP" | "ROW", "share_pct": 0~100}}
  ]
}}

[지침]
- 보고서에 명시되지 않은 수치는 null로 두세요. 추측 금지.
- region_code는 위 6종만 사용. "아시아"는 CN/JP 외엔 ROW. "유럽 전체"는 EU.
- 고객사가 비공개("주요 고객 A" 등)면 name_raw에 그대로 적고 tier="unknown".
- segments의 share_pct 총합이 ~100이 되지 않아도 됩니다 (보고서 기준 그대로).
- products는 보고서에서 직접 언급된 제품/서비스명만 (브랜드명 OK).

[보고서 본문]
{text}

[출력 — JSON only]
"""


def build_business_extraction_prompt(text: str, period_hint: str) -> str:
    return BUSINESS_EXTRACTION_PROMPT_TEMPLATE.format(text=text, period=period_hint)
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_llm_prompts.py -v
```

Expected: 3 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/llm/prompts.py tests/test_llm_prompts.py
git commit -m "feat(llm): add business extraction prompt template"
```

---

## Task 11: Claude CLI Wrapper

`claude -p` subprocess를 호출하는 wrapper. 호출 결과 JSON parse + Pydantic 검증.

**Files:**
- Create: `src/themek/llm/claude_cli.py`
- Create: `tests/test_claude_cli.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_claude_cli.py`

```python
import json
from unittest.mock import MagicMock
import pytest
from themek.llm.claude_cli import call_claude, ClaudeCallError


def test_call_claude_returns_parsed_text(mocker):
    mock_run = mocker.patch("themek.llm.claude_cli.subprocess.run")
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps({"type": "result", "subtype": "success",
                           "result": "안녕"}),
        stderr="",
    )
    result = call_claude("test prompt")
    assert result == "안녕"
    mock_run.assert_called_once()
    args, _ = mock_run.call_args
    assert args[0][0] == "claude"
    assert "-p" in args[0]
    assert "--output-format" in args[0]
    assert "json" in args[0]


def test_call_claude_raises_on_nonzero_exit(mocker):
    mocker.patch(
        "themek.llm.claude_cli.subprocess.run",
        return_value=MagicMock(returncode=1, stdout="", stderr="boom"),
    )
    with pytest.raises(ClaudeCallError, match="boom"):
        call_claude("test")


def test_call_claude_raises_on_invalid_json(mocker):
    mocker.patch(
        "themek.llm.claude_cli.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="not json", stderr=""),
    )
    with pytest.raises(ClaudeCallError, match="JSON"):
        call_claude("test")


def test_call_claude_extracts_json_block_from_text():
    """LLM 응답 안의 JSON 코드블록 추출."""
    from themek.llm.claude_cli import extract_json_block
    text = "여기 결과입니다:\n```json\n{\"a\": 1}\n```\n끝."
    assert extract_json_block(text) == {"a": 1}


def test_extract_json_block_plain_json():
    from themek.llm.claude_cli import extract_json_block
    assert extract_json_block('{"x": "y"}') == {"x": "y"}


def test_extract_json_block_raises_when_no_json():
    from themek.llm.claude_cli import extract_json_block, ClaudeCallError
    with pytest.raises(ClaudeCallError):
        extract_json_block("그냥 텍스트")
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_claude_cli.py -v
```

Expected: ImportError.

- [ ] **Step 3: claude_cli 구현** — `src/themek/llm/claude_cli.py`

```python
"""Claude Code CLI (claude -p) subprocess wrapper.

구독 기반 사용: ANTHROPIC_API_KEY 불필요. claude CLI가 사용자 인증된 상태여야 함.
"""
from __future__ import annotations
import json
import re
import subprocess
from typing import Any
from themek.config import get_settings


class ClaudeCallError(RuntimeError):
    pass


def call_claude(prompt: str, *, timeout_sec: int | None = None) -> str:
    """`claude -p <prompt> --output-format json` 호출 후 result 필드 텍스트 반환."""
    settings = get_settings()
    timeout = timeout_sec or settings.claude_cli_timeout_sec
    try:
        proc = subprocess.run(
            [settings.claude_cli_bin, "-p", prompt,
             "--output-format", "json"],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise ClaudeCallError(f"claude CLI timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise ClaudeCallError(
            f"claude CLI not found at '{settings.claude_cli_bin}'"
        ) from e

    if proc.returncode != 0:
        raise ClaudeCallError(
            f"claude CLI exited {proc.returncode}: {proc.stderr.strip()}"
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise ClaudeCallError(
            f"claude CLI output is not valid JSON: {proc.stdout[:300]}"
        ) from e

    if not isinstance(payload, dict) or "result" not in payload:
        raise ClaudeCallError(f"unexpected claude payload: {payload!r}")

    return payload["result"]


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL)


def extract_json_block(text: str) -> Any:
    """LLM 응답에서 JSON 객체를 추출.

    1) 응답이 통째로 valid JSON이면 그대로 parse
    2) ```json ... ``` 코드블록 안에 있으면 그 안만 parse
    3) 둘 다 실패 시 ClaudeCallError
    """
    text = text.strip()
    # 1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2)
    match = _JSON_FENCE_RE.search(text)
    if match:
        return json.loads(match.group(1))
    raise ClaudeCallError(f"no JSON block found in claude output: {text[:200]}")
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_claude_cli.py -v
```

Expected: 6 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/llm/claude_cli.py tests/test_claude_cli.py
git commit -m "feat(llm): add Claude Code CLI subprocess wrapper"
```

---

## Task 12: Ingestion Orchestration

parser → LLM → DB store를 묶어 1개 사업보고서를 처리하는 함수. Idempotent.

**Files:**
- Create: `src/themek/ingest/__init__.py` (빈)
- Create: `src/themek/ingest/business_report.py`
- Create: `tests/fixtures/samsung_extraction_expected.json` (mock LLM 응답)
- Create: `tests/test_ingest_business_report.py`

- [ ] **Step 1: mock LLM 응답 fixture 작성** — `tests/fixtures/samsung_extraction_expected.json`

```json
{
  "period": "2023",
  "segments": [
    {"name_ko": "메모리반도체", "share_pct": 42.5,
     "description": "DRAM/NAND 등", "products": ["DRAM", "NAND", "HBM"]},
    {"name_ko": "스마트폰/네트워크", "share_pct": 38.0,
     "description": "갤럭시 시리즈", "products": ["갤럭시 스마트폰", "갤럭시 워치"]},
    {"name_ko": "디스플레이", "share_pct": 15.5,
     "description": "OLED 패널", "products": ["OLED 패널"]}
  ],
  "customers": [
    {"name_raw": "Apple Inc.", "revenue_share_pct": 18.0, "tier": "1차"},
    {"name_raw": "주요 글로벌 IT 고객사 (비공개)", "revenue_share_pct": null, "tier": "unknown"}
  ],
  "geographic": [
    {"region_code": "KR", "share_pct": 18.0},
    {"region_code": "US", "share_pct": 35.0},
    {"region_code": "CN", "share_pct": 20.0},
    {"region_code": "EU", "share_pct": 15.0},
    {"region_code": "JP", "share_pct": 5.0},
    {"region_code": "ROW", "share_pct": 7.0}
  ]
}
```

- [ ] **Step 2: 실패 테스트 작성** — `tests/test_ingest_business_report.py`

```python
import json
from datetime import date
from pathlib import Path
from themek.ingest.business_report import ingest_business_report
from themek.db.models import (
    Corporation, BusinessReport, BusinessSegment,
    RevenueComposition, CustomerRelation, GeographicExposure,
)
from themek.seeds import seed_basic


FIXTURE_JSON = (Path(__file__).parent / "fixtures"
                / "samsung_extraction_expected.json")


def _stub_extractor(text, period_hint):
    """LLM 호출 대신 fixture JSON 반환."""
    from themek.llm.schemas import BusinessExtraction
    return BusinessExtraction.model_validate(
        json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    )


def test_ingest_creates_report_and_segments(db_session):
    seed_basic(db_session)
    db_session.commit()
    ingest_business_report(
        db_session,
        dart_rcept_no="20240314000123",
        corporation_id="00126380",
        report_type="사업보고서",
        period="2023",
        filing_date=date(2024, 3, 14),
        raw_text_excerpt="...irrelevant for stub...",
        url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123",
        extractor=_stub_extractor,
    )
    db_session.commit()

    report = db_session.get(BusinessReport, "20240314000123")
    assert report is not None
    assert report.corporation_id == "00126380"

    segments = db_session.query(BusinessSegment).filter_by(
        corporation_id="00126380"
    ).all()
    assert len(segments) == 3
    assert {s.name_ko for s in segments} == {"메모리반도체", "스마트폰/네트워크", "디스플레이"}

    revenue = db_session.query(RevenueComposition).filter_by(
        source_report_id="20240314000123"
    ).all()
    assert len(revenue) == 3  # 3 segments * 1 period

    customers = db_session.query(CustomerRelation).filter_by(
        source_report_id="20240314000123"
    ).all()
    assert len(customers) == 2
    apple = next(c for c in customers if c.buyer_raw == "Apple Inc.")
    assert apple.revenue_share_pct == 18.0
    assert apple.resolved is False  # unresolved by default; later task may resolve

    geographic = db_session.query(GeographicExposure).filter_by(
        source_report_id="20240314000123"
    ).all()
    assert len(geographic) == 6
    assert {g.region_id for g in geographic} == {"KR", "US", "CN", "EU", "JP", "ROW"}


def test_ingest_is_idempotent(db_session):
    seed_basic(db_session)
    db_session.commit()
    for _ in range(2):
        ingest_business_report(
            db_session,
            dart_rcept_no="20240314000123",
            corporation_id="00126380",
            report_type="사업보고서",
            period="2023",
            filing_date=date(2024, 3, 14),
            raw_text_excerpt="...",
            extractor=_stub_extractor,
        )
        db_session.commit()
    # 두 번째 호출이 중복 row 추가하지 않음
    assert db_session.query(BusinessReport).count() == 1
    assert db_session.query(BusinessSegment).filter_by(
        corporation_id="00126380"
    ).count() == 3
    assert db_session.query(RevenueComposition).count() == 3
```

- [ ] **Step 3: 실패 확인**

```bash
uv run pytest tests/test_ingest_business_report.py -v
```

Expected: ImportError.

- [ ] **Step 4: ingest 구현** — `src/themek/ingest/business_report.py`

```python
"""1개 사업보고서를 ingestion하는 오케스트레이션."""
from __future__ import annotations
import uuid
from datetime import date
from typing import Callable, Optional
from sqlalchemy.orm import Session
from themek.db.models import (
    BusinessReport, BusinessSegment, RevenueComposition,
    CustomerRelation, GeographicExposure,
)
from themek.llm.schemas import BusinessExtraction


def _default_extractor(text: str, period_hint: str) -> BusinessExtraction:
    from themek.llm.claude_cli import call_claude, extract_json_block
    from themek.llm.prompts import build_business_extraction_prompt
    prompt = build_business_extraction_prompt(text, period_hint=period_hint)
    raw = call_claude(prompt)
    payload = extract_json_block(raw)
    return BusinessExtraction.model_validate(payload)


def ingest_business_report(
    session: Session,
    *,
    dart_rcept_no: str,
    corporation_id: str,
    report_type: str,
    period: str,
    filing_date: date,
    raw_text_excerpt: str,
    url: Optional[str] = None,
    extractor: Callable[[str, str], BusinessExtraction] = _default_extractor,
) -> None:
    """사업보고서 1건을 ingest. 이미 존재하면 no-op (R4: idempotency)."""
    existing = session.get(BusinessReport, dart_rcept_no)
    if existing is not None:
        return

    extraction = extractor(raw_text_excerpt, period)

    report = BusinessReport(
        dart_rcept_no=dart_rcept_no,
        corporation_id=corporation_id,
        report_type=report_type,
        period=period,
        filing_date=filing_date,
        url=url,
    )
    session.add(report)
    session.flush()

    # Segments + per-segment Revenue
    for seg_item in extraction.segments:
        seg = BusinessSegment(
            id=str(uuid.uuid4()),
            corporation_id=corporation_id,
            name_ko=seg_item.name_ko,
            description=seg_item.description,
        )
        session.add(seg)
        session.flush()
        if seg_item.share_pct is not None:
            session.add(RevenueComposition(
                id=str(uuid.uuid4()),
                subject_corp_id=None,
                subject_segment_id=seg.id,
                period=period,
                share_pct=seg_item.share_pct,
                source_report_id=report.dart_rcept_no,
            ))

    # Customers
    for cust in extraction.customers:
        session.add(CustomerRelation(
            id=str(uuid.uuid4()),
            seller_id=corporation_id,
            buyer_corp_id=None,
            buyer_raw=cust.name_raw,
            resolved=False,
            period=period,
            revenue_share_pct=cust.revenue_share_pct,
            tier=cust.tier,
            source_report_id=report.dart_rcept_no,
        ))

    # Geographic
    for geo in extraction.geographic:
        session.add(GeographicExposure(
            id=str(uuid.uuid4()),
            subject_corp_id=corporation_id,
            subject_segment_id=None,
            region_id=geo.region_code,
            period=period,
            share_pct=geo.share_pct,
            source_report_id=report.dart_rcept_no,
        ))
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest tests/test_ingest_business_report.py -v
```

Expected: 2 passed.

- [ ] **Step 6: 커밋**

```bash
git add src/themek/ingest/ tests/fixtures/samsung_extraction_expected.json tests/test_ingest_business_report.py
git commit -m "feat(ingest): orchestrate business report ingestion (idempotent)"
```

---

## Task 13: E5 Query Logic

Ticker → 구조화된 사업 요약 객체.

**Files:**
- Create: `src/themek/query/__init__.py` (빈)
- Create: `src/themek/query/e5.py`
- Create: `tests/test_query_e5.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_query_e5.py`

```python
import json
from datetime import date
from pathlib import Path
import pytest
from themek.query.e5 import query_e5, E5Result
from themek.seeds import seed_basic
from themek.ingest.business_report import ingest_business_report
from themek.llm.schemas import BusinessExtraction


FIXTURE_JSON = Path(__file__).parent / "fixtures" / "samsung_extraction_expected.json"


def _stub(text, period_hint):
    return BusinessExtraction.model_validate(
        json.loads(FIXTURE_JSON.read_text(encoding="utf-8"))
    )


def _setup(db_session):
    seed_basic(db_session)
    db_session.commit()
    ingest_business_report(
        db_session,
        dart_rcept_no="20240314000123",
        corporation_id="00126380",
        report_type="사업보고서",
        period="2023",
        filing_date=date(2024, 3, 14),
        raw_text_excerpt="…",
        url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123",
        extractor=_stub,
    )
    db_session.commit()


def test_query_e5_returns_structured_result(db_session):
    _setup(db_session)
    result: E5Result = query_e5(db_session, ticker="005930")
    assert result.stock_name == "삼성전자"
    assert result.corporation_name == "삼성전자"
    assert result.sector_name == "반도체"
    assert len(result.segments) == 3
    top_seg = result.segments[0]
    assert top_seg.name == "메모리반도체"
    assert top_seg.share_pct == 42.5
    assert len(result.top_customers) >= 1
    assert any(c.name_raw == "Apple Inc." for c in result.top_customers)
    assert len(result.top_regions) == 5  # top 5만
    assert result.source_report_rcept_no == "20240314000123"
    assert result.period == "2023"


def test_query_e5_raises_on_unknown_ticker(db_session):
    seed_basic(db_session)
    db_session.commit()
    with pytest.raises(LookupError, match="999999"):
        query_e5(db_session, ticker="999999")


def test_query_e5_returns_none_summary_when_no_report(db_session):
    seed_basic(db_session)
    db_session.commit()
    # 보고서 ingest 안 함
    result = query_e5(db_session, ticker="005930")
    assert result.stock_name == "삼성전자"
    assert result.segments == []
    assert result.top_customers == []
    assert result.top_regions == []
    assert result.source_report_rcept_no is None
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_query_e5.py -v
```

Expected: ImportError.

- [ ] **Step 3: query/e5.py 구현** — `src/themek/query/e5.py`

```python
"""E5 ("이 회사 뭐 만들어?") query traversal."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from themek.db.models import (
    Stock, BusinessReport, BusinessSegment, RevenueComposition,
    CustomerRelation, GeographicExposure, Region,
)


@dataclass
class SegmentSummary:
    name: str
    share_pct: Optional[float]
    description: Optional[str]


@dataclass
class CustomerSummary:
    name_raw: str
    revenue_share_pct: Optional[float]
    tier: str


@dataclass
class RegionSummary:
    region_code: str
    region_name_ko: str
    share_pct: float


@dataclass
class E5Result:
    stock_ticker: str
    stock_name: str
    corporation_dart_code: str
    corporation_name: str
    sector_name: Optional[str]
    period: Optional[str]
    segments: list[SegmentSummary] = field(default_factory=list)
    top_customers: list[CustomerSummary] = field(default_factory=list)
    top_regions: list[RegionSummary] = field(default_factory=list)
    source_report_rcept_no: Optional[str] = None
    source_report_url: Optional[str] = None


def query_e5(session: Session, *, ticker: str,
             top_n_customers: int = 5, top_n_regions: int = 5) -> E5Result:
    """ticker 1개에 대한 사업 구조 요약."""
    stock = session.get(Stock, ticker)
    if stock is None:
        raise LookupError(f"Unknown ticker: {ticker}")
    corp = stock.issued_by

    # 최신 보고서 1건 (filing_date desc)
    report = session.execute(
        select(BusinessReport)
        .where(BusinessReport.corporation_id == corp.dart_code)
        .order_by(BusinessReport.filing_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    result = E5Result(
        stock_ticker=stock.ticker,
        stock_name=stock.name_ko,
        corporation_dart_code=corp.dart_code,
        corporation_name=corp.name_ko,
        sector_name=corp.in_sector.name_ko if corp.in_sector else None,
        period=report.period if report else None,
        source_report_rcept_no=report.dart_rcept_no if report else None,
        source_report_url=report.url if report else None,
    )
    if report is None:
        return result

    # Segments (with their RevenueComposition share)
    segments_rows = session.execute(
        select(BusinessSegment, RevenueComposition.share_pct)
        .join(
            RevenueComposition,
            RevenueComposition.subject_segment_id == BusinessSegment.id,
            isouter=True,
        )
        .where(BusinessSegment.corporation_id == corp.dart_code)
        .where(
            (RevenueComposition.source_report_id == report.dart_rcept_no)
            | (RevenueComposition.id.is_(None))
        )
    ).all()
    # share_pct desc, None last
    segments_rows.sort(
        key=lambda r: (r[1] is None, -(r[1] or 0)),
    )
    result.segments = [
        SegmentSummary(name=seg.name_ko,
                       share_pct=float(share) if share is not None else None,
                       description=seg.description)
        for seg, share in segments_rows
    ]

    # Top customers
    customer_rows = session.execute(
        select(CustomerRelation)
        .where(CustomerRelation.source_report_id == report.dart_rcept_no)
        .order_by(CustomerRelation.revenue_share_pct.desc().nullslast())
        .limit(top_n_customers)
    ).scalars().all()
    result.top_customers = [
        CustomerSummary(
            name_raw=c.buyer_raw or (c.buyer_corp.name_ko if c.buyer_corp else "?"),
            revenue_share_pct=float(c.revenue_share_pct) if c.revenue_share_pct is not None else None,
            tier=c.tier,
        )
        for c in customer_rows
    ]

    # Top regions
    geo_rows = session.execute(
        select(GeographicExposure, Region)
        .join(Region, Region.code == GeographicExposure.region_id)
        .where(GeographicExposure.source_report_id == report.dart_rcept_no)
        .order_by(GeographicExposure.share_pct.desc())
        .limit(top_n_regions)
    ).all()
    result.top_regions = [
        RegionSummary(region_code=g.region_id,
                      region_name_ko=region.name_ko,
                      share_pct=float(g.share_pct))
        for g, region in geo_rows
    ]

    return result
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
uv run pytest tests/test_query_e5.py -v
```

Expected: 3 passed.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/query/ tests/test_query_e5.py
git commit -m "feat(query): implement E5 traversal returning structured summary"
```

---

## Task 14: E5 자연어 답변 합성 (Jinja 템플릿)

LLM 호출 없이 Jinja 템플릿으로 자연어 답을 만들어 인용과 함께 반환.

**Files:**
- Create: `src/themek/query/templates/e5_answer.txt.j2`
- Create: `src/themek/query/synthesize.py`
- Create: `tests/test_synthesize_e5.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_synthesize_e5.py`

```python
from themek.query.e5 import E5Result, SegmentSummary, CustomerSummary, RegionSummary
from themek.query.synthesize import synthesize_e5_answer


def _sample_result():
    return E5Result(
        stock_ticker="005930", stock_name="삼성전자",
        corporation_dart_code="00126380", corporation_name="삼성전자",
        sector_name="반도체",
        period="2023",
        segments=[
            SegmentSummary("메모리반도체", 42.5, "DRAM/NAND 등"),
            SegmentSummary("스마트폰/네트워크", 38.0, "갤럭시"),
            SegmentSummary("디스플레이", 15.5, "OLED"),
        ],
        top_customers=[
            CustomerSummary("Apple Inc.", 18.0, "1차"),
            CustomerSummary("주요 글로벌 IT 고객사 (비공개)", None, "unknown"),
        ],
        top_regions=[
            RegionSummary("US", "미주", 35.0),
            RegionSummary("CN", "중국", 20.0),
            RegionSummary("KR", "국내", 18.0),
        ],
        source_report_rcept_no="20240314000123",
        source_report_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123",
    )


def test_synthesize_basic():
    answer = synthesize_e5_answer(_sample_result())
    assert "삼성전자" in answer
    assert "메모리반도체" in answer
    assert "42.5%" in answer
    assert "Apple Inc." in answer
    assert "미주" in answer or "US" in answer
    # 인용 포함
    assert "20240314000123" in answer
    assert "dart.fss.or.kr" in answer


def test_synthesize_handles_missing_report():
    result = E5Result(
        stock_ticker="999999", stock_name="가상종목",
        corporation_dart_code="00999999", corporation_name="가상법인",
        sector_name=None, period=None,
    )
    answer = synthesize_e5_answer(result)
    assert "가상종목" in answer
    # 보고서 부재 시 안내 문구
    assert "보고서" in answer
    assert "없" in answer or "찾지 못" in answer


def test_synthesize_handles_no_customers():
    r = _sample_result()
    r.top_customers = []
    answer = synthesize_e5_answer(r)
    # 고객 정보 없음 안내
    assert "고객" in answer
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_synthesize_e5.py -v
```

Expected: ImportError.

- [ ] **Step 3: Jinja 템플릿 작성** — `src/themek/query/templates/e5_answer.txt.j2`

```jinja
[{{ result.stock_name }} ({{ result.stock_ticker }}){% if result.sector_name %} — {{ result.sector_name }}{% endif %}]
{% if result.source_report_rcept_no -%}
출처: 사업보고서 (period={{ result.period }}, DART rcept_no={{ result.source_report_rcept_no }}){% if result.source_report_url %}
링크: {{ result.source_report_url }}{% endif %}

## 사업 부문 매출 구성
{% if result.segments -%}
{%- for seg in result.segments -%}
- {{ seg.name }}{% if seg.share_pct is not none %} {{ seg.share_pct }}%{% else %} (비중 미명시){% endif %}{% if seg.description %} — {{ seg.description }}{% endif %}
{% endfor %}
{%- else -%}
(보고서에서 사업부문 정보가 추출되지 않았습니다.)
{%- endif %}

## 주요 고객사 / 매출처
{% if result.top_customers -%}
{%- for c in result.top_customers -%}
- {{ c.name_raw }}{% if c.revenue_share_pct is not none %} ({{ c.revenue_share_pct }}%){% endif %}{% if c.tier != "unknown" %} · {{ c.tier }} 협력사{% endif %}
{% endfor %}
{%- else -%}
(보고서에서 주요 고객사가 추출되지 않았습니다.)
{%- endif %}

## 지역별 매출 노출
{% if result.top_regions -%}
{%- for g in result.top_regions -%}
- {{ g.region_name_ko }} ({{ g.region_code }}): {{ g.share_pct }}%
{% endfor %}
{%- else -%}
(보고서에서 지역별 매출 정보가 추출되지 않았습니다.)
{%- endif %}
{%- else -%}
이 종목에 대한 사업보고서가 아직 ingest되지 않았습니다.
먼저 `themek ingest --rcept-no <dart_rcept_no>` 로 보고서를 등록한 뒤 다시 조회하세요.
{%- endif %}
```

- [ ] **Step 4: synthesize.py 구현** — `src/themek/query/synthesize.py`

```python
"""E5 결과를 Jinja 템플릿으로 자연어 답으로 변환."""
from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from themek.query.e5 import E5Result


_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def synthesize_e5_answer(result: E5Result) -> str:
    template = _env.get_template("e5_answer.txt.j2")
    return template.render(result=result)
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
uv run pytest tests/test_synthesize_e5.py -v
```

Expected: 3 passed.

- [ ] **Step 6: 커밋**

```bash
git add src/themek/query/templates/ src/themek/query/synthesize.py tests/test_synthesize_e5.py
git commit -m "feat(query): synthesize E5 answer via Jinja template with citations"
```

---

## Task 15: CLI

`themek seed`, `themek ingest`, `themek query e5` 명령.

**Files:**
- Create: `src/themek/cli.py`
- Modify: `pyproject.toml` — add `[project.scripts]` entry
- Create: `tests/test_cli.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_cli.py`

```python
import json
from datetime import date
from pathlib import Path
from typer.testing import CliRunner
from themek.cli import app
from themek.llm.schemas import BusinessExtraction


runner = CliRunner()
FIXTURE_JSON = Path(__file__).parent / "fixtures" / "samsung_extraction_expected.json"


def test_cli_seed_command(engine):
    # DB 초기 상태로 clean — conftest engine은 session-scope drop+create
    result = runner.invoke(app, ["seed"])
    assert result.exit_code == 0, result.stdout
    assert "Seeded" in result.stdout


def test_cli_query_e5_no_report(engine):
    runner.invoke(app, ["seed"])
    result = runner.invoke(app, ["query", "e5", "--ticker", "005930"])
    assert result.exit_code == 0, result.stdout
    assert "삼성전자" in result.stdout
    assert "ingest되지 않았" in result.stdout


def test_cli_query_e5_unknown_ticker(engine):
    runner.invoke(app, ["seed"])
    result = runner.invoke(app, ["query", "e5", "--ticker", "999999"])
    assert result.exit_code != 0
    assert "999999" in (result.stdout + result.stderr)


def test_cli_ingest_with_stub(engine, monkeypatch, tmp_path):
    """ingest command with stub LLM (env var to bypass real claude)."""
    runner.invoke(app, ["seed"])

    # 임시 fixture 파일
    raw_html = tmp_path / "report.html"
    raw_html.write_text("<html><body><p>샘플 본문</p></body></html>", encoding="utf-8")

    # stub for LLM extractor via env var
    monkeypatch.setenv("THEMEK_STUB_EXTRACTION_FILE", str(FIXTURE_JSON))

    result = runner.invoke(app, [
        "ingest",
        "--rcept-no", "20240314000123",
        "--corp", "00126380",
        "--report-type", "사업보고서",
        "--period", "2023",
        "--filing-date", "2024-03-14",
        "--html-file", str(raw_html),
        "--url", "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123",
    ])
    assert result.exit_code == 0, result.stdout

    # 이제 query하면 보고서 기반 답
    result = runner.invoke(app, ["query", "e5", "--ticker", "005930"])
    assert result.exit_code == 0
    assert "메모리반도체" in result.stdout
    assert "20240314000123" in result.stdout
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: ImportError.

- [ ] **Step 3: cli.py 구현** — `src/themek/cli.py`

```python
"""themek CLI entry point."""
from __future__ import annotations
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional
import typer
from sqlalchemy.orm import Session
from themek.config import get_settings
from themek.db.engine import make_engine, make_session_factory
from themek.seeds import seed_basic
from themek.dart.parser import extract_business_content
from themek.ingest.business_report import ingest_business_report
from themek.query.e5 import query_e5
from themek.query.synthesize import synthesize_e5_answer
from themek.llm.schemas import BusinessExtraction

app = typer.Typer(help="themek — 한국 테마주 ontology CLI")
query_app = typer.Typer(help="Run competency queries")
app.add_typer(query_app, name="query")


def _session() -> Session:
    factory = make_session_factory(make_engine())
    return factory()


@app.command()
def seed():
    """샘플 데이터 시드."""
    with _session() as s:
        seed_basic(s)
        s.commit()
    typer.echo("Seeded 3 stocks, 3 corporations, sectors, regions.")


def _stub_extractor_from_env():
    path = os.environ.get("THEMEK_STUB_EXTRACTION_FILE")
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    extraction = BusinessExtraction.model_validate(payload)

    def stub(text: str, period_hint: str) -> BusinessExtraction:
        return extraction

    return stub


@app.command()
def ingest(
    rcept_no: str = typer.Option(..., "--rcept-no"),
    corp: str = typer.Option(..., "--corp", help="DART corporation code (8자리)"),
    report_type: str = typer.Option(..., "--report-type",
                                    help="사업보고서|반기보고서|분기보고서"),
    period: str = typer.Option(..., "--period", help="예: 2023, 2024Q3"),
    filing_date: str = typer.Option(..., "--filing-date", help="YYYY-MM-DD"),
    html_file: Path = typer.Option(..., "--html-file",
                                   help="DART 사업보고서 HTML 파일"),
    url: Optional[str] = typer.Option(None, "--url"),
):
    """사업보고서 1건을 ingest."""
    html = html_file.read_text(encoding="utf-8")
    text = extract_business_content(html)
    extractor = _stub_extractor_from_env()
    with _session() as s:
        kwargs = dict(
            dart_rcept_no=rcept_no,
            corporation_id=corp,
            report_type=report_type,
            period=period,
            filing_date=date.fromisoformat(filing_date),
            raw_text_excerpt=text,
            url=url,
        )
        if extractor is not None:
            kwargs["extractor"] = extractor
        ingest_business_report(s, **kwargs)
        s.commit()
    typer.echo(f"Ingested report {rcept_no}")


@query_app.command("e5")
def query_e5_cmd(ticker: str = typer.Option(..., "--ticker")):
    """E5: 이 회사 뭐 만들어?"""
    with _session() as s:
        try:
            result = query_e5(s, ticker=ticker)
        except LookupError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=1)
    typer.echo(synthesize_e5_answer(result))


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: pyproject.toml에 entry script 추가**

`[project]` 블록 아래에 추가:

```toml
[project.scripts]
themek = "themek.cli:app"
```

`uv sync`로 다시 install.

- [ ] **Step 5: conftest.py 보강 — engine fixture를 CLI 테스트에서도 사용 가능하게**

기존 `tests/conftest.py`의 engine fixture는 `scope="session"`이므로 CLI 테스트도 같은 engine을 공유. 추가로 CLI 테스트 시작 시 테이블을 정리하기 위해 별도 fixture 추가:

`tests/conftest.py` 끝에 추가:

```python
@pytest.fixture(autouse=False)
def fresh_db(engine):
    """CLI 테스트 전 모든 테이블 비우기."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
```

그리고 `tests/test_cli.py`의 각 test에 `fresh_db` fixture 추가하도록 수정:

```python
def test_cli_seed_command(engine, fresh_db):
    ...
def test_cli_query_e5_no_report(engine, fresh_db):
    ...
def test_cli_query_e5_unknown_ticker(engine, fresh_db):
    ...
def test_cli_ingest_with_stub(engine, fresh_db, monkeypatch, tmp_path):
    ...
```

- [ ] **Step 6: 테스트 통과 확인**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: 4 passed.

- [ ] **Step 7: 커밋**

```bash
git add src/themek/cli.py pyproject.toml tests/test_cli.py tests/conftest.py
git commit -m "feat(cli): add themek seed / ingest / query e5 commands"
```

---

## Task 16: Real-data Smoke Run

실제 `claude` CLI를 호출해서 fixture HTML로 1회 전체 흐름 검증.

이 task는 **자동화된 테스트가 아니라 manual 검증**입니다. 단계 그대로 따라하고 결과 캡처.

- [ ] **Step 1: 환경 준비**

```bash
docker compose up -d
uv run alembic upgrade head
uv run themek seed
```

Expected: "Seeded 3 stocks..." 출력.

- [ ] **Step 2: 실제 LLM으로 ingestion** (stub env var 없이)

```bash
uv run themek ingest \
  --rcept-no 20240314000123 \
  --corp 00126380 \
  --report-type 사업보고서 \
  --period 2023 \
  --filing-date 2024-03-14 \
  --html-file tests/fixtures/samsung_business_report_excerpt.html \
  --url "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240314000123"
```

Expected: "Ingested report 20240314000123" 출력. 1~2분 소요 (claude CLI subprocess).

⚠️ 실패 사례:
- `ClaudeCallError: claude CLI not found` → `claude --version` 으로 설치/PATH 확인
- `ClaudeCallError: ... timed out` → `CLAUDE_CLI_TIMEOUT_SEC=300` 으로 늘림
- `ClaudeCallError: ... not valid JSON` → claude의 출력 포맷 변동 가능성. raw stdout 확인 후 prompt 보강
- `ValidationError: ...` → LLM이 schema와 어긋난 JSON 반환. prompt를 더 엄격하게.

- [ ] **Step 3: 쿼리 실행**

```bash
uv run themek query e5 --ticker 005930
```

Expected: 삼성전자 사업 요약 출력. 사업부문, 고객사, 지역 노출, 인용 모두 포함.

- [ ] **Step 4: 결과 평가 + 메모**

사람이 직접 다음을 확인:
- 사업부문이 보고서 실제 내용과 합치되는가?
- 매출 비중 숫자가 보고서에 명시된 값과 일치하는가?
- 인용된 rcept_no·URL이 정확한가?

문제가 있으면 다음 사항 중 어디 단계 문제인지 분류:
- (a) Parser가 텍스트를 제대로 못 뽑음 → Task 8 수정
- (b) LLM이 schema 어긋난 출력 → Task 10 prompt 보강
- (c) DB 모델/저장 매핑 오류 → Task 12 수정
- (d) 템플릿 출력 어색 → Task 14 보강

`docs/walking-skeleton-smoke-run-notes.md`에 평가 메모 작성.

- [ ] **Step 5: 평가 메모 커밋 (옵션)**

```bash
# 메모를 작성했다면
git add docs/walking-skeleton-smoke-run-notes.md
git commit -m "docs: smoke run notes on real LLM extraction"
```

---

## Task 17: README 업데이트

setup + usage 문서 갱신.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README.md 추가 섹션 작성**

기존 README.md 끝에 추가:

```markdown
## Walking Skeleton (Plan #1)

E5 ("이 회사 뭐 만들어?") 한 CQ를 end-to-end로 답하는 최소 슬라이스.

### 빌드 / 실행

```bash
# 의존성 설치
uv sync

# Postgres 기동
docker compose up -d

# 마이그레이션
uv run alembic upgrade head

# 샘플 시드
uv run themek seed

# 사업보고서 ingest (Claude CLI 사용, 1~2분 소요)
uv run themek ingest \
  --rcept-no 20240314000123 \
  --corp 00126380 \
  --report-type 사업보고서 \
  --period 2023 \
  --filing-date 2024-03-14 \
  --html-file tests/fixtures/samsung_business_report_excerpt.html

# 쿼리
uv run themek query e5 --ticker 005930
```

### 테스트

```bash
uv run pytest
```

(외부 LLM 호출 없이 모두 mock + fixture 기반.)

### 다음 plan들

- DART API client 자동 fetch
- Theme / Narrative / Membership / Activation 추가 (E1·E2·E3·E6)
- pgvector 통합 (E2·E4 analog/semantic 매칭)
- 24개월 backfill orchestrator
- 평가 rubric
```

- [ ] **Step 2: 커밋**

```bash
git add README.md
git commit -m "docs: add walking skeleton setup and usage"
```

---

## Plan-level Self-Review

**Spec coverage:**
- [x] E5 (External CQ) — 완전 구현 (Task 11~14)
- [x] I-2 (Theme → structural exposure stocks) — 일부, segment·revenue 기반 traversal로 검증됨 (단 Theme 자체는 다른 plan에서)
- [x] I-5 (Stock → BusinessReport summary) — 완전 구현 (Task 13)
- [x] I-10 (Customer/Supplier 그래프) — CustomerRelation 1-hop은 구현, multi-hop은 후속 plan
- [x] D1 시간 모델 ③ (period 스냅샷) — RevenueComposition·CustomerRelation·GeographicExposure 모두 period 슬롯 보유
- [x] D3 (CustomerRelation buyer Union + resolved flag) — 구현 (Task 5, Task 12)
- [x] R4 (idempotent ingestion) — 구현 (Task 12 idempotency 테스트)
- [ ] E1·E2·E3·E4·E6·E7·E8 — 의도적 out-of-scope (각 후속 plan)
- [ ] R8 (period 2-snapshot archive) — 이번 plan은 1 보고서만 다루므로 다중 period 시나리오 발생 안 함. 후속 plan에서 시행.
- [ ] Theme, Narrative, Membership, Activation — out-of-scope, 후속 plan

**Placeholder scan:** 검토 완료 — TBD/TODO/implement later 없음. 모든 step에 실제 코드 또는 명령 포함.

**Type consistency:** Stock.ticker, Corporation.dart_code, BusinessReport.dart_rcept_no, BusinessSegment.id, CustomerRelation.buyer_raw, RegionSummary.region_code 등 전 task에 걸쳐 일관 사용 확인.

**Spec gap이지만 의도된 deferral:** 위에 명시된 미구현 항목들은 모두 후속 plan에서 다룸. Walking skeleton은 "한 종목·한 보고서·한 CQ" 닫는 게 목적.

---

## Status

Plan ready for execution. Goal: 사용자가 `themek query e5 --ticker 005930` 했을 때 삼성전자 사업 구조 요약 + DART 인용을 받아본다.
