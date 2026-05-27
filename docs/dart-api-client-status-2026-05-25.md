# Plan #3 (DART API Client) — Completion Status

**완료일:** 2026-05-25
**Plan:** `docs/superpowers/plans/2026-05-25-dart-api-client.md`
**Spec:** `docs/superpowers/specs/2026-05-25-dart-api-client-design.md`

## 1. Goal Recap

Walking Skeleton(Plan #1)이 수동 fixture HTML 1건으로 검증한 ingest 파이프라인을, **(ticker, period)** 입력만으로 DART에서 사업보고서를 자동 fetch → 추출 → 캐시 → 기존 `ingest_business_report`에 연결하도록 확장. 종목 1 → N 확장 backbone.

## 2. Deliverables

### 2.1 코드

| 파일 | 라인 | 역할 |
|------|------|------|
| `src/themek/config.py` | +5 | `dart_api_key`, `dart_cache_dir`, `dart_rate_per_min`, `dart_http_timeout_sec` |
| `src/themek/dart/client.py` | +75 | `DartClient` + 3 메서드 + 4 에러 클래스 |
| `src/themek/dart/cache.py` | +50 | `DartCache` 디스크 캐시 |
| `src/themek/dart/corp_lookup.py` | +35 | `parse_corp_code_zip`, `sync_corp_master`, `lookup_corp_code` |
| `src/themek/dart/fetch.py` | +115 | `_select_main_report_xml`, `_extract_business_section_xml`, `extract_business_html_from_zip`, `find_business_report_rcept_no`, `fetch_business_report_html` |
| `src/themek/cli.py` | +110 | `dart` 서브앱 + 3 명령 (`sync-corp`/`fetch`/`ingest`) + `_ensure_corporation` |
| `pyproject.toml` | +1 | `httpx>=0.28` 추가 |

### 2.2 테스트 (138 passed)

| 파일 | 테스트 | 실 fixture |
|------|--------|------------|
| `tests/test_config.py` | 6 | - |
| `tests/test_dart_client.py` | 15 | 3 (실 corp_zip / list_json / doc_zip playback) |
| `tests/test_dart_cache.py` | 7 | - |
| `tests/test_dart_corp_lookup.py` | 8 | 2 (실 118k row 파싱 + 005930/005380/277810 lookup) |
| `tests/test_dart_fetch.py` | 18 | 3 (실 zip XML 추출 + pipeline) |
| `tests/test_cli_dart.py` | 8 | - (mock 기반, auto-upsert 검증 포함) |
| 기타 회귀 | 76 | - |
| **합계** | **138** | **8** |

### 2.3 문서

| 파일 | 내용 |
|------|------|
| `docs/dart-api-recon-notes.md` | T0 실 API 정찰 결과 — corpCode/list/document 구조, spec D1 정정 근거 |
| `docs/dart-fetch-smoke-run-notes.md` | T12 baseline — 3종목 실 API end-to-end, idempotent/cache hit 검증 |
| `docs/dart-api-client-status-2026-05-25.md` | (이 문서) |
| `README.md` | Plan #3 완료 마킹 + DART 사용 예시 + 디렉토리 구조 갱신 |

### 2.4 환경/설정

- `.env.example` — `DART_API_KEY`, `DART_CACHE_DIR`, `DART_RATE_PER_MIN`, `DART_HTTP_TIMEOUT_SEC` 추가
- `.gitignore` — `/data/dart/`, `/scripts/` (정찰 스크립트) 무시
- `tests/fixtures/dart_cassettes/` — git tracked 실 응답 fixture 3건 (4MB 전체)

## 3. 핵심 의사결정 변경 (v1.1 spec 대비)

### D1 (사업보고서 본문 추출) — **변경**

| 항목 | spec v1.1 | 실제 (T0 정찰 후) |
|------|-----------|-------------------|
| zip 내용 | HTML 파일 다수 | DART 전용 XML 3개 (HTML 0개) |
| 추출 휴리스틱 | 파일명에 "사업의내용" 매치, fallback: 정렬 2번째 .html | `DOCUMENT-NAME ACODE="11011"` 본 보고서 선택 → `<TITLE AASSOCNOTE="D-*-2-0-0">` SECTION-1 추출 |
| 캐시 파일 | `business.html` (원본 HTML) | `business.html` (XML을 `<html><body>` wrap한 텍스트) |

기존 `dart/parser.py:extract_business_content` (BeautifulSoup 기반)는 wrap된 XML도 처리 가능 — 인터페이스 호환 유지.

### D2 (테스트 HTTP 방식) — **변경**

vcrpy/respx 대신 **raw bytes fixture + monkeypatch httpx**. 실 API 0회 hit + CI 호환은 그대로 유지.

### D5 (`Corporation.dart_corp_code` migration) — **noop**

기존 모델에 `Corporation.dart_code`(varchar 8, PK)가 이미 존재. spec의 `dart_corp_code`와 이름만 다름. alembic migration 불필요.

## 4. 실 API Smoke Run 결과

| 종목 | corp_code | rcept_no (2023) | document.zip | business.html | 본문 text |
|------|-----------|-----------------|--------------|---------------|-----------|
| 005930 삼성전자 | 00126380 | 20240312000736 | 596 KB | 179 KB | 38,085 chars |
| 005380 현대차 | 00164742 | 20240313001451 | 664 KB | 7.3 MB | 241,568 chars |
| 277810 레인보우로보틱스 | 01261644 | 20240321001029 | 270 KB | 136 KB | 32,406 chars |

키워드 sanity check 통과:
- 삼성: "DRAM", "NAND Flash", "DX/DS 부문", "SDC", "Harman"
- 현대차: "차량부문 80%", "금융부문 14%", "기타부문 6%"
- 레인보우: "협동로봇", "이족보행 로봇"

cache hit 검증: 재실행 시 DART API 0회 + 1.2s 내 응답.

## 5. Acceptance Criteria (spec section 15)

| # | 조건 | 결과 |
|---|------|------|
| 1 | `themek dart sync-corp` 0 exit + corp_master ≥80,000 row | ✅ 118,145 row |
| 2 | `themek dart ingest --ticker 005930 --period 2023` 0 exit + DB row 생성 + 재실행 idempotent (API 0회) | ✅ |
| 3 | 동일 흐름이 005380 / 277810 동작 | ✅ 둘 다 ingest 성공 |
| 4 | `themek query e5 --ticker 005930` 답 반환 | ✅ |
| 5 | `themek eval e5 --html-file <cached> --period 2023 --ground-truth ...` 동작 | ✅ (점수는 stub 한계로 segment 0 매치, 실 LLM run에서 baseline 갱신 예정) |
| 6 | 신규 테스트 + 기존 회귀 모두 통과 | ✅ 138 passed |
| 7 | smoke run baseline 기록 | ✅ `docs/dart-fetch-smoke-run-notes.md` |
| 8 | README Plan #3 ✅ 갱신 | ✅ |

## 6. 알려진 한계 / Follow-up

1. **실 LLM baseline 미측정** — ingest 파이프라인은 stub LLM(`samsung_extraction_expected.json`)으로만 검증. 실 `claude` CLI로 3종목 추출 후 ground_truth 대비 점수 측정 필요. **다음 작업으로 권장.**
2. **eval e5 segment 매치 0** — stub과 ground_truth가 segment naming(메모리반도체 vs DS-메모리)이 달라서 stub 기준 점수만 보면 무의미. 실 LLM 추출 후 의미 있음.
3. **현대차 본문 7.3MB** — XML 추출 결과가 매우 큼 (다년도 비교표 + 종속회사 70여 개). LLM context limit 부담 → trimming 정책 필요 (Plan #5 또는 별도 issue).
4. **반기/분기 보고서 미지원** (D4) — `--period`는 연도만 받음. `--period 2024Q3`/`2024H1` 확장은 Plan #5에서 같은 코드로 가능.
5. **rate limit 토큰 버킷 미활성** — 설정값(`dart_rate_per_min=60`)은 있지만 코드상 미적용. 단건 호출에는 불필요, 다종목 backfill(Plan #5)에서 활성.
6. **첨부 PDF 처리 불가** — 본 zip에는 _00760/_00761 같은 부속 보고서 XML도 있지만 현재는 본 보고서만 추출. 첨부는 out-of-scope.
7. **cassette refresh 정책 없음** — fixture는 2026-05-25 시점. DART 응답 schema 변경 시 manual refresh 필요.

## 7. 다음 권장 작업

순서:
1. **실 LLM E5 baseline (1~2시간)** — `THEMEK_STUB_EXTRACTION_FILE` 없이 실 claude CLI로 3종목 ingest → eval e5로 ground_truth 대비 점수 → `docs/eval-e5-real-llm-baseline.md` 작성
2. **Plan #5: 다종목 backfill** — token bucket 활성, 동시 N개 fetch, 진행상황 logging, 실패 재시도
3. **Plan #2 + #7: social layer ingestion** — 텔레그램/블로그/팍스넷 + Theme/Narrative ontology

## 8. 검증 명령

```bash
# 전체 회귀
uv run pytest

# 실 API end-to-end (DART_API_KEY 필요)
uv run themek dart sync-corp
uv run themek dart ingest --ticker 005930 --period 2023
uv run themek query e5 --ticker 005930

# 재실행 (idempotent + cache hit)
uv run themek dart ingest --ticker 005930 --period 2023
```
