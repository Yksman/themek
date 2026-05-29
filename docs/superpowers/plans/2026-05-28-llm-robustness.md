# LLM Robustness — Timeout & Schema Coercion (Plan #5.3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Plan #5.2 운영 smoke (2026-05-28, 20-target + 25-random sample)에서 발견된 backfill 실패 3종류를 정정한다.
1. **A: LLM CLI timeout 120s** — 대용량 PDF (`AK홀딩스 2025`, `BGF 2025` 등 `full_text` escalation 케이스)에서 claude CLI 응답 시간 초과로 실패
2. **B: Pydantic schema 검증 실패** — `BGF리테일 2025` / `코다코 2025`에서 `geographic.0.share_pct` / `segments.4.share_pct` 가 LLM이 반환한 비숫자 문자열을 float로 강제 변환하지 못해 `BusinessExtraction` 검증 실패
3. **C: Transient claude CLI 실패** — 사조대림/현대홈쇼핑/나라엠앤디/뷰티스킨 2025 동시 `exit 1` + empty body + ~4s 종료. 동일 4건 ~3.5h 후 재시도 시 4/4 done. Rate limit 또는 transient quota throttling 추정 (확정 미상). 자동 short retry + opt-in long wait 메커니즘 필요.

**Final Success Metric:**
- Task 1 단위 테스트로 escalation-aware timeout 동작 검증 (regex/llm=60s, full_text=600s)
- Task 2 단위 테스트로 `share_pct` 문자열 형식 ("12%", "약 15", "12.3 %") 모두 float로 정상 coerce
- Task 4 단위 테스트로 transient claude CLI 실패 시 (i) short retry back-off [10s, 60s, 300s] (ii) 명시적 rate-limit 메시지 즉시 ClaudeRateLimitError (iii) backfill batch에서 opt-in 5h wait 동작 검증
- 통합 smoke로 실패 시나리오 (AK홀딩스/BGF/BGF리테일/코다코/사조대림) 모두 done 처리 가능 여부 시뮬레이션

**Architecture:** 4개 파일 수정 — `src/themek/config.py`, `src/themek/llm/{claude_cli.py, schemas.py}`, `src/themek/dart/backfill.py`. 호출자(`parser.py`, `business_report.py`)는 변경 없음. 후방호환 유지. 신규 예외 `ClaudeRateLimitError`는 `ClaudeCallError` 상속 (기존 catch 호환).

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
- `src/themek/config.py` — escalation별 timeout + transient retry/wait env vars 추가
- `src/themek/llm/claude_cli.py` — `escalation` 인자 + short retry + ClaudeRateLimitError + debug log
- `src/themek/llm/schemas.py` — share_pct field_validator 추가
- `src/themek/dart/parser.py` — `call_claude` 호출 시 escalation 전달 (1-2줄)
- `src/themek/dart/backfill.py` — `run_batch`에 ClaudeRateLimitError catch + opt-in 5h wait
- `tests/test_claude_cli.py` — escalation-aware timeout + transient retry 단위 테스트
- `tests/test_llm_schemas.py` — share_pct coercion 단위 테스트
- `tests/test_backfill.py` — rate limit propagation + wait 옵션 단위 테스트
- `tests/test_parser_escalation.py` — 정정 후 회귀 확인 (변경 없으면 skip)
- `data/log/claude_cli_failures.jsonl` (런타임 생성, gitignore) — debug log 출력

**Out (후속):**
- LLM API 직접 호출로 전환 (CLI wrapper 제거) — 별도 plan
- 본격 chunked input + 병렬 LLM call — 별도 plan
- Prompt engineering 강화 (numeric only emphasis) — 별도 plan
- BackfillTarget 영구 실패 시 alarm/escalation — 별도 plan

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

### Task 1 Success Gate (deterministic, all mock-based)

| # | 검증 명령 | Expected (정확치) |
|---|----------|-----------------|
| 1.1 | `uv run pytest tests/test_claude_cli.py::test_call_claude_uses_regex_timeout -v` | exit 0, 1 PASS, subprocess.run timeout == **60** |
| 1.2 | `uv run pytest tests/test_claude_cli.py::test_call_claude_uses_full_text_timeout -v` | exit 0, 1 PASS, subprocess.run timeout == **600** |
| 1.3 | `uv run pytest tests/test_claude_cli.py::test_call_claude_explicit_timeout_overrides_escalation -v` | exit 0, 1 PASS, subprocess.run timeout == **300** (explicit override) |
| 1.4 | `uv run pytest tests/test_claude_cli.py::test_call_claude_no_escalation_keeps_default -v` | exit 0, 1 PASS, subprocess.run timeout == **120** (config default) |
| 1.5 | `uv run python -c "from themek.config import get_settings; s = get_settings(); print(s.claude_cli_timeout_regex_sec, s.claude_cli_timeout_llm_sec, s.claude_cli_timeout_full_text_sec)"` | 정확히 `60 120 600` 출력 |
| 1.6 | `uv run pytest tests/test_claude_cli.py tests/test_parser_escalation.py tests/test_dart_parser.py -v` | exit 0, **0 FAIL, 0 ERROR** (회귀) |
| 1.7 | `grep -c "escalation=" src/themek/dart/parser.py` | ≥ **1** (parser가 `call_claude`에 escalation 전달함을 정적 확인) |

**Task 1 PASS = 1.1~1.7 모두 통과.**

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

### Task 2 Success Gate (deterministic, all mock-based)

| # | 검증 명령 | Expected (정확치) |
|---|----------|-----------------|
| 2.1 | `uv run pytest tests/test_llm_schemas.py::test_geographic_share_pct_accepts_string_forms -v` | exit 0, 6 PASS (parametrize 6 케이스). 각 케이스에서 `.share_pct == expected` exact equality |
| 2.2 | `uv run pytest tests/test_llm_schemas.py::test_geographic_share_pct_rejects_unparseable -v` | exit 0, 1 PASS. ValidationError 메시지에 "숫자" 문자열 포함 |
| 2.3 | `uv run pytest tests/test_llm_schemas.py::test_segment_share_pct_optional_string_coercion -v` | exit 0, 1 PASS, `.share_pct == 50.0` |
| 2.4 | `uv run pytest tests/test_llm_schemas.py::test_customer_revenue_share_pct_optional_string_coercion -v` | exit 0, 1 PASS, `.revenue_share_pct == 30.0` |
| 2.5 | `uv run pytest tests/test_llm_schemas.py::test_share_pct_unchanged_for_normal_inputs -v` | exit 0, 1 PASS (정상 float/None 무영향) |
| 2.6 | `uv run pytest tests/test_llm_schemas.py tests/test_parser_escalation.py tests/test_ingest_business_report.py -v` | exit 0, **0 FAIL, 0 ERROR** (회귀) |
| 2.7 | `uv run python -c "from themek.llm.schemas import GeographicItem; g = GeographicItem(region_code='KR', share_pct='12.3%'); print(g.share_pct == 12.3)"` | 정확히 `True` 출력 |
| 2.8 | `grep -c "field_validator" src/themek/llm/schemas.py` | ≥ **3** (Segment/Customer/Geographic 각 1) |

**Task 2 PASS = 2.1~2.8 모두 통과.**

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

### Task 3 Success Gate (실 API 호출, 환경 의존)

| # | 검증 | Expected (정확치) |
|---|------|-----------------|
| 3.1 | **사전 reset 검증** — Step 1 실행 후 다음 SQL: `SELECT COUNT(*) FROM backfill_targets WHERE status='failed' AND corp_code IN ('00125080', '00219097', '01263022') AND period='2025'` | 정확히 **0** (모두 pending으로 reset됨) |
| 3.2 | **재실행 결과** — Step 2 `backfill run --max-targets 3` stdout | 정규식 `processed=3 done=[23] skipped=[01] failed=0` 매치 (done=2~3 + skipped=0~1, failed=**0**) |
| 3.3 | **사후 검증** — Step 2 완료 후 SQL: `SELECT COUNT(*) FROM backfill_targets WHERE status='failed' AND corp_code IN ('00125080', '00219097', '01263022')` | 정확히 **0** |
| 3.4 | **누적 done 증가** — Step 3 status 출력의 `done` 카운트 | reset 전 done 카운트 + 처리된 개수 (≥2) |
| 3.5 | **escalation 분포** — Step 3 status `Escalation distribution` 섹션 | full_text 카운트 ≥ 1 (대용량 PDF가 600s timeout으로 처리됐다는 증거) |
| 3.6 | **share_pct 적재 검증** — `SELECT COUNT(*) FROM geographic_revenue WHERE share_pct > 0` 또는 이에 상응하는 동적 검증 | reset 전 count + 신규 row ≥ 1 (Task 2 fix 가 실 데이터에서 동작했다는 증거) |

**Task 3 PASS = 3.1~3.5 모두 통과 (3.6은 schema/테이블 구조에 따라 best-effort).**

**Task 3 MANUAL-NEEDED**: 실 DART/LLM 호출이라 CI 자동화 불가. 운영자가 Step 1-3를 순차 실행하고 각 gate를 수동 확인.

---

## Task 4: Transient failure 자동 복구 — short retry + opt-in long wait

**Background (2026-05-28 실 sample 발견):**
- random 25 sample 중 마지막 4건 (#22~#25 사조대림/현대홈쇼핑/나라엠앤디/뷰티스킨) 동시 `claude CLI exited 1` + empty body + ~4s 종료
- 동일 4건을 ~3.5시간 후 직접 재시도 → **4/4 done** (regex escalation 정상)
- 결론: **transient issue (rate limit 또는 transient quota throttling 추정, 확정 불가)**. LLM 호출 자체까지 안 가고 즉시 종료되는 패턴
- 정확한 stderr/stdout 정보 미확보 → `last_error` 빈 값. 향후 패턴 분석 위해 capture 강화 필요

**4-A: claude_cli.py — short retry (in-call back-off)**

**Files:**
- Modify: `src/themek/config.py` (+`claude_cli_short_retry_attempts`, `claude_cli_short_retry_backoffs_sec`)
- Modify: `src/themek/llm/claude_cli.py` (+ short retry loop)
- Test: `tests/test_claude_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_cli.py`:

```python
def test_call_claude_retries_on_empty_body_exit_1(mocker, monkeypatch):
    """exit 1 + empty stdout/stderr + 빠른 종료 → short retry 시도."""
    monkeypatch.setenv("CLAUDE_CLI_SHORT_RETRY_ATTEMPTS", "3")
    sleep_mock = mocker.patch("themek.llm.claude_cli.time.sleep")
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    # 첫 2회는 transient 실패, 3번째는 성공
    fake.side_effect = [
        mocker.Mock(returncode=1, stdout="", stderr=""),
        mocker.Mock(returncode=1, stdout="", stderr=""),
        mocker.Mock(returncode=0, stdout='{"result":"ok","usage":{}}', stderr=""),
    ]
    from themek.llm.claude_cli import call_claude
    r = call_claude("p", escalation="regex")
    assert r.text == "ok"
    assert fake.call_count == 3
    # back-off 두 번 호출 (10s, 60s)
    assert sleep_mock.call_args_list == [
        mocker.call(10), mocker.call(60),
    ]


def test_call_claude_non_transient_exit_skips_retry(mocker, monkeypatch):
    """exit 1 이지만 stderr 메시지 있으면 retry 안 함 (real error로 간주)."""
    monkeypatch.setenv("CLAUDE_CLI_SHORT_RETRY_ATTEMPTS", "3")
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value = mocker.Mock(returncode=1, stdout="", stderr="auth failed")
    from themek.llm.claude_cli import call_claude, ClaudeCallError
    with pytest.raises(ClaudeCallError, match="auth failed"):
        call_claude("p", escalation="regex")
    assert fake.call_count == 1  # 즉시 fail, retry 안 함
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: 구현**

In `config.py`:
```python
claude_cli_short_retry_attempts: int = Field(default=3)
claude_cli_short_retry_backoffs_sec: list[int] = Field(default=[10, 60, 300])
```

In `claude_cli.py`:
```python
import time

def _is_transient_failure(proc) -> bool:
    """exit 1 + empty body 패턴 = transient (LLM call 미도달)."""
    return (
        proc.returncode != 0
        and not (proc.stdout or "").strip()
        and not (proc.stderr or "").strip()
    )

def call_claude(prompt, *, timeout_sec=None, escalation=None):
    settings = get_settings()
    # ... timeout 계산 (기존) ...
    attempts = settings.claude_cli_short_retry_attempts
    backoffs = settings.claude_cli_short_retry_backoffs_sec
    last_proc = None
    for attempt in range(attempts):
        try:
            proc = subprocess.run(...)
        except subprocess.TimeoutExpired as e:
            raise ClaudeCallError(f"claude CLI timed out after {timeout}s") from e
        last_proc = proc
        if proc.returncode == 0:
            break
        if not _is_transient_failure(proc):
            # 명시 에러 → 즉시 raise
            raise ClaudeCallError(
                f"claude CLI exited {proc.returncode}: {proc.stderr.strip()}"
            )
        # transient → back-off + retry (마지막 시도 아니면)
        if attempt + 1 < attempts:
            time.sleep(backoffs[min(attempt, len(backoffs) - 1)])
    else:
        # 모든 retry 소진 → ClaudeRateLimitError raise (4-B에서 정의)
        raise ClaudeRateLimitError(
            f"transient failure after {attempts} attempts "
            f"(exit={last_proc.returncode}, empty body)"
        )
    # ... 기존 JSON parse ...
```

- [ ] **Step 4: Run tests — all PASS**

- [ ] **Step 5: Commit**
```bash
git add src/themek/config.py src/themek/llm/claude_cli.py tests/test_claude_cli.py
git commit -m "feat(llm): short retry with back-off for transient claude CLI failures (4-A)"
```

### Task 4-A Success Gate (deterministic, mock-based)

| # | 검증 | Expected (정확치) |
|---|------|-----------------|
| 4A.1 | `uv run pytest tests/test_claude_cli.py::test_call_claude_retries_on_empty_body_exit_1 -v` | 1 PASS. subprocess.run 정확히 **3회** 호출, time.sleep 정확히 `[call(10), call(60)]` |
| 4A.2 | `uv run pytest tests/test_claude_cli.py::test_call_claude_non_transient_exit_skips_retry -v` | 1 PASS. subprocess.run 정확히 **1회** 호출 (즉시 fail) |
| 4A.3 | `Settings().claude_cli_short_retry_attempts` | `3` |
| 4A.4 | `Settings().claude_cli_short_retry_backoffs_sec` | `[10, 60, 300]` |

---

**4-B: ClaudeRateLimitError + 명시적 패턴 감지**

**Files:**
- Modify: `src/themek/llm/claude_cli.py` (+ exception class + 명시 메시지 감지)
- Test: `tests/test_claude_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_cli.py`:

```python
def test_call_claude_raises_rate_limit_on_explicit_message(mocker, monkeypatch):
    """stderr에 'rate limit' 명시되면 retry 없이 즉시 ClaudeRateLimitError."""
    monkeypatch.setenv("CLAUDE_CLI_SHORT_RETRY_ATTEMPTS", "3")
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value = mocker.Mock(
        returncode=1, stdout="",
        stderr="Error: 5-hour usage limit reached",
    )
    from themek.llm.claude_cli import call_claude, ClaudeRateLimitError
    with pytest.raises(ClaudeRateLimitError, match="usage limit"):
        call_claude("p")
    assert fake.call_count == 1  # retry 안 함, 명시 알림이라 즉시 raise


def test_rate_limit_error_is_subclass_of_claude_call_error():
    """ClaudeRateLimitError는 ClaudeCallError 상속 (기존 catch 호환)."""
    from themek.llm.claude_cli import ClaudeRateLimitError, ClaudeCallError
    assert issubclass(ClaudeRateLimitError, ClaudeCallError)


def test_call_claude_exhausted_retries_raises_rate_limit(mocker, monkeypatch):
    """transient 패턴이 모든 retry에서 반복되면 최종 ClaudeRateLimitError."""
    monkeypatch.setenv("CLAUDE_CLI_SHORT_RETRY_ATTEMPTS", "2")
    mocker.patch("themek.llm.claude_cli.time.sleep")
    fake = mocker.patch("themek.llm.claude_cli.subprocess.run")
    fake.return_value = mocker.Mock(returncode=1, stdout="", stderr="")
    from themek.llm.claude_cli import call_claude, ClaudeRateLimitError
    with pytest.raises(ClaudeRateLimitError, match="after 2 attempts"):
        call_claude("p")
    assert fake.call_count == 2
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: 구현**

In `claude_cli.py`:
```python
class ClaudeCallError(RuntimeError):
    pass

class ClaudeRateLimitError(ClaudeCallError):
    pass


_RATE_LIMIT_PATTERNS = (
    "rate limit", "usage limit", "5-hour limit",
    "quota exceeded", "too many requests",
)

def _is_explicit_rate_limit(proc) -> bool:
    blob = (proc.stderr or "") + " " + (proc.stdout or "")
    blob_lc = blob.lower()
    return any(p in blob_lc for p in _RATE_LIMIT_PATTERNS)


# 기존 call_claude 안의 비-transient 분기에서:
if _is_explicit_rate_limit(proc):
    raise ClaudeRateLimitError(
        f"claude CLI rate limit: {proc.stderr.strip()[:200]}"
    )
# (이외 비-transient는 ClaudeCallError 그대로)
```

- [ ] **Step 4: Run tests — all PASS**

- [ ] **Step 5: Commit**
```bash
git add src/themek/llm/claude_cli.py tests/test_claude_cli.py
git commit -m "feat(llm): ClaudeRateLimitError + explicit rate-limit message detection (4-B)"
```

### Task 4-B Success Gate (deterministic, mock-based)

| # | 검증 | Expected (정확치) |
|---|------|-----------------|
| 4B.1 | `uv run pytest tests/test_claude_cli.py::test_call_claude_raises_rate_limit_on_explicit_message -v` | 1 PASS. subprocess.run 정확히 **1회** 호출 |
| 4B.2 | `uv run pytest tests/test_claude_cli.py::test_rate_limit_error_is_subclass_of_claude_call_error -v` | 1 PASS. `issubclass(ClaudeRateLimitError, ClaudeCallError) == True` |
| 4B.3 | `uv run pytest tests/test_claude_cli.py::test_call_claude_exhausted_retries_raises_rate_limit -v` | 1 PASS. subprocess.run 정확히 **2회** 호출, ClaudeRateLimitError.args[0] regex `after 2 attempts` 매치 |
| 4B.4 | `grep -c "ClaudeRateLimitError" src/themek/llm/claude_cli.py` | ≥ **2** (class 정의 + raise 위치) |

---

**4-C: backfill.run_batch에서 ClaudeRateLimitError catch + opt-in long wait**

**Files:**
- Modify: `src/themek/config.py` (+`themek_wait_for_quota`, `themek_wait_for_quota_sec`)
- Modify: `src/themek/dart/backfill.py` (run_batch + run_one_target에 catch)
- Test: `tests/test_backfill.py`

설계:
- **Default (env `THEMEK_WAIT_FOR_QUOTA=0`)**: ClaudeRateLimitError catch → target status pending 복원 → batch 즉시 종료. cron이 다음 호출에서 자연 재시도.
- **Opt-in (`THEMEK_WAIT_FOR_QUOTA=1`)**: ClaudeRateLimitError catch → target pending 복원 → `time.sleep(themek_wait_for_quota_sec)` (default 18000s=5h) → 같은 target부터 batch 재개.
- `SIGTERM`/`SIGINT` 받으면 sleep 도중 즉시 break + 상태 보존.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backfill.py`:

```python
def test_run_batch_exits_on_rate_limit_when_wait_disabled(test_session, mocker, monkeypatch):
    """기본 동작: rate limit hit → 즉시 종료 + target pending 복원."""
    monkeypatch.setenv("THEMEK_WAIT_FOR_QUOTA", "0")
    from themek.dart.backfill import run_batch
    from themek.llm.claude_cli import ClaudeRateLimitError
    # ... fixtures: 2 pending targets, run_one_target mocker가 첫 호출에 rate limit raise ...
    summary = run_batch(...)
    assert summary.processed == 0
    assert summary.rate_limit_hits == 1
    # target은 여전히 pending (status 복원)
    # ...


def test_run_batch_waits_then_resumes_when_opt_in(test_session, mocker, monkeypatch):
    """THEMEK_WAIT_FOR_QUOTA=1: rate limit hit → sleep → 같은 target 재시도 성공."""
    monkeypatch.setenv("THEMEK_WAIT_FOR_QUOTA", "1")
    monkeypatch.setenv("THEMEK_WAIT_FOR_QUOTA_SEC", "300")  # test 짧게
    sleep_mock = mocker.patch("themek.dart.backfill.time.sleep")
    # run_one_target 첫 호출: rate limit raise, 두 번째: done
    from themek.dart.backfill import run_batch
    summary = run_batch(...)
    assert summary.processed == 1
    assert summary.done == 1
    sleep_mock.assert_called_once_with(300)


def test_run_batch_max_wait_iterations(test_session, mocker, monkeypatch):
    """무한 wait 방지: max iterations 도달 시 종료."""
    monkeypatch.setenv("THEMEK_WAIT_FOR_QUOTA", "1")
    monkeypatch.setenv("THEMEK_WAIT_FOR_QUOTA_SEC", "300")
    monkeypatch.setenv("THEMEK_WAIT_FOR_QUOTA_MAX_ITERATIONS", "2")
    mocker.patch("themek.dart.backfill.time.sleep")
    # run_one_target은 매번 rate limit raise
    # batch는 sleep 2회 후 종료
    # ...
    assert sleep_mock.call_count == 2
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: 구현**

In `config.py`:
```python
themek_wait_for_quota: bool = Field(default=False)
themek_wait_for_quota_sec: int = Field(default=18000)  # 5h
themek_wait_for_quota_max_iterations: int = Field(default=2)
```

In `backfill.py`:
```python
import time
from themek.llm.claude_cli import ClaudeRateLimitError

@dataclass
class BatchSummary:
    # 기존 ...
    rate_limit_hits: int = 0
    rate_limit_waits: int = 0


def run_batch(..., max_targets, ...):
    settings = get_settings()
    summary = BatchSummary()
    wait_iter = 0
    while summary.processed < max_targets:
        if rate_budget.remaining() < 1:
            break
        target = ...
        if target is None:
            break
        try:
            r = run_one_target(...)
        except ClaudeRateLimitError:
            # status 복원
            target.status = "pending"
            target.last_error = "rate limit (auto-recovery in progress)"
            session.commit()
            summary.rate_limit_hits += 1
            if not settings.themek_wait_for_quota:
                break
            if wait_iter >= settings.themek_wait_for_quota_max_iterations:
                break
            wait_iter += 1
            summary.rate_limit_waits += 1
            time.sleep(settings.themek_wait_for_quota_sec)
            continue  # 같은 target부터 재개
        except RateBudgetExceeded:
            break
        # 정상 처리 카운트 ...
```

In `run_one_target`: `ClaudeRateLimitError`는 re-raise (잡지 않음). 일반 `ClaudeCallError`는 기존대로 status='failed'로 변환.

- [ ] **Step 4: Run tests — all PASS**

- [ ] **Step 5: Commit**
```bash
git add src/themek/config.py src/themek/dart/backfill.py tests/test_backfill.py
git commit -m "feat(backfill): catch ClaudeRateLimitError + opt-in 5h wait (4-C)"
```

### Task 4-C Success Gate (deterministic, mock-based)

| # | 검증 | Expected (정확치) |
|---|------|-----------------|
| 4C.1 | `uv run pytest tests/test_backfill.py::test_run_batch_exits_on_rate_limit_when_wait_disabled -v` | 1 PASS. summary.rate_limit_hits == 1, target.status == 'pending' (복원됨) |
| 4C.2 | `uv run pytest tests/test_backfill.py::test_run_batch_waits_then_resumes_when_opt_in -v` | 1 PASS. time.sleep 정확히 1회 (300s 인자), summary.done == 1 |
| 4C.3 | `uv run pytest tests/test_backfill.py::test_run_batch_max_wait_iterations -v` | 1 PASS. time.sleep 정확히 2회 호출 |
| 4C.4 | `Settings().themek_wait_for_quota` | `False` (default opt-out) |
| 4C.5 | `Settings().themek_wait_for_quota_sec` | `18000` (5h) |
| 4C.6 | `grep -c "ClaudeRateLimitError" src/themek/dart/backfill.py` | ≥ **1** (catch 위치) |

---

**4-D: claude_cli.py — stderr/stdout debug log capture**

**Files:**
- Modify: `src/themek/llm/claude_cli.py` (+`_log_failure` helper)
- Test: `tests/test_claude_cli.py`

설계:
- 실패 발생 시 (`returncode != 0`) timestamp + returncode + stderr/stdout (truncated 1KB each) + 환경 메타 (escalation, prompt_len) 을 `data/log/claude_cli_failures.jsonl` 에 1줄 append
- gitignore에 `data/log/claude_cli_failures.jsonl` 추가 (이미 `data/log/` 추가됐다면 무관)
- 향후 transient 패턴 통계 분석용 (rate limit vs quota vs 기타 구분)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_claude_cli.py`:

```python
def test_call_claude_logs_failure_to_jsonl(mocker, monkeypatch, tmp_path):
    """exit != 0 시 data/log/claude_cli_failures.jsonl 에 1줄 append."""
    monkeypatch.setenv("CLAUDE_CLI_SHORT_RETRY_ATTEMPTS", "1")
    monkeypatch.setenv("THEMEK_LOG_DIR", str(tmp_path))
    mocker.patch("themek.llm.claude_cli.subprocess.run").return_value = mocker.Mock(
        returncode=1, stdout="", stderr="some error",
    )
    from themek.llm.claude_cli import call_claude, ClaudeCallError
    with pytest.raises(ClaudeCallError):
        call_claude("p", escalation="regex")
    log = tmp_path / "claude_cli_failures.jsonl"
    assert log.exists()
    import json
    line = log.read_text().strip()
    rec = json.loads(line)
    assert rec["returncode"] == 1
    assert rec["stderr"] == "some error"
    assert rec["escalation"] == "regex"
    assert "timestamp" in rec


def test_call_claude_does_not_log_on_success(mocker, monkeypatch, tmp_path):
    """exit 0 시 log 파일 미생성."""
    monkeypatch.setenv("THEMEK_LOG_DIR", str(tmp_path))
    mocker.patch("themek.llm.claude_cli.subprocess.run").return_value = mocker.Mock(
        returncode=0, stdout='{"result":"ok","usage":{}}', stderr="",
    )
    from themek.llm.claude_cli import call_claude
    call_claude("p")
    log = tmp_path / "claude_cli_failures.jsonl"
    assert not log.exists()
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: 구현**

In `config.py`:
```python
themek_log_dir: str = Field(default="data/log")
```

In `claude_cli.py`:
```python
import json
from datetime import datetime, timezone
from pathlib import Path

def _log_failure(proc, *, escalation, prompt_len, attempt):
    settings = get_settings()
    log_dir = Path(settings.themek_log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "returncode": proc.returncode,
        "stderr": (proc.stderr or "")[:1024],
        "stdout": (proc.stdout or "")[:1024],
        "escalation": escalation,
        "prompt_len": prompt_len,
        "attempt": attempt,
    }
    with (log_dir / "claude_cli_failures.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
```

호출 위치: `call_claude` 내 `if proc.returncode != 0:` 직후 (every fail logs, retry 포함).

- [ ] **Step 4: Run tests — all PASS**

- [ ] **Step 5: Update .gitignore**

Append to `.gitignore`:
```
data/log/claude_cli_failures.jsonl
```

- [ ] **Step 6: Commit**
```bash
git add src/themek/config.py src/themek/llm/claude_cli.py tests/test_claude_cli.py .gitignore
git commit -m "feat(llm): capture claude CLI failures to jsonl for pattern analysis (4-D)"
```

### Task 4-D Success Gate (deterministic, mock-based)

| # | 검증 | Expected (정확치) |
|---|------|-----------------|
| 4D.1 | `uv run pytest tests/test_claude_cli.py::test_call_claude_logs_failure_to_jsonl -v` | 1 PASS. jsonl 파일 존재, 1줄, parse 가능, `returncode==1`, `stderr=="some error"`, `escalation=="regex"`, timestamp 키 존재 |
| 4D.2 | `uv run pytest tests/test_claude_cli.py::test_call_claude_does_not_log_on_success -v` | 1 PASS. jsonl 파일 미존재 |
| 4D.3 | `Settings().themek_log_dir` | `"data/log"` |
| 4D.4 | `grep -c "claude_cli_failures.jsonl" .gitignore` | ≥ **1** |
| 4D.5 | `grep -c "_log_failure" src/themek/llm/claude_cli.py` | ≥ **2** (정의 + 호출) |

---

**Task 4 통합 회귀 + 운영 smoke**

- [ ] **(a)** `uv run pytest tests/test_claude_cli.py tests/test_backfill.py -v` → 0 FAIL
- [ ] **(b)** 운영 smoke (선택, 실 API): 사조대림 1건 직접 처리 후 jsonl 로그 확인
  ```bash
  set -a && source .env && set +a && uv run python -c "
  from themek.cli import _dart_client_and_cache, _stub_extractor_from_env
  from themek.db.engine import make_engine, make_session_factory
  from themek.db.models import BackfillTarget
  from themek.dart.backfill import run_one_target
  from themek.dart.rate_budget import RateBudget
  from themek.config import get_settings
  from sqlalchemy import select
  s = get_settings()
  client, cache = _dart_client_and_cache()
  S = make_session_factory(make_engine())
  with S() as sess:
      t = sess.scalar(select(BackfillTarget).where(BackfillTarget.status=='pending').limit(1))
      r = run_one_target(target=t, session=sess, client=client, cache=cache,
                         rate_budget=RateBudget(daily_cap=38000, state_file=s.dart_cache_dir/'budget_state.json'),
                         extractor=_stub_extractor_from_env())
      print(r.status)
  "
  ```

### Task 4 종합 Success Gate

**Task 4 PASS = 4-A, 4-B, 4-C, 4-D 모든 sub-gate 통과 + 위 통합 회귀 (a) PASS.**

---

## Success Gate (deterministic)

본 plan 전체 PASS 조건. 각 Task의 per-task Success Gate를 합집합으로 만족해야 한다.

| # | 검증 | Expected |
|---|------|---------|
| G1 | Task 1 Success Gate (1.1~1.7) | 7건 모두 PASS |
| G2 | Task 2 Success Gate (2.1~2.8) | 8건 모두 PASS |
| G3 | Task 4-A Success Gate (4A.1~4A.4) | 4건 모두 PASS |
| G4 | Task 4-B Success Gate (4B.1~4B.4) | 4건 모두 PASS |
| G5 | Task 4-C Success Gate (4C.1~4C.6) | 6건 모두 PASS |
| G6 | Task 4-D Success Gate (4D.1~4D.5) | 5건 모두 PASS |
| G7 | `uv run pytest tests/test_claude_cli.py tests/test_llm_schemas.py tests/test_backfill.py -v` | exit 0, 0 FAIL, 0 ERROR (대상 단위 회귀) |
| G8 | `uv run pytest -v` 전체 | exit 0, **0 FAIL, 0 ERROR** |
| G9 | (manual, optional) Task 3 reset + retry 3건 → 모두 done | done 3 / failed 0 |

**G1-G8**: 자동, mock 기반. **G9**: 실 DART API + LLM 호출 (~$1, ~5분).

**WHY 단순 합산이 아닌가**: 각 Task의 sub-gate가 코드 단위 정합성을 보장하고, G7-G8이 cross-file 회귀를 추가 보호. 모든 Task의 sub-gate가 PASS인데 G7/G8이 FAIL이면 → 다른 file에 collateral 영향 의심.

---

## 후속 작업 (out of scope)

- Prompt engineering 강화 — LLM 응답에 "decimal only" 명시
- LLM API 직접 호출 (CLI wrapper 제거) — latency + 안정성 개선
- chunked input + 병렬 처리 — full_text 600s timeout도 부족한 케이스 대비
- BackfillTarget 자동 retry — N회 실패 시 retry 또는 alarm
- Failed targets dashboard — `themek dart backfill status --failed` 추가
