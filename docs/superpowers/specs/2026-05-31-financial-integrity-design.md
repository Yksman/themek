# Track A — 재무 데이터 정합성 (Financial Integrity) 설계

- 작성일: 2026-05-31
- 상태: 승인됨 (구현 플랜 작성 대상)
- 범위: 온톨로지 코어 재무 적재(`financial_facts`) 정합성 + 엣지 중복 방지 + 경량 무결성 가드

## 1. 배경 / 문제

~45개 기업 백필 이후 온톨로지 스키마 리뷰에서 데이터를 실제로 손상시키는 확정 버그가 발견되었다.

### 1.1 확정 버그 — 분기 재무상태표(BS) 오염

`src/themek/ontology/ingest/financials.py`의 `parse_financial_rows`는 DART `fnlttSinglAcntAll`
응답 1행(당기 `thstrm` / 전기 `frmtrm` / 전전기 `bfefrmtrm` 3개년 금액)을 `yr / yr-1 / yr-2`로
펼치되, **세 컬럼 모두 현재 보고서의 `fiscal_period`를 그대로** 붙인다.

- flow 지표(매출/영업이익/당기순이익): 비교열은 "전기 동기 누계"이므로 `(yr-1, 같은 period)`
  라벨이 의미상 맞다.
- **stock 지표(자산/부채/자본총계): 분기보고서의 비교열(frmtrm)은 *직전 사업연도 말*
  스냅샷**이다. 이를 현재 보고서의 interim period(Q1/H1/Q3)로 라벨링하면 잘못된 값이 적재되고,
  `_upsert_fact`가 충돌 시 덮어쓰므로(financials.py 내 upsert) 진짜 분기 스냅샷이 연말값으로 교체된다.

증거 (CJ, `company:00148540`, 자산총계 CFS):

| 2024 Q1 | 2024 H1 | 2024 Q3 | 2024 FY |
|---|---|---|---|
| 47,496,993,224,000 | 47,480,577,938,000 | 47,480,577,938,000 | 47,480,577,938,000 |

H1·Q3가 FY와 정확히 일치 — 2025 interim 보고서의 frmtrm(=2024 연말 BS)이 `2024 H1/Q3`로
잘못 저장된 결과다. 전역으로 assets/liabilities/equity 각 H1·Q1·Q3 79행이 의심 대상이며,
파생 지표(부채비율·ROE)의 interim 컬럼이 함께 틀린다.

### 1.2 구조 리스크 — 엣지 중복 방지가 DB에 없음

`(subject_id, predicate, object_id, period)` 멱등성은 `resolve.py:upsert_edge`의
애플리케이션 레벨 SELECT-then-insert에만 의존한다. DB에 UNIQUE 제약이 없어, 우회 경로나
동시성에서 중복 엣지가 생길 수 있다. (현재 실측 위반 0건 — 앱 레벨 dedup이 지금까지 막아옴.)

## 2. 목표 / 비목표

### 목표 (In scope)
1. `parse_financial_rows`의 flow/stock 분기 처리 수정.
2. 오염된 `financial_facts` 전체 purge 후 DART 재적재 (반복 가능한 CLI).
3. 엣지 `(subject, predicate, object, period)` UNIQUE 제약 추가 (NULL period 포함 보장).
4. 경량 무결성 가드 모듈 — 재적재 검증 근거 + 상시 재발 방지.

### 비목표 (Out of scope)
- 엔티티 해소(ConceptAlias 시드, customer resolved/kind 투영) — Track B.
- 섹터/그룹/종목 연결 커버리지 — Track B.
- 정본(관계형 ↔ 그래프) 단방향 정리 — Track B.
- vault QA 노트(`_qa-report.md`)·frontmatter 보강 — Track C.
- flow 지표의 누적(YTD) vs 당기분 의미 구분 — 별도 과제(§7 한계).

## 3. 설계

### 3.1 파싱 수정 — `src/themek/ontology/ingest/financials.py`

- metric 종류를 명시 집합으로 분리:
  - `_FLOW = {"revenue", "operating_income", "net_income"}`
  - `_STOCK = {"assets", "liabilities", "equity"}`
- `parse_financial_rows`의 3개년 전개 로직 변경:
  - **flow**: 기존대로 `thstrm/frmtrm/bfefrmtrm` → `(yr, yr-1, yr-2)` 전개 유지.
  - **stock**: `thstrm`(당기, `yr`)만 적재. `frmtrm/bfefrmtrm`는 드롭.
- 근거: 각 연도의 interim stock 값은 그 연도 보고서의 `thstrm`으로 직접 확보되므로 데이터
  손실이 없다. FY stock 비교열도 그 연도 FY 보고서의 thstrm으로 확보된다.
- `_metric_of`의 sj_div 게이팅(`_METRIC_SJ`)은 그대로 유지(SCE/CF 오염 차단).

### 3.2 교정 실행 — `themek financials rebuild` CLI

- 동작: `DELETE FROM financial_facts` → `ingest_financials_all(session, client)` (회사별 실제
  제출 회계연도 기준, rate budget 존중) → `check_integrity(session)` 실행 후 요약 출력.
- 멱등: 재실행 안전. metric/period 노드는 기존 upsert로 유지.
- 출력: 삭제 행수, 재적재 fact 수, 실패 목록, 무결성 이슈 요약.

### 3.3 엣지 UNIQUE 제약 — `migrations/versions/0005_*.py`

- 함수형 UNIQUE 인덱스: `(subject_id, predicate, object_id, COALESCE(period, ''))`.
  - NULL period(구조적 IN_SECTOR/ISSUES_STOCK 6건)도 (s,p,o)당 1건 보장.
- ORM `Edge.__table_args__`에 동일 제약 반영(코드-스키마 패리티).
- 현재 위반 0건 — dedup 마이그레이션 단계 불필요. up/down 모두 정의.

### 3.4 무결성 가드 — `src/themek/ontology/validate.py` (순수 함수)

`check_integrity(session) -> list[Issue]` (Issue: `code`, `severity`, `message`, `subject` 필드):

- `interim_bs_equals_fy` (error): 동일 회사·연도에서 stock 지표의 Q1/H1/Q3 값이 FY와 정확히
  일치 → 1.1 버그의 시그니처.
- `duplicate_edge` (error): `(subject, predicate, object, period)` 그룹 카운트 > 1.
- `orphan_fact` (warn): `financial_facts.company_id`가 `nodes`에 없음.
- `negative_or_zero_equity` (info): 자본총계 ≤ 0 (참고).

파이프라인/CLI는 `error` 심각도 발견 시 경고 로그 + 비0 종료 코드. `info`/`warn`은 표시만.

## 4. 데이터 흐름

```
DART fnlttSinglAcntAll
  → parse_financial_rows (flow=3yr, stock=thstrm only)   [3.1]
  → ingest_financials_for_company → _upsert_fact
  → financial_facts

themek financials rebuild:                                 [3.2]
  DELETE financial_facts → ingest_financials_all → check_integrity → report

themek (pipeline export 단계 이후 또는 독립):
  check_integrity(session) → error 시 경고/비0 종료        [3.4]
```

## 5. 컴포넌트 경계

- `ingest/financials.py` — DART 응답 → fact 파싱·적재 (순수 파싱 + 얇은 적재). 변경: §3.1.
- `ontology/validate.py` (신규) — 세션 → 이슈 리스트. 순수 조회, 부작용 없음. §3.4.
- `cli.py` — `financials rebuild` 서브커맨드 추가. 오케스트레이션만. §3.2.
- `migrations/versions/0005_*.py` (신규) — 엣지 UNIQUE 인덱스. §3.3.

## 6. 테스트 (TDD)

1. `parse_financial_rows`:
   - interim(Q1/H1/Q3) 응답: stock 지표는 당기 1개만, flow 지표는 3개년 전개.
   - FY 응답: stock 지표도 당기만(yr) 적재.
   - 픽스처: 분기 BS 비교열을 포함한 카세트/응답 픽스처 1개 추가.
2. `check_integrity`:
   - 오염 합성 데이터(interim BS == FY) → `interim_bs_equals_fy` flag.
   - 클린 데이터 → 빈 리스트.
   - 중복 엣지 합성 → `duplicate_edge` flag.
3. 엣지 UNIQUE: 동일 (s,p,o,period) 중복 insert 시 `IntegrityError`. NULL period 중복도 차단.
4. migration 0005 up/down 스모크.
5. `financials rebuild` CLI: 인메모리/카세트로 purge→재적재→가드 흐름 end-to-end.

## 7. 알려진 한계 (문서화만)

- flow 지표의 분기값이 누적(YTD)인지 당기분인지 미구분 — DART 응답 의미 그대로 적재. 별도 과제.

## 8. 전체 넥스트 백로그 (참고)

### Track A · 정합성 (이번 spec)
1. 파싱 수정 (flow/stock 분기)
2. purge + DART 재적재 CLI
3. 엣지 UNIQUE 제약
4. 경량 무결성 가드

### Track B · 온톨로지 본질
5. 엔티티 해소 — ConceptAlias 시드 + customer `resolved/kind`를 노드 attrs로 투영 + 정규화
   함수 일원화(`normalize_alias` vs `slug`)
6. 섹터/그룹/종목 연결 적재 — IN_SECTOR · BELONGS_TO_GROUP · SUB_SECTOR_OF (현재 3/39)
7. 정본 결정 — 관계형(corp_models) ↔ 그래프 코어 단방향 파생으로 정리
8. 재무 metric 확장 — EPS · 현금흐름 · 발행주식수

### Track C · 탐색 가시성
9. vault `_qa-report.md` emit (check_integrity 재사용)
10. 회사 frontmatter 보강 — ticker/market/sector/periods/report_count/segment_count/issue_count
11. segment 과병합 완화 — 회사 prefix 옵션
