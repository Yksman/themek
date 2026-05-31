# KRX Stock Sync & Auto-Universe Implementation Plan (Plan #5.2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan #5가 만든 `data/universe/active.txt` 수동 SSOT를 자동화한다. pykrx로 KOSPI/KOSDAQ 전체 상장종목을 매일 sync해서 Stock 테이블에 upsert + 상장폐지 감지 + 신규 상장은 BackfillTarget으로 자동 enroll. 운영자 개입 없이 KOSPI/KOSDAQ 전체 universe에 대해 매일 cron이 증분 ontology를 누적한다.

**Final Success Metric:** Task 14 통합 smoke가 (a) pykrx → Stock 테이블 upsert ≥2,000 row (실제 KOSPI+KOSDAQ 합산), (b) 신규 상장 감지 → BackfillTarget pending 생성, (c) 상장폐지 감지 → `delisted_at` set, (d) `dart backfill run --from-stocks-universe` 가 Stock 기반 universe로 1종목 이상 done까지 진행, (e) cron 스크립트 5단계 dry-run 모두 exit 0 — 5개 모두 통과해야 SUCCESS.

**Architecture:** 신규 `src/themek/krx/{client,sync}.py` 2 파일 + `Stock` 테이블에 `delisted_at`/`last_seen_at` 컬럼 추가 (migration 0004) + 기존 `dart/universe.py`에 `load_universe_from_stocks` 추가 + 기존 `dart/backfill.py`의 `enumerate_targets` 확장 + CLI 1 신규 명령 (`themek krx sync-listed`) + 3 기존 명령 옵션 확장 (`dart sync-corp --if-stale-days`, `dart backfill init --from-stocks`, `dart incremental --universe-source stocks`). 기존 ingest/fetch/parser/backfill 코어 로직은 **재사용만 하고 변경 없음**.

**Tech Stack:** Python 3.12+, pytest, pytest-mock, SQLAlchemy 2 + alembic, typer, pykrx (≥1.0.45), 기존 DART client (httpx) + claude CLI wrapper.

---

## 핵심 설계 결정 (선행 합의)

### 1. Universe SSOT 전환 — file → Stock 테이블 (점진적)

| 기존 | 신규 |
|------|------|
| `data/universe/active.txt` (수동 corp_code list) | `Stock` 테이블 (KRX `get_market_ticker_list` 자동 sync) |
| `themek dart backfill init --universe-file ...` | `themek dart backfill init --from-stocks` (기본 후속) |
| `themek dart incremental --universe-file ...` | `themek dart incremental --universe-source stocks` |

**점진적 전환 원칙**: 기존 `--universe-file` 인터페이스는 **유지** (backward compat, manual override 용). 디폴트만 `--from-stocks` 쪽으로 옮기지 않고 운영자가 옵션으로 선택. `active.txt`는 "특정 종목만 처리하려는" 임시 universe로 의미 변경.

### 2. ticker → corp_code 매핑은 DART corp_master에 의존

DART `corp_master.json` row 구조 확인 (`/Users/kevin.brave/themek/data/dart/corp_master.json` 실제 inspection):
```json
{"corp_code": "00109693", "corp_name": "DL", "stock_code": "000210", "modify_date": "20250919"}
```

- `stock_code == ""` → 비상장사 (펀드/SPC/회계법인 등) → Stock 미생성
- `stock_code != ""` → 상장사 (우리 후보)
- pykrx가 반환한 ticker가 corp_master에 없으면 → **DART 등록 lag 또는 종목 종류 미스매치** → 해당 ticker는 `unlinked` 상태로 두고 다음 sync에서 retry (skip이지 error 아님)

### 3. pykrx 호출 정책

[pykrx 공식 문서](https://github.com/sharebook-kr/pykrx) 확인:
- `from pykrx import stock`
- `stock.get_market_ticker_list(date="YYYYMMDD", market="KOSPI"|"KOSDAQ")` — 시장별 호출 필요 (반환에 market 정보 없음)
- 1초 sleep 도의적 권장
- 상장폐지 dedicated function 없음 → **일자별 ticker list diff**로 감지

**호출 수**: 매일 cron당 `get_market_ticker_list("KOSPI") + get_market_ticker_list("KOSDAQ")` = **2회**. sleep 무의미하지만 1초씩 끼워 도의 준수.

**종목명**: pykrx `get_market_ticker_name(ticker)`는 종목당 1회 호출 → 2,500종목 × 1초 = 40분 부담. 대신 **DART corp_master의 `corp_name`** 사용 (이미 있음). Stock.name_ko에 채울 때 corp_master에서 가져온다.

### 4. 상장폐지 처리 — append-only

| 상황 | 동작 |
|------|------|
| 기존 Stock + pykrx 미반환 | `delisted_at = today` set. row 삭제 X. |
| `delisted_at` set된 Stock + pykrx 재반환 | `delisted_at = None` 복원 (재상장 케이스, 드물지만 가능) |
| BackfillTarget pending 중 상장폐지 | 그대로 두고 다음 run에서 자연스럽게 skip 결정 (universe filter) |
| BackfillTarget done인 종목 | 과거 BusinessReport는 historical fact라 그대로 유지 |

`load_universe_from_stocks(session, include_delisted=False)` 가 default로 active만 반환.

### 5. 신규 상장사 → BackfillTarget 자동 enroll

`themek krx sync-listed --auto-enroll --periods 2023:CURRENT` 옵션 사용 시:
- `SyncResult.added`에 든 신규 ticker마다 `(corp_code, period)` 곱으로 `BackfillTarget pending` 생성
- 기존 UNIQUE(corp_code, period) 충돌은 skip — idempotent
- 첫 sync 시 KOSPI+KOSDAQ 2,500종목 × 3년 = 7,500 row burst. budget 38K/day로 ~2-3일 분산 처리. 의도된 burst.

### 6. DART corp_master refresh — `--if-stale-days N`

DART는 분기 1회 refresh 권장. 매일 cron에서 매번 12MB zip 다운로드는 낭비.
- `themek dart sync-corp --if-stale-days 90` → `corp_master.json` mtime이 90일 이내면 skip
- 첫 sync 시에는 unconditional (파일 없음)

### 7. 점진적 도입 (Phase 1 / Phase 2)

| Phase | 상태 | 동작 |
|-------|------|------|
| **Phase 1 (본 plan 완료 시)** | `--from-stocks` 옵션으로 가능, `active.txt` 유지 | 운영자가 옵션 선택 |
| **Phase 2 (후속 1주 운영 후)** | cron 스크립트 default 변경, `active.txt` deprecated | runbook 갱신 |

본 plan은 Phase 1까지. Phase 2는 운영 검증 후 후속 PR.

---

## Prerequisites

- ✅ Plan #1 (Walking Skeleton)
- ✅ Plan #3 (DART API client)
- ✅ Plan #4 (Parser Robust Extraction)
- ✅ Plan #5 (Multi-Corp Backfill) — `dart backfill {init,run,status}` 동작
- ✅ Plan #6 (Eval Harness)
- `.env`에 `DART_API_KEY` 설정 + `claude` CLI 로그인
- `data/dart/corp_master.json` 1회 sync (`themek dart sync-corp`)
- 인터넷 접속 (pykrx → KRX 스크래핑)

---

## Scope (in / out)

**In:**
- `src/themek/krx/__init__.py` (NEW)
- `src/themek/krx/client.py` (NEW) — pykrx 의존성 격리 wrapper
- `src/themek/krx/sync.py` (NEW) — sync_listed_stocks + fetch_listed_universe
- `src/themek/dart/corp_lookup.py` 확장 — `build_ticker_index` (O(1) 조회)
- `src/themek/dart/universe.py` 확장 — `load_universe_from_stocks`
- `src/themek/dart/backfill.py` 확장 — `enumerate_targets_from_corps`
- `src/themek/db/models.py` 수정 — `Stock.delisted_at`, `Stock.last_seen_at`
- `migrations/versions/0004_stock_lifecycle.py` (NEW)
- `src/themek/cli.py` 수정 — `krx sync-listed` 신규, `dart sync-corp/backfill init/incremental` 옵션 확장
- `pyproject.toml` — `pykrx>=1.0.45` 추가
- 단위 테스트 ~20개 + 통합 smoke 1건 (Task 14)
- `scripts/themek_backfill.sh` 갱신
- `docs/dart-backfill-runbook.md` §11 추가 (KRX sync 절차)
- `README.md` "후속 Plan들" 섹션 갱신

**Out (후속 plan):**
- KONEX, 우선주 별도 처리 (현재는 같은 KOSPI/KOSDAQ row로 통합 처리)
- pykrx `get_market_ticker_name` 기반 종목명 (DART corp_name 사용으로 대체)
- ISIN 자동 채움 (Stock.isin은 NULL 유지)
- share_class 자동 구분 (모두 "common" 고정 — 우선주는 ticker 끝자리 5/7 패턴으로 후속 분리 가능)
- pykrx 호출 실패 시 alt 데이터 소스 fallback
- 시즌 외 매일 호출 최적화 (`get_market_ticker_list`은 영업일만 결과 변경되지만 무조건 호출)
- 상장폐지 종목의 BackfillTarget pending row 자동 정리 (운영자가 SQL로 처리)
- KRX 외 시장 (NXT 등)

---

## File Structure

```
themek/
├── src/themek/
│   ├── krx/                          # NEW
│   │   ├── __init__.py
│   │   ├── client.py                 # KrxClient (pykrx wrapper, DI 가능)
│   │   └── sync.py                   # fetch_listed_universe + sync_listed_stocks
│   ├── dart/
│   │   ├── corp_lookup.py            # 수정: build_ticker_index 추가
│   │   ├── universe.py               # 수정: load_universe_from_stocks 추가
│   │   └── backfill.py               # 수정: enumerate_targets_from_corps 추가
│   ├── db/
│   │   └── models.py                 # 수정: Stock.delisted_at, last_seen_at
│   └── cli.py                        # 수정: krx_app + 4 명령 옵션 확장
├── migrations/versions/
│   └── 0004_stock_lifecycle.py       # NEW
├── pyproject.toml                    # 수정: pykrx 추가
├── scripts/
│   └── themek_backfill.sh            # 수정: 5단계 cron 흐름
├── docs/
│   ├── dart-backfill-runbook.md      # 수정: §11 추가
│   └── superpowers/plans/
│       └── 2026-05-27-krx-stock-sync-and-auto-universe.md  # this file
└── tests/
    ├── test_krx_client.py            # NEW
    ├── test_krx_sync.py              # NEW
    ├── test_universe.py              # 수정: load_universe_from_stocks 추가
    ├── test_backfill.py              # 수정: enumerate_targets_from_corps
    ├── test_cli_krx.py               # NEW
    └── test_cli_dart_backfill.py     # 수정: --from-stocks
```

---

## Task 1: pykrx 의존성 추가 + 기본 동작 확인

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: pyproject.toml에 pykrx 추가**

`pyproject.toml`의 `dependencies` 리스트 끝에 한 줄 추가 (lxml 다음 줄):

```toml
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
    "httpx>=0.28.1",
    "pykrx>=1.0.45",
]
```

- [ ] **Step 2: 의존성 설치**

Run: `uv sync`
Expected: pykrx 및 transitive deps 설치 성공, lock 갱신.

- [ ] **Step 3: pykrx import 동작 확인 (one-shot 수동 검증)**

Run: `uv run python -c "from pykrx import stock; print(len(stock.get_market_ticker_list(market='KOSPI')))"`
Expected: KOSPI 종목 수 출력 (대략 800~900). 네트워크 실패면 재시도.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add pykrx for KRX listed ticker sync"
```

---

## Task 2: KrxClient wrapper (DI 가능 + 테스트 가능)

**Files:**
- Create: `src/themek/krx/__init__.py`
- Create: `src/themek/krx/client.py`
- Test: `tests/test_krx_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_krx_client.py`:

```python
"""KrxClient: pykrx 의존성 격리 wrapper."""
from __future__ import annotations

import pytest

from themek.krx.client import KrxClient


def test_krx_client_list_tickers_calls_pykrx(mocker):
    """KrxClient.list_tickers는 pykrx.stock.get_market_ticker_list로 위임한다."""
    fake = mocker.patch(
        "themek.krx.client.stock.get_market_ticker_list",
        return_value=["005930", "000660"],
    )
    client = KrxClient()
    result = client.list_tickers(market="KOSPI")
    assert result == ["005930", "000660"]
    fake.assert_called_once_with(market="KOSPI")


def test_krx_client_list_tickers_with_date(mocker):
    fake = mocker.patch(
        "themek.krx.client.stock.get_market_ticker_list",
        return_value=["005930"],
    )
    client = KrxClient()
    result = client.list_tickers(market="KOSDAQ", date="20240515")
    assert result == ["005930"]
    fake.assert_called_once_with("20240515", market="KOSDAQ")


def test_krx_client_rejects_invalid_market():
    client = KrxClient()
    with pytest.raises(ValueError, match="market"):
        client.list_tickers(market="INVALID")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_krx_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'themek.krx'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/themek/krx/__init__.py` (빈 파일):

```python
"""KRX 상장사 sync 모듈."""
```

Create `src/themek/krx/client.py`:

```python
"""pykrx 의존성 격리 wrapper.

pykrx는 KRX 웹사이트 스크래핑 기반이라 직접 의존하면 테스트가 네트워크에 묶인다.
이 wrapper를 통해 mocker.patch('themek.krx.client.stock....') 로 격리한다.
"""
from __future__ import annotations

from pykrx import stock

ALLOWED_MARKETS = ("KOSPI", "KOSDAQ", "KONEX", "ALL")


class KrxClient:
    """pykrx 호출 어댑터."""

    def list_tickers(
        self, *, market: str, date: str | None = None,
    ) -> list[str]:
        """KRX 종목 list. market은 KOSPI/KOSDAQ/KONEX/ALL."""
        if market not in ALLOWED_MARKETS:
            raise ValueError(
                f"market은 {ALLOWED_MARKETS} 중 하나여야 함 (got {market!r})"
            )
        if date is None:
            return stock.get_market_ticker_list(market=market)
        return stock.get_market_ticker_list(date, market=market)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_krx_client.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/themek/krx/__init__.py src/themek/krx/client.py tests/test_krx_client.py
git commit -m "feat(krx): add KrxClient pykrx wrapper with DI seam"
```

---

## Task 3: fetch_listed_universe — KOSPI+KOSDAQ 통합 fetch

**Files:**
- Create: `src/themek/krx/sync.py`
- Test: `tests/test_krx_sync.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_krx_sync.py`:

```python
"""krx/sync.py: fetch_listed_universe 통합 + sync_listed_stocks DB 반영."""
from __future__ import annotations

from datetime import date

import pytest

from themek.krx.sync import fetch_listed_universe


class FakeKrxClient:
    def __init__(self, by_market: dict[str, list[str]]):
        self._by_market = by_market
        self.calls: list[tuple[str, str | None]] = []

    def list_tickers(self, *, market: str, date: str | None = None) -> list[str]:
        self.calls.append((market, date))
        return self._by_market.get(market, [])


def test_fetch_listed_universe_merges_kospi_kosdaq():
    """KOSPI+KOSDAQ을 각각 호출해 ticker → market 매핑으로 합친다."""
    client = FakeKrxClient({
        "KOSPI": ["005930", "000660"],
        "KOSDAQ": ["247540", "035720"],
    })
    result = fetch_listed_universe(client)
    assert result == {
        "005930": "KOSPI",
        "000660": "KOSPI",
        "247540": "KOSDAQ",
        "035720": "KOSDAQ",
    }
    assert [c[0] for c in client.calls] == ["KOSPI", "KOSDAQ"]


def test_fetch_listed_universe_passes_date():
    client = FakeKrxClient({"KOSPI": [], "KOSDAQ": []})
    fetch_listed_universe(client, date="20240515")
    assert client.calls == [("KOSPI", "20240515"), ("KOSDAQ", "20240515")]


def test_fetch_listed_universe_kospi_kosdaq_overlap_kosdaq_wins():
    """동일 ticker가 양쪽 호출에 반환되면 마지막(KOSDAQ)이 우선 — 현실에선 거의 없는 케이스지만 deterministic 동작 보장."""
    client = FakeKrxClient({
        "KOSPI": ["005930"],
        "KOSDAQ": ["005930"],
    })
    result = fetch_listed_universe(client)
    assert result == {"005930": "KOSDAQ"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_krx_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: themek.krx.sync`.

- [ ] **Step 3: Write minimal implementation**

Create `src/themek/krx/sync.py`:

```python
"""KRX 상장사 → Stock 테이블 sync."""
from __future__ import annotations

from typing import Protocol


class _KrxClientLike(Protocol):
    def list_tickers(
        self, *, market: str, date: str | None = None,
    ) -> list[str]: ...


def fetch_listed_universe(
    client: _KrxClientLike,
    *,
    date: str | None = None,
) -> dict[str, str]:
    """KOSPI + KOSDAQ 통합. {ticker: market} 반환.

    date=None이면 최근 영업일.
    """
    out: dict[str, str] = {}
    for market in ("KOSPI", "KOSDAQ"):
        for t in client.list_tickers(market=market, date=date):
            out[t] = market
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_krx_sync.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/themek/krx/sync.py tests/test_krx_sync.py
git commit -m "feat(krx): add fetch_listed_universe (KOSPI+KOSDAQ merge)"
```

---

## Task 4: 마이그레이션 0004 — Stock.delisted_at, Stock.last_seen_at

**Files:**
- Create: `migrations/versions/0004_stock_lifecycle.py`
- Modify: `src/themek/db/models.py`
- Test: `tests/test_db_models.py` (확장)

- [ ] **Step 1: 기존 down_revision 확인**

Run: `grep -h "^revision\b\|^down_revision\b" migrations/versions/*.py`
Expected output snippet:
```
revision: str = "0003_backfill_target"
down_revision: Union[str, Sequence[str], None] = "bb34bb9167b6"
```
→ 새 migration의 `down_revision`은 `"0003_backfill_target"`.

- [ ] **Step 2: Write the failing test (model 확장 검증)**

Add to `tests/test_db_models.py` (파일 끝에 append):

```python
def test_stock_lifecycle_columns_exist():
    """Stock 모델에 delisted_at, last_seen_at, created_at 컬럼이 존재한다."""
    from themek.db.models import Stock
    cols = {c.name for c in Stock.__table__.columns}
    assert "delisted_at" in cols
    assert "last_seen_at" in cols
    assert "created_at" in cols


def test_stock_lifecycle_columns_nullable(test_session):
    """delisted_at/last_seen_at NULL 허용 + created_at 자동 set."""
    from datetime import date
    from themek.db.models import Stock, Corporation
    test_session.add(Corporation(dart_code="00000001", name_ko="테스트"))
    test_session.flush()
    s = Stock(
        ticker="999999", name_ko="테스트주", market="KOSPI",
        share_class="common", issued_by_id="00000001",
        last_seen_at=date(2026, 5, 27),
    )
    test_session.add(s)
    test_session.commit()
    test_session.refresh(s)
    assert s.delisted_at is None
    assert s.last_seen_at == date(2026, 5, 27)
    assert s.created_at is not None  # server_default
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_db_models.py::test_stock_lifecycle_columns_exist -v`
Expected: FAIL — `delisted_at not in cols`.

- [ ] **Step 4: 모델 갱신**

Modify `src/themek/db/models.py` — `Stock` 클래스에 두 필드 추가 (`issued_by` relationship 다음에):

```python
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

    # Plan #5.2: lifecycle
    delisted_at: Mapped[Optional[_date]] = mapped_column(Date)
    last_seen_at: Mapped[Optional[_date]] = mapped_column(Date)
    created_at: Mapped[Optional[_datetime]] = mapped_column(
        DateTime, server_default=func.current_timestamp(),
    )
```

(주의: `_datetime`, `DateTime`, `func`는 파일 상단에 이미 import되어 있음 — `from datetime import datetime as _datetime`, `from sqlalchemy import DateTime, func`. 누락 시 추가.)

- [ ] **Step 5: 마이그레이션 작성**

Create `migrations/versions/0004_stock_lifecycle.py`:

```python
"""add_stock_lifecycle_columns

Revision ID: 0004_stock_lifecycle
Revises: 0003_backfill_target
Create Date: 2026-05-27 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_stock_lifecycle"
down_revision: Union[str, Sequence[str], None] = "0003_backfill_target"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("stocks") as batch:
        batch.add_column(sa.Column("delisted_at", sa.Date(), nullable=True))
        batch.add_column(sa.Column("last_seen_at", sa.Date(), nullable=True))
        batch.add_column(sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.current_timestamp(), nullable=True,
        ))


def downgrade() -> None:
    with op.batch_alter_table("stocks") as batch:
        batch.drop_column("created_at")
        batch.drop_column("last_seen_at")
        batch.drop_column("delisted_at")
```

`batch_alter_table`은 SQLite에서 ADD COLUMN 호환을 보장하기 위해 사용 (alembic 표준 패턴).

- [ ] **Step 6: 마이그레이션 적용 + 테스트 통과 확인**

Run: `uv run alembic upgrade head && uv run pytest tests/test_db_models.py::test_stock_lifecycle_columns_exist tests/test_db_models.py::test_stock_lifecycle_columns_nullable -v`
Expected: 2 tests PASS.

- [ ] **Step 7: 회귀 확인**

Run: `uv run pytest -v`
Expected: 기존 198개 + 신규 2개 = 200개 모두 PASS.

- [ ] **Step 8: Commit**

```bash
git add migrations/versions/0004_stock_lifecycle.py src/themek/db/models.py tests/test_db_models.py
git commit -m "feat(db): add Stock.delisted_at and Stock.last_seen_at (migration 0004)"
```

---

## Task 5: build_ticker_index — corp_master O(1) 조회

**Files:**
- Modify: `src/themek/dart/corp_lookup.py`
- Test: `tests/test_dart_corp_lookup.py` (확장)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dart_corp_lookup.py` (파일 끝에 append):

```python
def test_build_ticker_index_skips_empty_stock_code(tmp_path, monkeypatch):
    """stock_code=''은 비상장 → 인덱스 제외."""
    from themek.dart.cache import DartCache
    from themek.dart.corp_lookup import build_ticker_index
    cache = DartCache(base_dir=tmp_path)
    cache.save_corp_master([
        {"corp_code": "00109693", "corp_name": "DL", "stock_code": "000210", "modify_date": "20250919"},
        {"corp_code": "00434003", "corp_name": "다코", "stock_code": "", "modify_date": "20170630"},
        {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930", "modify_date": "20240312"},
    ])
    idx = build_ticker_index(cache)
    assert set(idx.keys()) == {"000210", "005930"}
    assert idx["005930"]["corp_code"] == "00126380"
    assert idx["005930"]["corp_name"] == "삼성전자"


def test_build_ticker_index_missing_master_raises(tmp_path):
    from themek.dart.cache import DartCache
    from themek.dart.corp_lookup import build_ticker_index
    cache = DartCache(base_dir=tmp_path)
    with pytest.raises(LookupError, match="corp_master"):
        build_ticker_index(cache)
```

(`pytest`는 이미 import되어 있다고 가정. 없으면 파일 상단에 `import pytest` 추가.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_dart_corp_lookup.py::test_build_ticker_index_skips_empty_stock_code -v`
Expected: FAIL — `cannot import name 'build_ticker_index'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/themek/dart/corp_lookup.py` (`lookup_corp_code` 함수 다음):

```python
def build_ticker_index(cache: DartCache) -> dict[str, dict]:
    """corp_master.json → {stock_code: row}. stock_code 빈 값은 제외.

    O(1) lookup 필요할 때 (예: sync_listed_stocks 2,500종목 조회).
    """
    rows = cache.load_corp_master()
    if rows is None:
        raise LookupError(
            "corp_master 없음. `themek dart sync-corp` 먼저 실행하세요."
        )
    return {r["stock_code"]: r for r in rows if r.get("stock_code")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_dart_corp_lookup.py -v`
Expected: 신규 2 + 기존 N개 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/themek/dart/corp_lookup.py tests/test_dart_corp_lookup.py
git commit -m "feat(dart): add build_ticker_index for O(1) corp_master lookup"
```

---

## Task 6: sync_listed_stocks — Stock upsert + delisting 감지

**Files:**
- Modify: `src/themek/krx/sync.py`
- Test: `tests/test_krx_sync.py` (확장)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_krx_sync.py` (파일 끝에 append):

```python
from sqlalchemy import select

from themek.db.models import Stock, Corporation


def _save_corp_master(cache, rows):
    cache.save_corp_master(rows)


def test_sync_listed_stocks_inserts_new_with_corp_link(
    test_session, tmp_path,
):
    """첫 sync — Stock + Corporation upsert + last_seen_at=today."""
    from themek.dart.cache import DartCache
    from themek.krx.sync import sync_listed_stocks

    cache = DartCache(base_dir=tmp_path)
    _save_corp_master(cache, [
        {"corp_code": "00126380", "corp_name": "삼성전자",
         "stock_code": "005930", "modify_date": "20240312"},
        {"corp_code": "01160363", "corp_name": "에코프로비엠",
         "stock_code": "247540", "modify_date": "20240312"},
    ])
    client = FakeKrxClient({
        "KOSPI": ["005930"],
        "KOSDAQ": ["247540"],
    })

    r = sync_listed_stocks(
        test_session, krx_client=client, cache=cache,
        today=date(2026, 5, 27),
    )

    stocks = {s.ticker: s for s in test_session.scalars(select(Stock)).all()}
    assert set(stocks.keys()) == {"005930", "247540"}
    assert stocks["005930"].market == "KOSPI"
    assert stocks["005930"].name_ko == "삼성전자"
    assert stocks["005930"].issued_by_id == "00126380"
    assert stocks["005930"].last_seen_at == date(2026, 5, 27)
    assert stocks["005930"].delisted_at is None
    assert set(r.added) == {"005930", "247540"}
    assert r.delisted == []
    assert r.updated == []
    assert r.unlinked == []


def test_sync_listed_stocks_marks_delisted(test_session, tmp_path):
    """기존 Stock이 KRX에 없으면 delisted_at=today set."""
    from themek.dart.cache import DartCache
    from themek.krx.sync import sync_listed_stocks

    cache = DartCache(base_dir=tmp_path)
    _save_corp_master(cache, [
        {"corp_code": "00126380", "corp_name": "삼성전자",
         "stock_code": "005930", "modify_date": "20240312"},
        {"corp_code": "00009999", "corp_name": "구상장사",
         "stock_code": "888888", "modify_date": "20100101"},
    ])
    test_session.add(Corporation(dart_code="00009999", name_ko="구상장사"))
    test_session.flush()
    test_session.add(Stock(
        ticker="888888", name_ko="구상장사", market="KOSPI",
        share_class="common", issued_by_id="00009999",
        last_seen_at=date(2026, 5, 20),
    ))
    test_session.commit()

    client = FakeKrxClient({"KOSPI": ["005930"], "KOSDAQ": []})
    r = sync_listed_stocks(
        test_session, krx_client=client, cache=cache,
        today=date(2026, 5, 27),
    )

    delisted = test_session.get(Stock, "888888")
    assert delisted.delisted_at == date(2026, 5, 27)
    assert r.delisted == ["888888"]


def test_sync_listed_stocks_unlinked_when_corp_master_missing(
    test_session, tmp_path,
):
    """pykrx ticker가 corp_master에 없으면 unlinked로 두고 skip (error 아님)."""
    from themek.dart.cache import DartCache
    from themek.krx.sync import sync_listed_stocks

    cache = DartCache(base_dir=tmp_path)
    _save_corp_master(cache, [])
    client = FakeKrxClient({"KOSPI": ["005930"], "KOSDAQ": []})
    r = sync_listed_stocks(
        test_session, krx_client=client, cache=cache,
        today=date(2026, 5, 27),
    )
    assert r.unlinked == ["005930"]
    assert r.added == []


def test_sync_listed_stocks_relisting_clears_delisted_at(
    test_session, tmp_path,
):
    """delisted_at=set인 Stock이 다시 KRX에 나타나면 None으로 복원."""
    from themek.dart.cache import DartCache
    from themek.krx.sync import sync_listed_stocks

    cache = DartCache(base_dir=tmp_path)
    _save_corp_master(cache, [
        {"corp_code": "00009999", "corp_name": "재상장사",
         "stock_code": "005930", "modify_date": "20240312"},
    ])
    test_session.add(Corporation(dart_code="00009999", name_ko="재상장사"))
    test_session.flush()
    test_session.add(Stock(
        ticker="005930", name_ko="재상장사", market="KOSPI",
        share_class="common", issued_by_id="00009999",
        delisted_at=date(2026, 1, 1), last_seen_at=date(2025, 12, 31),
    ))
    test_session.commit()

    client = FakeKrxClient({"KOSPI": ["005930"], "KOSDAQ": []})
    r = sync_listed_stocks(
        test_session, krx_client=client, cache=cache,
        today=date(2026, 5, 27),
    )
    stock = test_session.get(Stock, "005930")
    assert stock.delisted_at is None
    assert stock.last_seen_at == date(2026, 5, 27)
    assert "005930" in r.updated
```

`test_session` fixture는 기존 `tests/conftest.py`가 제공한다고 가정 (Plan #1).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_krx_sync.py::test_sync_listed_stocks_inserts_new_with_corp_link -v`
Expected: FAIL — `cannot import name 'sync_listed_stocks'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/themek/krx/sync.py` (`fetch_listed_universe` 다음):

```python
from dataclasses import dataclass, field
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.db.models import Stock, Corporation
from themek.dart.cache import DartCache
from themek.dart.corp_lookup import build_ticker_index


@dataclass
class SyncResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    delisted: list[str] = field(default_factory=list)
    unlinked: list[str] = field(default_factory=list)


def sync_listed_stocks(
    session: Session,
    *,
    krx_client: _KrxClientLike,
    cache: DartCache,
    today: date,
) -> SyncResult:
    """KRX KOSPI+KOSDAQ ticker list → Stock 테이블 upsert + delisting 감지.

    동작:
    - listed에 있는 ticker:
      - corp_master 매칭: Corporation upsert + Stock upsert (last_seen_at=today)
      - delisted_at set인 row면 None으로 복원 (재상장)
      - corp_master 미매칭: unlinked로 기록, Stock 미생성
    - listed에 없는 기존 Stock + delisted_at=None: delisted_at=today set
    """
    listed = fetch_listed_universe(krx_client)
    idx = build_ticker_index(cache)
    existing = {s.ticker: s for s in session.scalars(select(Stock)).all()}

    result = SyncResult()
    for ticker, market in listed.items():
        corp = idx.get(ticker)
        if corp is None:
            result.unlinked.append(ticker)
            continue
        corp_code = corp["corp_code"]
        name = corp.get("corp_name") or ticker

        if session.get(Corporation, corp_code) is None:
            session.add(Corporation(dart_code=corp_code, name_ko=name))
            session.flush()

        row = existing.get(ticker)
        if row is None:
            session.add(Stock(
                ticker=ticker, name_ko=name, market=market,
                share_class="common", issued_by_id=corp_code,
                last_seen_at=today,
            ))
            result.added.append(ticker)
        else:
            row.market = market
            row.last_seen_at = today
            if row.delisted_at is not None:
                row.delisted_at = None
            result.updated.append(ticker)

    listed_set = set(listed.keys())
    for ticker, row in existing.items():
        if ticker not in listed_set and row.delisted_at is None:
            row.delisted_at = today
            result.delisted.append(ticker)

    session.commit()
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_krx_sync.py -v`
Expected: 신규 4 + 기존 3 = 7 PASS.

- [ ] **Step 5: 회귀 확인**

Run: `uv run pytest -v`
Expected: 모두 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/themek/krx/sync.py tests/test_krx_sync.py
git commit -m "feat(krx): sync_listed_stocks — upsert Stock + delisting detection"
```

---

## Task 7: load_universe_from_stocks

**Files:**
- Modify: `src/themek/dart/universe.py`
- Test: `tests/test_universe.py` (확장)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_universe.py` (파일 끝에 append):

```python
from datetime import date

from themek.db.models import Stock, Corporation


def test_load_universe_from_stocks_returns_corp_codes(test_session):
    from themek.dart.universe import load_universe_from_stocks

    test_session.add_all([
        Corporation(dart_code="00126380", name_ko="삼성전자"),
        Corporation(dart_code="00164742", name_ko="현대자동차"),
    ])
    test_session.flush()
    test_session.add_all([
        Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
              share_class="common", issued_by_id="00126380",
              last_seen_at=date(2026, 5, 27)),
        Stock(ticker="005380", name_ko="현대자동차", market="KOSPI",
              share_class="common", issued_by_id="00164742",
              last_seen_at=date(2026, 5, 27)),
    ])
    test_session.commit()

    corps = load_universe_from_stocks(test_session)
    assert sorted(corps) == ["00126380", "00164742"]


def test_load_universe_from_stocks_excludes_delisted_by_default(test_session):
    from themek.dart.universe import load_universe_from_stocks

    test_session.add_all([
        Corporation(dart_code="00126380", name_ko="삼성전자"),
        Corporation(dart_code="00009999", name_ko="구상장사"),
    ])
    test_session.flush()
    test_session.add_all([
        Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
              share_class="common", issued_by_id="00126380",
              last_seen_at=date(2026, 5, 27)),
        Stock(ticker="888888", name_ko="구상장사", market="KOSPI",
              share_class="common", issued_by_id="00009999",
              delisted_at=date(2026, 1, 1)),
    ])
    test_session.commit()

    assert sorted(load_universe_from_stocks(test_session)) == ["00126380"]
    assert sorted(load_universe_from_stocks(
        test_session, include_delisted=True,
    )) == ["00009999", "00126380"]


def test_load_universe_from_stocks_distinct_when_multiple_share_classes(test_session):
    """동일 corp가 보통주+우선주 발행해도 corp_code는 1번만."""
    from themek.dart.universe import load_universe_from_stocks

    test_session.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
    test_session.flush()
    test_session.add_all([
        Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
              share_class="common", issued_by_id="00126380",
              last_seen_at=date(2026, 5, 27)),
        Stock(ticker="005935", name_ko="삼성전자우", market="KOSPI",
              share_class="preferred", issued_by_id="00126380",
              last_seen_at=date(2026, 5, 27)),
    ])
    test_session.commit()
    assert load_universe_from_stocks(test_session) == ["00126380"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_universe.py -v`
Expected: 신규 3건 FAIL — `cannot import name 'load_universe_from_stocks'`.

- [ ] **Step 3: Write minimal implementation**

Add to `src/themek/dart/universe.py` (`load_universe` 함수 다음):

```python
from sqlalchemy import select
from sqlalchemy.orm import Session


def load_universe_from_stocks(
    session: Session,
    *,
    include_delisted: bool = False,
) -> list[str]:
    """Stock 테이블 → distinct corp_code list. delisted 기본 제외."""
    from themek.db.models import Stock

    q = select(Stock.issued_by_id).distinct()
    if not include_delisted:
        q = q.where(Stock.delisted_at.is_(None))
    return list(session.scalars(q).all())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_universe.py -v`
Expected: 신규 3 + 기존 6 = 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/themek/dart/universe.py tests/test_universe.py
git commit -m "feat(dart): add load_universe_from_stocks (Stock 테이블 SSOT)"
```

---

## Task 8: enumerate_targets_from_corps

**Files:**
- Modify: `src/themek/dart/backfill.py`
- Test: `tests/test_backfill.py` (확장)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_backfill.py` (파일 끝에 append):

```python
def test_enumerate_targets_from_corps_basic():
    from themek.dart.backfill import enumerate_targets_from_corps

    specs = enumerate_targets_from_corps(
        corp_codes=["00126380", "00164742"], periods="2023:2024",
    )
    assert [(s.corp_code, s.period) for s in specs] == [
        ("00126380", "2023"),
        ("00126380", "2024"),
        ("00164742", "2023"),
        ("00164742", "2024"),
    ]


def test_enumerate_targets_from_corps_single_period():
    from themek.dart.backfill import enumerate_targets_from_corps

    specs = enumerate_targets_from_corps(
        corp_codes=["00126380"], periods="2023",
    )
    assert [(s.corp_code, s.period) for s in specs] == [("00126380", "2023")]


def test_enumerate_targets_existing_universe_file_still_works(tmp_path):
    """기존 enumerate_targets는 변경 없이 동작 (backward compat)."""
    from themek.dart.backfill import enumerate_targets

    p = tmp_path / "active.txt"
    p.write_text("00126380\n", encoding="utf-8")
    specs = enumerate_targets(universe_file=p, periods="2023")
    assert len(specs) == 1
    assert specs[0].corp_code == "00126380"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_backfill.py::test_enumerate_targets_from_corps_basic -v`
Expected: FAIL — `cannot import name 'enumerate_targets_from_corps'`.

- [ ] **Step 3: Write minimal implementation**

Modify `src/themek/dart/backfill.py` — `enumerate_targets` 위에 신규 함수 추가하고, 기존 `enumerate_targets`는 새 함수를 호출하도록 리팩터링:

```python
def enumerate_targets_from_corps(
    *,
    corp_codes: list[str],
    periods: str,
) -> list[BackfillTargetSpec]:
    """corp_code list + periods → BackfillTargetSpec 곱.

    universe source가 file이든 Stock 테이블이든 상위에서 결정한 뒤 호출.
    """
    period_list = _parse_periods(periods)
    return [BackfillTargetSpec(c, p) for c in corp_codes for p in period_list]


def enumerate_targets(
    *,
    universe_file: Path,
    periods: str,
) -> list[BackfillTargetSpec]:
    """active.txt + periods → 단순 곱."""
    corps = load_universe(universe_file)
    return enumerate_targets_from_corps(corp_codes=corps, periods=periods)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_backfill.py -v`
Expected: 신규 3 + 기존 N개 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/themek/dart/backfill.py tests/test_backfill.py
git commit -m "refactor(backfill): extract enumerate_targets_from_corps for universe-source flexibility"
```

---

## Task 9: CLI `themek krx sync-listed`

**Files:**
- Modify: `src/themek/cli.py`
- Test: `tests/test_cli_krx.py` (NEW)

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_krx.py`:

```python
"""CLI: themek krx sync-listed."""
from __future__ import annotations

from datetime import date

import pytest
from typer.testing import CliRunner

from themek.cli import app


runner = CliRunner()


@pytest.fixture
def fake_listed(mocker):
    """KrxClient를 mock해서 KOSPI 2 + KOSDAQ 1 종목 반환."""

    class _Fake:
        def list_tickers(self, *, market, date=None):
            return {
                "KOSPI": ["005930", "000660"],
                "KOSDAQ": ["247540"],
            }.get(market, [])

    mocker.patch("themek.cli.KrxClient", return_value=_Fake())
    return _Fake


@pytest.fixture
def fake_corp_master(test_session, tmp_path, mocker):
    """corp_master.json 3건 — KOSPI 2 + KOSDAQ 1."""
    from themek.dart.cache import DartCache
    cache = DartCache(base_dir=tmp_path)
    cache.save_corp_master([
        {"corp_code": "00126380", "corp_name": "삼성전자",
         "stock_code": "005930", "modify_date": "20240312"},
        {"corp_code": "00164779", "corp_name": "SK하이닉스",
         "stock_code": "000660", "modify_date": "20240312"},
        {"corp_code": "01160363", "corp_name": "에코프로비엠",
         "stock_code": "247540", "modify_date": "20240312"},
    ])
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(None, cache),
    )
    return cache


def test_krx_sync_listed_dry_run(fake_listed, fake_corp_master):
    """--dry-run은 listed count만 출력하고 DB 미변경."""
    result = runner.invoke(app, ["krx", "sync-listed", "--dry-run"])
    assert result.exit_code == 0
    assert "3" in result.stdout  # 2 KOSPI + 1 KOSDAQ


def test_krx_sync_listed_actual_run_inserts_stocks(
    fake_listed, fake_corp_master, test_session,
):
    """실 sync — Stock 3 row 추가."""
    from sqlalchemy import select

    from themek.db.models import Stock

    result = runner.invoke(app, ["krx", "sync-listed"])
    assert result.exit_code == 0, result.stdout
    assert "added=3" in result.stdout

    stocks = test_session.scalars(select(Stock)).all()
    assert {s.ticker for s in stocks} == {"005930", "000660", "247540"}


def test_krx_sync_listed_auto_enroll_creates_backfill_targets(
    fake_listed, fake_corp_master, test_session,
):
    """--auto-enroll --periods 2023 시 신규 ticker마다 BackfillTarget pending."""
    from sqlalchemy import select

    from themek.db.models import BackfillTarget

    result = runner.invoke(app, [
        "krx", "sync-listed",
        "--auto-enroll", "--periods", "2023:2024",
    ])
    assert result.exit_code == 0, result.stdout
    assert "auto-enrolled" in result.stdout

    targets = test_session.scalars(select(BackfillTarget)).all()
    assert len(targets) == 6  # 3 corps × 2 years
    for t in targets:
        assert t.status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_krx.py -v`
Expected: FAIL — `No such command 'krx'`.

- [ ] **Step 3: Write minimal implementation**

Modify `src/themek/cli.py`:

(a) 파일 상단 import 섹션에 추가:

```python
from themek.krx.client import KrxClient
from themek.krx.sync import sync_listed_stocks, fetch_listed_universe
```

(b) `dart_app` 정의 다음에 `krx_app` 추가:

```python
krx_app = typer.Typer(help="KRX 상장사 sync 명령")
app.add_typer(krx_app, name="krx")
```

(c) 파일 끝의 `if __name__ == "__main__":` 직전에 신규 명령 추가:

```python
@krx_app.command("sync-listed")
def krx_sync_listed_cmd(
    auto_enroll: bool = typer.Option(
        False, "--auto-enroll",
        help="신규 상장 종목마다 BackfillTarget pending row 자동 생성",
    ),
    periods: Optional[str] = typer.Option(
        None, "--periods",
        help="--auto-enroll 사용 시 BackfillTarget 생성 period 범위 (예: 2023:2024)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="KRX 호출까지만 하고 DB 미변경, ticker 수만 출력",
    ),
):
    """KOSPI/KOSDAQ 상장사를 Stock 테이블에 sync."""
    from sqlalchemy import select

    from themek.db.models import BackfillTarget, Stock
    from themek.dart.backfill import _parse_periods

    try:
        _, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)

    client = KrxClient()

    if dry_run:
        listed = fetch_listed_universe(client)
        typer.echo(
            f"[dry-run] KOSPI/KOSDAQ {len(listed)} listed tickers "
            f"(KOSPI={sum(1 for v in listed.values() if v == 'KOSPI')}, "
            f"KOSDAQ={sum(1 for v in listed.values() if v == 'KOSDAQ')})"
        )
        return

    with _session() as sess:
        r = sync_listed_stocks(
            sess, krx_client=client, cache=cache, today=date.today(),
        )
    typer.echo(
        f"added={len(r.added)} delisted={len(r.delisted)} "
        f"updated={len(r.updated)} unlinked={len(r.unlinked)}"
    )

    if auto_enroll and r.added:
        if not periods:
            typer.echo(
                "Warning: --auto-enroll 사용 시 --periods 필요 — skip",
                err=True,
            )
            return
        period_list = _parse_periods(periods)
        inserted = 0
        with _session() as sess:
            for ticker in r.added:
                stock = sess.get(Stock, ticker)
                if stock is None:
                    continue
                for p in period_list:
                    existing = sess.scalar(
                        select(BackfillTarget)
                        .where(BackfillTarget.corp_code == stock.issued_by_id)
                        .where(BackfillTarget.period == p)
                    )
                    if existing is not None:
                        continue
                    sess.add(BackfillTarget(
                        corp_code=stock.issued_by_id, period=p,
                        status="pending",
                    ))
                    inserted += 1
            sess.commit()
        typer.echo(f"auto-enrolled {inserted} new BackfillTarget rows")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_krx.py -v`
Expected: 3 tests PASS.

- [ ] **Step 5: 회귀 확인**

Run: `uv run pytest -v`
Expected: 모든 테스트 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/themek/cli.py tests/test_cli_krx.py
git commit -m "feat(cli): add 'themek krx sync-listed' with --auto-enroll"
```

---

## Task 10: `dart backfill init --from-stocks`

**Files:**
- Modify: `src/themek/cli.py`
- Test: `tests/test_cli_dart_backfill.py` (확장)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_dart_backfill.py` (파일 끝에 append):

```python
def test_backfill_init_from_stocks_uses_stock_table(test_session, mocker):
    """--from-stocks는 Stock 테이블에서 universe를 가져온다."""
    from datetime import date

    from sqlalchemy import select
    from typer.testing import CliRunner

    from themek.cli import app
    from themek.db.models import BackfillTarget, Corporation, Stock

    test_session.add_all([
        Corporation(dart_code="00126380", name_ko="삼성전자"),
        Corporation(dart_code="00164742", name_ko="현대자동차"),
    ])
    test_session.flush()
    test_session.add_all([
        Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
              share_class="common", issued_by_id="00126380",
              last_seen_at=date(2026, 5, 27)),
        Stock(ticker="005380", name_ko="현대자동차", market="KOSPI",
              share_class="common", issued_by_id="00164742",
              last_seen_at=date(2026, 5, 27)),
    ])
    test_session.commit()

    runner = CliRunner()
    result = runner.invoke(app, [
        "dart", "backfill", "init",
        "--from-stocks", "--periods", "2023", "--confirm",
    ])
    assert result.exit_code == 0, result.stdout

    targets = test_session.scalars(select(BackfillTarget)).all()
    assert {(t.corp_code, t.period) for t in targets} == {
        ("00126380", "2023"),
        ("00164742", "2023"),
    }


def test_backfill_init_from_stocks_dry_run_no_db_change(test_session, mocker):
    from datetime import date

    from sqlalchemy import select
    from typer.testing import CliRunner

    from themek.cli import app
    from themek.db.models import BackfillTarget, Corporation, Stock

    test_session.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
    test_session.flush()
    test_session.add(Stock(
        ticker="005930", name_ko="삼성전자", market="KOSPI",
        share_class="common", issued_by_id="00126380",
        last_seen_at=date(2026, 5, 27),
    ))
    test_session.commit()

    runner = CliRunner()
    result = runner.invoke(app, [
        "dart", "backfill", "init",
        "--from-stocks", "--periods", "2023",
    ])
    assert result.exit_code == 0
    assert "dry-run" in result.stdout.lower()
    assert test_session.scalars(select(BackfillTarget)).all() == []


def test_backfill_init_rejects_both_universe_sources():
    """--from-stocks와 --universe-file 동시 사용은 거부."""
    from typer.testing import CliRunner

    from themek.cli import app

    runner = CliRunner()
    result = runner.invoke(app, [
        "dart", "backfill", "init",
        "--from-stocks", "--universe-file", "data/universe/active.txt",
        "--periods", "2023",
    ])
    assert result.exit_code != 0
    assert "동시" in result.stdout or "동시" in result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_dart_backfill.py::test_backfill_init_from_stocks_uses_stock_table -v`
Expected: FAIL — `--from-stocks unknown option`.

- [ ] **Step 3: Write minimal implementation**

Modify `src/themek/cli.py` — `backfill_init_cmd` 함수 전체를 다음으로 교체:

```python
@backfill_app.command("init")
def backfill_init_cmd(
    universe_file: Optional[Path] = typer.Option(
        None, "--universe-file",
        help="corp_code 1줄당 1개. # 주석 허용. --from-stocks와 배타.",
    ),
    from_stocks: bool = typer.Option(
        False, "--from-stocks",
        help="Stock 테이블의 active 종목을 universe로 사용 (--universe-file 대체).",
    ),
    include_delisted: bool = typer.Option(
        False, "--include-delisted",
        help="--from-stocks 사용 시 delisted_at set된 종목도 포함.",
    ),
    periods: str = typer.Option(
        ..., "--periods",
        help="YYYY 단일 또는 YYYY:YYYY 범위",
    ),
    confirm: bool = typer.Option(
        False, "--confirm",
        help="dry-run 끄고 실제 row 생성",
    ),
):
    """universe × periods → BackfillTarget row 생성 (dry-run 기본)."""
    from sqlalchemy import select

    from themek.dart.backfill import (
        enumerate_targets, enumerate_targets_from_corps,
    )
    from themek.dart.universe import load_universe_from_stocks
    from themek.db.models import BackfillTarget

    if from_stocks and universe_file is not None:
        typer.echo(
            "Error: --from-stocks와 --universe-file 동시 사용 불가",
            err=True,
        )
        raise typer.Exit(code=1)

    if from_stocks:
        with _session() as sess:
            corps = load_universe_from_stocks(
                sess, include_delisted=include_delisted,
            )
        specs = enumerate_targets_from_corps(
            corp_codes=corps, periods=periods,
        )
        universe_label = (
            f"Stock table ({'incl. delisted' if include_delisted else 'active only'})"
        )
    else:
        uf = universe_file or Path(DEFAULT_UNIVERSE_FILE)
        specs = enumerate_targets(universe_file=uf, periods=periods)
        universe_label = str(uf)

    n_targets = len(specs)
    n_calls = n_targets * 2
    est_cost = n_targets * 0.25

    typer.echo("=== Backfill Init Dry-Run ===")
    typer.echo(f"universe: {universe_label}")
    typer.echo(f"periods: {periods}")
    typer.echo(f"예상 처리: {n_targets} target")
    typer.echo(f"예상 DART 호출: ~{n_calls} (limit 38000/day)")
    typer.echo(f"예상 LLM 비용: ~${est_cost:.2f} (평균 단가 기준)")

    if not confirm:
        typer.echo("\n--confirm 추가 시 실제 BackfillTarget row 생성.")
        return

    inserted, skipped = 0, 0
    with _session() as sess:
        for spec in specs:
            existing = sess.scalar(
                select(BackfillTarget)
                .where(BackfillTarget.corp_code == spec.corp_code)
                .where(BackfillTarget.period == spec.period)
            )
            if existing is not None:
                skipped += 1
                continue
            sess.add(BackfillTarget(
                corp_code=spec.corp_code, period=spec.period, status="pending",
            ))
            inserted += 1
        sess.commit()
    typer.echo(f"\ninserted={inserted} skipped (already exists)={skipped}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_dart_backfill.py -v`
Expected: 신규 3 + 기존 N개 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/themek/cli.py tests/test_cli_dart_backfill.py
git commit -m "feat(cli): add 'dart backfill init --from-stocks' (Stock 테이블 SSOT)"
```

---

## Task 11: `dart incremental --universe-source stocks`

**Files:**
- Modify: `src/themek/cli.py`
- Test: `tests/test_cli_dart.py` (확장)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_dart.py` (파일 끝에 append):

```python
def test_dart_incremental_universe_source_stocks(test_session, mocker):
    """--universe-source stocks는 Stock 테이블에서 corp_code set을 만든다."""
    from datetime import date

    from typer.testing import CliRunner

    from themek.cli import app
    from themek.db.models import Corporation, Stock
    from themek.dart.incremental import IncrementalRunResult

    test_session.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
    test_session.flush()
    test_session.add(Stock(
        ticker="005930", name_ko="삼성전자", market="KOSPI",
        share_class="common", issued_by_id="00126380",
        last_seen_at=date(2026, 5, 27),
    ))
    test_session.commit()

    captured: dict = {}

    def fake_run(*, universe, **kwargs):
        captured["universe"] = universe
        return IncrementalRunResult()

    mocker.patch("themek.cli.run_incremental", fake_run)
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), mocker.MagicMock()),
    )

    runner = CliRunner()
    result = runner.invoke(app, [
        "dart", "incremental",
        "--universe-source", "stocks",
        "--since", "yesterday", "--until", "today",
    ])
    assert result.exit_code == 0, result.stdout
    assert captured["universe"] == {"00126380"}


def test_dart_incremental_universe_source_file_still_works(test_session, mocker, tmp_path):
    from typer.testing import CliRunner

    from themek.cli import app
    from themek.dart.incremental import IncrementalRunResult

    p = tmp_path / "active.txt"
    p.write_text("00126380\n", encoding="utf-8")

    captured: dict = {}

    def fake_run(*, universe, **kwargs):
        captured["universe"] = universe
        return IncrementalRunResult()

    mocker.patch("themek.cli.run_incremental", fake_run)
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), mocker.MagicMock()),
    )

    runner = CliRunner()
    result = runner.invoke(app, [
        "dart", "incremental",
        "--universe-file", str(p),
    ])
    assert result.exit_code == 0
    assert captured["universe"] == {"00126380"}
```

`themek.cli.run_incremental`이 import되어 있어야 mock 가능 → cli.py가 함수를 함수 본문 안에서 import하지 말고 모듈 import로 끌어올려야 한다. 그렇게 수정.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_dart.py::test_dart_incremental_universe_source_stocks -v`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

Modify `src/themek/cli.py`:

(a) 파일 상단 import에 추가:

```python
from themek.dart.incremental import run_incremental
```

(b) `dart_incremental_cmd` 함수 전체를 다음으로 교체:

```python
@dart_app.command("incremental")
def dart_incremental_cmd(
    since: str = typer.Option("yesterday", "--since"),
    until: str = typer.Option("today", "--until"),
    universe_source: str = typer.Option(
        "file", "--universe-source",
        help="file | stocks",
    ),
    universe_file: Path = typer.Option(
        DEFAULT_UNIVERSE_FILE, "--universe-file",
        help="active.txt 경로 (--universe-source=file 일 때만)",
    ),
    include_delisted: bool = typer.Option(
        False, "--include-delisted",
        help="--universe-source=stocks 시 delisted 종목 포함",
    ),
    purge_zip: bool = typer.Option(False, "--purge-zip-after-extract"),
):
    """Layer B: scan → universe filter → 신규만 ingest."""
    from datetime import timedelta

    from themek.dart.universe import load_universe, load_universe_from_stocks
    from themek.dart.rate_budget import RateBudget

    s = get_settings()
    today = date.today()
    since_d = (
        today - timedelta(days=1) if since == "yesterday"
        else date.fromisoformat(since)
    )
    until_d = (
        today if until == "today" else date.fromisoformat(until)
    )

    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)

    if universe_source == "stocks":
        with _session() as sess:
            universe = set(load_universe_from_stocks(
                sess, include_delisted=include_delisted,
            ))
    elif universe_source == "file":
        universe = set(load_universe(universe_file))
    else:
        typer.echo(
            f"Error: --universe-source는 'file' 또는 'stocks' (got {universe_source!r})",
            err=True,
        )
        raise typer.Exit(code=1)

    budget = RateBudget(
        daily_cap=38000,
        state_file=s.dart_cache_dir / "budget_state.json",
    )
    extractor = _stub_extractor_from_env()

    with _session() as sess:
        result = run_incremental(
            client=client, cache=cache, session=sess,
            universe=universe, rate_budget=budget, extractor=extractor,
            since=since_d, until=until_d,
            purge_zip=purge_zip,
        )
    typer.echo(
        f"scanned={result.scanned} in_universe={result.in_universe} "
        f"already_ingested={result.already_ingested} "
        f"to_ingest={result.to_ingest} ingested={result.ingested} "
        f"failed={len(result.failed)}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_dart.py -v`
Expected: 신규 2 + 기존 N개 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/themek/cli.py tests/test_cli_dart.py
git commit -m "feat(cli): add '--universe-source stocks' to dart incremental"
```

---

## Task 12: `dart sync-corp --if-stale-days N`

**Files:**
- Modify: `src/themek/cli.py`
- Test: `tests/test_cli_dart.py` (확장)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_dart.py` (파일 끝에 append):

```python
def test_dart_sync_corp_skips_when_fresh(tmp_path, mocker):
    """--if-stale-days N: corp_master.json mtime이 N일 이내면 skip."""
    import os
    import time

    from typer.testing import CliRunner

    from themek.cli import app
    from themek.dart.cache import DartCache

    cache = DartCache(base_dir=tmp_path)
    cache.save_corp_master([{"corp_code": "00000001", "corp_name": "x",
                              "stock_code": "", "modify_date": "20240101"}])
    # 방금 저장되어 mtime이 now
    fake_sync = mocker.patch("themek.cli.sync_corp_master")
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), cache),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["dart", "sync-corp", "--if-stale-days", "90"])
    assert result.exit_code == 0
    assert "skipped" in result.stdout.lower()
    fake_sync.assert_not_called()


def test_dart_sync_corp_runs_when_stale(tmp_path, mocker):
    import os
    import time

    from typer.testing import CliRunner

    from themek.cli import app
    from themek.dart.cache import DartCache

    cache = DartCache(base_dir=tmp_path)
    cache.save_corp_master([])
    old_mtime = time.time() - 100 * 86400  # 100일 전
    os.utime(cache.corp_master_path, (old_mtime, old_mtime))

    fake_sync = mocker.patch("themek.cli.sync_corp_master", return_value=42)
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), cache),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["dart", "sync-corp", "--if-stale-days", "90"])
    assert result.exit_code == 0
    fake_sync.assert_called_once()


def test_dart_sync_corp_runs_when_missing(tmp_path, mocker):
    from typer.testing import CliRunner

    from themek.cli import app
    from themek.dart.cache import DartCache

    cache = DartCache(base_dir=tmp_path)
    fake_sync = mocker.patch("themek.cli.sync_corp_master", return_value=42)
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(mocker.MagicMock(), cache),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["dart", "sync-corp", "--if-stale-days", "90"])
    assert result.exit_code == 0
    fake_sync.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_dart.py::test_dart_sync_corp_skips_when_fresh -v`
Expected: FAIL — `--if-stale-days unknown option`.

- [ ] **Step 3: Write minimal implementation**

Modify `src/themek/cli.py` — `dart_sync_corp_cmd` 함수 전체 교체:

```python
@dart_app.command("sync-corp")
def dart_sync_corp_cmd(
    if_stale_days: Optional[int] = typer.Option(
        None, "--if-stale-days",
        help="N일 이내 sync된 corp_master는 skip (cron 안전용)",
    ),
):
    """corp_code 마스터를 DART에서 받아 캐시."""
    import time

    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)

    if if_stale_days is not None and cache.corp_master_path.exists():
        age_days = (
            time.time() - cache.corp_master_path.stat().st_mtime
        ) / 86400
        if age_days < if_stale_days:
            typer.echo(
                f"corp_master {age_days:.1f} days old "
                f"< {if_stale_days} — skipped"
            )
            return

    try:
        n = sync_corp_master(client, cache)
    except DartApiError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=4)
    typer.echo(f"synced {n} corporations to {cache.corp_master_path}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_dart.py -v`
Expected: 신규 3 + 기존 N개 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/themek/cli.py tests/test_cli_dart.py
git commit -m "feat(cli): add 'dart sync-corp --if-stale-days N' for cron safety"
```

---

## Task 13: `backfill status` — 신규 상장 / 상장폐지 요약 추가

**Files:**
- Modify: `src/themek/cli.py`
- Test: `tests/test_cli_dart_backfill.py` (확장)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli_dart_backfill.py`:

```python
def test_backfill_status_lifecycle_summary(test_session):
    """status --verbose는 최근 7일 신규 상장 / 상장폐지 카운트도 표시."""
    from datetime import date, timedelta

    from typer.testing import CliRunner

    from themek.cli import app
    from themek.db.models import Corporation, Stock

    today = date.today()
    recent = today - timedelta(days=3)
    old = today - timedelta(days=30)

    test_session.add_all([
        Corporation(dart_code="00000001", name_ko="신규상장"),
        Corporation(dart_code="00000002", name_ko="기상장"),
        Corporation(dart_code="00000003", name_ko="최근폐지"),
        Corporation(dart_code="00000004", name_ko="옛날폐지"),
    ])
    test_session.flush()
    test_session.add_all([
        Stock(ticker="111111", name_ko="신규상장", market="KOSPI",
              share_class="common", issued_by_id="00000001",
              last_seen_at=recent),
        Stock(ticker="222222", name_ko="기상장", market="KOSPI",
              share_class="common", issued_by_id="00000002",
              last_seen_at=old),
        Stock(ticker="333333", name_ko="최근폐지", market="KOSPI",
              share_class="common", issued_by_id="00000003",
              delisted_at=recent),
        Stock(ticker="444444", name_ko="옛날폐지", market="KOSPI",
              share_class="common", issued_by_id="00000004",
              delisted_at=old),
    ])
    test_session.commit()

    runner = CliRunner()
    result = runner.invoke(app, ["dart", "backfill", "status", "--verbose"])
    assert result.exit_code == 0
    # 최근 7일 — 신규 1개, 폐지 1개. 옛날 것은 카운트 안 됨.
    assert "신규 상장 (7일): 1" in result.stdout
    assert "상장폐지 (7일): 1" in result.stdout
```

신규 상장 감지는 Task 4에서 추가한 `Stock.created_at` (server_default=CURRENT_TIMESTAMP) 으로 판단. 즉 "7일 내 INSERT된 Stock = 7일 내 신규 상장". 상장폐지는 `Stock.delisted_at >= cutoff.date()`로 7일 내 폐지된 것 카운트.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_dart_backfill.py::test_backfill_status_lifecycle_summary -v`
Expected: FAIL — "신규 상장 (7일):" 부재.

- [ ] **Step 3: Write minimal implementation**

Modify `src/themek/cli.py` — `backfill_status_cmd` 함수 끝(verbose 블록 안)에 추가:

```python
@backfill_app.command("status")
def backfill_status_cmd(
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="escalation 분포 + 비용 top-10 + 7일 신규/폐지 표시",
    ),
):
    """BackfillTarget status 분포 + 누적 LLM 비용 + lifecycle 요약."""
    from datetime import datetime, timedelta

    from sqlalchemy import select, func, desc

    from themek.db.models import BackfillTarget, Stock

    with _session() as sess:
        rows = sess.execute(
            select(BackfillTarget.status, func.count())
            .group_by(BackfillTarget.status)
        ).all()
        counts = {status: n for status, n in rows}
        total = sum(counts.values())
        total_cost = sess.scalar(
            select(func.sum(BackfillTarget.cost_estimate_usd))
        ) or 0

    typer.echo("=== BackfillTarget summary ===")
    for status in ("pending", "in_progress", "done", "failed", "skipped"):
        typer.echo(f"  {status:12s}: {counts.get(status, 0):6d}")
    typer.echo(f"  {'total':12s}: {total:6d}")
    typer.echo(f"\nTotal LLM cost (done): ${float(total_cost):.2f}")

    if not verbose:
        return

    with _session() as sess:
        esc_rows = sess.execute(
            select(BackfillTarget.escalation_level, func.count())
            .where(BackfillTarget.status == "done")
            .group_by(BackfillTarget.escalation_level)
        ).all()
        typer.echo("\n=== Escalation distribution (done) ===")
        for level, n in esc_rows:
            typer.echo(f"  {str(level):12s}: {n:6d}")

        top = sess.execute(
            select(
                BackfillTarget.corp_code, BackfillTarget.period,
                BackfillTarget.input_chars, BackfillTarget.cost_estimate_usd,
            )
            .where(BackfillTarget.status == "done")
            .order_by(desc(BackfillTarget.cost_estimate_usd))
            .limit(10)
        ).all()
        typer.echo("\n=== Top 10 by cost ===")
        for cc, p, ic, cost in top:
            typer.echo(
                f"  {cc} {p}: input_chars={ic} cost=${float(cost or 0):.4f}"
            )

        # 7일 lifecycle 요약
        cutoff = datetime.utcnow() - timedelta(days=7)
        new_n = sess.scalar(
            select(func.count())
            .select_from(Stock)
            .where(Stock.created_at >= cutoff)
        ) or 0
        delisted_n = sess.scalar(
            select(func.count())
            .select_from(Stock)
            .where(Stock.delisted_at.isnot(None))
            .where(Stock.delisted_at >= cutoff.date())
        ) or 0
        typer.echo("\n=== Lifecycle (7일) ===")
        typer.echo(f"  신규 상장 (7일): {new_n}")
        typer.echo(f"  상장폐지 (7일): {delisted_n}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_dart_backfill.py::test_backfill_status_lifecycle_summary -v`
Expected: PASS.

- [ ] **Step 5: 회귀 확인**

Run: `uv run pytest -v`
Expected: 모든 테스트 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/themek/cli.py tests/test_cli_dart_backfill.py migrations/versions/0004_stock_lifecycle.py src/themek/db/models.py
git commit -m "feat(cli): add 7-day lifecycle summary to 'dart backfill status -v'"
```

---

## Task 14: 통합 smoke + cron 스크립트 + 문서

**Files:**
- Modify: `scripts/themek_backfill.sh`
- Modify: `docs/dart-backfill-runbook.md`
- Modify: `README.md`
- Test: `tests/test_integration_krx_backfill.py` (NEW)

이 Task는 다음 5가지를 한 번에 다룬다:
- (a) 통합 smoke — pykrx 전체 흐름을 mock으로 end-to-end 검증
- (b) cron 스크립트 새 5단계 흐름
- (c) runbook §11 신규 절차
- (d) README 후속 plan 섹션 갱신
- (e) shell smoke (`bash -n` syntax check)

### Step 1: 통합 smoke test 작성

- [ ] **(1a) Write the failing test**

Create `tests/test_integration_krx_backfill.py`:

```python
"""통합 smoke: pykrx mock → Stock sync → BackfillTarget enroll → backfill init from-stocks."""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from themek.cli import app
from themek.db.models import BackfillTarget, Stock, Corporation


@pytest.fixture
def fake_krx_50(mocker):
    """KRX mock — KOSPI 30 + KOSDAQ 20 = 50개 ticker."""
    kospi = [f"{100000 + i:06d}" for i in range(30)]
    kosdaq = [f"{200000 + i:06d}" for i in range(20)]

    class _Fake:
        def list_tickers(self, *, market, date=None):
            return {"KOSPI": kospi, "KOSDAQ": kosdaq}.get(market, [])

    mocker.patch("themek.cli.KrxClient", return_value=_Fake())
    return kospi, kosdaq


@pytest.fixture
def fake_corp_master_50(test_session, tmp_path, mocker):
    """50개 ticker가 모두 corp_master에 있는 상태."""
    from themek.dart.cache import DartCache
    cache = DartCache(base_dir=tmp_path)
    rows = []
    for i in range(30):
        rows.append({
            "corp_code": f"{1000000 + i:08d}",
            "corp_name": f"KOSPI종목_{i}",
            "stock_code": f"{100000 + i:06d}",
            "modify_date": "20240312",
        })
    for i in range(20):
        rows.append({
            "corp_code": f"{2000000 + i:08d}",
            "corp_name": f"KOSDAQ종목_{i}",
            "stock_code": f"{200000 + i:06d}",
            "modify_date": "20240312",
        })
    cache.save_corp_master(rows)
    mocker.patch(
        "themek.cli._dart_client_and_cache",
        return_value=(None, cache),
    )
    return cache


def test_full_flow_sync_then_enroll_then_init_from_stocks(
    fake_krx_50, fake_corp_master_50, test_session,
):
    """krx sync-listed --auto-enroll → backfill init --from-stocks."""
    runner = CliRunner()

    # Step 1: sync-listed --auto-enroll --periods 2023
    r1 = runner.invoke(app, [
        "krx", "sync-listed",
        "--auto-enroll", "--periods", "2023:2024",
    ])
    assert r1.exit_code == 0, r1.stdout
    assert "added=50" in r1.stdout

    stocks = test_session.scalars(select(Stock)).all()
    assert len(stocks) == 50

    targets = test_session.scalars(select(BackfillTarget)).all()
    assert len(targets) == 100  # 50 corps × 2 years
    assert all(t.status == "pending" for t in targets)

    # Step 2: backfill init --from-stocks (idempotent — 중복 skip)
    r2 = runner.invoke(app, [
        "dart", "backfill", "init",
        "--from-stocks", "--periods", "2023:2024", "--confirm",
    ])
    assert r2.exit_code == 0, r2.stdout
    assert "skipped (already exists)=100" in r2.stdout

    # Step 3: backfill init --from-stocks --periods 2025 (신규 1년)
    r3 = runner.invoke(app, [
        "dart", "backfill", "init",
        "--from-stocks", "--periods", "2025", "--confirm",
    ])
    assert r3.exit_code == 0
    targets_after = test_session.scalars(select(BackfillTarget)).all()
    assert len(targets_after) == 150  # +50 for 2025


def test_relisting_round_trip(fake_corp_master_50, test_session, mocker):
    """상장폐지 → 다음 sync에서 다시 listed → delisted_at 복원."""
    runner = CliRunner()

    # Day 1: 50개 sync
    class _Fake1:
        def list_tickers(self, *, market, date=None):
            return {
                "KOSPI": [f"{100000 + i:06d}" for i in range(30)],
                "KOSDAQ": [f"{200000 + i:06d}" for i in range(20)],
            }.get(market, [])

    mocker.patch("themek.cli.KrxClient", return_value=_Fake1())
    r1 = runner.invoke(app, ["krx", "sync-listed"])
    assert r1.exit_code == 0
    assert "added=50" in r1.stdout

    # Day 2: KOSPI 1개 빠짐 → delisted
    class _Fake2:
        def list_tickers(self, *, market, date=None):
            return {
                "KOSPI": [f"{100000 + i:06d}" for i in range(29)],
                "KOSDAQ": [f"{200000 + i:06d}" for i in range(20)],
            }.get(market, [])

    mocker.patch("themek.cli.KrxClient", return_value=_Fake2())
    r2 = runner.invoke(app, ["krx", "sync-listed"])
    assert r2.exit_code == 0
    assert "delisted=1" in r2.stdout

    # Day 3: 다시 50개 → 복원
    mocker.patch("themek.cli.KrxClient", return_value=_Fake1())
    r3 = runner.invoke(app, ["krx", "sync-listed"])
    assert r3.exit_code == 0
    # updated=50 (모두 last_seen_at 갱신, 1개는 delisted_at 복원)
    assert "updated=50" in r3.stdout
    delisted_now = test_session.scalars(
        select(Stock).where(Stock.delisted_at.isnot(None))
    ).all()
    assert len(delisted_now) == 0
```

- [ ] **(1b) Run test to verify it fails**

Run: `uv run pytest tests/test_integration_krx_backfill.py -v`
Expected: 2 PASS (if all prior tasks done; otherwise FAIL at the failing component).

- [ ] **(1c) (이미 모든 component가 구현되어 있다면 바로 PASS — 통합 회귀 검증)**

### Step 2: cron 스크립트 갱신

- [ ] **(2a) `scripts/themek_backfill.sh` 갱신**

Replace `scripts/themek_backfill.sh` entire content with:

```bash
#!/bin/bash
# Plan #5 + #5.2 — daily cron wrapper
# 매일 KST 5시 권장 (DART 한도가 KST 0시에 reset된 후 안정화 시간).

set -euo pipefail

# repo dir — cron 등록 시 절대 경로로 수정
THEMEK_DIR="${THEMEK_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$THEMEK_DIR"

if [ -f .env ]; then
    # shellcheck disable=SC1091
    source .env
fi

DATE=$(date +%Y%m%d)
mkdir -p data/log

# 0. KRX 상장사 sync (Plan #5.2)
#    신규 상장은 자동 BackfillTarget enroll (2023:current 3년치 백필)
CURRENT_YEAR=$(date +%Y)
uv run themek krx sync-listed \
    --auto-enroll --periods "2023:${CURRENT_YEAR}" \
    >> "data/log/krx_sync_${DATE}.log" 2>&1

# 1. DART corp_master refresh (90일 이내면 skip)
uv run themek dart sync-corp --if-stale-days 90 \
    >> "data/log/corp_sync_${DATE}.log" 2>&1

# 2. daily incremental (가벼움 — 시즌 외에는 ingested ≈ 0)
uv run themek dart incremental \
    --universe-source stocks \
    --since yesterday --until today \
    --purge-zip-after-extract \
    >> "data/log/incremental_${DATE}.log" 2>&1

# 3. backfill 남은 작업 진행 (한도까지)
uv run themek dart backfill run \
    --purge-zip-after-extract \
    >> "data/log/backfill_${DATE}.log" 2>&1 \
    || echo "backfill ended (budget or done)"

# 4. status 요약 (lifecycle 포함)
uv run themek dart backfill status --verbose \
    >> "data/log/status_${DATE}.log" 2>&1
```

- [ ] **(2b) bash syntax check**

Run: `bash -n scripts/themek_backfill.sh`
Expected: exit 0, no output.

### Step 3: runbook §11 추가

- [ ] **(3a) `docs/dart-backfill-runbook.md` 끝에 §11 추가**

Append to `docs/dart-backfill-runbook.md`:

```markdown
## 11. KRX 자동 universe sync (Plan #5.2)

`active.txt` 수동 관리 대신 KRX KOSPI/KOSDAQ 전체 상장사를 자동 sync하는 모드.

### 일회성 초기 setup (자동 모드 전환)

```bash
# 1. corp_master refresh (분기 1회 또는 stale 90일+)
uv run themek dart sync-corp --if-stale-days 90

# 2. KRX 전체 sync (pykrx → Stock 테이블 ~2,500종목)
uv run themek krx sync-listed --dry-run                 # listed count 확인
uv run themek krx sync-listed                            # 실 sync

# 3. Stock 테이블 → BackfillTarget enroll (3년치)
uv run themek dart backfill init --from-stocks \
    --periods 2023:2025                                  # dry-run
uv run themek dart backfill init --from-stocks \
    --periods 2023:2025 --confirm                        # 약 7,500 row 생성

# 4. 첫 backfill (RateBudget 38K/day로 ~2-3일 분산)
uv run themek dart backfill run --purge-zip-after-extract
```

### cron 흐름 (자동 모드)

`scripts/themek_backfill.sh` 갱신본은 5단계:
1. `themek krx sync-listed --auto-enroll --periods 2023:CURRENT` — 신규 상장 자동 enroll
2. `themek dart sync-corp --if-stale-days 90` — 분기 1회 corp_master refresh
3. `themek dart incremental --universe-source stocks` — Stock 테이블 기반 universe
4. `themek dart backfill run --purge-zip-after-extract` — pending 처리
5. `themek dart backfill status --verbose` — lifecycle + 비용 요약

### `--universe-source file` vs `stocks` 선택 가이드

| 상황 | 권장 |
|------|------|
| KOSPI/KOSDAQ 전체 자동 운영 | `stocks` |
| 특정 종목군만 처리 (테마/MVP) | `file` (`active.txt`) |
| 임시 우선순위 백필 | `file` + 별도 universe 파일 |

### 신규 상장 / 상장폐지 모니터링

`themek dart backfill status --verbose` 출력에 다음 섹션이 포함된다:

```
=== Lifecycle (7일) ===
  신규 상장 (7일): 3
  상장폐지 (7일): 1
```

신규 상장 종목은 `--auto-enroll` 사용 시 자동 BackfillTarget enroll. 상장폐지 종목은 `delisted_at` set되며 다음 `--universe-source stocks` 호출부터 자동 제외.

### unlinked 종목 (pykrx ↔ corp_master 미매칭)

신규 상장 직후는 DART corp_master 등록 lag 며칠. `themek krx sync-listed` 결과 `unlinked=N`은 다음 sync에서 자동 retry되므로 무시 가능. 1주 이상 unlinked가 지속되면 `data/dart/corp_master.json`을 수동 refresh.
```

### Step 4: README 갱신

- [ ] **(4a) `README.md` 후속 plan 섹션 갱신**

Modify `README.md` — "후속 Plan들 (예정)" 섹션 안의 첫 줄 ("🚧 **다음**: ..." 부분)을 다음으로 교체:

```markdown
- 🚧 **다음**: 실 `claude` CLI 기반 E5 추출 baseline 측정 (3종목 × 3 runs, `--save-runs` 사용) + Plan #5.2 KRX 자동 universe (KOSPI/KOSDAQ 전체 sync + cron 자동화).
```

같은 섹션 끝에 "완료 plans" 항목 추가:

```markdown
- ~~**Plan #5.2**: KRX 자동 universe (pykrx KOSPI/KOSDAQ sync + Stock 테이블 SSOT + 신규 상장 자동 BackfillTarget enroll)~~ ✅ 완료 (`docs/superpowers/plans/2026-05-27-krx-stock-sync-and-auto-universe.md`)
```

또한 "디렉토리 구조" 섹션 안에 `krx/` 모듈 추가:

```
src/themek/
├── krx/                       # [Plan #5.2] KRX 상장사 sync
│   ├── client.py             # pykrx wrapper
│   └── sync.py               # Stock 테이블 upsert + delisting 감지
├── dart/
│   ...
```

### Step 5: 전체 회귀

- [ ] **(5a) 전체 테스트 실행**

Run: `uv run pytest -v`
Expected: 기존 198 + 신규 약 20 = ~218 tests PASS.

- [ ] **(5b) CLI dry-run 5단계 검증**

Run sequentially:

```bash
# 1. krx sync-listed dry-run
uv run themek krx sync-listed --dry-run
```
Expected: `[dry-run] KOSPI/KOSDAQ N listed tickers` 형식 1줄 출력, exit 0.

```bash
# 2. sync-corp 90일 stale 체크 (이미 sync된 상태에서 skip 예상)
uv run themek dart sync-corp --if-stale-days 90
```
Expected: `corp_master ... days old < 90 — skipped` 또는 실 sync 진행, exit 0.

```bash
# 3. backfill init --from-stocks dry-run
uv run themek dart backfill init --from-stocks --periods 2024:2025
```
Expected: `=== Backfill Init Dry-Run ===` 출력 + Stock 테이블 종목 수 기반 예상치, exit 0.

```bash
# 4. backfill status --verbose
uv run themek dart backfill status --verbose
```
Expected: lifecycle 7일 요약 포함된 status 출력, exit 0.

```bash
# 5. cron 스크립트 syntax check
bash -n scripts/themek_backfill.sh
```
Expected: exit 0, no output.

### Step 6: Commit

- [ ] **(6a) 모든 변경 commit**

```bash
git add tests/test_integration_krx_backfill.py \
        scripts/themek_backfill.sh \
        docs/dart-backfill-runbook.md \
        README.md
git commit -m "feat(plan-5.2): integrate KRX sync into cron + runbook + smoke"
```

---

## Success Gate (deterministic)

Plan #5.2 SUCCESS = 다음 10개 항목 모두 PASS. 모두 mock 기반 + 명시 assertion. 항목 #10 외에는 네트워크/외부 시각에 비의존이다.

| # | 검증 명령 | Expected (정확치) |
|---|----------|-----------------|
| **1** | `uv run pytest tests/test_integration_krx_backfill.py::test_full_flow_sync_then_enroll_then_init_from_stocks -v` | exit 0, 1 PASS |
| **2** | `uv run pytest tests/test_integration_krx_backfill.py::test_relisting_round_trip -v` | exit 0, 1 PASS |
| **3** | `uv run pytest -v` 전체 | exit 0, **218 ± 2 PASS, 0 FAIL, 0 ERROR** |
| **4** | `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` | 3 명령 모두 exit 0 (migration round-trip 검증) |
| **5** | 통합 smoke fake 50종목 시나리오: `SyncResult.added == 50` AND `len(스냅샷의 Stock) == 50` | exact equality (Task 14 Step 1c smoke 안에서 assert) |
| **6** | `--auto-enroll --periods 2023:2024` 후 `SELECT COUNT(*) FROM backfill_targets WHERE status='pending'` | `== 100` (정확히 50 corps × 2 years) |
| **7** | 동일 `krx sync-listed --auto-enroll --periods 2023:2024` 2회 실행 시 2회차 stdout | `"auto-enrolled 0 new BackfillTarget rows"` 문자열 정확 일치 (idempotency) |
| **8** | Day 2 mock (1개 제거)에서 `SyncResult.delisted == ["100000"]` (정확한 ticker list) AND `Stock(ticker="100000").delisted_at == date(2026, 5, 27)` (test 주입 today 값) | exact equality |
| **9** | `bash -n scripts/themek_backfill.sh` | exit 0, 빈 stdout (cron 스크립트 문법 검증, 실행 X) |
| **10** | `uv run themek krx sync-listed --dry-run` (실 KRX 호출 1회) | exit 0 AND stdout이 정규식 `/KOSPI=\d+, KOSDAQ=\d+/` 매치 (값 무관 — pykrx가 0건 반환해도 PASS) |

**왜 deterministic한가:**
- #1–#8: 모두 fake/mock 기반. 외부 네트워크/시각 비의존. CI에서 반복 가능.
- #9: 정적 syntax check, 실행 없음.
- #10: 유일한 외부 호출. 값 검증 없이 **출력 형식만** 매칭 — pykrx 빈 응답도 PASS.

**Task 14 의 smoke와의 관계:** 본 Success Gate의 #5–#8은 Task 14 Step 1a에 작성된 `tests/test_integration_krx_backfill.py`의 두 함수 안에서 모두 assert된다. 즉 Gate #1·#2 PASS = Gate #5·#6·#7·#8 PASS가 자동 만족.

**KRX 실 universe 규모 검증 (manual, success gate 외):** "실제 KOSPI+KOSDAQ ~2,500종목이 sync된다"의 실측 검증은 본 plan의 acceptance gate가 아니라 [`docs/dart-backfill-runbook.md`](../../dart-backfill-runbook.md) §11의 manual setup 절차에서 운영자가 1회 확인한다. 영업일/시즌에 따라 변동하는 값을 자동 gate에 넣지 않는다.

---

## Task별 시간 추정 (참고)

| Task | 예상 시간 |
|------|-----------|
| 1. pykrx 의존성 | 5분 |
| 2. KrxClient | 15분 |
| 3. fetch_listed_universe | 10분 |
| 4. migration + 모델 | 25분 (created_at 추가 보강 포함) |
| 5. build_ticker_index | 10분 |
| 6. sync_listed_stocks | 35분 |
| 7. load_universe_from_stocks | 10분 |
| 8. enumerate_targets_from_corps | 10분 |
| 9. CLI krx sync-listed | 30분 |
| 10. backfill init --from-stocks | 20분 |
| 11. incremental --universe-source | 20분 |
| 12. sync-corp --if-stale-days | 15분 |
| 13. status lifecycle | 20분 |
| 14. 통합 smoke + cron + docs | 45분 |
| **합계** | **약 4시간** |

(실측은 TDD 익숙도 + 네트워크 안정성에 따라 ±50% 변동)

---

## 후속 작업 (본 plan out of scope)

- **Phase 2 전환**: `active.txt` deprecated 표시 + cron 기본을 `--universe-source stocks`로 (1주 운영 검증 후 별도 PR)
- **우선주 자동 분리**: `share_class = "preferred"` if `ticker.endswith(('5', '7'))` (KRX 명명 규약)
- **시즌 외 스킵**: pykrx 호출은 영업일에만 (주말/공휴일 cron skip)
- **KONEX 추가**: 필요 시 `fetch_listed_universe`에 KONEX 추가 (1줄 변경)
- **ISIN 매핑**: KRX OpenAPI나 별도 소스에서 ISIN sync
- **신규 상장 retroactive backfill 기간 조정**: 현재 default `2023:CURRENT` — 5년 history가 필요하면 `--periods 2020:CURRENT`로 cron 변경
