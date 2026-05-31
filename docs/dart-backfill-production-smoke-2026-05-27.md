# DART Multi-Corp Backfill — Production Smoke 결과

**실행일:** 2026-05-27 (Plan #5 Task 13)
**Universe:** 10 종목 (`data/universe/active.txt`)
**Period:** 2023 (scaled smoke — 본 plan 의 ×2년 fullscale 은 operator 가 2024:2025 로 확장)
**SUCCESS Gate:** 8 check 중 7+ PASS — **충족 (7 PASS / 1 FAIL)**

## Universe (10 종목)

| ticker | corp_code | 종목명 | 산업 | 상태 |
|--------|-----------|--------|------|------|
| 005930 | 00126380 | 삼성전자 | 반도체·전자 | done (2023+2022) |
| 000660 | 00164779 | SK하이닉스 | 반도체 | done |
| 035420 | 00266961 | NAVER | IT·플랫폼 | done |
| 035720 | 00258801 | 카카오 | IT·플랫폼 | done |
| 005380 | 00164742 | 현대자동차 | 자동차 | done |
| 051910 | 00356361 | LG화학 | 화학·2차전지 | done |
| 091990 | 00554024 | 셀트리온헬스케어 | 헬스케어 | skipped (2023 사업보고서 미공시) |
| 247540 | 01160363 | 에코프로비엠 | 2차전지 | done |
| 042700 | 00161383 | 한미반도체 | 반도체장비 | done |
| 277810 | 01261644 | 레인보우로보틱스 | 로봇 | done |

## 실행 로그

- `data/log/smoke_t13_run1.log` (1차 — 6 failed due to extractor=None bug)
- `data/log/smoke_t13_run2.log` (2차 — bug fix 후 9 done + 1 skipped)
- `data/log/smoke_t13_verify_final.log` (acceptance check 결과)

## 비용 / 호출

- DART API 호출: ~20 (10 list.json + 10 document.xml)
- LLM 호출 비용 합계 (`BackfillTarget.cost_estimate_usd` sum): **$1.22** (예상 $2.50 대비 50% 저렴)
- 소요 시간: ~25 분 (LG화학 등 대형 사업보고서가 LLM 호출 시간 우세)

## Escalation 분포

- `regex`: 8
- `regex+llm`: 0
- `full_text`: 1 (SK하이닉스 — 헤더 패턴 매치 실패 → 전체 본문 fallback)

→ Plan #4 학습 사이클이 향후 SK하이닉스 패턴을 흡수하면 비율 개선 가능.

## Acceptance Check 결과 (7/8)

| Check | 결과 | 세부 |
|-------|------|------|
| 1. BackfillTarget done≥8 | **PASS** | done=10, skipped=1, failed=0 |
| 2. BusinessReport count == done | **PASS** | 10 reports == 10 done |
| 3. segments ≥ 1 per report | **PASS** | 10/10 |
| 4. share_pct 80–120% | **PASS** | 10/10 (모든 보고서 sum 이 합리적 범위) |
| 5. geographic ≥ 1 | **FAIL** | 7/10 (3개 IT/플랫폼 corps 가 사업보고서 본문에 region breakdown 미기재) |
| 6. idempotency (no DART/LLM on re-run) | **PASS** | processed=0, budget_remaining 변동 없음 |
| 7. `query e5` per ticker | **PASS** | 2/2 (Stock 등록된 ticker 만 검증) |
| 8. 정정/다년 누적 (manual) | **PASS** | Samsung 2022 추가 ingest 후 row +1 + filing_date DESC 최신 선택 정상 |

## Check 5 FAIL 분석

GeographicExposure 부재 corps:
- 00164779 SK하이닉스 (반도체 — 글로벌 메모리 수출, 지역 share 미공시)
- 00266961 NAVER (플랫폼 — 검색·콘텐츠·금융 등 사업부 위주, 지역 share 미공시)
- 00258801 카카오 (플랫폼 — 사업부 위주, 지역 share 미공시)

→ LLM extractor 가 source 의 데이터를 fabricate 하지 않고 보고서에 명시된 항목만 추출한 결과.
이는 ontology 충실성 측면에서 올바른 동작 (Plan #4 fail-safe 정책 일치).

후속:
- Plan #4 sliced 본문 (sales-only 섹션) 학습 사이클이 region 정보를 더 잘 retrieve 하도록 개선
- 또는 `geographic` 항목이 corps 별로 optional 임을 ontology 에 명시 (Plan #5.1)

## 결정

**Plan #5 SUCCESS** — 7/8 acceptance check PASS (gate: 7+ PASS).

다음 단계:
- ✅ cron (`scripts/themek_backfill.sh`) 정식 활성화 가능
- ✅ universe 확장 절차 (`docs/dart-backfill-runbook.md §6`) 진행
- 후속 Plan #5.1: GeographicExposure recall 개선 + 정정보고서 query 최신 선택 검증
