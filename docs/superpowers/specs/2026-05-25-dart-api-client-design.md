---
title: DART API Client — Design Spec (Plan #3)
date: 2026-05-25
status: Draft v1 (사용자 검토 대기 — Open Decisions 섹션 합의 후 plan으로 분기)
scope: DART OpenAPI 기반 사업보고서 자동 fetch + 캐시 + ingest 통합. 다종목·다기간 backbone (전 종목 backfill은 Plan #5 위임).
---

# DART API Client — Design Spec (Plan #3)

## 1. Vision & Goal

themek의 모든 structural fact(매출 구성·고객·지역 노출 등)는 DART 사업보고서에서 추출된다. Walking Skeleton(Plan #1)은 fixture HTML 1건을 수동으로 넣어 동작을 증명했고, Eval Harness(Plan #6)는 이 1건에 대한 추출 품질을 측정한다. **그러나 fixture가 사람이 손으로 채우는 한 종목 수는 늘 수 없다.**

Plan #3은 이 병목을 푼다:

- DART OpenAPI를 호출해 corp_code ↔ ticker 매핑 sync
- 종목·기간을 입력하면 사업보고서 rcept_no 자동 탐색
- 사업보고서 본문(사업의 내용 section)을 fetch + 로컬 캐시
- 기존 `themek ingest` 파이프라인에 무손실 연결 → 종목 수 = O(1) → O(N)

### 1.1 측정 가능한 성공

- seed 3 종목(삼성전자/현대차/레인보우로보틱스) 2023년 사업보고서를 명령 1줄로 fetch → ingest → query E5 → eval e5까지 일관 동작
- 같은 명령을 두 번 실행해도 DART API 0회 호출 (캐시 hit + ingest idempotent)
- API key 미설정·rate limit·HTTP 5xx 시 명확한 에러 + retry 정책

### 1.2 측정 비대상

- 전 KOSPI/KOSDAQ 종목 backfill (Plan #5)
- 사업의 내용 외 section(재무제표·임원 현황 등) — Plan #1이 정의한 E5 본문만
- 공시(Disclosure) fetch — Plan #2 또는 별도 plan
- 첨부파일 zip 처리 (DART 일부 보고서는 첨부 PDF만 제공 — 우선 HTML 보고서만)

## 2. Why DART OpenAPI (대안 비교)

| 옵션 | 장점 | 단점 | 결정 |
|------|------|------|------|
| DART OpenAPI (개인 key) | 안정·합법·공식·rate 600/min | API key 발급·corp_code zip 처리 | ✅ 채택 |
| DART 웹 페이지 크롤링 | key 불필요 | ToS·DOM 변경 위험·블록 위험 | ❌ |
| KIND·전자공시검색 API | 부분 데이터 | 사업보고서 본문 미제공 | ❌ |
| 유료 데이터 벤더(에프앤가이드 등) | 정제됨 | 비용·라이선스 | ❌ MVP 부적합 |

## 3. Scope

### 3.1 In-scope (이 plan)

- `src/themek/dart/client.py` — DART OpenAPI HTTP client (3개 endpoint)
- `src/themek/dart/cache.py` — 디스크 캐시 (응답을 `data/dart/raw/`에 저장)
- `src/themek/dart/corp_lookup.py` — ticker ↔ corp_code 매핑 sync + 조회
- `src/themek/dart/fetch.py` — 종목+기간 → rcept_no 탐색 + 사업보고서 HTML 다운로드
- `src/themek/db/models.py` 수정 — Corporation에 `dart_corp_code` unique index 추가 (이미 있으면 no-op)
- CLI 명령 3개:
  - `themek dart sync-corp` — corp_code 마스터 1회 sync
  - `themek dart fetch --ticker <> --period <> --report-type 사업보고서` — 사업보고서 HTML 캐시 디렉토리에 저장
  - `themek dart ingest --ticker <> --period <>` — fetch + 기존 `ingest_business_report` 호출
- 에러 정책: API key 미설정/HTTP 4xx/HTTP 5xx/timeout 모두 명확한 exit code != 0
- Rate limit: 보수적 토큰 버킷 (default 분당 60회, 초당 5회)
- 단위 + 통합 테스트(HTTP는 stub) ~15-20 케이스
- 1회 실 호출 smoke run + baseline 기록

### 3.2 Out-of-scope (후속)

- 전 종목 backfill (Plan #5)
- 공시(Disclosure) ingestion
- 첨부 zip / PDF 본문 추출
- 다년도 동시 fetch (각 호출은 1 (ticker, period) 단위)
- 캐시 만료/refresh 정책 — Plan #5에서 정책화
- DART API key 권한 등급 처리 (개인용 key 단일 등급 가정)
- 동시 N개 요청 병렬화 — sync 순차 호출로 충분
- Schedule / cron 통합

## 4. DART OpenAPI Endpoints (사용 3개)

DART OpenAPI 문서: https://opendart.fss.or.kr/intro/main.do

### 4.1 `corpCode.xml` — 기업 마스터

- URL: `https://opendart.fss.or.kr/api/corpCode.xml?crtfc_key=<KEY>`
- 응답: zip → `CORPCODE.xml` (~3MB, 9만+ 기업)
- 사용: 초기 1회 + 분기마다 refresh
- 파싱 결과: `[(corp_code: str(8), corp_name: str, stock_code: str(6) or "", modify_date: str(YYYYMMDD)), ...]`

### 4.2 `list.json` — 정기보고서 조회

- URL: `https://opendart.fss.or.kr/api/list.json?crtfc_key=<KEY>&corp_code=<8자리>&bgn_de=<YYYYMMDD>&end_de=<YYYYMMDD>&pblntf_ty=A&page_count=100`
  - `pblntf_ty=A` → 정기공시(사업/반기/분기보고서 등)
- 응답: `{"status":"000", "list":[{"rcept_no":"...","report_nm":"사업보고서 (2023.12)", ...}, ...]}`
- 우리 함수: `find_business_report(corp_code, year) → rcept_no | None`
  - filter: report_nm이 "사업보고서" 시작 + 표기 연도 일치

### 4.3 사업보고서 본문 HTML

DART OpenAPI에는 **본문 HTML을 직접 주는 endpoint가 없다.** 사업보고서는 zip 첨부 또는 viewer URL.

- 옵션 A: `document.xml?rcept_no=<>` → zip 첨부 (재무제표 등 다수 파일)
  - 사업의 내용 HTML이 zip 안에 있지만 파일명 규칙이 보고서마다 다름 → 추출 로직 복잡
- 옵션 B: viewer URL fetch (`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=<rcept_no>`)
  - 본문 iframe 추적 → 1단계 더 필요
- 옵션 C: 단일 zip endpoint(`document.xml`) 다운로드 후 "사업의 내용" 파일을 zip 내부에서 휴리스틱(파일명에 "사업의내용" 또는 두 번째 HTML 파일 등)으로 선택

**Plan #3 결정 (Open Decision D1):** 옵션 C — `document.xml` zip 다운로드 + 휴리스틱 선택. 이유: OpenAPI 단일 endpoint·인증·rate 일관, 휴리스틱 fail 시 명확한 에러로 fallback 가능.

휴리스틱 (1차 시도):
1. zip 내 파일 중 이름에 "사업의 내용" 또는 "II. 사업의 내용" 패턴 포함하는 .html
2. 없으면 파일명 정렬 시 2번째 .html (1번째는 보통 표지/요약)
3. 둘 다 실패 시 `DartFetchError(rcept_no, reason="business-section-html-not-found")`

## 5. Architecture

### 5.1 파일 구조

```
themek/
├── src/themek/
│   ├── config.py                    # 수정: dart_api_key, dart_cache_dir 추가
│   └── dart/
│       ├── __init__.py
│       ├── parser.py                # 기존 (변경 없음)
│       ├── client.py                # NEW: HTTP + rate limit + 에러
│       ├── cache.py                 # NEW: 디스크 캐시
│       ├── corp_lookup.py           # NEW: corp_code ↔ ticker 매핑
│       └── fetch.py                 # NEW: 종목+기간 → HTML (오케스트레이션)
├── tests/
│   ├── test_dart_client.py          # HTTP stub 기반
│   ├── test_dart_cache.py
│   ├── test_dart_corp_lookup.py
│   ├── test_dart_fetch.py
│   └── test_cli_dart.py             # CLI 통합
├── data/
│   └── dart/
│       ├── corp_master.json         # corp_code 마스터 캐시 (sync 결과)
│       └── raw/
│           └── <rcept_no>/
│               ├── document.zip     # 원본
│               └── business.html    # 추출된 사업의 내용
└── docs/
    └── dart-fetch-smoke-run-notes.md
```

### 5.2 컴포넌트 의존성

```
cli.py (dart sync-corp / fetch / ingest)
   │
   ▼
fetch.py: fetch_business_report_html(ticker, period) → Path
   │
   ├──▶ corp_lookup.py: ticker → corp_code   (이미 sync된 마스터에서 조회)
   │
   ├──▶ client.py: list.json 호출 → rcept_no 탐색
   │
   ├──▶ client.py: document.xml zip 다운로드
   │
   ├──▶ cache.py: zip + 추출 HTML 저장
   │
   ▼
ingest_business_report(...)  ← 기존 (Plan #1)
```

### 5.3 데이터 흐름

```
[user] uv run themek dart ingest --ticker 005930 --period 2023
   │
   ▼
1. corp_lookup: "005930" → "00126380"
2. client.list_json(corp_code=00126380, bgn_de=20230101, end_de=20231231)
   → [{rcept_no: "20240314000123", report_nm: "사업보고서 (2023.12)"}, ...]
3. 선택: report_nm이 "사업보고서" + 연도 매치 → rcept_no
4. cache hit 확인: data/dart/raw/20240314000123/business.html 존재?
   YES → 그대로 사용  (DART API 0회 호출)
   NO  → client.fetch_document_zip(rcept_no)
        → unzip → 휴리스틱 HTML 선택 → cache 저장
5. ingest_business_report(html_file=cache_path, rcept_no=..., corp=corp_code, ...)
```

## 6. Tech Stack

- Python 3.12+
- HTTP: `httpx` (sync 클라이언트, retry는 우리가 명시적 구현 — tenacity는 의존성 증가라 미채택)
- XML: `lxml` (이미 dep)
- Zip: stdlib `zipfile`
- 캐시: stdlib 파일 시스템
- Rate limit: 자체 구현 토큰 버킷(시간 기반, 외부 lib 없음)
- Pydantic v2 (Settings 확장)
- typer (CLI)
- pytest + `respx` (httpx stub) 또는 `pytest-httpx`

**Open Decision D2:** HTTP stub 라이브러리 — `respx` vs `pytest-httpx` vs 수동 monkeypatch. 권장: `respx` (가독성 좋음, dev 의존성만 추가).

## 7. API Design (Python signatures)

### 7.1 `dart/client.py`

```python
class DartApiError(RuntimeError): ...
class DartRateLimitError(DartApiError): ...
class DartAuthError(DartApiError): ...

class DartClient:
    def __init__(self, api_key: str, *, base_url: str = ..., rate_per_min: int = 60, timeout_sec: int = 30): ...
    def fetch_corp_code_zip(self) -> bytes: ...
    def list_periodic_reports(self, *, corp_code: str, bgn_de: str, end_de: str) -> list[dict]: ...
    def fetch_document_zip(self, *, rcept_no: str) -> bytes: ...
```

### 7.2 `dart/cache.py`

```python
class DartCache:
    def __init__(self, base_dir: Path): ...
    def has_business_html(self, rcept_no: str) -> bool: ...
    def get_business_html_path(self, rcept_no: str) -> Path: ...
    def save_raw_zip(self, rcept_no: str, zip_bytes: bytes) -> Path: ...
    def save_business_html(self, rcept_no: str, html_bytes: bytes) -> Path: ...
    def save_corp_master(self, payload: list[dict]) -> Path: ...
    def load_corp_master(self) -> list[dict] | None: ...
```

### 7.3 `dart/corp_lookup.py`

```python
def sync_corp_master(client: DartClient, cache: DartCache) -> int: ...
    """corp_code zip → parse → cache.save_corp_master → row count 반환."""

def lookup_corp_code(cache: DartCache, *, ticker: str) -> str:
    """ticker(6자리) → corp_code(8자리). 못 찾으면 LookupError."""
```

### 7.4 `dart/fetch.py`

```python
class BusinessReportFetchError(RuntimeError): ...

def find_business_report_rcept_no(
    client: DartClient, *, corp_code: str, year: int,
) -> str:
    """list.json 조회 + report_nm filter → rcept_no. 못 찾으면 BusinessReportFetchError."""

def extract_business_html_from_zip(zip_bytes: bytes) -> bytes:
    """zip → 사업의 내용 HTML bytes. 휴리스틱 실패 시 BusinessReportFetchError."""

def fetch_business_report_html(
    client: DartClient, cache: DartCache, *, ticker: str, year: int,
) -> tuple[Path, str]:
    """주 entry point. cache miss 시 fetch + save. Returns (html_path, rcept_no)."""
```

## 8. Caching Strategy

- 모든 raw API 응답을 디스크에 저장 → 재실행 시 0 호출 (테스트 + 재현성)
- 캐시 키:
  - corp 마스터: `data/dart/corp_master.json` (단일 파일)
  - 사업보고서: `data/dart/raw/<rcept_no>/{document.zip, business.html}`
- 캐시 invalidation: **Plan #3에서는 명시적 정책 없음** — 사용자가 디렉토리를 손으로 지우면 다시 fetch. Plan #5에서 TTL/refresh 도입.
- git ignore: `data/dart/raw/` (크기·저작권), `data/dart/corp_master.json`도 ignore (분기마다 변동 + 9만 row)
- `.gitignore`에 `/data/dart/` 추가
- ground truth(`data/eval/ground_truth/`)는 계속 tracked (분리 디렉토리)

**Open Decision D3:** corp_master는 git tracked? — 권장 NO (변동·크기). 사용자가 처음 1회 `themek dart sync-corp` 실행 전제.

## 9. Rate Limit & Error Handling

### 9.1 Rate limit

- 자체 토큰 버킷 (in-memory, process scope)
- default 60 req/min (DART 한도 600의 1/10, 보수적). settings로 조정 가능
- 한도 초과 직전 sleep 또는 즉시 `DartRateLimitError` — 권장: sleep + 진행 (CLI 단건 호출에선 충분)
- 동시성 미고려 (process 1개 가정)

### 9.2 Error matrix

| 상황 | 예외 / 종료 | 사용자 메시지 |
|------|-----------|--------------|
| `DART_API_KEY` 미설정 | `DartAuthError` → exit 2 | "DART API key 미설정. .env에 DART_API_KEY=... 추가" |
| HTTP 4xx (401/403 key invalid) | `DartAuthError` → exit 2 | DART 응답 status·message 그대로 |
| HTTP 429 rate limit | retry 3회 + 백오프 → 실패 시 `DartRateLimitError` → exit 3 | "rate limit. 잠시 후 재시도." |
| HTTP 5xx | retry 3회 (1s/2s/4s 백오프) → 실패 시 `DartApiError` → exit 4 | "DART 서버 오류. 재시도 후 실패." |
| Timeout | 동일 retry | "timeout" |
| `list.json` status != "000" | `DartApiError` → exit 4 | status·message |
| 사업보고서 미존재(연도 fit 0건) | `BusinessReportFetchError` → exit 5 | "ticker=X period=Y 사업보고서 없음 (DART 미공시 또는 비상장)" |
| zip 내 사업의 내용 HTML 추출 실패 | `BusinessReportFetchError` → exit 5 | rcept_no + 휴리스틱 fail 사유 |

retry 정책: 3회, 1s/2s/4s exponential. jitter 없음(단일 process). retry 대상 코드: 429·500·502·503·504·timeout. 4xx(429 외)는 즉시 실패.

## 10. CLI 설계

```bash
# 1회 sync (corp_master 준비) — DART API 1 호출
uv run themek dart sync-corp
# stdout: "synced 92847 corporations to data/dart/corp_master.json"

# 단일 종목 사업보고서 HTML만 fetch (캐시)
uv run themek dart fetch --ticker 005930 --period 2023 --report-type 사업보고서
# stdout: "data/dart/raw/20240314000123/business.html"
# stderr: cache hit/miss 로그

# fetch + ingest 통합 (가장 빈번한 사용 패턴)
uv run themek dart ingest --ticker 005930 --period 2023 --report-type 사업보고서
# 내부: corp_lookup → list.json → document.xml → cache → ingest_business_report(...)
# stdout: "Ingested report 20240314000123"
```

**Open Decision D4:** `report-type`을 사업보고서 외 반기/분기까지 지원할지. 권장: **MVP는 사업보고서만**. 반기·분기는 Plan #5에서 같은 코드로 확장 가능.

`--period`: 사업보고서는 연도 단위. `--period 2023` → bgn_de=20230101 end_de=20231231. 반기/분기 확장 시 `--period 2024Q3` 형식 (`BusinessReport.period` 기존 컬럼과 호환).

## 11. Testing Strategy

| 레이어 | 도구 | 케이스 수 |
|--------|------|----------|
| `DartClient` HTTP (`respx` stub) | unit | 5 (success·rate·auth·5xx·timeout) |
| `DartCache` 파일 IO | unit | 4 (save·load·hit·miss) |
| `corp_lookup` parse + lookup | unit | 3 (sync·hit·miss) |
| `fetch.extract_business_html_from_zip` | unit | 3 (heuristic match·fallback·fail) |
| `fetch.find_business_report_rcept_no` | unit | 3 (match·multi-match→latest·no-match) |
| `fetch.fetch_business_report_html` 오케스트레이션 | integration (respx + tmp_path) | 2 (cache miss → fetch, cache hit → 0 호출) |
| CLI `dart ingest` (stub respx + tmp DB) | integration | 2 (perfect path, missing ticker) |

총 ~22개. 모두 실 DART API 호출 없음. 1회 smoke run은 사람이 수동 + baseline 문서.

### 11.1 Fixture 자료

- 가짜 corp_master.json (10 row, 3 종목 포함)
- 가짜 document.zip (in-memory zipfile에 2 HTML)
- 가짜 list.json 응답 1건

## 12. Ontology / DB 모델 영향

- `Corporation.dart_corp_code` 컬럼은 spec(line 99·280)에 이미 PK로 정의되어 있다. 실제 model 확인 필요(아래 Open Decision D5).
- ticker(6자리)는 `Stock.ticker`이고 종목 ↔ 기업(`Corporation.dart_corp_code`)는 별개 PK라 매핑 필요. seed에 이미 매핑 존재 → corp_lookup은 seed 또는 corp_master에서 조회.
- Plan #3에서 schema 변경 0줄을 목표 (있으면 alembic revision 필요).

**Open Decision D5:** `Corporation.dart_corp_code`가 현 model에 있는지 확인 후, 없으면 Plan #3에 alembic migration task 1건 추가.

## 13. Open Decisions Summary (사용자 검토)

| ID | 결정 사항 | 권장 default | 다른 옵션 |
|----|----------|------------|----------|
| D1 | 사업보고서 본문 fetch 방식 | `document.xml` zip + 휴리스틱 HTML 선택 | viewer URL 크롤링, 첨부 zip 명시 파싱 |
| D2 | HTTP stub 라이브러리 | `respx` | `pytest-httpx`, monkeypatch |
| D3 | `data/dart/corp_master.json` git tracked? | NO (gitignore) | YES (재현성) |
| D4 | `report-type` MVP 범위 | 사업보고서만 | 사업+반기+분기 |
| D5 | `Corporation.dart_corp_code` migration | model 확인 후 결정 | 없으면 Plan #3에 add column task |
| D6 | corp_lookup 데이터 출처 | corp_master.json (sync-corp 선행 강제) | seed 직접 사용 |
| D7 | retry 횟수·백오프 | 3회 / 1s·2s·4s | 5회 / jitter |
| D8 | DART_API_KEY env 키 이름 | `DART_API_KEY` | `THEMEK_DART_API_KEY` (prefix) |

## 14. Risks

- **DART zip 내 HTML 구조 변동** — 휴리스틱 fail 가능. 실제 zip 1-2건으로 사전 검증 권장 (D1 확정 전에).
- **HTML 본문이 base64 인코딩되어 zip에 들어가는 케이스** — 일부 보고서는 그렇다. 우선 일반 HTML 가정, fail 시 plan 수정.
- **API key rate 변동** — 개인 key 분당 600 / 일 10000 한도. 단일 사용은 안전하지만 backfill(Plan #5)에서 재검토.
- **corp_master 동기 시점 이슈** — 신규 상장사가 sync 후 fetch 요청되면 lookup 실패. UX는 "sync-corp 다시 실행" 권유.
- **테스트 fixture 신뢰성** — 가짜 zip 구조가 실제와 다를 가능성. 1건 실 응답을 anonymized fixture로 보관 권장.

## 15. Acceptance Criteria

이 spec → plan → 구현 완료 시 다음이 모두 참:

1. `uv run themek dart sync-corp` 가 0 exit + `data/dart/corp_master.json` 생성 (≥80,000 row)
2. `uv run themek dart ingest --ticker 005930 --period 2023` 가 0 exit, DB에 BusinessReport + Segments + Customers + Geographic rows 생성, 같은 명령 재실행 시 DART API 0회 호출 + DB idempotent
3. 동일 흐름이 현대차(005380), 레인보우로보틱스(277810)에도 동작 (seed에 둘 다 있음)
4. ingest 후 `uv run themek query e5 --ticker 005930` 가 답을 반환
5. `uv run themek eval e5 --html-file <cached path> --period 2023 --ground-truth ...` 가 동작
6. ~22개 신규 unit/integration 테스트 + 기존 78개 모두 통과
7. `docs/dart-fetch-smoke-run-notes.md` 에 실 fetch 1회 baseline 기록
8. README의 "후속 Plan들" 섹션 Plan #3이 ✅ 완료로 갱신

## 16. Plan 분기 (다음 단계)

본 spec 검토(Open Decisions 8개 합의) 완료 후 `docs/superpowers/plans/2026-05-25-dart-api-client.md` 작성:

- T0: D1-D8 결정 반영 + alembic migration 필요 여부 확정
- T1-T3: client.py + 테스트 (HTTP stub)
- T4: cache.py + 테스트
- T5-T6: corp_lookup.py + 테스트 (corp_master fixture)
- T7-T8: fetch.py — extract_business_html_from_zip + find_rcept_no
- T9: fetch.fetch_business_report_html 오케스트레이션
- T10-T11: CLI 3개 명령 + 통합 테스트
- T12: smoke run + baseline notes
- T13: README 갱신
