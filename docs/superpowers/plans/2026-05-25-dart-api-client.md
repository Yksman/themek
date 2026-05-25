# DART API Client Implementation Plan (Plan #3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DART OpenAPI(`corpCode.xml` / `list.json` / `document.xml`)를 직접 호출해서 (ticker, period) → 사업보고서 본문 HTML을 자동 다운로드 → 캐시 → 기존 `ingest_business_report` 파이프라인에 연결한다. 수동 fixture를 손으로 만들 필요 없이 모든 상장 종목으로 확장 가능한 backbone.

**Architecture:** 신규 `src/themek/dart/{client,cache,corp_lookup,fetch}.py` 4파일 + `cli.py`에 `dart sync-corp` / `dart fetch` / `dart ingest` 3 서브커맨드 추가. HTTP는 `httpx` sync 클라이언트, 테스트는 **vcrpy cassette playback** (실 API 0회 hit, T0 정찰 단계에서만 실 호출).

**Tech Stack:** Python 3.12+, `httpx`, `vcrpy` (dev), stdlib `zipfile`, `lxml` (기존), typer, Pydantic Settings.

**Spec:** `docs/superpowers/specs/2026-05-25-dart-api-client-design.md` (v1.1, commit 9585a3b)

---

## Prerequisites

- Plan #1 (Walking Skeleton) + Plan #6 (Eval Harness) 완료
- `.env`에 `DART_API_KEY=...` 등록 완료 (사용자가 발급)
- vcrpy, httpx dev 의존성 추가 (T1 step 1에서 수행)
- `claude` CLI 로그인 상태 (T14 smoke run에서만 필요)

## Scope (in / out)

**In:**
- `src/themek/dart/{client,cache,corp_lookup,fetch}.py` 4파일
- `src/themek/cli.py` 수정: `dart` 서브앱 + 3 명령
- `src/themek/config.py` 수정: `dart_api_key`, `dart_cache_dir` 추가
- DB model 변경 가능성 (T0에서 `Corporation.dart_corp_code` 컬럼 확인 후 D5 결정)
- vcrpy cassette: `tests/fixtures/dart_cassettes/` 3건 (T0에서 저장, git tracked)
- ~22개 신규 테스트 + 기존 78개 회귀 통과
- 실 LLM smoke run 3종목(005930·005380·277810) + baseline 문서

**Out (Plan #5+ 위임):** 전 종목 backfill / 반기·분기 보고서 / 공시(Disclosure) ingestion / 첨부 PDF 처리 / cassette TTL refresh 정책 / 동시 N개 fetch / cron 통합.

## File Structure

```
themek/
├── src/themek/
│   ├── config.py                # 수정: dart_api_key, dart_cache_dir
│   ├── cli.py                   # 수정: dart_app + 3 명령
│   └── dart/
│       ├── __init__.py
│       ├── parser.py            # 기존 (변경 없음)
│       ├── client.py            # NEW
│       ├── cache.py             # NEW
│       ├── corp_lookup.py       # NEW
│       └── fetch.py             # NEW
├── tests/
│   ├── fixtures/
│   │   └── dart_cassettes/
│   │       ├── corp_code_zip_success.yaml          # T0
│   │       ├── list_json_samsung_2023.yaml         # T0
│   │       └── document_zip_samsung_2023.yaml      # T0
│   ├── test_dart_client.py
│   ├── test_dart_cache.py
│   ├── test_dart_corp_lookup.py
│   ├── test_dart_fetch.py
│   └── test_cli_dart.py
├── data/
│   └── dart/                    # gitignored
│       ├── corp_master.json
│       └── raw/
│           └── <rcept_no>/
│               ├── document.zip
│               └── business.html
├── docs/
│   ├── dart-api-recon-notes.md       # T0 산출물
│   └── dart-fetch-smoke-run-notes.md # T14 산출물
└── .gitignore                   # 수정: /data/dart/
```

---

## Task 0: 실 API 정찰 + cassette 저장 (특수 task — TDD 아님)

**Files:**
- Create: `tests/fixtures/dart_cassettes/{corp_code_zip,list_json_samsung_2023,document_zip_samsung_2023}.yaml`
- Create: `docs/dart-api-recon-notes.md`
- Read-only: `src/themek/db/models.py` (D5 확정)

**Goal:** spec의 zip + HTML 휴리스틱 가정이 실제 응답에 맞는지 1회 검증 + cassette 저장. 이 task가 실패(zip 구조가 예상과 다름)하면 spec 수정 후 plan을 다시 조정해야 한다.

- [ ] **Step 1: 의존성 추가**

```bash
uv add httpx
uv add --dev vcrpy
```

- [ ] **Step 2: 임시 정찰 스크립트 작성 + 실 API 호출**

`scripts/recon_dart.py` (이 task 전용 — T0 commit에는 포함하지 않고 .gitignore 추가 또는 commit 시 제거):

```python
"""DART OpenAPI 응답 구조 정찰 — 1회용."""
import os
import httpx
from pathlib import Path

key = os.environ["DART_API_KEY"]

# 1. corpCode.xml zip
r = httpx.get(f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={key}", timeout=60)
print(f"corpCode: status={r.status_code} bytes={len(r.content)} content-type={r.headers.get('content-type')}")
Path("/tmp/recon_corpcode.zip").write_bytes(r.content)

# 2. list.json (삼성전자 = 00126380, 2023)
r = httpx.get("https://opendart.fss.or.kr/api/list.json", params={
    "crtfc_key": key, "corp_code": "00126380",
    "bgn_de": "20240101", "end_de": "20240701",
    "pblntf_ty": "A", "page_count": 100,
}, timeout=30)
print(f"list.json: status={r.status_code}")
print(r.text[:2000])

# rcept_no 추출 (응답 내 사업보고서)
import json
data = r.json()
samsung_2023 = [d for d in data["list"] if "사업보고서" in d["report_nm"]]
print("samsung 사업보고서 후보:")
for d in samsung_2023:
    print(f"  {d['rcept_no']}  {d['report_nm']}  {d['rcept_dt']}")
rcept_no = samsung_2023[0]["rcept_no"]

# 3. document.xml zip
r = httpx.get("https://opendart.fss.or.kr/api/document.xml", params={
    "crtfc_key": key, "rcept_no": rcept_no,
}, timeout=120)
print(f"document.xml: status={r.status_code} bytes={len(r.content)}")
Path("/tmp/recon_document.zip").write_bytes(r.content)

# zip 내부 파일 목록
import zipfile
with zipfile.ZipFile("/tmp/recon_document.zip") as z:
    print(f"zip files ({len(z.namelist())}개):")
    for n in z.namelist():
        info = z.getinfo(n)
        print(f"  {n}  ({info.file_size} bytes)")
```

```bash
uv run python scripts/recon_dart.py 2>&1 | tee /tmp/recon_output.txt
```

Expected:
- corpCode zip ~3MB
- list.json에 사업보고서 1건 이상 (rcept_no=20240314000123 예상)
- document.xml zip ~수십MB, 내부에 다수 HTML

- [ ] **Step 3: zip 내부 HTML 구조 분석**

```bash
# zip의 첫 5개 HTML 파일을 inspect
uv run python -c "
import zipfile
with zipfile.ZipFile('/tmp/recon_document.zip') as z:
    htmls = [n for n in z.namelist() if n.endswith('.html')]
    print(f'HTML 파일 {len(htmls)}개:')
    for h in htmls[:10]:
        print(f'  {h}')
    # 사업의 내용 후보 찾기
    for h in htmls:
        if '사업' in h or 'business' in h.lower():
            print(f'  ★ {h}')
"
```

D1 휴리스틱 검증:
1. 파일명에 "사업의 내용" 패턴이 있는가?
2. 없으면 정렬 시 2번째 HTML이 본문인가?
3. base64 인코딩 등 비표준 케이스가 있는가?

- [ ] **Step 4: vcrpy cassette 저장 — Python 코드로 응답 캐시**

`scripts/recon_dart.py`를 cassette mode로 1회 더 실행 (응답을 yaml로 저장):

```python
import vcr

my_vcr = vcr.VCR(
    cassette_library_dir="tests/fixtures/dart_cassettes",
    filter_query_parameters=["crtfc_key"],
    record_mode="all",  # 실 호출하면서 저장
)

# corp_code zip
with my_vcr.use_cassette("corp_code_zip_success.yaml"):
    httpx.get(f"https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key={key}", timeout=60)

with my_vcr.use_cassette("list_json_samsung_2023.yaml"):
    httpx.get("https://opendart.fss.or.kr/api/list.json", params={...})

with my_vcr.use_cassette("document_zip_samsung_2023.yaml"):
    httpx.get("https://opendart.fss.or.kr/api/document.xml", params={...})
```

⚠ vcrpy 기본 transport는 `requests`/`urllib3`/`http.client` 만 patch함. **httpx는 별도 어댑터 필요** → vcrpy 대신 `pytest-recording`(httpx 지원) 또는 `respx`를 사용하는 것이 안전.

**Decision (D2 정정 가능):** T0 시점에 vcrpy + httpx 호환성 확인. 호환 안 되면 대안 채택:
- 옵션 1: `vcrpy-httpx` (커뮤니티 패키지)
- 옵션 2: 자체 cassette — 응답 bytes를 단순 `tests/fixtures/dart_responses/<name>.{json,zip}`로 저장 + `respx`로 재생 (가장 단순·안정)

T0 step 4 실행 시점에 호환 안 되면 **옵션 2로 전환** + spec D2를 commit으로 정정.

- [ ] **Step 5: `Corporation.dart_corp_code` 컬럼 존재 확인 (D5 확정)**

```bash
grep -n "dart_corp_code\|corp_code" src/themek/db/models.py
```

존재하면 D5=noop. 없으면 plan에 alembic migration task 추가 commit.

- [ ] **Step 6: `docs/dart-api-recon-notes.md` 작성**

```markdown
# DART API Recon — 2026-05-25

## corpCode.xml
- bytes: ~XMB
- format: zip → CORPCODE.xml
- row count: ~XX,XXX 기업
- 컬럼: corp_code(8) / corp_name / stock_code(6 or "") / modify_date

## list.json (corp_code=00126380, bgn_de=20240101, end_de=20240701)
- 사업보고서 후보 rcept_no: ...
- report_nm 패턴: "사업보고서 (2023.12)" 등
- 응답 status="000" 정상

## document.xml zip (rcept_no=20240314000123)
- bytes: ~XMB
- 내부 HTML 파일 수: ~N
- "사업의 내용" 파일 후보: <파일명>
- 휴리스틱 검증 결과:
  - 옵션 A (파일명 패턴 "사업의 내용"): 성공/실패
  - 옵션 B (정렬 후 2번째 .html): 성공/실패
  - base64 인코딩 케이스: 있음/없음

## D5 (dart_corp_code 컬럼) 확정
- 결과: 있음 / 없음
- 후속: noop / alembic migration 추가

## D2 정정 여부
- vcrpy + httpx 호환: OK / FAIL
- FAIL 시 채택 대안: respx + 응답 fixture
```

- [ ] **Step 7: cassette + recon notes 커밋, recon 스크립트 제거**

```bash
# scripts/recon_dart.py를 .gitignore에 추가 또는 삭제
rm -f scripts/recon_dart.py
git add tests/fixtures/dart_cassettes/ docs/dart-api-recon-notes.md
git commit -m "feat(dart): T0 실 API 정찰 + cassette 3건 저장 (Plan #3 T0)"
```

---

## Task 1: config.py + 의존성 확장

**Files:**
- Modify: `src/themek/config.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_config.py` (없으면 새로):

```python
import os
import pytest
from themek.config import get_settings


def test_settings_loads_dart_api_key(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "test-key-xyz")
    monkeypatch.setenv("POSTGRES_DSN", "sqlite:///:memory:")
    s = get_settings()
    assert s.dart_api_key == "test-key-xyz"


def test_settings_dart_cache_dir_default():
    s = get_settings()
    assert str(s.dart_cache_dir).endswith("data/dart")
```

- [ ] **Step 2: `config.py` 확장**

```python
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_dsn: str = Field(...)
    log_level: str = Field(default="INFO")
    claude_cli_bin: str = Field(default="claude")
    claude_cli_timeout_sec: int = Field(default=120)
    dart_api_key: str = Field(default="")
    dart_cache_dir: Path = Field(default=Path("data/dart"))
    dart_rate_per_min: int = Field(default=60)
    dart_http_timeout_sec: int = Field(default=60)
```

- [ ] **Step 3: `.env.example` 갱신**

```
DART_API_KEY=
DART_CACHE_DIR=data/dart
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_config.py -v
git add pyproject.toml uv.lock src/themek/config.py tests/test_config.py .env.example
git commit -m "feat(config): add dart_api_key + dart_cache_dir settings (Plan #3 T1)"
```

---

## Task 2: `dart/client.py` — DartClient + 3 메서드 (cassette 기반)

**Files:**
- Create: `src/themek/dart/client.py`
- Create: `tests/test_dart_client.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from pathlib import Path
import pytest
from themek.dart.client import DartClient, DartAuthError, DartApiError


CASSETTES = Path(__file__).parent / "fixtures" / "dart_cassettes"


def test_client_init_requires_api_key():
    with pytest.raises(DartAuthError):
        DartClient(api_key="")


def test_fetch_corp_code_zip_returns_bytes():
    # cassette playback (응답을 미리 저장)
    client = DartClient(api_key="redacted", base_url="https://opendart.fss.or.kr/api")
    with cassette_playback(CASSETTES / "corp_code_zip_success.yaml"):
        data = client.fetch_corp_code_zip()
    assert isinstance(data, bytes)
    assert data[:2] == b"PK"  # zip magic
    assert len(data) > 1_000_000  # >1MB


def test_list_periodic_reports_returns_list():
    client = DartClient(api_key="redacted")
    with cassette_playback(CASSETTES / "list_json_samsung_2023.yaml"):
        result = client.list_periodic_reports(
            corp_code="00126380",
            bgn_de="20240101",
            end_de="20240701",
        )
    assert result["status"] == "000"
    assert any("사업보고서" in r["report_nm"] for r in result["list"])


def test_fetch_document_zip_returns_bytes():
    client = DartClient(api_key="redacted")
    with cassette_playback(CASSETTES / "document_zip_samsung_2023.yaml"):
        data = client.fetch_document_zip(rcept_no="20240314000123")
    assert data[:2] == b"PK"
```

(`cassette_playback`는 T0에서 결정한 라이브러리 — vcrpy 호환 OK면 vcr.VCR, 아니면 respx 어댑터)

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/test_dart_client.py -v
```

Expected: ImportError on `DartClient`.

- [ ] **Step 3: `client.py` 구현**

```python
"""DART OpenAPI HTTP client."""
from __future__ import annotations
import httpx


class DartApiError(RuntimeError):
    pass


class DartAuthError(DartApiError):
    pass


class DartRateLimitError(DartApiError):
    pass


class DartClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://opendart.fss.or.kr/api",
        timeout_sec: int = 60,
    ):
        if not api_key:
            raise DartAuthError("DART_API_KEY 미설정")
        self._key = api_key
        self._base = base_url
        self._timeout = timeout_sec
        self._client = httpx.Client(timeout=timeout_sec)

    def fetch_corp_code_zip(self) -> bytes:
        r = self._client.get(f"{self._base}/corpCode.xml", params={"crtfc_key": self._key})
        self._raise_on_error(r)
        return r.content

    def list_periodic_reports(self, *, corp_code: str, bgn_de: str, end_de: str) -> dict:
        r = self._client.get(f"{self._base}/list.json", params={
            "crtfc_key": self._key, "corp_code": corp_code,
            "bgn_de": bgn_de, "end_de": end_de,
            "pblntf_ty": "A", "page_count": 100,
        })
        self._raise_on_error(r)
        payload = r.json()
        if payload.get("status") not in ("000", "013"):  # 013 = 데이터 없음
            raise DartApiError(f"list.json status={payload.get('status')} message={payload.get('message')}")
        return payload

    def fetch_document_zip(self, *, rcept_no: str) -> bytes:
        r = self._client.get(f"{self._base}/document.xml", params={
            "crtfc_key": self._key, "rcept_no": rcept_no,
        })
        self._raise_on_error(r)
        return r.content

    def _raise_on_error(self, r: httpx.Response) -> None:
        if r.status_code == 401 or r.status_code == 403:
            raise DartAuthError(f"HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code == 429:
            raise DartRateLimitError("rate limit")
        if r.status_code >= 500:
            raise DartApiError(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise DartApiError(f"HTTP {r.status_code}: {r.text[:200]}")
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_dart_client.py -v
git add src/themek/dart/client.py src/themek/dart/__init__.py tests/test_dart_client.py
git commit -m "feat(dart): DartClient with corpCode/list/document fetch (Plan #3 T2)"
```

---

## Task 3: `client.py` 에러 분기 (rate / auth / 5xx / timeout)

**Files:**
- Modify: `tests/test_dart_client.py`

- [ ] **Step 1: 실패 테스트 추가** — monkeypatch로 httpx.Client.get을 모킹

```python
def test_client_raises_auth_error_on_401(monkeypatch):
    def fake_get(self, url, **kwargs):
        return _fake_response(status_code=401, text="invalid key")
    monkeypatch.setattr(httpx.Client, "get", fake_get)
    client = DartClient(api_key="bad")
    with pytest.raises(DartAuthError):
        client.fetch_corp_code_zip()


def test_client_raises_rate_limit_on_429(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", lambda *a, **k: _fake_response(429, "rate"))
    client = DartClient(api_key="x")
    with pytest.raises(DartRateLimitError):
        client.fetch_corp_code_zip()


def test_client_raises_api_error_on_5xx(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", lambda *a, **k: _fake_response(503, "down"))
    client = DartClient(api_key="x")
    with pytest.raises(DartApiError):
        client.fetch_corp_code_zip()


def test_list_json_raises_on_non_zero_status(monkeypatch):
    monkeypatch.setattr(httpx.Client, "get", lambda *a, **k: _fake_response(
        200, json_body={"status": "020", "message": "권한 없음"},
    ))
    client = DartClient(api_key="x")
    with pytest.raises(DartApiError):
        client.list_periodic_reports(corp_code="x", bgn_de="x", end_de="x")
```

`_fake_response` 헬퍼는 같은 파일 상단에:

```python
def _fake_response(status_code, text="", json_body=None):
    r = httpx.Response(status_code=status_code, text=text or "")
    if json_body is not None:
        r = httpx.Response(status_code=status_code, json=json_body)
    return r
```

- [ ] **Step 2: 통과 확인** (현재 구현으로 통과해야 함 — Step 3 없음 except 통과 확인)

- [ ] **Step 3: 커밋**

```bash
uv run pytest tests/test_dart_client.py -v
git add tests/test_dart_client.py
git commit -m "test(dart): DartClient error branches — auth/rate/5xx/api (Plan #3 T3)"
```

---

## Task 4: `dart/cache.py` — 디스크 캐시

**Files:**
- Create: `src/themek/dart/cache.py`
- Create: `tests/test_dart_cache.py`

- [ ] **Step 1: 실패 테스트**

```python
import json
from pathlib import Path
import pytest
from themek.dart.cache import DartCache


def test_cache_init_creates_subdirs(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    assert (tmp_path / "dart" / "raw").is_dir()


def test_cache_save_and_load_corp_master(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    payload = [{"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930"}]
    cache.save_corp_master(payload)
    assert cache.load_corp_master() == payload


def test_cache_load_corp_master_returns_none_when_missing(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    assert cache.load_corp_master() is None


def test_cache_save_and_lookup_business_html(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    rcept = "20240314000123"
    assert not cache.has_business_html(rcept)
    cache.save_raw_zip(rcept, b"PK\x03\x04...")
    cache.save_business_html(rcept, b"<html><body>x</body></html>")
    assert cache.has_business_html(rcept)
    p = cache.get_business_html_path(rcept)
    assert p.exists()
    assert p.read_bytes().startswith(b"<html>")
```

- [ ] **Step 2: 구현 추가**

```python
"""DART 응답 디스크 캐시."""
from __future__ import annotations
import json
from pathlib import Path


class DartCache:
    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self.raw_dir = self.base_dir / "raw"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._corp_master = self.base_dir / "corp_master.json"

    def save_corp_master(self, payload: list[dict]) -> Path:
        self._corp_master.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return self._corp_master

    def load_corp_master(self) -> list[dict] | None:
        if not self._corp_master.exists():
            return None
        return json.loads(self._corp_master.read_text(encoding="utf-8"))

    def _rcept_dir(self, rcept_no: str) -> Path:
        d = self.raw_dir / rcept_no
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_raw_zip(self, rcept_no: str, zip_bytes: bytes) -> Path:
        p = self._rcept_dir(rcept_no) / "document.zip"
        p.write_bytes(zip_bytes)
        return p

    def save_business_html(self, rcept_no: str, html_bytes: bytes) -> Path:
        p = self._rcept_dir(rcept_no) / "business.html"
        p.write_bytes(html_bytes)
        return p

    def has_business_html(self, rcept_no: str) -> bool:
        return (self.raw_dir / rcept_no / "business.html").exists()

    def get_business_html_path(self, rcept_no: str) -> Path:
        return self.raw_dir / rcept_no / "business.html"
```

- [ ] **Step 3: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_dart_cache.py -v
git add src/themek/dart/cache.py tests/test_dart_cache.py
git commit -m "feat(dart): DartCache disk-based response cache (Plan #3 T4)"
```

---

## Task 5: `dart/corp_lookup.py` — corp_master sync + ticker 조회

**Files:**
- Create: `src/themek/dart/corp_lookup.py`
- Create: `tests/test_dart_corp_lookup.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
import zipfile
from io import BytesIO
from pathlib import Path
import pytest
from themek.dart.cache import DartCache
from themek.dart.corp_lookup import (
    sync_corp_master, lookup_corp_code, parse_corp_code_zip,
)


def _make_corp_zip(rows: list[tuple[str, str, str]]) -> bytes:
    """rows: [(corp_code, corp_name, stock_code), ...] → corp_code.zip"""
    xml = "<?xml version='1.0' encoding='UTF-8'?>\n<result>"
    for c, n, s in rows:
        xml += f"<list><corp_code>{c}</corp_code><corp_name>{n}</corp_name>"
        xml += f"<stock_code>{s}</stock_code><modify_date>20240101</modify_date></list>"
    xml += "</result>"
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("CORPCODE.xml", xml.encode("utf-8"))
    return buf.getvalue()


def test_parse_corp_code_zip_extracts_rows():
    zip_bytes = _make_corp_zip([
        ("00126380", "삼성전자", "005930"),
        ("00164742", "현대자동차", "005380"),
        ("01234567", "비상장A", ""),
    ])
    rows = parse_corp_code_zip(zip_bytes)
    assert len(rows) == 3
    assert rows[0]["corp_code"] == "00126380"
    assert rows[0]["corp_name"] == "삼성전자"
    assert rows[0]["stock_code"] == "005930"


def test_sync_corp_master_saves_to_cache(tmp_path, monkeypatch):
    cache = DartCache(base_dir=tmp_path / "dart")
    zip_bytes = _make_corp_zip([("00126380", "삼성전자", "005930")])

    class FakeClient:
        def fetch_corp_code_zip(self): return zip_bytes

    n = sync_corp_master(FakeClient(), cache)
    assert n == 1
    assert cache.load_corp_master()[0]["corp_code"] == "00126380"


def test_lookup_corp_code_hit(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    cache.save_corp_master([
        {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930"},
    ])
    assert lookup_corp_code(cache, ticker="005930") == "00126380"


def test_lookup_corp_code_miss(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    cache.save_corp_master([
        {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930"},
    ])
    with pytest.raises(LookupError):
        lookup_corp_code(cache, ticker="999999")


def test_lookup_corp_code_no_master_raises(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    with pytest.raises(LookupError, match="sync-corp"):
        lookup_corp_code(cache, ticker="005930")
```

- [ ] **Step 2: 구현**

```python
"""DART corp_code 마스터 sync + ticker 조회."""
from __future__ import annotations
import zipfile
from io import BytesIO
from lxml import etree
from themek.dart.cache import DartCache


def parse_corp_code_zip(zip_bytes: bytes) -> list[dict]:
    with zipfile.ZipFile(BytesIO(zip_bytes)) as z:
        xml_bytes = z.read("CORPCODE.xml")
    root = etree.fromstring(xml_bytes)
    rows = []
    for item in root.findall("list"):
        rows.append({
            "corp_code": item.findtext("corp_code", "").strip(),
            "corp_name": item.findtext("corp_name", "").strip(),
            "stock_code": item.findtext("stock_code", "").strip(),
            "modify_date": item.findtext("modify_date", "").strip(),
        })
    return rows


def sync_corp_master(client, cache: DartCache) -> int:
    zip_bytes = client.fetch_corp_code_zip()
    rows = parse_corp_code_zip(zip_bytes)
    cache.save_corp_master(rows)
    return len(rows)


def lookup_corp_code(cache: DartCache, *, ticker: str) -> str:
    rows = cache.load_corp_master()
    if rows is None:
        raise LookupError(
            "corp_master 없음. `themek dart sync-corp` 먼저 실행하세요."
        )
    for r in rows:
        if r.get("stock_code") == ticker:
            return r["corp_code"]
    raise LookupError(f"ticker={ticker} corp_master에 없음")
```

- [ ] **Step 3: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_dart_corp_lookup.py -v
git add src/themek/dart/corp_lookup.py tests/test_dart_corp_lookup.py
git commit -m "feat(dart): corp_master sync + ticker lookup (Plan #3 T5)"
```

---

## Task 6: `fetch.extract_business_html_from_zip` — 휴리스틱 HTML 추출

**Files:**
- Create: `src/themek/dart/fetch.py`
- Create: `tests/test_dart_fetch.py`

T0의 정찰 결과로 실제 zip 구조를 알게 된 상태. 휴리스틱을 그에 맞춰 정의.

- [ ] **Step 1: 실패 테스트**

```python
import zipfile
from io import BytesIO
import pytest
from themek.dart.fetch import (
    extract_business_html_from_zip, BusinessReportFetchError,
)


def _make_zip(files: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_extract_picks_filename_with_사업의내용():
    zip_bytes = _make_zip({
        "20240314000123_0_표지.html": b"<html>표지</html>",
        "20240314000123_1_II_사업의내용.html": b"<html>사업 본문</html>",
        "20240314000123_2_재무.html": b"<html>재무</html>",
    })
    html = extract_business_html_from_zip(zip_bytes)
    assert html == b"<html>사업 본문</html>"


def test_extract_falls_back_to_second_html():
    """파일명 패턴 매치 실패 시 정렬 후 2번째 .html."""
    zip_bytes = _make_zip({
        "00_cover.html": b"<html>cover</html>",
        "01_body.html": b"<html>body</html>",
        "02_extra.html": b"<html>extra</html>",
    })
    html = extract_business_html_from_zip(zip_bytes)
    assert html == b"<html>body</html>"


def test_extract_raises_when_no_html():
    zip_bytes = _make_zip({"data.xml": b"<x/>"})
    with pytest.raises(BusinessReportFetchError):
        extract_business_html_from_zip(zip_bytes)
```

(T0 정찰 결과 실 구조에 따라 추가 테스트 1-2건 더 추가 가능)

- [ ] **Step 2: 구현**

```python
"""DART 보고서 본문 fetch 오케스트레이션."""
from __future__ import annotations
import zipfile
from io import BytesIO


class BusinessReportFetchError(RuntimeError):
    pass


_BUSINESS_PATTERNS = ("사업의내용", "사업의 내용", "II_사업의내용")


def extract_business_html_from_zip(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(BytesIO(zip_bytes)) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith(".html"))
        if not names:
            raise BusinessReportFetchError("zip에 HTML 파일 없음")

        # 1차: 파일명에 사업의 내용 패턴 포함
        for n in names:
            if any(p in n for p in _BUSINESS_PATTERNS):
                return z.read(n)

        # 2차 fallback: 정렬 후 2번째 (1번째는 표지·요약 가정)
        if len(names) >= 2:
            return z.read(names[1])

        raise BusinessReportFetchError(
            f"HTML {len(names)}개 — 사업의 내용 후보를 식별 못 함"
        )
```

- [ ] **Step 3: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_dart_fetch.py -v -k extract_
git add src/themek/dart/fetch.py tests/test_dart_fetch.py
git commit -m "feat(dart): extract_business_html_from_zip heuristic (Plan #3 T6)"
```

---

## Task 7: `fetch.find_business_report_rcept_no` — list.json 필터

**Files:**
- Modify: `src/themek/dart/fetch.py`
- Modify: `tests/test_dart_fetch.py`

- [ ] **Step 1: 실패 테스트**

```python
from themek.dart.fetch import find_business_report_rcept_no


class _FakeClient:
    def __init__(self, list_payload): self.payload = list_payload
    def list_periodic_reports(self, **kwargs): return self.payload


def test_find_rcept_no_picks_matching_year():
    payload = {"status": "000", "list": [
        {"rcept_no": "20240314000123", "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240314"},
        {"rcept_no": "20230315000456", "report_nm": "사업보고서 (2022.12)", "rcept_dt": "20230315"},
    ]}
    rcept = find_business_report_rcept_no(_FakeClient(payload), corp_code="00126380", year=2023)
    assert rcept == "20240314000123"


def test_find_rcept_no_returns_latest_when_multiple():
    """같은 연도에 정정보고서가 여러 건이면 가장 최근 rcept_dt 선택."""
    payload = {"status": "000", "list": [
        {"rcept_no": "20240501000001", "report_nm": "사업보고서 (2023.12) (정정)", "rcept_dt": "20240501"},
        {"rcept_no": "20240314000123", "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240314"},
    ]}
    rcept = find_business_report_rcept_no(_FakeClient(payload), corp_code="00126380", year=2023)
    assert rcept == "20240501000001"


def test_find_rcept_no_raises_when_no_match():
    payload = {"status": "000", "list": [
        {"rcept_no": "20230315000456", "report_nm": "사업보고서 (2022.12)", "rcept_dt": "20230315"},
    ]}
    with pytest.raises(BusinessReportFetchError, match="사업보고서 없음"):
        find_business_report_rcept_no(_FakeClient(payload), corp_code="00126380", year=2023)
```

- [ ] **Step 2: 구현**

```python
def find_business_report_rcept_no(client, *, corp_code: str, year: int) -> str:
    """report_nm이 '사업보고서' + 명시된 연도 매치, 가장 최근 rcept_dt."""
    bgn_de = f"{year+1}0101"
    end_de = f"{year+1}0701"
    payload = client.list_periodic_reports(
        corp_code=corp_code, bgn_de=bgn_de, end_de=end_de,
    )
    year_token = f"({year}.12)"
    candidates = [
        r for r in payload.get("list", [])
        if r["report_nm"].startswith("사업보고서") and year_token in r["report_nm"]
    ]
    if not candidates:
        raise BusinessReportFetchError(
            f"corp_code={corp_code} year={year} 사업보고서 없음 (DART)"
        )
    candidates.sort(key=lambda r: r["rcept_dt"], reverse=True)
    return candidates[0]["rcept_no"]
```

- [ ] **Step 3: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_dart_fetch.py -v -k find_
git add src/themek/dart/fetch.py tests/test_dart_fetch.py
git commit -m "feat(dart): find_business_report_rcept_no list.json filter (Plan #3 T7)"
```

---

## Task 8: `fetch.fetch_business_report_html` 오케스트레이션

**Files:**
- Modify: `src/themek/dart/fetch.py`
- Modify: `tests/test_dart_fetch.py`

- [ ] **Step 1: 실패 테스트** (cache hit/miss 양쪽)

```python
from themek.dart.fetch import fetch_business_report_html
from themek.dart.cache import DartCache


class _SpyClient:
    """호출 횟수 카운트 + 미리 정의된 응답."""
    def __init__(self, list_payload, doc_zip):
        self.list_payload = list_payload
        self.doc_zip = doc_zip
        self.list_calls = 0
        self.doc_calls = 0

    def list_periodic_reports(self, **kwargs):
        self.list_calls += 1
        return self.list_payload

    def fetch_document_zip(self, *, rcept_no):
        self.doc_calls += 1
        return self.doc_zip


def test_fetch_cache_miss_fetches_and_saves(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    doc_zip = _make_zip({"01_표지.html": b"<html>표지</html>", "02_사업의내용.html": b"<html>본문</html>"})
    client = _SpyClient(
        list_payload={"status": "000", "list": [
            {"rcept_no": "20240314000123", "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240314"},
        ]},
        doc_zip=doc_zip,
    )
    html_path, rcept_no = fetch_business_report_html(client, cache, ticker="005930", year=2023, corp_code="00126380")
    assert rcept_no == "20240314000123"
    assert html_path.read_bytes() == b"<html>본문</html>"
    assert client.list_calls == 1
    assert client.doc_calls == 1


def test_fetch_cache_hit_skips_api(tmp_path):
    cache = DartCache(base_dir=tmp_path / "dart")
    cache.save_business_html("20240314000123", b"<html>cached</html>")
    client = _SpyClient(
        list_payload={"status": "000", "list": [
            {"rcept_no": "20240314000123", "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240314"},
        ]},
        doc_zip=b"",
    )
    html_path, rcept_no = fetch_business_report_html(client, cache, ticker="005930", year=2023, corp_code="00126380")
    assert html_path.read_bytes() == b"<html>cached</html>"
    # list.json은 호출되지만 document.xml은 cache hit으로 skip
    assert client.doc_calls == 0
```

- [ ] **Step 2: 구현**

```python
from pathlib import Path
from themek.dart.cache import DartCache


def fetch_business_report_html(
    client, cache: DartCache, *, ticker: str, year: int, corp_code: str,
) -> tuple[Path, str]:
    rcept_no = find_business_report_rcept_no(client, corp_code=corp_code, year=year)
    if cache.has_business_html(rcept_no):
        return cache.get_business_html_path(rcept_no), rcept_no
    zip_bytes = client.fetch_document_zip(rcept_no=rcept_no)
    cache.save_raw_zip(rcept_no, zip_bytes)
    html_bytes = extract_business_html_from_zip(zip_bytes)
    path = cache.save_business_html(rcept_no, html_bytes)
    return path, rcept_no
```

- [ ] **Step 3: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_dart_fetch.py -v
git add src/themek/dart/fetch.py tests/test_dart_fetch.py
git commit -m "feat(dart): fetch_business_report_html orchestration (Plan #3 T8)"
```

---

## Task 9: CLI `themek dart sync-corp`

**Files:**
- Modify: `src/themek/cli.py`
- Create: `tests/test_cli_dart.py`

- [ ] **Step 1: 실패 테스트**

```python
from typer.testing import CliRunner
from themek.cli import app


runner = CliRunner()


def test_cli_dart_sync_corp_no_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("DART_API_KEY", "")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))
    result = runner.invoke(app, ["dart", "sync-corp"])
    assert result.exit_code != 0
    assert "DART_API_KEY" in (result.stdout + (result.stderr or ""))


def test_cli_dart_sync_corp_writes_master(monkeypatch, tmp_path):
    """fake client으로 호출 — 실 API 안 침."""
    monkeypatch.setenv("DART_API_KEY", "test")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))
    # cli.py에서 client factory를 주입 가능하게 (또는 monkeypatch DartClient.fetch_corp_code_zip)
    from themek.dart import client as client_mod
    monkeypatch.setattr(
        client_mod.DartClient, "fetch_corp_code_zip",
        lambda self: _make_corp_zip([("00126380", "삼성전자", "005930")]),
    )
    result = runner.invoke(app, ["dart", "sync-corp"])
    assert result.exit_code == 0, result.stdout
    assert "synced" in result.stdout
    assert (tmp_path / "dart" / "corp_master.json").exists()
```

- [ ] **Step 2: `cli.py`에 dart 서브앱 + sync-corp 추가**

```python
from themek.dart.client import DartClient, DartAuthError
from themek.dart.cache import DartCache
from themek.dart.corp_lookup import sync_corp_master, lookup_corp_code
from themek.dart.fetch import fetch_business_report_html, BusinessReportFetchError

dart_app = typer.Typer(help="DART OpenAPI 명령")
app.add_typer(dart_app, name="dart")


def _dart_client_and_cache() -> tuple[DartClient, DartCache]:
    s = get_settings()
    client = DartClient(api_key=s.dart_api_key, timeout_sec=s.dart_http_timeout_sec)
    cache = DartCache(base_dir=s.dart_cache_dir)
    return client, cache


@dart_app.command("sync-corp")
def dart_sync_corp_cmd():
    """corp_code 마스터를 DART에서 받아 캐시."""
    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    n = sync_corp_master(client, cache)
    typer.echo(f"synced {n} corporations to {cache._corp_master}")
```

- [ ] **Step 3: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_cli_dart.py -v -k sync_corp
git add src/themek/cli.py tests/test_cli_dart.py
git commit -m "feat(cli): themek dart sync-corp (Plan #3 T9)"
```

---

## Task 10: CLI `themek dart fetch` + `themek dart ingest`

**Files:**
- Modify: `src/themek/cli.py`
- Modify: `tests/test_cli_dart.py`

- [ ] **Step 1: 실패 테스트**

```python
def test_cli_dart_fetch_writes_html(monkeypatch, tmp_path):
    """fetch는 ingest 없이 HTML 캐시만."""
    monkeypatch.setenv("DART_API_KEY", "test")
    monkeypatch.setenv("DART_CACHE_DIR", str(tmp_path / "dart"))
    # 미리 corp_master 준비
    cache_dir = tmp_path / "dart"
    (cache_dir / "raw").mkdir(parents=True)
    (cache_dir / "corp_master.json").write_text(json.dumps([
        {"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930"},
    ]), encoding="utf-8")
    # client mocking
    from themek.dart import client as client_mod
    doc_zip = _make_zip({"01_표지.html": b"<html>표지</html>", "02_사업의내용.html": b"<html>본문</html>"})
    monkeypatch.setattr(
        client_mod.DartClient, "list_periodic_reports",
        lambda self, **kw: {"status": "000", "list": [
            {"rcept_no": "20240314000123", "report_nm": "사업보고서 (2023.12)", "rcept_dt": "20240314"},
        ]},
    )
    monkeypatch.setattr(
        client_mod.DartClient, "fetch_document_zip",
        lambda self, *, rcept_no: doc_zip,
    )

    result = runner.invoke(app, ["dart", "fetch", "--ticker", "005930", "--period", "2023"])
    assert result.exit_code == 0, result.stdout
    assert "business.html" in result.stdout
    assert (cache_dir / "raw" / "20240314000123" / "business.html").exists()


def test_cli_dart_ingest_runs_full_pipeline(monkeypatch, tmp_path):
    """dart ingest → DB에 BusinessReport 행이 생성됨 (stub LLM)."""
    # 사전: DB 격리 (conftest 처리), corp_master, stub LLM, DART client mocking
    # 자세한 fixture setup은 conftest 확장 또는 in-test
    ...
```

- [ ] **Step 2: cli.py에 fetch + ingest 명령 추가**

```python
@dart_app.command("fetch")
def dart_fetch_cmd(
    ticker: str = typer.Option(..., "--ticker"),
    period: str = typer.Option(..., "--period", help="연도 (예: 2023)"),
):
    """ticker+period → 사업보고서 HTML을 캐시에 저장 후 경로 출력."""
    try:
        client, cache = _dart_client_and_cache()
        corp_code = lookup_corp_code(cache, ticker=ticker)
    except (DartAuthError, LookupError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        html_path, rcept_no = fetch_business_report_html(
            client, cache, ticker=ticker, year=int(period), corp_code=corp_code,
        )
    except BusinessReportFetchError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=5)
    typer.echo(str(html_path))


@dart_app.command("ingest")
def dart_ingest_cmd(
    ticker: str = typer.Option(..., "--ticker"),
    period: str = typer.Option(..., "--period"),
    report_type: str = typer.Option("사업보고서", "--report-type"),
):
    """dart fetch + 기존 ingest_business_report 통합."""
    try:
        client, cache = _dart_client_and_cache()
        corp_code = lookup_corp_code(cache, ticker=ticker)
    except (DartAuthError, LookupError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        html_path, rcept_no = fetch_business_report_html(
            client, cache, ticker=ticker, year=int(period), corp_code=corp_code,
        )
    except BusinessReportFetchError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=5)

    html = html_path.read_text(encoding="utf-8")
    text = extract_business_content(html)
    extractor = _stub_extractor_from_env()  # 기존
    with _session() as s:
        kwargs = dict(
            dart_rcept_no=rcept_no,
            corporation_id=corp_code,
            report_type=report_type,
            period=period,
            filing_date=date.today(),  # TODO: rcept_dt에서 파싱
            raw_text_excerpt=text,
            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        )
        if extractor is not None:
            kwargs["extractor"] = extractor
        ingest_business_report(s, **kwargs)
        s.commit()
    typer.echo(f"Ingested report {rcept_no}")
```

- [ ] **Step 3: 통과 확인 + 커밋**

```bash
uv run pytest tests/test_cli_dart.py -v
git add src/themek/cli.py tests/test_cli_dart.py
git commit -m "feat(cli): themek dart fetch + ingest commands (Plan #3 T10)"
```

---

## Task 11: 전체 회귀 + .gitignore 갱신

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: `.gitignore`에 `/data/dart/` 추가**

```gitignore
# Plan #3: DART 캐시 (corp_master + raw zip + 추출 HTML)
/data/dart/

# 정찰 스크립트
/scripts/recon_dart.py
```

- [ ] **Step 2: 전체 pytest 회귀**

```bash
uv run pytest
```

Expected: 78 (기존) + 약 22 (Plan #3) = ~100 passed.

- [ ] **Step 3: 커밋**

```bash
git add .gitignore
git commit -m "chore: gitignore /data/dart and recon script (Plan #3 T11)"
```

---

## Task 12: 실 LLM smoke run — 3 종목 end-to-end

**Files:**
- Create: `docs/dart-fetch-smoke-run-notes.md`

- [ ] **Step 1: 사전 — corp_master sync (실 API 1회)**

```bash
uv run themek dart sync-corp
```

Expected: `synced ~92000 corporations to data/dart/corp_master.json`

- [ ] **Step 2: 3 종목 ingest (실 DART + 실 LLM)**

```bash
for ticker in 005930 005380 277810; do
  echo "=== ticker=$ticker ==="
  uv run themek dart ingest --ticker $ticker --period 2023
done | tee /tmp/dart_smoke.txt
```

Expected: 각 종목 "Ingested report ..." 출력. 두 번째 실행 시 DB idempotent (재 ingest 안 됨) + DART API 0 호출 (cache hit).

- [ ] **Step 3: 각 종목 E5 쿼리**

```bash
for ticker in 005930 005380 277810; do
  uv run themek query e5 --ticker $ticker
done | tee -a /tmp/dart_smoke.txt
```

- [ ] **Step 4: 삼성전자 eval e5 (기존 ground truth 재사용)**

```bash
uv run themek eval e5 \
  --html-file data/dart/raw/20240314000123/business.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json \
  >> /tmp/dart_smoke.txt
```

Expected: 4 metric 1.000 / MAE 0.00 (Plan #6 baseline과 동일 — fixture HTML이 실 DART 본문과 일치하는지 검증).

- [ ] **Step 5: baseline notes 작성**

`docs/dart-fetch-smoke-run-notes.md`:

```markdown
# DART API Fetch — Smoke Run Baseline

**실행일:** 2026-05-25
**대상:** 삼성전자(005930) / 현대차(005380) / 레인보우로보틱스(277810) 2023 사업보고서

## Commands & Output

(/tmp/dart_smoke.txt 내용 붙임)

## Observations

- sync-corp: ~XX,XXX 기업, X.X초
- 삼성전자: rcept_no=20240314000123, zip ~XMB, HTML 추출 정상
- 현대차: rcept_no=..., 휴리스틱 매치 결과
- 레인보우로보틱스: rcept_no=..., 휴리스틱 매치 결과
- 재실행 시 DART API 0회 호출, ingest는 idempotent (Plan #1 R4 unchanged)
- 기존 fixture HTML과 실 DART business.html 비교 — eval 점수가 baseline과 동일/다르면 분석

## Issues

- (휴리스틱 fallback이 작동한 종목 있는지 / 추출 HTML 본문 손실 있는지 / 등)
```

- [ ] **Step 6: 커밋**

```bash
git add docs/dart-fetch-smoke-run-notes.md
git commit -m "docs(dart): smoke run baseline 3 종목 end-to-end (Plan #3 T12)"
```

---

## Task 13: README + ingest 명령 deprecation 표시

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README "후속 Plan들" 섹션 갱신**

```markdown
- 🚧 **Plan #3 (다음)** → ~~**Plan #3**~~ ✅ 완료 (`docs/superpowers/plans/2026-05-25-dart-api-client.md`)
```

- [ ] **Step 2: Status 섹션에 진행 history 항목 추가**

```markdown
- Plan #3 (DART API client, 13 task TDD) ✅ 2026-05-XX — 종목 1 → N 확장 backbone
```

- [ ] **Step 3: Walking Skeleton 사용 예시 갱신 (수동 fixture → `dart ingest`로)**

기존 `themek ingest --rcept-no ... --html-file ...` 예시를 다음으로 대체:

```bash
# 1. corp_code 마스터 1회 sync (사전 요건)
uv run themek dart sync-corp

# 2. 종목+연도로 자동 ingest
uv run themek dart ingest --ticker 005930 --period 2023
```

- [ ] **Step 4: "다음 작업" 갱신**

```markdown
**다음 작업:** Plan #2 + #7 (social layer ontology + 텔레/블로그/팍스넷 ingestion), 또는 Plan #5 (다종목 backfill 전 자동화).
```

- [ ] **Step 5: 커밋**

```bash
git add README.md
git commit -m "docs: README Plan #3 완료 + dart ingest 사용 예시 (Plan #3 T13)"
```

---

## Acceptance Verification

```bash
# 1. 전체 테스트 (78 기존 + ~22 신규)
uv run pytest

# 2. 실 DART API end-to-end
uv run themek dart sync-corp
uv run themek dart ingest --ticker 005930 --period 2023
uv run themek query e5 --ticker 005930
uv run themek eval e5 \
  --html-file data/dart/raw/20240314000123/business.html \
  --period 2023 \
  --ground-truth data/eval/ground_truth/samsung_e5_2023.json

# 3. 동일 명령 재실행 — API 0회 호출 + DB idempotent
uv run themek dart ingest --ticker 005930 --period 2023

# 4. Spec Section 15의 8개 acceptance criteria 모두 충족
```
