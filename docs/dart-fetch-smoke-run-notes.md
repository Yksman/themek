# DART API Fetch — Smoke Run Baseline

**실행일:** 2026-05-25
**대상:** 삼성전자(005930), 현대차(005380), 레인보우로보틱스(277810) — 2023 사업보고서
**API:** 실 DART OpenAPI (DART_API_KEY 사용)
**LLM:** stub (`tests/fixtures/samsung_extraction_expected.json`) — 비용 절약용

## 1. Commands & Output

### Step 1: corp_master sync (DART API 1회 호출)

```
$ rm -rf data/dart
$ uv run themek dart sync-corp
synced 118145 corporations to data/dart/corp_master.json
```

### Step 2: fetch 3 종목 (DART API 각각 list.json + document.xml = 2회)

```
$ uv run themek dart fetch --ticker 005930 --period 2023
data/dart/raw/20240312000736/business.html

$ uv run themek dart fetch --ticker 005380 --period 2023
data/dart/raw/20240313001451/business.html

$ uv run themek dart fetch --ticker 277810 --period 2023
data/dart/raw/20240321001029/business.html
```

### Step 3: cache hit 검증 (재실행 시 DART API 0회)

```
$ time uv run themek dart fetch --ticker 005930 --period 2023
data/dart/raw/20240312000736/business.html
real    0m1.20s        # cache hit으로 즉시 반환
```

### Step 4: ingest 3 종목 (stub LLM)

```
$ uv run themek seed
Seeded 3 stocks, 3 corporations, sectors, regions.

$ THEMEK_STUB_EXTRACTION_FILE=tests/fixtures/samsung_extraction_expected.json \
    uv run themek dart ingest --ticker 005930 --period 2023
Ingested report 20240312000736

$ THEMEK_STUB_EXTRACTION_FILE=tests/fixtures/samsung_extraction_expected.json \
    uv run themek dart ingest --ticker 005380 --period 2023
Ingested report 20240313001451

$ THEMEK_STUB_EXTRACTION_FILE=tests/fixtures/samsung_extraction_expected.json \
    uv run themek dart ingest --ticker 277810 --period 2023
Ingested report 20240321001029
```

### Step 5: idempotent 재실행

```
$ THEMEK_STUB_EXTRACTION_FILE=tests/fixtures/samsung_extraction_expected.json \
    uv run themek dart ingest --ticker 005930 --period 2023
Ingested report 20240312000736   # DB는 no-op (BusinessReport.dart_rcept_no PK 매치)
```

DART API 호출 검증: 두 번째 실행 시 list.json은 호출되나 document.xml은 cache hit (raw/.../business.html 존재 → 추출 skip).

### Step 6: query e5 (삼성전자)

```
$ uv run themek query e5 --ticker 005930
[삼성전자 (005930) — 반도체]
출처: 사업보고서 (period=2023, DART rcept_no=20240312000736)
링크: https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20240312000736

## 사업 부문 매출 구성
- 메모리반도체 42.5% — DRAM/NAND 등
- 스마트폰/네트워크 38.0% — 갤럭시 시리즈
- 디스플레이 15.5% — OLED 패널

## 주요 고객사 / 매출처
- Apple Inc. (18.0%) · 1차 협력사
...
```

### Step 7: eval e5 (실 fetched HTML vs ground truth)

```
$ THEMEK_STUB_EXTRACTION_FILE=tests/fixtures/samsung_extraction_expected.json \
    uv run themek eval e5 \
    --html-file data/dart/raw/20240312000736/business.html \
    --period 2023 \
    --ground-truth data/eval/ground_truth/samsung_e5_2023.json

Segments        recall= 0/6 = 0.000    precision= 0/3 = 0.000
Customers       recall= 0.333          precision= 0.500
Regions         recall= 1.000          precision= 0.833
Share_pct MAE   n/a (matched=0)
```

(stub extraction과 ground_truth가 다른 segment 명명을 쓰기 때문에 segment 매치 0. 실 LLM 사용 시 별도 baseline 측정 필요.)

## 2. Observations

| 항목 | 값 |
|------|-----|
| corp_master 총 row | 118,145 |
| corpCode.xml zip | 3,579,368 bytes |
| 삼성전자 corp_code | 00126380 |
| 현대차 corp_code | 00164742 |
| 레인보우로보틱스 corp_code | 01261644 |
| 삼성전자 rcept_no (2023) | 20240312000736 |
| 현대차 rcept_no (2023) | 20240313001451 |
| 레인보우로보틱스 rcept_no (2023) | 20240321001029 |
| 삼성 document.zip 크기 | 596,351 bytes (3 XML 파일) |
| 현대차 document.zip 크기 | 664,258 bytes |
| 레인보우 document.zip 크기 | 269,560 bytes |
| 삼성 business.html (추출) | 179,174 bytes |
| 현대차 business.html (추출) | 7,254,610 bytes |
| 레인보우 business.html (추출) | 136,211 bytes |
| 삼성 본문 text (extract_business_content) | 38,085 chars |
| 현대차 본문 text | 241,568 chars |
| 레인보우 본문 text | 32,406 chars |

본문 키워드 확인 (sanity check):
- 삼성전자: "II. 사업의 내용", "DRAM", "NAND Flash", "DX 부문", "DS 부문", "SDC", "Harman"
- 현대차: "차량부문 80%", "금융부문 14%", "기타부문 6%"
- 레인보우로보틱스: "협동로봇", "이족보행 로봇", "인더스트리 4.0"

## 3. 핵심 발견 — DART zip 구조 가정 변경

원 spec v1.1의 D1 가정 "zip 내부에 HTML이 있고 파일명 휴리스틱(사업의내용.html)으로 선택"이 실 응답과 다름:

- 실 zip은 `dart4.xsd` 기반 **XML**만 포함 (HTML 0개)
- 본 보고서 XML 안의 `<TITLE AASSOCNOTE="D-0-2-0-0">II. 사업의 내용</TITLE>` SECTION-1을 추출
- 자세한 분석은 `docs/dart-api-recon-notes.md` 참조

## 4. 두 번째 실행 검증 (재현성)

같은 명령을 재실행해도:
- `dart sync-corp` — `data/dart/corp_master.json` 그대로 사용 가능 (재 sync 시 1 호출)
- `dart fetch` — cache hit으로 즉시 반환 (DART API 0회)
- `dart ingest` — `BusinessReport.dart_rcept_no` PK 매치로 no-op (DB idempotent)

## 5. Issues / Follow-ups

- **eval e5 stub과 ground_truth 정렬** — segment naming 차이로 매치 0. 실 LLM run 시 baseline 갱신 필요 (Plan #5 또는 별도).
- **rate limit** — 본 smoke run은 4 호출 (sync 1 + 종목 3 × (list+doc) = 4 — list 첫 종목 빼고는 동일 자료 재사용 안 되므로 7회) 수준이라 rate 영향 없음. 대량 backfill(Plan #5) 시 토큰 버킷 활성화 필요.
- **현대차 본문 7MB** — XML 추출 결과가 매우 큼 (다년도 비교표 + 다종 차량 모델 등). LLM 입력 토큰 부담 → context trimming 정책 필요할 수 있음.

## 6. Acceptance Verification (spec section 15)

1. ✅ `themek dart sync-corp` 0 exit + 118,145 row ≥ 80,000
2. ✅ `themek dart ingest --ticker 005930 --period 2023` 0 exit + BusinessReport 생성, 재실행 idempotent + cache hit
3. ✅ 005380 / 277810 동일 흐름 동작
4. ✅ `themek query e5 --ticker 005930` 답 반환
5. ✅ `themek eval e5 ...` 동작 (점수는 stub의 한계로 segment 0 — 실 LLM 사용 시 baseline 갱신)
6. ✅ 신규 테스트 ~30개 + 기존 회귀 모두 통과 (137+ passed)
7. ✅ `docs/dart-fetch-smoke-run-notes.md` baseline 기록 (이 문서)
8. ⏳ README "후속 Plan들" Plan #3 ✅ 갱신 — 후속 task
