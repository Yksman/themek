# DART Multi-Corp Backfill Implementation Plan (Plan #5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 본 plan은 design + execution을 단일 문서에 통합한 형태 — 별도 spec 파일이 없다.

**Goal:** Plan #1/#3/#4가 만든 `dart ingest --ticker X --period Y` backbone을 운영 자동화 layer로 확장한다. (1) 명시적 universe 파일 × period range를 **다일 분산 batch**로 1회 backfill, (2) 매일 cron으로 **신규 사업보고서만** 증분 ingest. 둘 다 일일 40,000 DART API 호출 한도 안에서 안전하게 동작한다.

**Final Success Metric:** 본 plan 전체의 성공 판정은 **마지막 Task 13: 프로덕션 10건 적재 검증**에서 결정한다. 합의된 10 종목 × 2024:2025 (사업보고서 회계연도, 최신 2개년)을 실제로 적재하고 schema/share_pct/cross-table consistency가 의도대로 채워졌는지 8개 acceptance check를 통과해야 SUCCESS.

**Architecture:** 신규 `src/themek/dart/{backfill,incremental,rate_budget,universe}.py` 4 파일 + `BackfillTarget` 신규 테이블 + alembic migration + CLI 4 명령. 기존 ingest / fetch / parser / extractor 로직은 **재사용만 하고 변경 없음**.

**Tech Stack:** Python 3.12+, pytest, pytest-mock, SQLAlchemy 2 + alembic, typer, 기존 DART client (httpx) + claude CLI wrapper.

---

## 핵심 설계 결정 (선행 합의)

### 1. 보고서 누적 정책 — append-only

| 시점 | 동작 |
|------|------|
| **DB 저장** | 모든 사업보고서를 누적. 같은 corp 2년치 = 2 BusinessReport row × 2 sets of segments/revenue/customer/geographic. 각 row는 `source_report_id`로 어느 보고서 출처인지 trace. |
| **Idempotency 단위** | `BusinessReport.dart_rcept_no` PK. 같은 rcept_no 재실행은 no-op (Plan #1 R4). |
| **정정보고서** | 새 rcept_no이므로 **새 row로 누적**. 동일 (corp, period)에 다수 row 존재 허용. |
| **Query 노출** | `query_e5`는 `filing_date DESC LIMIT 1`로 최신 1건만 표시 — Plan #5에서 변경 없음. 시계열 query는 후속. |

이 정책은 `docs/superpowers/specs/2026-05-22-korean-theme-stock-ontology-design.md` 의 "Reification lifecycle 룰 (append-only bi-temporal)"과 일치한다.

### 2. Universe 단일 source of truth — `data/universe/active.txt` (C1)

- 운영자가 관리하는 단일 텍스트 파일이 *어떤 종목을 운영 대상으로 할지* 의 유일한 정의.
- format: `corp_code` 1줄당 1개. `#` 시작은 주석. 빈 줄 허용.
- `dart backfill init` 이 이 파일 + `--periods` 인자로 `BackfillTarget` row 생성.
- `dart incremental` 이 이 파일을 매 실행마다 읽어 scan 결과 filter.
- **두 layer가 같은 파일을 본다** → backfill 대상 = incremental scan 대상. 의도 명확.
- `BackfillTarget` 테이블은 *진행 추적 전용* 으로 의미 명확화 (universe 정의 역할 제거).

### 3. BackfillTarget에 비용·품질 컬럼 (C4)

`escalation_level` / `input_chars` / `cost_estimate_usd` 컬럼을 추가해 ingest 결과를 영속화. `dart backfill status --verbose` 가 escalation 분포 + 종목별 top-cost를 표시 → 비용 모니터링과 Plan #4 학습 반영도를 일상적으로 추적.

### 4. Retry 정책 차등화 (C5)

| 에러 종류 | 정책 | 이유 |
|----------|------|------|
| `BusinessReportFetchError` (사업보고서 미존재) | 즉시 `skipped` | 재시도 무의미 (DART에 없음) |
| `BusinessReportFetchError` (zip 손상 등 그 외) | retry 3회 | 일시적 가능 |
| `httpx.TimeoutException`, `httpx.HTTPError` | retry 3회 | network |
| `ExtractionError`, schema validation 실패 | **즉시 `failed`** | LLM/extractor가 deterministic — 재시도해도 같은 결과, LLM 비용만 낭비 |
| `RateBudgetExceeded` | 예외 re-raise | batch loop이 종료 결정 |

### 5. 디스크 효율 (C7)

- `data/dart/raw/<rcept_no>/document.zip` (수MB)는 business.html 추출 후 *선택적으로* 삭제 가능.
- CLI flag `--purge-zip-after-extract` (default: false — 디버깅 위해 보존).
- 운영 cron에서는 on, 1년 운영 시 디스크 ~90% 절약.

### 6. DART API 호출 전략

- 일일 한도: 40,000. 안전 마진 10% → 운영 cap **38,000/day**.
- **Layer A (initial backfill)**: 종목별 `list.json` 1회 + `document.xml` per period
- **Layer B (daily incremental)**: 시간 범위 `list.json` 페이지네이션 (corp_code 없이) → 전체 신규 공시 한 번에 → universe filter → 신규 rcept_no만 `document.xml`
- 사업보고서 정기 공시 시즌(3~5월) 외에는 incremental 호출 거의 0. 매일 cron이 가벼움.

### 7. 비용 모델 (참고)

- 종목당 LLM 1회 ingest ≈ $0.10~$0.33 (pre-backfill validation Step 2 측정)
- 10 종목 × 2년 ≈ $6.60 (Task 13 smoke)
- KOSPI200 × 2년 ≈ $132
- 전 상장 (~2,800) × 2년 ≈ $1,850 (universe 결정 시 dry-run으로 사전 출력)

---

## Prerequisites

- ✅ Plan #1 (Walking Skeleton)
- ✅ Plan #3 (DART API client) — `dart sync-corp`, `dart ingest` 동작
- ✅ Plan #4 (Parser Robust Extraction) — 3-tier escalation
- ✅ Plan #6 (Eval Harness)
- ✅ Pre-Backfill Validation Step 1·2 통과 (consensus 1.00, share_pct stdev 0.00)
- `.env`에 `DART_API_KEY` 설정 + `claude` CLI 로그인
- `data/dart/corp_master.json` 준비 (`themek dart sync-corp` 1회 실행)

---

## Scope (in / out)

**In:**
- `src/themek/dart/backfill.py` — Layer A 오케스트레이터 + status machine + 에러 분기
- `src/themek/dart/incremental.py` — Layer B 시간범위 스캐너
- `src/themek/dart/rate_budget.py` — 일일 호출 budget tracker
- `src/themek/dart/universe.py` — active.txt 로더 (단일 source of truth)
- `src/themek/db/models.py` 수정 — `BackfillTarget` 추가 (escalation_level / input_chars / cost_estimate_usd 컬럼 포함)
- alembic migration 1건
- `src/themek/dart/client.py` 수정 — `list_periodic_reports`에 `corp_code: Optional` + `page_no` 지원
- `src/themek/cli.py` 수정 — `dart backfill {init,run,status}` + `dart incremental` 4 명령
- 단위 테스트 ~28개 + 통합 smoke 1건 (Task 13)
- `docs/dart-backfill-runbook.md` 운영 매뉴얼
- README "후속 Plan들" 갱신

**Out (Plan #5.1 또는 후속 이연):**
- 반기·분기 보고서 (`pblntf_ty=A`의 사업보고서만)
- 공시(Disclosure) ingestion — Plan #2/#7
- 정정보고서 query 단계 최신 선택 검증 (현재 query/e5는 단순 filing_date desc)
- LLM 비용 자동 cap
- 다년도 병렬 fetch · 멀티 process 동시 실행
- 신규 상장사 실시간 감지 (corp_master 분기 수동 refresh 가정)
- failed status 자동 재시도
- universe 외 종목의 incremental 흡수 (자동 universe 확장)

---

## File Structure

```
themek/
├── src/themek/
│   ├── dart/
│   │   ├── backfill.py            # NEW
│   │   ├── incremental.py         # NEW
│   │   ├── rate_budget.py         # NEW
│   │   ├── universe.py            # NEW (active.txt 로더)
│   │   ├── client.py              # 수정: corp_code optional + page_no
│   │   └── (cache/corp_lookup/fetch/parser.py 변경 없음)
│   ├── db/models.py               # 수정: BackfillTarget 추가
│   └── cli.py                     # 수정: dart backfill + incremental
├── migrations/versions/
│   └── XXXX_add_backfill_target.py
├── tests/
│   ├── test_rate_budget.py
│   ├── test_universe.py
│   ├── test_backfill.py
│   ├── test_incremental.py
│   ├── test_cli_dart_backfill.py
│   └── fixtures/
│       └── dart_cassettes/
│           ├── list_json_corp_code_optional_2024.yaml  # T0
│           └── (기존 cassettes 재사용)
├── scripts/
│   ├── themek_backfill.sh         # gitignore
│   └── verify_backfill_smoke.py   # gitignore (T13)
├── docs/
│   ├── dart-backfill-recon-notes.md       # T0
│   ├── dart-backfill-runbook.md           # T12
│   └── dart-backfill-production-smoke-2026-XX-XX.md  # T13
├── data/
│   ├── universe/
│   │   └── active.txt             # gitignore (운영자 관리)
│   └── dart/
│       ├── budget_state.json     # gitignore (RateBudget persist)
│       └── (raw/, corp_master.json 기존)
└── README.md                      # 수정
```

---

# Phase 1 — Foundation (T0~T2)

학습된 가정을 검증하고, 운영 layer가 의존할 budget tracker + state table + universe loader를 만든다.

---

## Task 0: DART API 정찰 — 운영 가정 검증

**Goal:** Plan #5가 깔린 3개 핵심 가정이 실제로 성립하는지 1회 실 호출로 검증. 실패 시 plan 수정 commit.

**Files:**
- Create: `docs/dart-backfill-recon-notes.md`
- Create: `tests/fixtures/dart_cassettes/list_json_corp_code_optional_2024.yaml` (또는 응답 fixture)

**가정 3개:**

1. `list.json`을 `corp_code` 없이 호출 가능 — DART OpenAPI가 전체 정기공시 list를 페이지네이션으로 반환
2. 호출 한도 reset 시점은 KST 0시
3. `total_page` 필드가 응답에 포함되어 페이지네이션 종료 조건으로 사용 가능

- [ ] **Step 1: 정찰 스크립트 작성 + 실 호출 (1회)**

```bash
# scripts/recon_backfill.py (gitignore)
import os, httpx, json
key = os.environ["DART_API_KEY"]

# 가정 1·3: corp_code 없이 list.json 페이지네이션 — 최근 정기 시즌
r = httpx.get("https://opendart.fss.or.kr/api/list.json", params={
    "crtfc_key": key,
    "bgn_de": "20260301", "end_de": "20260331",  # 2026년 3월 정기 시즌
    "pblntf_ty": "A", "page_count": 100, "page_no": 1,
}, timeout=60)
payload = r.json()
print(f"status_code={payload.get('status')} total_count={payload.get('total_count')} "
      f"total_page={payload.get('total_page')} list_len={len(payload.get('list', []))}")
biz = [d for d in payload["list"] if d["report_nm"].startswith("사업보고서")]
print(f"사업보고서 비율: {len(biz)}/{len(payload['list'])}")
```

- [ ] **Step 2: 응답 fixture 저장**

응답을 `tests/fixtures/dart_cassettes/list_json_corp_code_optional_2024.yaml`로 저장 (cassette 또는 단순 JSON dump).

- [ ] **Step 3: `docs/dart-backfill-recon-notes.md` 작성**

```markdown
# DART Backfill Recon — 2026-05-XX

## 가정 1: corp_code 없이 list.json 호출
- 결과: OK / FAIL
- 응답: status="000", total_count=X, total_page=Y, list[0]=...

## 가정 2: 호출 한도 reset 시점
- 측정 방법: ...
- 결과: KST 0시 / 다른 시각 (X시)

## 가정 3: total_page 필드 존재
- 결과: OK / 없음 (대안: total_count / page_count 계산)

## 사업보고서 비율 (참고)
- 2026-03 한 달 전체 정기공시 중 사업보고서: X% (페이지네이션 비용 산정)

## 후속
- 가정 1 FAIL → Layer B 알고리즘 재설계 (종목별 호출 fallback)
- 가정 3 FAIL → 페이지네이션 종료 조건 변경
```

- [ ] **Step 4: scripts/recon_backfill.py를 .gitignore에 추가 (또는 삭제) + 커밋**

```bash
git add tests/fixtures/dart_cassettes/list_json_corp_code_optional_2024.yaml \
        docs/dart-backfill-recon-notes.md
git commit -m "docs(backfill): T0 API 정찰 + corp_code optional list.json 가정 검증 (Plan #5 T0)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 가정 1 (corp_code 없이 list.json 동작) | recon 응답 status | `"000"` + `len(list) ≥ 1` |
| 가정 2 (한도 reset 시점) | recon notes에 KST/UTC 명시 | 결과값 명시됨 (값 자체는 PASS 무관) |
| 가정 3 (`total_page` 필드) | `payload.get("total_page")` | not None |
| Cassette 저장 | 파일 존재 | `tests/fixtures/dart_cassettes/list_json_corp_code_optional_2024.yaml` |
| Recon notes 작성 | 파일 존재 + 가정 1/2/3 결과 명시 | 셋 다 OK/FAIL 명확 |

**Critical Gate**: 가정 1 FAIL → 본 plan 중단, Layer B 알고리즘 재설계. 가정 3 FAIL → T6 페이지네이션 종료 조건 spec 정정 commit 후 진행.

---

## Task 1: `RateBudget` — 일일 호출 한도 tracker

**Files:**
- Create: `src/themek/dart/rate_budget.py`
- Create: `tests/test_rate_budget.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
"""RateBudget: 일일 DART 호출 한도 추적 + 디스크 영속화."""
from datetime import date
from pathlib import Path
import pytest
from themek.dart.rate_budget import RateBudget, RateBudgetExceeded


def test_budget_starts_at_zero(tmp_path):
    b = RateBudget(daily_cap=10, state_file=tmp_path / "budget.json")
    assert b.remaining() == 10


def test_budget_consume_decrements(tmp_path):
    b = RateBudget(daily_cap=10, state_file=tmp_path / "budget.json")
    b.consume(3)
    assert b.remaining() == 7


def test_budget_exceeded_raises(tmp_path):
    b = RateBudget(daily_cap=5, state_file=tmp_path / "budget.json")
    b.consume(5)
    with pytest.raises(RateBudgetExceeded):
        b.consume(1)


def test_budget_persists_to_disk(tmp_path):
    """같은 state_file로 재초기화 시 used 누적이 유지된다."""
    state = tmp_path / "budget.json"
    RateBudget(daily_cap=10, state_file=state).consume(3)
    b2 = RateBudget(daily_cap=10, state_file=state)
    assert b2.remaining() == 7


def test_budget_resets_on_new_day(tmp_path):
    """state_file의 date가 오늘과 다르면 used=0으로 reset."""
    state = tmp_path / "budget.json"
    state.write_text('{"date": "2020-01-01", "used": 38000}', encoding="utf-8")
    b = RateBudget(daily_cap=38000, state_file=state, today=date(2026, 5, 27))
    assert b.remaining() == 38000
```

- [ ] **Step 2: 실패 확인 → 구현 (rate_budget.py)**

```python
"""DART API 일일 호출 한도 tracker.

state 파일 schema (JSON):
  {"date": "YYYY-MM-DD", "used": int}
"""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo


class RateBudgetExceeded(RuntimeError):
    """일일 호출 한도 초과."""


def _today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


class RateBudget:
    def __init__(
        self, *, daily_cap: int, state_file: Path,
        today: Optional[date] = None,
    ):
        self.daily_cap = daily_cap
        self.state_file = Path(state_file)
        self._today = today or _today_kst()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._load_and_maybe_reset()

    def _load_and_maybe_reset(self) -> None:
        if not self.state_file.exists():
            self._used = 0
            self._persist()
            return
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        if data.get("date") != self._today.isoformat():
            self._used = 0
            self._persist()
        else:
            self._used = int(data.get("used", 0))

    def _persist(self) -> None:
        self.state_file.write_text(json.dumps({
            "date": self._today.isoformat(),
            "used": self._used,
        }), encoding="utf-8")

    def remaining(self) -> int:
        return max(0, self.daily_cap - self._used)

    def consume(self, n: int = 1) -> None:
        if self._used + n > self.daily_cap:
            raise RateBudgetExceeded(
                f"daily_cap={self.daily_cap} used={self._used} requested={n}"
            )
        self._used += n
        self._persist()
```

- [ ] **Step 3: 통과 + 커밋**

```bash
uv run pytest tests/test_rate_budget.py -v
git add src/themek/dart/rate_budget.py tests/test_rate_budget.py
git commit -m "feat(dart): RateBudget daily API budget tracker (Plan #5 T1)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `uv run pytest tests/test_rate_budget.py -v` | 5 tests passed, 0 failed |
| Import 정상 | `uv run python -c "from themek.dart.rate_budget import RateBudget, RateBudgetExceeded"` | exit 0 |
| 회귀 없음 | `uv run pytest` 전체 | 기존 + 5 신규 모두 PASS |

**Gate**: 3 항목 모두 PASS → T2. 하나라도 FAIL → 원인 분석 후 fix.

---

## Task 2: `BackfillTarget` model + alembic migration (C4)

> 비용·품질 모니터링용 컬럼 3개 (escalation_level / input_chars / cost_estimate_usd) 포함.

**Files:**
- Modify: `src/themek/db/models.py`
- Create: `migrations/versions/XXXX_add_backfill_target.py`
- Create: `tests/test_backfill_model.py`

- [ ] **Step 1: 실패 테스트**

```python
"""BackfillTarget model + status 전이 + 비용 컬럼."""
import pytest
from datetime import datetime
from sqlalchemy import select
from themek.db.engine import Base, make_engine, make_session_factory
from themek.db.models import BackfillTarget


def test_backfill_target_creates(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "sqlite:///:memory:")
    engine = make_engine()
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        t = BackfillTarget(corp_code="00126380", period="2025", status="pending")
        s.add(t); s.commit()
        row = s.scalar(select(BackfillTarget).where(BackfillTarget.corp_code == "00126380"))
        assert row.status == "pending"
        assert row.attempts == 0
        assert row.escalation_level is None
        assert row.input_chars is None
        assert row.cost_estimate_usd is None


def test_backfill_target_unique_corp_period(monkeypatch):
    monkeypatch.setenv("POSTGRES_DSN", "sqlite:///:memory:")
    engine = make_engine()
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        s.add(BackfillTarget(corp_code="00126380", period="2025", status="pending"))
        s.commit()
        s.add(BackfillTarget(corp_code="00126380", period="2025", status="pending"))
        with pytest.raises(Exception):
            s.commit()


def test_backfill_target_cost_columns_updatable(monkeypatch):
    """ingest 완료 후 컬럼 채워질 수 있다."""
    monkeypatch.setenv("POSTGRES_DSN", "sqlite:///:memory:")
    engine = make_engine()
    Base.metadata.create_all(engine)
    Session = make_session_factory(engine)
    with Session() as s:
        t = BackfillTarget(corp_code="00126380", period="2025", status="done",
                           escalation_level="regex", input_chars=38000,
                           cost_estimate_usd=0.33)
        s.add(t); s.commit()
        row = s.scalar(select(BackfillTarget))
        assert row.escalation_level == "regex"
        assert row.input_chars == 38000
        assert float(row.cost_estimate_usd) == 0.33
```

- [ ] **Step 2: model 추가**

```python
# src/themek/db/models.py — 끝에 추가

class BackfillTarget(Base):
    __tablename__ = "backfill_targets"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    corp_code: Mapped[str] = mapped_column(String(8), nullable=False)
    period: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum("pending", "in_progress", "done", "failed", "skipped",
               name="backfill_target_status_enum"),
        nullable=False, default="pending",
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    rcept_no: Mapped[Optional[str]] = mapped_column(String(14))
    # C4: 비용·품질 추적 컬럼
    escalation_level: Mapped[Optional[str]] = mapped_column(String(32))
    input_chars: Mapped[Optional[int]] = mapped_column(Integer)
    cost_estimate_usd: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp(),
    )

    __table_args__ = (
        UniqueConstraint("corp_code", "period", name="ux_backfill_corp_period"),
    )
```

필요 import (`Integer`, `DateTime`, `UniqueConstraint`, `func`, `datetime`, `Numeric`) 추가.

- [ ] **Step 3: alembic migration 생성 + apply**

```bash
uv run alembic revision -m "add_backfill_target_table"
# 생성된 파일에 op.create_table(...) + UniqueConstraint + 3 nullable 비용 컬럼 작성
uv run alembic upgrade head
```

- [ ] **Step 4: 통과 + 커밋**

```bash
uv run pytest tests/test_backfill_model.py -v
git add src/themek/db/models.py migrations/versions/XXXX_add_backfill_target.py \
        tests/test_backfill_model.py
git commit -m "feat(db): BackfillTarget model with cost/quality columns (Plan #5 T2)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `uv run pytest tests/test_backfill_model.py -v` | 3 tests passed |
| Migration apply | `uv run alembic upgrade head` | exit 0 |
| Migration 가역성 | `uv run alembic downgrade -1 && uv run alembic upgrade head` | exit 0 |
| 테이블 + UNIQUE | DB inspect — `backfill_targets` 테이블 + `ux_backfill_corp_period` constraint | 둘 다 존재 |
| 비용 컬럼 nullable | `escalation_level/input_chars/cost_estimate_usd` 빈 row 삽입 가능 | INSERT 성공 |
| 회귀 없음 | `uv run pytest` | 모두 PASS |

**Gate**: 6 항목 모두 PASS → T3.

---

# Phase 2 — Universe Loader + Layer A (T3~T5)

---

## Task 3: `universe.py` — active.txt loader (C1)

> 본 plan의 핵심 단순화. `universe` source는 *오직* `data/universe/active.txt` 1개 파일. 모드 분기 제거.

**Files:**
- Create: `src/themek/dart/universe.py`
- Create: `tests/test_universe.py`

- [ ] **Step 1: 실패 테스트**

```python
"""universe.py: active.txt에서 corp_code list 로드."""
import pytest
from pathlib import Path
from themek.dart.universe import load_universe


def test_load_universe_basic(tmp_path):
    p = tmp_path / "active.txt"
    p.write_text("00126380\n00164742\n01133217\n", encoding="utf-8")
    assert load_universe(p) == ["00126380", "00164742", "01133217"]


def test_load_universe_skips_comments_and_blanks(tmp_path):
    p = tmp_path / "active.txt"
    p.write_text(
        "# Header comment\n"
        "00126380\n"
        "\n"
        "  # indented comment\n"
        "00164742  \n"   # 양쪽 공백
        "\n",
        encoding="utf-8",
    )
    assert load_universe(p) == ["00126380", "00164742"]


def test_load_universe_dedupe(tmp_path):
    p = tmp_path / "active.txt"
    p.write_text("00126380\n00164742\n00126380\n", encoding="utf-8")
    # dedup 순서 보존
    assert load_universe(p) == ["00126380", "00164742"]


def test_load_universe_validates_corp_code_format(tmp_path):
    p = tmp_path / "active.txt"
    p.write_text("12345\n", encoding="utf-8")  # 5자리 (8자리여야 함)
    with pytest.raises(ValueError, match="corp_code"):
        load_universe(p)


def test_load_universe_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_universe(tmp_path / "missing.txt")
```

- [ ] **Step 2: 구현**

```python
"""Universe 단일 source of truth — active.txt 로더.

format:
  corp_code 1줄당 1개 (8자리). #로 시작하는 주석 + 빈 줄 허용.
  중복은 자동 dedup (순서 보존).
"""
from __future__ import annotations
import re
from pathlib import Path

_CORP_CODE_RE = re.compile(r"^\d{8}$")


def load_universe(path: Path) -> list[str]:
    if not Path(path).exists():
        raise FileNotFoundError(f"universe file 없음: {path}")
    seen: set[str] = set()
    out: list[str] = []
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not _CORP_CODE_RE.match(line):
            raise ValueError(
                f"{path}:{lineno} corp_code 형식 오류 (8자리 숫자 필요): {line!r}"
            )
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out
```

- [ ] **Step 3: 통과 + 커밋**

```bash
uv run pytest tests/test_universe.py -v
git add src/themek/dart/universe.py tests/test_universe.py
git commit -m "feat(dart): universe.py active.txt single-source-of-truth loader (Plan #5 T3)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `uv run pytest tests/test_universe.py -v` | 5 tests passed |
| Edge cases | empty / comments-only / dedup / format-error 4 시나리오 모두 expected | 4/4 |
| 회귀 없음 | `uv run pytest` | 모두 PASS |

**Gate**: 3 항목 모두 PASS → T4.

---

## Task 4: `backfill.run_one_target` — 1 target ingest + 차등 retry + 비용 캡처 (C5, C4, C7)

**Files:**
- Create: `src/themek/dart/backfill.py`
- Create: `tests/test_backfill.py`

이 task가 본 plan의 최대 변경 지점:
- **C5**: 에러 분류 (`_categorize_error`) — fetch/network는 retry, LLM/schema는 즉시 failed
- **C4**: 성공 시 escalation_level / input_chars / cost_estimate_usd 캡처
- **C7**: `--purge-zip-after-extract` 파라미터로 document.zip 즉시 삭제

- [ ] **Step 1: 실패 테스트**

```python
"""backfill.run_one_target: 1 target ingest + 에러 차등 + 비용 캡처."""
from datetime import date
from themek.dart.backfill import run_one_target, RunTargetResult
from themek.db.models import BackfillTarget, BusinessReport
from themek.llm.schemas import BusinessExtraction, BusinessSegmentItem
from themek.dart.rate_budget import RateBudgetExceeded
from themek.dart.fetch import BusinessReportFetchError


def _stub_extractor():
    def stub(text, period_hint):
        return BusinessExtraction(
            period=period_hint,
            segments=[BusinessSegmentItem(name_ko="테스트부문", share_pct=100.0)],
            customers=[], geographic=[],
        )
    return stub


def test_run_one_target_happy_path_captures_cost(tmp_path, db_session):
    """fetch + ingest 성공 → status=done, 비용 컬럼 채워짐."""
    target = BackfillTarget(corp_code="00126380", period="2025", status="pending")
    db_session.add(target); db_session.commit()

    result = run_one_target(
        target=target, session=db_session,
        client=_fake_client_returning_zip(),
        cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
    )
    db_session.refresh(target)
    assert result.status == "done"
    assert target.status == "done"
    assert target.attempts == 1
    assert target.rcept_no is not None
    assert target.escalation_level == "regex"           # C4
    assert target.input_chars > 0                        # C4
    assert target.cost_estimate_usd is not None          # C4


def test_run_one_target_no_report_skipped_no_retry(tmp_path, db_session):
    """사업보고서 미존재 → status=skipped 즉시, attempts=1."""
    target = BackfillTarget(corp_code="00126380", period="1999", status="pending")
    db_session.add(target); db_session.commit()
    result = run_one_target(
        target=target, session=db_session,
        client=_fake_client_no_report(),
        cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
    )
    assert target.status == "skipped"
    assert target.attempts == 1
    assert "사업보고서 없음" in (target.last_error or "")


def test_run_one_target_fetch_error_retries(tmp_path, db_session):
    """zip 손상 등 fetch 에러 → retry 대상 (pending로 되돌림)."""
    target = BackfillTarget(corp_code="00126380", period="2025", status="pending",
                            attempts=0)
    db_session.add(target); db_session.commit()
    result = run_one_target(
        target=target, session=db_session,
        client=_fake_client_raises(BusinessReportFetchError("zip 손상")),
        cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
    )
    assert target.status == "pending"  # retry 대상
    assert target.attempts == 1


def test_run_one_target_fetch_error_exhausted_failed(tmp_path, db_session):
    """fetch 에러 3회 도달 → failed."""
    target = BackfillTarget(corp_code="00126380", period="2025", status="pending",
                            attempts=2)
    db_session.add(target); db_session.commit()
    result = run_one_target(
        target=target, session=db_session,
        client=_fake_client_raises(BusinessReportFetchError("zip 손상")),
        cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
    )
    assert target.status == "failed"
    assert target.attempts == 3


def test_run_one_target_llm_error_no_retry(tmp_path, db_session):
    """C5: LLM/schema 에러는 retry 안 함 — 즉시 failed."""
    from pydantic import ValidationError
    target = BackfillTarget(corp_code="00126380", period="2025", status="pending")
    db_session.add(target); db_session.commit()
    def bad_extractor(text, period_hint):
        raise ValueError("schema validation 실패")  # ExtractionError 대표
    result = run_one_target(
        target=target, session=db_session,
        client=_fake_client_returning_zip(),
        cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=bad_extractor,
    )
    assert target.status == "failed"
    assert target.attempts == 1   # retry 안 함 — 1회만


def test_run_one_target_budget_exceeded_reraises(tmp_path, db_session):
    """RateBudgetExceeded → in_progress 유지 + 예외 re-raise."""
    target = BackfillTarget(corp_code="00126380", period="2025", status="pending")
    db_session.add(target); db_session.commit()
    import pytest
    with pytest.raises(RateBudgetExceeded):
        run_one_target(
            target=target, session=db_session,
            client=_fake_client_returning_zip(),
            cache=_tmp_cache(tmp_path),
            rate_budget=_tmp_budget(tmp_path, daily_cap=0),
            extractor=_stub_extractor(),
        )
    assert target.status == "in_progress"


def test_run_one_target_purge_zip(tmp_path, db_session):
    """C7: purge_zip=True → business.html 추출 후 document.zip 삭제."""
    target = BackfillTarget(corp_code="00126380", period="2025", status="pending")
    db_session.add(target); db_session.commit()
    cache = _tmp_cache(tmp_path)
    result = run_one_target(
        target=target, session=db_session,
        client=_fake_client_returning_zip(),
        cache=cache,
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
        purge_zip=True,
    )
    # business.html 존재 + document.zip 삭제
    rcept_dir = cache.raw_dir / target.rcept_no
    assert (rcept_dir / "business.html").exists()
    assert not (rcept_dir / "document.zip").exists()
```

- [ ] **Step 2: 구현**

```python
"""Layer A: initial backfill 오케스트레이터."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import httpx

from sqlalchemy.orm import Session
from themek.db.models import BackfillTarget
from themek.dart.cache import DartCache
from themek.dart.rate_budget import RateBudget, RateBudgetExceeded
from themek.dart.fetch import (
    fetch_business_report_html, BusinessReportFetchError,
)
from themek.dart.parser import extract_business_content, extract_business_sections
from themek.ingest.business_report import ingest_business_report

MAX_ATTEMPTS = 3

# C4: 비용 추정 단가 (대략) — input_chars 기준 토큰 비례. validation Step 2 기준.
# claude opus 4.x: input $15/M, output $75/M. 사업보고서 1 char ≈ 0.5 token.
# 종합 단가 ~$8.7/M input char + 고정 output. 보수적으로 $0.000009 / char + $0.05 base.
COST_PER_CHAR_USD = 9e-6
COST_BASE_USD = 0.05


@dataclass
class RunTargetResult:
    status: str
    rcept_no: Optional[str] = None
    error: Optional[str] = None
    escalation_level: Optional[str] = None
    input_chars: Optional[int] = None
    cost_estimate_usd: Optional[float] = None


def _is_no_report_error(e: Exception) -> bool:
    return isinstance(e, BusinessReportFetchError) and "사업보고서 없음" in str(e)


def _is_retryable(e: Exception) -> bool:
    """C5: fetch/network 계열만 retry. LLM/schema는 즉시 failed."""
    if isinstance(e, BusinessReportFetchError) and not _is_no_report_error(e):
        return True
    if isinstance(e, (httpx.TimeoutException, httpx.HTTPError)):
        return True
    return False


def run_one_target(
    *, target: BackfillTarget, session: Session,
    client, cache: DartCache, rate_budget: RateBudget,
    extractor,
    purge_zip: bool = False,
) -> RunTargetResult:
    """1개 BackfillTarget을 ingest. 예외는 status 반영 + 정상 return.
    RateBudgetExceeded는 re-raise (batch loop이 종료 결정)."""
    target.status = "in_progress"
    target.attempts += 1
    target.last_attempt_at = datetime.utcnow()
    session.commit()

    # Phase 1: fetch (DART 호출)
    try:
        rate_budget.consume(1)  # list.json
        html_path, rcept_no = fetch_business_report_html(
            client, cache,
            ticker="",
            year=int(target.period),
            corp_code=target.corp_code,
        )
        # document.xml 호출은 cache miss 시에만 발생 — fetch_business_report_html
        # 내부에서 처리. 정확 추적은 Plan #5.1로 이연.
    except RateBudgetExceeded:
        raise
    except Exception as e:
        if _is_no_report_error(e):
            target.status = "skipped"
            target.last_error = str(e)[:500]
            session.commit()
            return RunTargetResult(status="skipped", error=str(e))
        # retryable vs 즉시 failed
        target.last_error = str(e)[:500]
        if _is_retryable(e) and target.attempts < MAX_ATTEMPTS:
            target.status = "pending"
        else:
            target.status = "failed"
        session.commit()
        return RunTargetResult(status=target.status, error=str(e))

    # Phase 2: extract sections + ingest (LLM 호출)
    try:
        html_text = html_path.read_text(encoding="utf-8")
        # C4: section_resolution에서 escalation_level / 본문 길이 캡처
        text, resolution = extract_business_sections(html_text)
        escalation = resolution.escalation_level
        input_chars = resolution.output_chars
        cost = round(COST_BASE_USD + input_chars * COST_PER_CHAR_USD, 4)

        ingest_business_report(
            session,
            dart_rcept_no=rcept_no,
            corporation_id=target.corp_code,
            report_type="사업보고서",
            period=target.period,
            filing_date=date.today(),
            raw_text_excerpt=text,
            extractor=extractor,
        )
        target.rcept_no = rcept_no
        target.status = "done"
        target.last_error = None
        target.escalation_level = escalation
        target.input_chars = input_chars
        target.cost_estimate_usd = cost
        session.commit()

        # C7: 디스크 절약 — document.zip 삭제
        if purge_zip:
            zip_path = cache.raw_dir / rcept_no / "document.zip"
            if zip_path.exists():
                zip_path.unlink()

        return RunTargetResult(
            status="done", rcept_no=rcept_no,
            escalation_level=escalation, input_chars=input_chars,
            cost_estimate_usd=cost,
        )
    except Exception as e:
        # C5: LLM/extract/schema 에러는 retry 무의미 — 즉시 failed
        session.rollback()
        target.last_error = str(e)[:500]
        target.status = "failed"
        session.commit()
        return RunTargetResult(status="failed", error=str(e))
```

- [ ] **Step 3: 통과 + 커밋**

```bash
uv run pytest tests/test_backfill.py -v -k run_one_target
git add src/themek/dart/backfill.py tests/test_backfill.py
git commit -m "feat(backfill): run_one_target with retry classification + cost capture + purge-zip (Plan #5 T4)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `pytest tests/test_backfill.py -v -k run_one_target` | 7 tests passed (happy / no-report-skipped / fetch-retry / fetch-exhausted-failed / llm-no-retry / budget-reraise / purge-zip) |
| 비용 컬럼 캡처 (happy) | target.cost_estimate_usd | `> 0` 양수 실수 |
| 비용 컬럼 캡처 (escalation_level) | target.escalation_level | `regex` / `regex+llm` / `full_text` 중 하나 |
| Purge-zip 동작 | purge_zip=True 후 cache 디렉토리 | `business.html` 존재 + `document.zip` 부재 |
| Retry 분류 (C5) | LLM/schema 에러 시 target.attempts | 정확히 1 (재시도 안 함) |
| Retry 분류 (C5) | fetch 에러 시 attempts<3 후 target.status | `pending` (재시도 대상) |
| Skip 분류 | "사업보고서 없음" 에러 후 status | `skipped` (재시도 안 함) |
| 회귀 없음 | `uv run pytest` | 모두 PASS |

**Gate**: 8 항목 모두 PASS → T5. 비용/retry 분류는 본 plan의 핵심 — 미달 시 fix 강제.

---

## Task 5: `backfill.enumerate_targets` + `run_batch` — universe file driven (C1)

> Universe는 *오직* active.txt에서 로드. 모드 분기 제거.

**Files:**
- Modify: `src/themek/dart/backfill.py`
- Modify: `tests/test_backfill.py`

- [ ] **Step 1: 실패 테스트**

```python
def test_enumerate_targets_from_file(tmp_path):
    """active.txt + periods → BackfillTargetSpec 곱."""
    universe_file = tmp_path / "active.txt"
    universe_file.write_text("00126380\n00164742\n", encoding="utf-8")
    specs = enumerate_targets(universe_file=universe_file, periods="2024:2025")
    assert len(specs) == 4
    assert {(s.corp_code, s.period) for s in specs} == {
        ("00126380", "2024"), ("00126380", "2025"),
        ("00164742", "2024"), ("00164742", "2025"),
    }


def test_enumerate_targets_single_period(tmp_path):
    universe_file = tmp_path / "active.txt"
    universe_file.write_text("00126380\n", encoding="utf-8")
    specs = enumerate_targets(universe_file=universe_file, periods="2025")
    assert specs == [BackfillTargetSpec("00126380", "2025")]


def test_run_batch_processes_until_budget(tmp_path, db_session):
    """5 pending + budget=4 → 4개 처리 후 종료."""
    for i in range(5):
        db_session.add(BackfillTarget(
            corp_code=f"0012638{i}", period="2025", status="pending",
        ))
    db_session.commit()
    summary = run_batch(
        session=db_session,
        client=_fake_client_all_success(),
        cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path, daily_cap=4),
        extractor=_stub_extractor(),
        max_targets=10,
    )
    assert summary.processed == 4
    from sqlalchemy import select, func
    pending = db_session.scalar(
        select(func.count()).select_from(BackfillTarget)
        .where(BackfillTarget.status == "pending")
    )
    assert pending == 1


def test_run_batch_respects_max_targets(tmp_path, db_session):
    for i in range(5):
        db_session.add(BackfillTarget(
            corp_code=f"0012638{i}", period="2025", status="pending",
        ))
    db_session.commit()
    summary = run_batch(
        session=db_session,
        client=_fake_client_all_success(),
        cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path, daily_cap=100),
        extractor=_stub_extractor(),
        max_targets=2,
    )
    assert summary.processed == 2


def test_run_batch_reset_stale_in_progress(tmp_path, db_session):
    """default 180분 초과 in_progress → pending reset."""
    from datetime import datetime, timedelta
    stale = BackfillTarget(
        corp_code="00126380", period="2025", status="in_progress",
        last_attempt_at=datetime.utcnow() - timedelta(hours=4),
    )
    db_session.add(stale); db_session.commit()
    summary = run_batch(
        session=db_session,
        client=_fake_client_all_success(),
        cache=_tmp_cache(tmp_path),
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
    )
    db_session.refresh(stale)
    assert stale.status == "done"
```

- [ ] **Step 2: 구현**

```python
from sqlalchemy import select, update, func
from datetime import timedelta
from themek.dart.universe import load_universe


@dataclass
class BackfillTargetSpec:
    corp_code: str
    period: str


def _parse_periods(periods: str) -> list[str]:
    if ":" in periods:
        a, b = periods.split(":")
        return [str(y) for y in range(int(a), int(b) + 1)]
    if "," in periods:
        return [p.strip() for p in periods.split(",")]
    return [periods.strip()]


def enumerate_targets(
    *, universe_file: Path, periods: str,
) -> list[BackfillTargetSpec]:
    """active.txt + periods → 단순 곱."""
    corps = load_universe(universe_file)
    period_list = _parse_periods(periods)
    return [BackfillTargetSpec(c, p) for c in corps for p in period_list]


@dataclass
class BatchSummary:
    processed: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    pending_remaining: int = 0
    budget_remaining: int = 0


def run_batch(
    *, session: Session, client, cache: DartCache,
    rate_budget: RateBudget, extractor,
    max_targets: int = 500,
    reset_stale_minutes: int = 180,   # C8 (옵션 A에서 채택 안 됐지만 합리적 default)
    purge_zip: bool = False,
) -> BatchSummary:
    # stale in_progress reset
    cutoff = datetime.utcnow() - timedelta(minutes=reset_stale_minutes)
    session.execute(
        update(BackfillTarget)
        .where(BackfillTarget.status == "in_progress")
        .where(BackfillTarget.last_attempt_at < cutoff)
        .values(status="pending")
    )
    session.commit()

    summary = BatchSummary()
    while summary.processed < max_targets:
        target = session.scalar(
            select(BackfillTarget)
            .where(BackfillTarget.status == "pending")
            .order_by(BackfillTarget.id)
            .limit(1)
        )
        if target is None:
            break
        try:
            r = run_one_target(
                target=target, session=session,
                client=client, cache=cache, rate_budget=rate_budget,
                extractor=extractor, purge_zip=purge_zip,
            )
        except RateBudgetExceeded:
            break
        summary.processed += 1
        if r.status == "done": summary.done += 1
        elif r.status == "skipped": summary.skipped += 1
        elif r.status == "failed": summary.failed += 1

    summary.pending_remaining = session.scalar(
        select(func.count()).select_from(BackfillTarget)
        .where(BackfillTarget.status == "pending")
    )
    summary.budget_remaining = rate_budget.remaining()
    return summary
```

- [ ] **Step 3: 통과 + 커밋**

```bash
uv run pytest tests/test_backfill.py -v
git add src/themek/dart/backfill.py tests/test_backfill.py
git commit -m "feat(backfill): enumerate_targets from active.txt + run_batch (Plan #5 T5)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `pytest tests/test_backfill.py -v -k "enumerate or run_batch"` | 5 tests passed (enumerate×2 + budget cap + max cap + stale reset) |
| Budget cap | budget=4 + 5 pending → summary.processed | 정확히 4 |
| Max targets cap | budget 충분 + max_targets=2 → summary.processed | 정확히 2 |
| Stale reset | 180+분 in_progress row → 자동 pending 변경 | last_attempt_at < cutoff인 row의 status 전이 검증 |
| enumerate 곱 | 2 corp × 2 period → 4 spec | 정확히 |
| 회귀 없음 | `uv run pytest` | 모두 PASS |

**Gate**: 6 항목 모두 PASS → T6.

---

# Phase 3 — Layer B: Daily Incremental (T6~T7)

---

## Task 6: `incremental.scan_new_reports` — 페이지네이션

**Files:**
- Create: `src/themek/dart/incremental.py`
- Create: `tests/test_incremental.py`
- Modify: `src/themek/dart/client.py` — `list_periodic_reports`에 `corp_code: Optional` + `page_no` 추가

- [ ] **Step 1: client.py 확장**

```python
def list_periodic_reports(
    self, *, corp_code: Optional[str] = None,
    bgn_de: str, end_de: str, page_no: int = 1, page_count: int = 100,
) -> dict:
    params = {
        "crtfc_key": self._key,
        "bgn_de": bgn_de, "end_de": end_de,
        "pblntf_ty": "A", "page_count": page_count, "page_no": page_no,
    }
    if corp_code:
        params["corp_code"] = corp_code
    r = self._client.get(f"{self._base}/list.json", params=params)
    self._raise_on_error(r)
    payload = r.json()
    if payload.get("status") not in ("000", "013"):
        raise DartApiError(f"list.json status={payload.get('status')} message={payload.get('message')}")
    return payload
```

기존 호출 (`fetch.find_business_report_rcept_no`)은 호환.

- [ ] **Step 2: 실패 테스트**

```python
"""incremental.scan_new_reports: 시간 범위 페이지네이션."""
from themek.dart.incremental import scan_new_reports


class _SpyPagedClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
    def list_periodic_reports(self, **kwargs):
        self.calls.append(kwargs)
        idx = kwargs.get("page_no", 1) - 1
        return self.pages[idx] if idx < len(self.pages) else {"status": "013", "list": []}


def test_scan_single_page():
    client = _SpyPagedClient([{
        "status": "000", "total_page": 1, "page_no": 1,
        "list": [
            {"rcept_no": "20260301001", "corp_code": "00126380",
             "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260301"},
            {"rcept_no": "20260301002", "corp_code": "00164742",
             "report_nm": "반기보고서 (2025.06)", "rcept_dt": "20260301"},
        ],
    }])
    rows = scan_new_reports(client, bgn_de="20260301", end_de="20260302")
    assert len(rows) == 2
    assert len(client.calls) == 1


def test_scan_multi_page():
    client = _SpyPagedClient([
        {"status": "000", "total_page": 3, "page_no": 1, "list": [{"rcept_no": "A"}]},
        {"status": "000", "total_page": 3, "page_no": 2, "list": [{"rcept_no": "B"}]},
        {"status": "000", "total_page": 3, "page_no": 3, "list": [{"rcept_no": "C"}]},
    ])
    rows = scan_new_reports(client, bgn_de="20260301", end_de="20260331")
    assert {r["rcept_no"] for r in rows} == {"A", "B", "C"}


def test_scan_empty_013():
    client = _SpyPagedClient([{"status": "013", "list": []}])
    assert scan_new_reports(client, bgn_de="20260101", end_de="20260102") == []
```

- [ ] **Step 3: 구현**

```python
"""Layer B: daily incremental scanner."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date


def scan_new_reports(
    client, *, bgn_de: str, end_de: str,
) -> list[dict]:
    """list.json을 corp_code 없이 호출, 페이지네이션 끝까지 전체 정기공시 수집."""
    all_rows: list[dict] = []
    page = 1
    while True:
        payload = client.list_periodic_reports(
            corp_code=None, bgn_de=bgn_de, end_de=end_de, page_no=page,
        )
        if payload.get("status") == "013":
            break
        all_rows.extend(payload.get("list", []))
        total = payload.get("total_page", 1)
        if page >= total:
            break
        page += 1
    return all_rows
```

- [ ] **Step 4: 통과 + 커밋**

```bash
uv run pytest tests/test_incremental.py -v -k scan_
git add src/themek/dart/incremental.py src/themek/dart/client.py tests/test_incremental.py
git commit -m "feat(incremental): scan_new_reports paginated list.json (Plan #5 T6)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `pytest tests/test_incremental.py -v -k scan` | 3 tests passed (single page / multi page / 013 empty) |
| 페이지네이션 종료 | total_page=3 → client 호출 횟수 | 정확히 3 |
| 빈 응답 처리 | status="013" 시 빈 list return | `[]` |
| 회귀 없음 | `uv run pytest` | 모두 PASS |

**Gate**: 4 항목 모두 PASS → T7.

---

## Task 7: `incremental.run_incremental` — universe filter + diff + ingest (C1, C7)

> Universe는 active.txt에서 로드. 결과 ingest는 Layer A와 동일 함수 재사용.

**Files:**
- Modify: `src/themek/dart/incremental.py`
- Modify: `tests/test_incremental.py`

- [ ] **Step 1: 실패 테스트**

```python
def test_run_incremental_filters_and_ingests(tmp_path, db_session):
    """scan → 사업보고서 + universe filter + DB diff → 신규만 ingest."""
    universe = {"00126380", "00164742"}
    # 이미 ingest 된 1건
    db_session.add(BusinessReport(
        dart_rcept_no="20260301001", corporation_id="00126380",
        report_type="사업보고서", period="2025",
        filing_date=date(2026, 3, 1),
    ))
    db_session.commit()

    client = _SpyPagedClient([{
        "status": "000", "total_page": 1, "page_no": 1,
        "list": [
            {"rcept_no": "20260301001", "corp_code": "00126380",
             "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260301"},
            {"rcept_no": "20260301002", "corp_code": "00126380",
             "report_nm": "반기보고서 (2025.06)", "rcept_dt": "20260301"},
            {"rcept_no": "20260301003", "corp_code": "99999999",
             "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260301"},
            {"rcept_no": "20260301004", "corp_code": "00164742",
             "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260301"},
        ],
    }])
    result = run_incremental(
        client=client, cache=_tmp_cache(tmp_path),
        session=db_session, universe=universe,
        rate_budget=_tmp_budget(tmp_path),
        extractor=_stub_extractor(),
        since=date(2026, 3, 1), until=date(2026, 3, 2),
        fetcher=_fake_fetcher_returning_html(b"<html>본문</html>"),
    )
    assert result.scanned == 4
    assert result.in_universe == 2
    assert result.already_ingested == 1
    assert result.to_ingest == 1
    assert result.ingested == 1
    assert db_session.get(BusinessReport, "20260301004") is not None


def test_run_incremental_empty_run_zero_llm(tmp_path, db_session):
    """신규 0건 → ingest 0, LLM 0 호출."""
    client = _SpyPagedClient([{"status": "013", "list": []}])
    class _FailIfCalled:
        def __call__(self, *a, **kw): raise AssertionError("LLM 호출됨")
    result = run_incremental(
        client=client, cache=_tmp_cache(tmp_path),
        session=db_session, universe={"00126380"},
        rate_budget=_tmp_budget(tmp_path),
        extractor=_FailIfCalled(),
        since=date(2026, 1, 1), until=date(2026, 1, 2),
    )
    assert result.ingested == 0
```

- [ ] **Step 2: 구현**

```python
@dataclass
class IncrementalRunResult:
    scanned: int = 0
    in_universe: int = 0
    already_ingested: int = 0
    to_ingest: int = 0
    ingested: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)


def run_incremental(
    *, client, cache, session, universe: set[str],
    rate_budget, extractor,
    since: date, until: date,
    fetcher=None,
    purge_zip: bool = False,
) -> IncrementalRunResult:
    import re
    from sqlalchemy import select
    from themek.db.models import BusinessReport
    from themek.ingest.business_report import ingest_business_report
    from themek.dart.fetch import fetch_business_report_html, BusinessReportFetchError
    from themek.dart.parser import extract_business_sections

    fetcher = fetcher or fetch_business_report_html

    rate_budget.consume(1)
    scanned = scan_new_reports(
        client, bgn_de=since.strftime("%Y%m%d"), end_de=until.strftime("%Y%m%d"),
    )
    result = IncrementalRunResult(scanned=len(scanned))

    candidates = [
        r for r in scanned
        if r.get("report_nm", "").startswith("사업보고서")
        and r.get("corp_code") in universe
    ]
    result.in_universe = len(candidates)
    if not candidates:
        return result

    existing = set(session.scalars(select(BusinessReport.dart_rcept_no)).all())
    to_process = [r for r in candidates if r["rcept_no"] not in existing]
    result.already_ingested = len(candidates) - len(to_process)
    result.to_ingest = len(to_process)

    for r in to_process:
        try:
            rate_budget.consume(1)
            year = _year_from_report_nm(r["report_nm"])
            html_path, _ = fetcher(
                client, cache,
                ticker="", year=year,
                corp_code=r["corp_code"],
            )
            text, _ = extract_business_sections(
                html_path.read_text(encoding="utf-8"),
            )
            ingest_business_report(
                session,
                dart_rcept_no=r["rcept_no"],
                corporation_id=r["corp_code"],
                report_type="사업보고서",
                period=str(year),
                filing_date=_parse_dt(r["rcept_dt"]),
                raw_text_excerpt=text,
                extractor=extractor,
            )
            result.ingested += 1
            if purge_zip:
                zip_path = cache.raw_dir / r["rcept_no"] / "document.zip"
                if zip_path.exists():
                    zip_path.unlink()
        except Exception as e:
            session.rollback()
            result.failed.append((r["rcept_no"], str(e)))
    return result


def _year_from_report_nm(report_nm: str) -> int:
    import re
    m = re.search(r"\((\d{4})\.", report_nm)
    if not m:
        raise ValueError(f"report_nm year 추출 실패: {report_nm}")
    return int(m.group(1))


def _parse_dt(rcept_dt: str) -> date:
    return date(int(rcept_dt[:4]), int(rcept_dt[4:6]), int(rcept_dt[6:8]))
```

- [ ] **Step 3: 통과 + 커밋**

```bash
uv run pytest tests/test_incremental.py -v
git add src/themek/dart/incremental.py tests/test_incremental.py
git commit -m "feat(incremental): run_incremental filter+diff+ingest (Plan #5 T7)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `pytest tests/test_incremental.py -v -k run_incremental` | 2 tests passed |
| Filter 정확도 | 4 scanned (사업/반기/외부/universe) → IncrementalRunResult | scanned=4, in_universe=2, already=1, to_ingest=1, ingested=1 |
| Empty run zero LLM | 빈 응답 시 `_FailIfCalled` extractor 호출 | 호출 안 됨 (AssertionError 발생 X) |
| 회귀 없음 | `uv run pytest` | 모두 PASS |

**Gate**: 4 항목 모두 PASS → T8.

---

# Phase 4 — CLI (T8~T11)

---

## Task 8: CLI `themek dart backfill init` — universe file (C1)

**Files:**
- Modify: `src/themek/cli.py`
- Create: `tests/test_cli_dart_backfill.py`

- [ ] **Step 1: 실패 테스트**

```python
from typer.testing import CliRunner
from themek.cli import app

runner = CliRunner()


def test_cli_backfill_init_dry_run(tmp_path, monkeypatch):
    universe_file = tmp_path / "active.txt"
    universe_file.write_text("00126380\n00164742\n", encoding="utf-8")
    monkeypatch.setenv("DART_API_KEY", "test")

    result = runner.invoke(app, [
        "dart", "backfill", "init",
        "--universe-file", str(universe_file), "--periods", "2024:2025",
    ])
    assert result.exit_code == 0
    assert "예상 처리: 4 target" in result.stdout
    assert "예상 DART 호출" in result.stdout
    assert "예상 LLM 비용" in result.stdout


def test_cli_backfill_init_confirm_creates_rows(tmp_path, monkeypatch, db_session):
    universe_file = tmp_path / "active.txt"
    universe_file.write_text("00126380\n", encoding="utf-8")
    monkeypatch.setenv("DART_API_KEY", "test")

    result = runner.invoke(app, [
        "dart", "backfill", "init",
        "--universe-file", str(universe_file), "--periods", "2024:2025",
        "--confirm",
    ])
    assert result.exit_code == 0
    # 2 row 생성 (2024, 2025)
    from sqlalchemy import select, func
    from themek.db.models import BackfillTarget
    n = db_session.scalar(select(func.count()).select_from(BackfillTarget))
    assert n == 2
```

- [ ] **Step 2: 구현**

```python
backfill_app = typer.Typer(help="다종목 backfill 명령")
dart_app.add_typer(backfill_app, name="backfill")

DEFAULT_UNIVERSE_FILE = "data/universe/active.txt"


@backfill_app.command("init")
def backfill_init_cmd(
    universe_file: Path = typer.Option(
        DEFAULT_UNIVERSE_FILE, "--universe-file",
        help="corp_code 1줄당 1개. # 주석 허용.",
    ),
    periods: str = typer.Option(..., "--periods",
                                help="YYYY 단일 또는 YYYY:YYYY 범위"),
    confirm: bool = typer.Option(False, "--confirm",
                                 help="dry-run 끄고 실제 row 생성"),
):
    from themek.dart.backfill import enumerate_targets
    from themek.db.models import BackfillTarget
    from sqlalchemy import select

    specs = enumerate_targets(universe_file=universe_file, periods=periods)
    n_targets = len(specs)
    n_calls = n_targets * 2  # list + document per target (보수적)
    est_cost = n_targets * 0.25  # 평균 단가 — 실측은 input_chars 기반

    typer.echo(f"=== Backfill Init Dry-Run ===")
    typer.echo(f"universe-file: {universe_file}")
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

- [ ] **Step 3: 커밋**

```bash
uv run pytest tests/test_cli_dart_backfill.py -v -k init
git add src/themek/cli.py tests/test_cli_dart_backfill.py
git commit -m "feat(cli): dart backfill init from active.txt with dry-run (Plan #5 T8)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `pytest tests/test_cli_dart_backfill.py -v -k init` | 2 tests passed |
| Dry-run 출력 (라인) | runner stdout grep | "예상 처리:" + "예상 DART 호출:" + "예상 LLM 비용:" 3 라인 |
| --confirm 후 row | DB row count | `len(specs) - duplicates` 와 정확 일치 |
| 회귀 없음 | `uv run pytest` | 모두 PASS |

**Gate**: 4 항목 모두 PASS → T9.

---

## Task 9: CLI `themek dart backfill run` (+ `--purge-zip` C7)

**Files:**
- Modify: `src/themek/cli.py`
- Modify: `tests/test_cli_dart_backfill.py`

- [ ] **Step 1: 실패 테스트 + 구현**

```python
@backfill_app.command("run")
def backfill_run_cmd(
    max_targets: int = typer.Option(500, "--max-targets"),
    daily_cap: Optional[int] = typer.Option(None, "--daily-cap"),
    reset_stale_minutes: int = typer.Option(180, "--reset-stale-minutes"),
    purge_zip: bool = typer.Option(False, "--purge-zip-after-extract",
                                   help="business.html 추출 후 document.zip 삭제 (디스크 절약)"),
):
    from themek.dart.backfill import run_batch
    from themek.dart.rate_budget import RateBudget, RateBudgetExceeded
    s = get_settings()
    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)

    budget = RateBudget(
        daily_cap=daily_cap or 38000,
        state_file=s.dart_cache_dir / "budget_state.json",
    )
    extractor = _stub_extractor_from_env()
    try:
        with _session() as sess:
            summary = run_batch(
                session=sess, client=client, cache=cache,
                rate_budget=budget, extractor=extractor,
                max_targets=max_targets,
                reset_stale_minutes=reset_stale_minutes,
                purge_zip=purge_zip,
            )
    except RateBudgetExceeded as e:
        typer.echo(f"Budget exceeded: {e}", err=True); raise typer.Exit(code=6)

    typer.echo(
        f"processed={summary.processed} done={summary.done} "
        f"skipped={summary.skipped} failed={summary.failed} "
        f"pending_remaining={summary.pending_remaining} "
        f"budget_remaining={summary.budget_remaining}"
    )
```

- [ ] **Step 2: 통과 + 커밋**

```bash
uv run pytest tests/test_cli_dart_backfill.py -v -k run
git add src/themek/cli.py tests/test_cli_dart_backfill.py
git commit -m "feat(cli): dart backfill run with --purge-zip flag (Plan #5 T9)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `pytest tests/test_cli_dart_backfill.py -v -k "run and not status"` | 통과 |
| Budget 초과 → exit 6 | RateBudget(daily_cap=0) simulation | exit_code == 6 + stderr "Budget exceeded" |
| --purge-zip 동작 | run 후 `ls data/dart/raw/<rcept>/document.zip` | 부재 |
| 회귀 없음 | `uv run pytest` | 모두 PASS |

**Gate**: 4 항목 모두 PASS → T10.

---

## Task 10: CLI `themek dart backfill status` — escalation 분포 (C4)

**Files:**
- Modify: `src/themek/cli.py`
- Modify: `tests/test_cli_dart_backfill.py`

- [ ] **Step 1: 구현**

```python
@backfill_app.command("status")
def backfill_status_cmd(
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                 help="escalation 분포 + 비용 top-10 표시"),
):
    from themek.db.models import BackfillTarget
    from sqlalchemy import select, func, desc

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
        # escalation 분포
        esc_rows = sess.execute(
            select(BackfillTarget.escalation_level, func.count())
            .where(BackfillTarget.status == "done")
            .group_by(BackfillTarget.escalation_level)
        ).all()
        typer.echo("\n=== Escalation distribution (done) ===")
        for level, n in esc_rows:
            typer.echo(f"  {str(level):12s}: {n:6d}")

        # 비용 top 10
        top = sess.execute(
            select(BackfillTarget.corp_code, BackfillTarget.period,
                   BackfillTarget.input_chars, BackfillTarget.cost_estimate_usd)
            .where(BackfillTarget.status == "done")
            .order_by(desc(BackfillTarget.cost_estimate_usd))
            .limit(10)
        ).all()
        typer.echo("\n=== Top 10 by cost ===")
        for cc, p, ic, cost in top:
            typer.echo(f"  {cc} {p}: input_chars={ic} cost=${float(cost):.4f}")
```

- [ ] **Step 2: 커밋**

```bash
uv run pytest tests/test_cli_dart_backfill.py -v -k status
git add src/themek/cli.py tests/test_cli_dart_backfill.py
git commit -m "feat(cli): dart backfill status with escalation + cost top-10 (Plan #5 T10)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `pytest tests/test_cli_dart_backfill.py -v -k status` | 통과 |
| 기본 출력 | runner stdout grep | "BackfillTarget summary" + 5 status 라인 + "Total LLM cost" |
| --verbose 섹션 | runner stdout grep | "Escalation distribution" + "Top 10 by cost" 2 섹션 |
| 비용 합계 정확 | sum(cost_estimate_usd) DB query 결과 == 표시 값 | 일치 |
| 회귀 없음 | `uv run pytest` | 모두 PASS |

**Gate**: 5 항목 모두 PASS → T11.

---

## Task 11: CLI `themek dart incremental` — active.txt + `--purge-zip`

**Files:**
- Modify: `src/themek/cli.py`
- Modify: `tests/test_cli_dart_backfill.py`

- [ ] **Step 1: 구현**

```python
@dart_app.command("incremental")
def dart_incremental_cmd(
    since: str = typer.Option("yesterday", "--since"),
    until: str = typer.Option("today", "--until"),
    universe_file: Path = typer.Option(
        DEFAULT_UNIVERSE_FILE, "--universe-file",
        help="active.txt 경로 (backfill과 동일)",
    ),
    purge_zip: bool = typer.Option(False, "--purge-zip-after-extract"),
):
    from themek.dart.incremental import run_incremental
    from themek.dart.universe import load_universe
    from themek.dart.rate_budget import RateBudget
    from datetime import date, timedelta

    s = get_settings()
    today = date.today()
    since_d = today - timedelta(days=1) if since == "yesterday" else date.fromisoformat(since)
    until_d = today if until == "today" else date.fromisoformat(until)

    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True); raise typer.Exit(code=2)

    universe = set(load_universe(universe_file))
    budget = RateBudget(daily_cap=38000,
                       state_file=s.dart_cache_dir / "budget_state.json")
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
        f"already_ingested={result.already_ingested} to_ingest={result.to_ingest} "
        f"ingested={result.ingested} failed={len(result.failed)}"
    )
```

- [ ] **Step 2: 커밋**

```bash
uv run pytest tests/test_cli_dart_backfill.py -v -k incremental
git add src/themek/cli.py tests/test_cli_dart_backfill.py
git commit -m "feat(cli): dart incremental with active.txt + --purge-zip (Plan #5 T11)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| 단위 테스트 | `pytest tests/test_cli_dart_backfill.py -v -k incremental` | 통과 |
| --since yesterday default | 내부 since_d 값 | `date.today() - timedelta(days=1)` |
| active.txt 로드 | universe set이 파일 corp_codes와 일치 | 일치 |
| 출력 metric | stdout grep | "scanned=" + "in_universe=" + "ingested=" 3 키워드 |
| 회귀 없음 | `uv run pytest` | 모두 PASS |

**Gate**: 5 항목 모두 PASS → T12.

---

# Phase 5 — 운영 자료 + Final Verification (T12~T14)

---

## Task 12: cron wrapper + 운영 매뉴얼

**Files:**
- Create: `docs/dart-backfill-runbook.md`
- Create: `scripts/themek_backfill.sh` (gitignore)
- Modify: `.gitignore`

- [ ] **Step 1: cron wrapper 작성** (`scripts/themek_backfill.sh`):

```bash
#!/bin/bash
set -euo pipefail
cd /path/to/themek
source .env

DATE=$(date +%Y%m%d)
mkdir -p data/log

# 1. daily incremental (가벼움)
uv run themek dart incremental \
  --since yesterday --until today \
  --purge-zip-after-extract \
  >> data/log/incremental_${DATE}.log 2>&1

# 2. backfill 남은 작업 진행 (한도까지)
uv run themek dart backfill run \
  --purge-zip-after-extract \
  >> data/log/backfill_${DATE}.log 2>&1 || echo "backfill ended (budget or done)"

# 3. status 1줄 요약
uv run themek dart backfill status >> data/log/status_${DATE}.log
```

- [ ] **Step 2: `.gitignore` 갱신**

```
/scripts/themek_backfill.sh
/scripts/verify_backfill_smoke.py
/scripts/recon_backfill.py
/data/log/
/data/dart/budget_state.json
/data/universe/
```

- [ ] **Step 3: `docs/dart-backfill-runbook.md` 작성**

```markdown
# DART Backfill Runbook

## 1. Universe 정의 (단일 source of truth)
- `data/universe/active.txt` — corp_code 1줄당 1개. `#` 주석 + 빈 줄 허용.
- 이 파일이 backfill init과 incremental scan filter 둘 다의 정의.
- 운영자가 종목을 추가/제거하면 다음 cron부터 자동 반영.

예시:
```
# KOSPI 대형주
00126380   # 삼성전자
00164742   # 현대자동차

# KOSDAQ
01133217   # 레인보우로보틱스
```

## 2. 초기 setup
```bash
uv run themek dart sync-corp                                    # corp_master (분기 1회)
mkdir -p data/universe
# data/universe/active.txt 작성 (corp_code 8자리)
uv run themek dart backfill init \
  --universe-file data/universe/active.txt --periods 2024:2025
# dry-run 결과 확인 후
uv run themek dart backfill init \
  --universe-file data/universe/active.txt --periods 2024:2025 --confirm
uv run themek dart backfill status
```

## 3. cron 등록
```cron
# 매일 5시 KST (DART 한도 reset 후)
0 5 * * *  /path/to/themek/scripts/themek_backfill.sh
```

## 4. 일일 모니터링
- `uv run themek dart backfill status --verbose` (escalation 분포 + 비용 top-10)
- `tail -f data/log/backfill_YYYYMMDD.log`
- `tail -f data/log/incremental_YYYYMMDD.log`
- `uv run themek dart parser-stats` (Plan #4 학습 누적)

## 5. 사고 대응
- **Budget 초과 (exit 6)**: 자동 다음날 재개. 수동 개입 불필요.
- **in_progress 180분+ 멈춤**: 다음 cron이 자동 reset. 즉시 복구는
  `uv run themek dart backfill run --reset-stale-minutes 0`
- **failed row 누적**: `SELECT corp_code, period, last_error FROM backfill_targets WHERE status='failed'`
  분석. C5 정책상 failed는 LLM/schema 에러로 자동 재시도 안 함.
- **escalation_level=full_text 비율 높음**: Plan #4 학습 사이클 필요.
  `themek dart parser-learn` + `parser-consolidate`.

## 6. Universe 확장 절차
```bash
echo "00126380" >> data/universe/active.txt    # 종목 추가
uv run themek dart backfill init \
  --universe-file data/universe/active.txt --periods 2024:2025 --confirm
# 기존 done은 UNIQUE 충돌로 skip, 새 (corp, period)만 pending 추가
```

## 7. 정정보고서 정책
- 동일 (corp, period)에 정정보고서가 새 rcept_no로 들어오면:
  - **BusinessReport에 새 row 추가** (덮어쓰기 X — append-only)
  - **BackfillTarget는 그대로** (universe 진행 추적용, 기존 row 유지)
- `query e5`는 `filing_date DESC LIMIT 1`로 최신 보고서를 선택
- 같은 filing_date 동률 시 row 선택 정확성은 Plan #5.1로 검증 예정
```

- [ ] **Step 4: 커밋**

```bash
git add docs/dart-backfill-runbook.md .gitignore
git commit -m "docs(backfill): runbook with active.txt single source + cron template (Plan #5 T12)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| Cron syntax | `bash -n scripts/themek_backfill.sh` | exit 0 |
| Cron 실행 가능 | `[ -x scripts/themek_backfill.sh ]` (chmod +x 후) | true |
| Runbook 섹션 완비 | `grep -c '^## ' docs/dart-backfill-runbook.md` | ≥ 7 (Universe / Setup / Cron / 모니터링 / 사고대응 / 확장 / 정정정책) |
| Runbook에 active.txt 명시 | `grep "active.txt" docs/dart-backfill-runbook.md` | match ≥ 3회 |
| .gitignore 갱신 | `grep "/data/universe/" .gitignore` | match |

**Gate**: 5 항목 모두 PASS → T13.

---

## Task 13: **🎯 Final Success Gate — 프로덕션 10건 적재 검증 (10 종목 × 2024:2025)**

> 이 task의 통과 여부가 **Plan #5 전체의 SUCCESS/FAIL 판정**이다. 8개 acceptance check 모두 통과해야 plan 완료로 인정.

**Goal:** 합의된 10 종목을 실제 DART API + 실제 LLM으로 2024:2025 사업보고서 적재하고, 각 종목의 데이터가 사업보고서 의도대로 채워졌는지 정량 검증.

**Files:**
- Create: `data/universe/active.txt` (확정 10 종목)
- Create: `scripts/verify_backfill_smoke.py` (검증 자동화, gitignore)
- Create: `docs/dart-backfill-production-smoke-2026-XX-XX.md`

### Step 0: Universe 확정

본 plan에서 선정한 10 종목 (산업 다양성을 자연 분산하도록 랜덤 선정):

| ticker | corp_code (sync-corp 후 확인) | 종목명 | 산업 |
|--------|-----------------------------|--------|------|
| 005930 | 00126380 | 삼성전자 | 반도체·전자 |
| 000660 | 00164779 | SK하이닉스 | 반도체 |
| 035420 | 00266961 | NAVER | IT·플랫폼 |
| 035720 | 00918625 | 카카오 | IT·플랫폼 |
| 005380 | 00164742 | 현대자동차 | 자동차 |
| 051910 | 00356361 | LG화학 | 화학·2차전지 |
| 091990 | 00877059 | 셀트리온헬스케어 | 헬스케어 |
| 247540 | 01293603 | 에코프로비엠 | 2차전지 |
| 042700 | 00266961 | 한미반도체 | 반도체장비 |
| 277810 | 01133217 | 레인보우로보틱스 | 로봇 |

> 정확한 corp_code는 `data/dart/corp_master.json`에서 `themek dart sync-corp` 후 확인. 위 매핑은 추정치 — Step 0-1에서 실측 확정.

- [ ] **Step 0-1: corp_master에서 정확한 corp_code 추출**

```bash
uv run themek dart sync-corp  # 이미 완료된 상태 가정
uv run python -c "
import json
master = json.load(open('data/dart/corp_master.json'))
targets = {'005930','000660','035420','035720','005380','051910','091990','247540','042700','277810'}
for r in master:
    if r['stock_code'] in targets:
        print(f\"{r['stock_code']} -> {r['corp_code']} {r['corp_name']}\")
"
```

- [ ] **Step 0-2: `data/universe/active.txt` 작성**

```bash
mkdir -p data/universe
# Step 0-1 출력을 보고 corp_code 8자리만 추출
cat > data/universe/active.txt <<'EOF'
# Plan #5 Task 13 production smoke - 10 종목
00126380   # 005930 삼성전자
... (10줄)
EOF
```

### Step 1: Backfill 실행

- [ ] **Step 1-1: dry-run**

```bash
uv run themek dart backfill init \
  --universe-file data/universe/active.txt --periods 2024:2025
# 예상 처리: 20 target / 예상 DART 호출: ~40 / 예상 LLM 비용: ~$5.00
```

- [ ] **Step 1-2: BackfillTarget 생성**

```bash
uv run themek dart backfill init \
  --universe-file data/universe/active.txt --periods 2024:2025 --confirm
uv run themek dart backfill status
# 기대: pending=20 done=0 failed=0
```

- [ ] **Step 1-3: 1차 실행 (실 DART + 실 LLM, ~10~20분)**

```bash
time uv run themek dart backfill run \
  --max-targets 20 --purge-zip-after-extract \
  2>&1 | tee data/log/smoke20_run1.log
# 기대 출력: processed=20 done=N skipped=M failed=K pending_remaining=0
```

### Step 2: Acceptance Check (8개)

- [ ] **Check 1: BackfillTarget 상태** — done + skipped + failed = 20
  - **PASS 임계**: done ≥ 16 (80% 이상 정상). skipped는 사업보고서 미공시 종목 허용 (2024년 사업보고서가 2025-03~05 공시이므로 2024는 거의 다 있음, 2025는 일부 미공시 가능 — 2025년 사업보고서는 2026-03~05 공시).

- [ ] **Check 2: BusinessReport count == done** — DB row 수가 done 카운트와 일치
  - **PASS 임계**: 동일

- [ ] **Check 3: BusinessSegment ≥ 1 per report** — 모든 보고서에 segment 추출
  - **PASS 임계**: done 보고서의 100%

- [ ] **Check 4: RevenueComposition share_pct sum 80~120%** — 합리적 합계
  - **PASS 임계**: done 보고서의 80% 이상

- [ ] **Check 5: GeographicExposure ≥ 1** — 지역 노출 추출
  - **PASS 임계**: done 보고서의 80% 이상

- [ ] **Check 6: Idempotency** — 재실행 시 LLM/DART 호출 0
  - **PASS 임계**: `dart backfill run` 재실행 후 budget_remaining 1차와 동일, processed=0

- [ ] **Check 7: `query e5` end-to-end** — 각 ticker 정상 답변
  - **PASS 임계**: 10/10 ticker 모두 segments + regions 출력

- [ ] **Check 8: 정정/다년 누적 검증** — 1 종목에 추가 period 1건 ingest
  - BusinessReport row +1
  - `query e5`는 filing_date 최신 (2025) 노출
  - **PASS 임계**: row +1 + 최신 선택 정확

### Step 3: 검증 자동화 + 결과 문서

- [ ] **Step 3-1: `scripts/verify_backfill_smoke.py` 작성**

```python
"""Plan #5 Task 13 acceptance checks 자동화."""
import sys, subprocess, json
from sqlalchemy import select, func
from themek.db.engine import make_engine, make_session_factory
from themek.db.models import (
    Stock, Corporation, BackfillTarget, BusinessReport,
    BusinessSegment, RevenueComposition, GeographicExposure,
)

Session = make_session_factory(make_engine())
checks = []

with Session() as s:
    # Check 1
    counts = dict(s.execute(
        select(BackfillTarget.status, func.count())
        .group_by(BackfillTarget.status)
    ).all())
    done = counts.get("done", 0)
    checks.append(("Check 1 BackfillTarget done≥16", done >= 16, f"done={done} skipped={counts.get('skipped',0)} failed={counts.get('failed',0)}"))

    # Check 2
    n_reports = s.scalar(select(func.count(BusinessReport.dart_rcept_no)))
    checks.append(("Check 2 BusinessReport count == done", n_reports == done,
                   f"reports={n_reports} done={done}"))

    # Check 3
    reports = s.scalars(select(BusinessReport)).all()
    seg_ok = sum(
        1 for r in reports
        if s.scalar(
            select(func.count(BusinessSegment.id))
            .where(BusinessSegment.corporation_id == r.corporation_id)
        ) >= 1
    )
    checks.append(("Check 3 segments ≥ 1", seg_ok == len(reports),
                   f"ok={seg_ok}/{len(reports)}"))

    # Check 4
    in_range = 0
    sum_details = []
    for r in reports:
        total = float(s.scalar(
            select(func.sum(RevenueComposition.share_pct))
            .where(RevenueComposition.source_report_id == r.dart_rcept_no)
        ) or 0)
        sum_details.append((r.corporation_id, r.period, total))
        if 80 <= total <= 120:
            in_range += 1
    threshold = max(1, int(len(reports) * 0.8))
    checks.append(("Check 4 share_pct 80-120%", in_range >= threshold,
                   f"in_range={in_range}/{len(reports)} details={sum_details}"))

    # Check 5
    geo_ok = sum(
        1 for r in reports
        if s.scalar(
            select(func.count(GeographicExposure.id))
            .where(GeographicExposure.source_report_id == r.dart_rcept_no)
        ) >= 1
    )
    checks.append(("Check 5 geographic ≥ 1", geo_ok >= threshold,
                   f"ok={geo_ok}/{len(reports)}"))

# Check 6: idempotency
proc = subprocess.run(
    ["uv", "run", "themek", "dart", "backfill", "run", "--max-targets", "20"],
    capture_output=True, text=True,
)
last_line = (proc.stdout.strip().splitlines() or [""])[-1]
checks.append(("Check 6 idempotency", "processed=0" in last_line, last_line))

# Check 7: query e5 per ticker
with Session() as s:
    tickers = list(s.scalars(
        select(Stock.ticker)
        .join(Corporation, Stock.issued_by_id == Corporation.dart_code)
        .join(BackfillTarget, BackfillTarget.corp_code == Corporation.dart_code)
        .where(BackfillTarget.status == "done")
        .distinct()
    ).all())
ok_q = 0
for t in tickers:
    r = subprocess.run(["uv", "run", "themek", "query", "e5", "--ticker", t],
                       capture_output=True, text=True)
    if r.returncode == 0 and len(r.stdout) > 50:
        ok_q += 1
checks.append(("Check 7 query e5 all tickers", ok_q == len(tickers),
               f"ok={ok_q}/{len(tickers)}"))

# Check 8: manual check (별도 단계로 안내)
checks.append(("Check 8 정정/다년 누적", None, "manual step — Step 3-3 참조"))

# 결과 출력
all_pass = True
for name, ok, detail in checks:
    flag = "PASS" if ok is True else "FAIL" if ok is False else "MANUAL"
    print(f"[{flag}] {name}: {detail}")
    if ok is False: all_pass = False

sys.exit(0 if all_pass else 1)
```

- [ ] **Step 3-2: 자동 검증 실행 (Check 1-7)**

```bash
uv run python scripts/verify_backfill_smoke.py | tee data/log/smoke20_verify.log
```

기대: 7개 자동 check PASS, 1개 MANUAL.

- [ ] **Step 3-3: Check 8 수동 — 정정/다년 누적**

```bash
# 1 종목 1 period 추가 (이미 done인 데이터에 1건 더)
echo "00126380" > /tmp/extra_universe.txt
uv run themek dart backfill init \
  --universe-file /tmp/extra_universe.txt --periods 2023 --confirm
uv run themek dart backfill run --max-targets 1 --purge-zip-after-extract

# BusinessReport row +1 확인
uv run python -c "
from sqlalchemy import select, func
from themek.db.engine import make_engine, make_session_factory
from themek.db.models import BusinessReport
S = make_session_factory(make_engine())
with S() as s:
    n = s.scalar(select(func.count()).select_from(BusinessReport))
    print(f'BusinessReport count: {n}')
"
# 기대: 이전 + 1

# 최신 선택 확인 — 005930의 query e5 응답에 period=2025 (가장 최신)
uv run themek query e5 --ticker 005930 | grep -i period
# 기대: period: 2025
```

### Step 4: 결과 baseline 문서화

- [ ] **Step 4-1: `docs/dart-backfill-production-smoke-2026-XX-XX.md` 작성**

```markdown
# DART Multi-Corp Backfill — Production Smoke 결과

**실행일:** 2026-XX-XX
**Universe:** 10 종목 (data/universe/active.txt 기준)
**Period:** 2024:2025

## Universe (10 종목)

| ticker | corp_code | 종목명 | 산업 |
|--------|-----------|--------|------|
| 005930 | 00126380 | 삼성전자 | 반도체·전자 |
| 000660 | ... | SK하이닉스 | 반도체 |
| 035420 | ... | NAVER | IT |
| 035720 | ... | 카카오 | IT |
| 005380 | ... | 현대자동차 | 자동차 |
| 051910 | ... | LG화학 | 화학·2차전지 |
| 091990 | ... | 셀트리온헬스케어 | 헬스케어 |
| 247540 | ... | 에코프로비엠 | 2차전지 |
| 042700 | ... | 한미반도체 | 반도체장비 |
| 277810 | 01133217 | 레인보우로보틱스 | 로봇 |

## 실행 로그
- data/log/smoke20_run1.log
- data/log/smoke20_verify.log

## 비용 / 호출
- DART API 호출: ~40 (예측 일치)
- LLM 호출 비용 합 (BackfillTarget.cost_estimate_usd sum): $X.XX
- 소요 시간: M분

## Escalation 분포
- regex: N
- regex+llm: N
- full_text: N

## Acceptance Check 8/8

| Check | 결과 | 세부 |
|-------|------|------|
| 1. BackfillTarget done≥16 | PASS | done=20 |
| 2. BusinessReport count == done | PASS | 20/20 |
| 3. segments ≥ 1 | PASS | 20/20 |
| 4. share_pct 80-120% | PASS | 18/20 |
| 5. geographic ≥ 1 | PASS | 19/20 |
| 6. idempotency | PASS | processed=0, budget unchanged |
| 7. query e5 | PASS | 10/10 ticker |
| 8. 정정/다년 누적 | PASS | row +1 + 최신 선택 정확 |

## Issues / 관찰

- escalation_level=full_text 도달 종목: N건 (Plan #4 학습 사이클로 후속)
- skipped 종목: ... (2025년 사업보고서 미공시 등)

## 결정

→ **Plan #5 SUCCESS**. cron 정식 활성화 가능 + universe 확장 절차 (runbook §6) 진행.
```

- [ ] **Step 4-2: 커밋**

```bash
git add docs/dart-backfill-production-smoke-2026-XX-XX.md
git commit -m "docs(backfill): production smoke 10 종목 × 2024:2025 baseline (Plan #5 T13)"
```

**Gate**: 8개 check 중 7개 이상 PASS → **Plan #5 SUCCESS**. 6개 이하 → 실패 원인별 별도 fix plan 작성.

---

## Task 14: README 갱신 + Plan #5 ✅ 표기

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Status history**

```markdown
- Plan #5 (Multi-Corp Backfill, 14 task TDD + production smoke 10 종목 × 2024:2025 검증) ✅ 2026-XX-XX —
  Layer A initial backfill + Layer B daily incremental cron + RateBudget 38K/day cap + universe single-source-of-truth (active.txt)
```

- [ ] **Step 2: 사용 예시**

```markdown
### 다종목 backfill (Plan #5)

```bash
# 1. universe 정의 (단일 source of truth)
echo "00126380" > data/universe/active.txt  # corp_code 1줄당 1개

# 2. 1회: BackfillTarget 생성
uv run themek dart backfill init \
  --universe-file data/universe/active.txt --periods 2024:2025 --confirm

# 3. 매일 cron (scripts/themek_backfill.sh)
uv run themek dart incremental --since yesterday --until today --purge-zip-after-extract
uv run themek dart backfill run --purge-zip-after-extract

# 4. 모니터링
uv run themek dart backfill status --verbose   # escalation 분포 + 비용 top-10
```
```

- [ ] **Step 3: 다음 작업**

```markdown
**다음 작업:** Plan #2 + #7 (social layer ontology + 텔레/블로그/팍스넷 ingestion) 또는
Plan #5.1 (정정보고서 query 최신 선택 검증 + LLM 비용 자동 cap + 시계열 query layer).
```

- [ ] **Step 4: 커밋**

```bash
git add README.md
git commit -m "docs: README Plan #5 완료 + active.txt 사용 예시 (Plan #5 T14)"
```

### Success Gate

| 검증 항목 | 측정 | PASS 기준 |
|----------|------|----------|
| Plan #5 status 라인 | `grep "Plan #5 (Multi-Corp Backfill" README.md` | match |
| 사용 예시 | `grep "dart backfill init" README.md` | match |
| 다음 작업 갱신 | `grep -E "Plan #2 \+ #7\|Plan #5\.1" README.md` | match |

**Gate**: 3 항목 모두 PASS → 본 plan 종료.

---

## Plan SUCCESS Determination

본 plan은 다음 3개 조건을 모두 충족해야 SUCCESS로 종료된다.

### 조건 1: 14 Task 모두 Success Gate 통과

| Task | 핵심 Gate | 측정 |
|------|----------|------|
| T0 | 가정 1·3 PASS + cassette 저장 | recon notes 결과 |
| T1 | 5 tests + import + 회귀 | `pytest tests/test_rate_budget.py` |
| T2 | 3 tests + migration 가역성 + UNIQUE constraint | alembic up/down + DB inspect |
| T3 | 5 tests + 4 edge case | `pytest tests/test_universe.py` |
| T4 | **7 tests + 비용 캡처 + retry 분류 (C5)** | 8 항목 모두 |
| T5 | 5 tests + budget/max/stale cap 정확 | `pytest -k "enumerate or run_batch"` |
| T6 | 3 tests + 페이지네이션 종료 | `pytest -k scan` |
| T7 | 2 tests + filter 정확 + empty zero LLM | `pytest -k run_incremental` |
| T8 | 2 tests + dry-run 3 라인 + --confirm row 수 | CLI runner |
| T9 | 단위 + budget→exit 6 + --purge-zip | CLI runner |
| T10 | 단위 + --verbose 2 섹션 + 비용 합계 | CLI runner |
| T11 | 단위 + since default + active.txt 로드 | CLI runner |
| T12 | bash syntax + runbook 7 섹션 + .gitignore | shell check + grep |
| **T13** | **8 acceptance check 중 7+ PASS** | **`scripts/verify_backfill_smoke.py` exit 0** |
| T14 | README 3 라인 | grep |

### 조건 2: 전체 회귀 없음

```bash
uv run pytest
# 기대: 기존 ~200 + Plan #5 ~28 = ~228 passing
# Plan #5 task가 기존 테스트 중 1건이라도 깨면 → FAIL
```

### 조건 3: T13 프로덕션 검증 (Plan SUCCESS의 최종 판정)

```bash
uv run python scripts/verify_backfill_smoke.py
# 기대: exit 0 (자동 Check 1-7 모두 PASS) + 수동 Check 8 (정정/누적) PASS
# 7/8 이상 PASS → Plan #5 SUCCESS
# 6/8 이하 → 실패 원인별 fix plan 작성 후 재시도
```

### 운영 검증 (선택, T14 이후)

cron 1주일 동안 동작 확인:
- 매일 `dart backfill status --verbose`로 진행률 + 비용 누적 모니터링
- escalation_level=`full_text` 비율 < 10% (Plan #4 학습 사이클 동작 확인)
- `data/log/incremental_*.log` 매일 생성 + 평일 시즌 외에는 ingested ≈ 0

---

## 위험 / Note

- **R1 (T0 의존)**: 가정 1 (`corp_code` 없이 `list.json` 호출 가능) 깨지면 Layer B 재설계. 가정 성립 전제.
- **R2 (T13 비용)**: 10 종목 × 2년 = 20 ingest × $0.25 = $5 ~ ×$0.33 = $6.60. 예산 안.
- **R3 (정정보고서 query 정확성)**: Check 8은 filing_date 최신 선택을 검증하지만, 같은 filing_date 정정 다수 시 row 선택 비결정적. Plan #5.1.
- **R4 (LLM cost 폭주 방어)**: dry-run + `--confirm` flag 강제. 자동 cap은 Plan #5.1.
- **R5 (단일 process 가정)**: cron 1 process 동시 실행 전제. 멀티 instance는 외부 lock.
- **R6 (Plan #4 escalation full_text 도달)**: BackfillTarget.escalation_level로 모니터링 + Plan #4 학습 사이클 연동.
- **R7 (purge_zip 후 재학습 불가)**: document.zip 삭제 후 다른 HTML 파일에서 학습 패턴 찾고 싶으면 cache miss로 재 fetch 필요. operational tradeoff — 운영 cron은 on, 디버깅 환경은 off.
- **R8 (corp_code 매핑 신선도)**: corp_master 분기 수동 refresh. 신규 상장사는 그 사이 사업보고서 발표 시 incremental에서 universe filter로 떨어짐 (의도).
