# LLM Robustness — Timeout & Schema Coercion (Plan #5.3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan #5.2 운영 smoke (2026-05-28, 20-target test)에서 발견된 2건의 backfill 실패를 정정한다.
1. **A: LLM CLI timeout 120s** — 대용량 PDF (`AK홀딩스 2025`, `BGF 2025` 등 `full_text` escalation 케이스)에서 claude CLI 응답 시간 초과로 실패
2. **B: Pydantic schema 검증 실패** — `BGF리테일 2025`에서 `geographic.0.share_pct` 가 LLM이 반환한 비숫자 문자열을 float로 강제 변환하지 못해 `BusinessExtraction` 검증 실패

**Final Success Metric:**
- Task 1 단위 테스트로 escalation-aware timeout 동작 검증 (regex/llm=60s, full_text=600s)
- Task 2 단위 테스트로 `share_pct` 문자열 형식 ("12%", "약 15", "12.3 %") 모두 float로 정상 coerce
- 통합 smoke로 실패 3건 시나리오 (AK홀딩스 / BGF / BGF리테일) 모두 done 처리 가능 여부 시뮬레이션

**Architecture:** 2개 파일 수정 only — `src/themek/config.py`, `src/themek/llm/{claude_cli.py, schemas.py}`. 호출자(`parser.py`, `business_report.py`)는 변경 없음. 후방호환 유지.

**Tech Stack:** 기존 (pytest, pytest-mock, Pydantic 2, typer). 신규 의존성 없음.

---

## 핵심 설계 결정

### 1. Timeout은 escalation-level별 분기

```
regex   → 60s   (작은 chunk, 빠른 응답)
llm     → 120s  (현 default 유지)
full_text → 600s (10분, 대용량 PDF 충분)
```

이유:
- full_text mode는 평균 input chars 20K~170K (테스트에서 관측). 토큰화 + LLM 응답이 60-600s 분포.
- regex/llm mode는 5K char 이하 chunk라 60s로 단축 가능. fast-fail이 budget 보호에 유리.

구현: `call_claude(prompt, *, timeout_sec=None, escalation=None)` 시그니처에 `escalation` optional 추가. 명시되지 않으면 기존 default 동작.

### 2. share_pct coercion은 Pydantic `field_validator` 사용

LLM이 반환하는 문자열 형식 (관측):
- `"12.3%"` — 퍼센트 부호 붙음
- `"약 15"` — 한글 + 숫자
- `"12.3 %"` — 공백
- `"12.5"` — 정상 (현재도 통과)

전략: pre-validator로 문자열 받으면 정규식으로 첫 숫자 (소수 포함) 추출 후 float 변환. 추출 실패 시 None 반환 (geographic의 경우 schema가 비-Optional이므로 ValidationError 유지). geographic의 share_pct는 비-Optional이 의도된 설계라 None 변환은 명시적으로 거부 — 단, raise 메시지를 더 친절하게.

`segments.share_pct` (Optional) / `customers.revenue_share_pct` (Optional) / `geographic.share_pct` (Required) 3곳 모두 동일 validator 적용.

### 3. 후방호환

- `claude_cli_timeout_sec` env 변수는 그대로 (default fallback)
- `call_claude()` 호출 시 `escalation` 미지정이면 기존 동작
- Pydantic validator는 기존 정상 입력 (순수 float/int)에는 영향 없음 — coercion은 string에만 적용

---

## Prerequisites

- ✅ Plan #5.2 완료 (backfill 운영 진입 상태)
- 기존 `tests/test_llm_schemas.py`, `tests/test_claude_cli.py` 통과
- `.env`의 `DART_API_KEY`, `KRX_ID`, `KRX_PW` (Plan #5.2 운영 prerequisite)

---

## Scope (in / out)

**In:**
- `src/themek/config.py` — escalation별 timeout 추가
- `src/themek/llm/claude_cli.py` — `escalation` 인자 추가
- `src/themek/llm/schemas.py` — share_pct field_validator 추가
- `src/themek/dart/parser.py` — `call_claude` 호출 시 escalation 전달 (1-2줄)
- `tests/test_claude_cli.py` — escalation-aware timeout 단위 테스트
- `tests/test_llm_schemas.py` — share_pct coercion 단위 테스트
- `tests/test_parser_escalation.py` — 정정 후 회귀 확인 (변경 없으면 skip)

**Out (후속):**
- LLM API 직접 호출로 전환 (CLI wrapper 제거) — 별도 plan
- 본격 chunked input + 병렬 LLM call — 별도 plan
- Prompt engineering 강화 (numeric only emphasis) — 별도 plan
- 실패한 3건 BackfillTarget 자동 retry (운영자 SQL 수동 처리 권장)

---

## Task 1: Escalation-aware claude CLI timeout

**Files:**
- Modify: `src/themek/config.py` (+3 fields)
- Modify: `src/themek/llm/claude_cli.py` (+`escalation` param)
- Modify: `src/themek/dart/parser.py` (pass `escalation` through)
- Test: `tests/test_claude_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_cli.py`:

```python
def test_call_claude_uses_regex_timeout(mocker, monkeypatch):
    """escalation='regex' → 60s timeout."""
    monkeypatch.delenv("CLAUDE_CLI_REGEX_TIMEOUT_SEC", raising=False)
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value.stdout = "{}"
    fake.return_value.returncode = 0
    from themek.llm.claude_cli import call_claude
    call_claude("p", escalation="regex")
    assert fake.call_args.kwargs["timeout"] == 60


def test_call_claude_uses_full_text_timeout(mocker, monkeypatch):
    """escalation='full_text' → 600s timeout."""
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value.stdout = "{}"
    fake.return_value.returncode = 0
    from themek.llm.claude_cli import call_claude
    call_claude("p", escalation="full_text")
    assert fake.call_args.kwargs["timeout"] == 600


def test_call_claude_explicit_timeout_overrides_escalation(mocker):
    """timeout_sec 직접 지정이 escalation default보다 우선."""
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value.stdout = "{}"
    fake.return_value.returncode = 0
    from themek.llm.claude_cli import call_claude
    call_claude("p", escalation="regex", timeout_sec=300)
    assert fake.call_args.kwargs["timeout"] == 300


def test_call_claude_no_escalation_keeps_default(mocker):
    """escalation 미지정 시 기존 settings default 사용."""
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value.stdout = "{}"
    fake.return_value.returncode = 0
    from themek.llm.claude_cli import call_claude
    call_claude("p")  # no escalation
    assert fake.call_args.kwargs["timeout"] == 120  # config default
```

- [ ] **Step 2: Run tests — expect FAIL** (`call_claude` 미지원 인자)

- [ ] **Step 3: 모델 수정**

In `src/themek/config.py`:

```python
class Settings(BaseSettings):
    # ... 기존 ...
    claude_cli_timeout_sec: int = Field(default=120)
    claude_cli_timeout_regex_sec: int = Field(default=60)
    claude_cli_timeout_llm_sec: int = Field(default=120)
    claude_cli_timeout_full_text_sec: int = Field(default=600)
```

In `src/themek/llm/claude_cli.py`:

```python
def call_claude(
    prompt: str,
    *,
    timeout_sec: int | None = None,
    escalation: str | None = None,
) -> CallResult:
    settings = get_settings()
    if timeout_sec is not None:
        timeout = timeout_sec
    elif escalation == "regex":
        timeout = settings.claude_cli_timeout_regex_sec
    elif escalation == "full_text":
        timeout = settings.claude_cli_timeout_full_text_sec
    elif escalation == "llm":
        timeout = settings.claude_cli_timeout_llm_sec
    else:
        timeout = settings.claude_cli_timeout_sec
    # ... 이하 기존 동작 ...
```

In `src/themek/dart/parser.py` — `call_claude` 호출 위치 1-2개에 `escalation=<current_level>` 인자 추가. (정확한 위치는 grep으로 확인.)

- [ ] **Step 4: Run tests — all 4 PASS**

- [ ] **Step 5: 회귀** — `uv run pytest tests/test_claude_cli.py tests/test_parser_escalation.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/themek/config.py src/themek/llm/claude_cli.py src/themek/dart/parser.py tests/test_claude_cli.py
git commit -m "feat(llm): escalation-aware claude CLI timeouts (regex=60s, full_text=600s)"
```

---

## Task 2: share_pct string-to-float coercion

**Files:**
- Modify: `src/themek/llm/schemas.py` (+field_validator)
- Test: `tests/test_llm_schemas.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm_schemas.py`:

```python
import pytest
from themek.llm.schemas import (
    SegmentItem, CustomerItem, GeographicItem,
)


@pytest.mark.parametrize("raw,expected", [
    ("12.3%", 12.3),
    ("약 15", 15.0),
    ("12.3 %", 12.3),
    ("12.5", 12.5),
    (12.5, 12.5),
    (12, 12.0),
])
def test_geographic_share_pct_accepts_string_forms(raw, expected):
    g = GeographicItem(region_code="KR", share_pct=raw)
    assert g.share_pct == expected


def test_geographic_share_pct_rejects_unparseable():
    """비숫자 string은 ValidationError + 친절한 메시지."""
    with pytest.raises(Exception, match="share_pct.*숫자"):
        GeographicItem(region_code="KR", share_pct="N/A")


def test_segment_share_pct_optional_string_coercion():
    """Optional float인 segments.share_pct도 같은 coercion."""
    s = SegmentItem(name_ko="반도체", share_pct="50%")
    assert s.share_pct == 50.0


def test_customer_revenue_share_pct_optional_string_coercion():
    c = CustomerItem(name_raw="Samsung", revenue_share_pct="30 %")
    assert c.revenue_share_pct == 30.0


def test_share_pct_unchanged_for_normal_inputs():
    """순수 float/int/None은 영향 없음."""
    assert GeographicItem(region_code="KR", share_pct=50.0).share_pct == 50.0
    assert SegmentItem(name_ko="x", share_pct=None).share_pct is None
```

- [ ] **Step 2: Run tests — expect FAIL** (string은 float type error)

- [ ] **Step 3: Schema 수정**

In `src/themek/llm/schemas.py`:

```python
import re
from pydantic import BaseModel, Field, field_validator


def _coerce_share_pct(v):
    """문자열 share_pct를 float로 강제 변환.
    
    LLM 응답의 비표준 형식 처리:
    - '12.3%' / '12.3 %' → 12.3
    - '약 15' / '15.0개' → 15.0
    - 'N/A' / 비파싱 → ValueError ('숫자' 키워드 포함)
    - None / float / int → 그대로
    """
    if v is None or isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        m = re.search(r"\d+(\.\d+)?", v)
        if m is None:
            raise ValueError(f"share_pct에 숫자 없음: {v!r}")
        return float(m.group())
    raise ValueError(f"share_pct 타입 미지원: {type(v).__name__}")


class SegmentItem(BaseModel):
    name_ko: str
    share_pct: Optional[float] = Field(default=None, ge=0, le=100)
    description: Optional[str] = None
    products: list[str] = Field(default_factory=list)
    
    @field_validator("share_pct", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _coerce_share_pct(v)


class CustomerItem(BaseModel):
    name_raw: str
    revenue_share_pct: Optional[float] = Field(default=None, ge=0, le=100)
    tier: str = "unknown"
    
    @field_validator("revenue_share_pct", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _coerce_share_pct(v)


class GeographicItem(BaseModel):
    region_code: str
    share_pct: float = Field(ge=0, le=100)
    
    @field_validator("share_pct", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _coerce_share_pct(v)
```

- [ ] **Step 4: Run tests — all PASS**

- [ ] **Step 5: 회귀** — `uv run pytest tests/test_llm_schemas.py tests/test_parser_escalation.py tests/test_ingest_business_report.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/themek/llm/schemas.py tests/test_llm_schemas.py
git commit -m "fix(llm): coerce share_pct strings ('12%', '약 15') to float"
```

---

## Task 3: 실 데이터 검증 (manual operational smoke)

이전 테스트에서 실패한 3건 (`AK홀딩스 2025`, `BGF 2025`, `BGF리테일 2025`) 의 status를 pending으로 reset 후 재실행해 done 처리되는지 확인.

- [ ] **Step 1: failed → pending reset (manual SQL)**

```bash
uv run python -c "
from themek.db.engine import make_engine, make_session_factory
from themek.db.models import BackfillTarget
from sqlalchemy import select

S = make_session_factory(make_engine())
with S() as s:
    targets = s.execute(
        select(BackfillTarget).where(
            BackfillTarget.status == 'failed',
            BackfillTarget.corp_code.in_(['00125080', '00219097', '01263022']),
            BackfillTarget.period == '2025',
        )
    ).scalars().all()
    for t in targets:
        t.status = 'pending'
        t.last_error = None
        t.attempts = 0
    s.commit()
    print(f'Reset {len(targets)} targets to pending')
"
```

- [ ] **Step 2: backfill run 재실행 (3개 처리)**

```bash
set -a && source .env && set +a && uv run themek dart backfill run --max-targets 3 --purge-zip-after-extract
```

Expected: `processed=3 done=3 skipped=0 failed=0`

- [ ] **Step 3: 결과 status 확인**

```bash
set -a && source .env && set +a && uv run themek dart backfill status --verbose | head -20
```

Expected: failed count 감소 (3→0), done count 증가 (17→20).

---

## Success Gate (deterministic)

| # | 검증 | Expected |
|---|------|---------|
| 1 | `uv run pytest tests/test_claude_cli.py -v` | exit 0, 신규 4 + 기존 통과 |
| 2 | `uv run pytest tests/test_llm_schemas.py -v` | exit 0, 신규 7 + 기존 통과 |
| 3 | `uv run pytest -v` 전체 | exit 0, 0 FAIL |
| 4 | (manual) Task 3 reset + retry 3건 → 모두 done | done 3 / failed 0 |

**Gate #1-3**: 자동, mock 기반. **Gate #4**: 실 DART API + LLM 호출 (~$1, ~5분).

---

## 후속 작업 (out of scope)

- Prompt engineering 강화 — LLM 응답에 "decimal only" 명시
- LLM API 직접 호출 (CLI wrapper 제거) — latency + 안정성 개선
- chunked input + 병렬 처리 — full_text 600s timeout도 부족한 케이스 대비
- BackfillTarget 자동 retry — N회 실패 시 retry 또는 alarm
- Failed targets dashboard — `themek dart backfill status --failed` 추가
