# DART 통합 파이프라인 오케스트레이션 — Design Spec

> **Status:** Draft (브레인스토밍 합의 완료, 사용자 검토 대기)
> **Date:** 2026-05-29
> **다음 단계:** 승인 후 `writing-plans`로 구현 plan 작성

## 1. 배경 · 문제

DART 파이프라인이 코어 온톨로지로 재설계됐지만(`ontology/` 패키지), 실제 적재·산출은 여러 명령을 수동으로 순서대로 실행해야 한다:
`themek dart sync-corp` → `themek dart incremental` → `themek ingest financials --years ...` → `themek vault build` → `themek ontology export-graph`.

특히 `ingest financials`는 `--years`를 **수동 입력**해야 한다. 사용자는 기간을 직접 정의하지 않고 **적재된 데이터에서 자동 도출**되길 원한다(기존 incremental이 보고서명에서 연도를 자동 추출하던 방식과 일관).

목표: **한 명령 `themek pipeline run`** 으로 전체 DART 파이프라인을 통합 구동하고, 재무 적재 연도를 자동 도출한다.

## 2. 목표 · 비목표

### 목표
- `themek pipeline run` 한 명령으로 sync → structure → financials → export 4단계 통합 실행.
- 재무 적재 연도를 **적재된 코어 데이터에서 자동 도출**(수동 `--years` 불필요).
- 단계별 skip 플래그로 유연하게 부분 실행.
- 오케스트레이션 로직은 `ontology/pipeline.py` 순수함수, CLI는 얇게.

### 비목표 (YAGNI)
- 병렬 실행·신규 재시도 정책 (기존 `RateBudget`/`run_incremental`에 위임).
- 신규 스케줄러 (cron 등은 사용자가 이 명령을 감싸 운용).
- backfill(universe×명시기간) 통합 — structure 단계는 incremental(자동기간)만 사용.

## 3. 아키텍처

```
themek pipeline run (CLI, 얇음)
  └─ run_pipeline(session, client, cache, *, stages, since, until,
                  universe, rate_budget, extractor, out_vault, out_graph)
        ├─ stage "sync"        → sync_corp_master(...)              (기존)
        ├─ stage "structure"   → run_incremental(since, until, ...) (기존, 자동기간)
        ├─ stage "financials"  → ingest_financials_all(session, client,
        │                          years=derive_financial_years(session))  (신규 얇은 래퍼)
        └─ stage "export"      → build_vault(out_vault) + export_graph(out_graph)  (기존)
     → PipelineResult (단계별 통계)
```

신규 파일:
- `src/themek/ontology/pipeline.py` — `run_pipeline`, `derive_financial_years`, `ingest_financials_all`, `PipelineResult`.

수정:
- `src/themek/cli.py` — `pipeline_app` 등록 + `pipeline run` 명령.

의존: `pipeline.py → {dart.corp_lookup, dart.incremental, ontology.ingest.financials, ontology.projection.vault, ontology.projection.graph_export, ontology.core.models}`.

## 4. 단계 의미 · 기간 자동화

| 단계 | 호출 | 비고 |
|------|------|------|
| sync | `sync_corp_master(client, cache)` | corp 마스터 캐시 갱신 |
| structure | `run_incremental(client, cache, session, universe, rate_budget, extractor, since, until)` | 신규 사업보고서 스캔→코어 적재. 기간: `since~until`, 기본 `yesterday→today`. 연도는 보고서명에서 자동 추출(기존 동작). |
| financials | `ingest_financials_all(session, client, years)` where `years = derive_financial_years(session)` | structure **다음에** 도출 → 방금 적재분 반영. years×company노드×4 reprt_code. |
| export | `build_vault(session, out_vault)` + `export_graph(session, out_graph)` | 산출물. |

### `derive_financial_years(session) -> list[str]`
코어 `edges` 테이블에서 `period`가 4자리 연도 패턴(`^\d{4}$`)인 distinct 값을 정렬해 반환. (사업구조 엣지 period = 회계연도.) 빈 리스트면 financials 단계는 경고 출력 후 skip.

### `ingest_financials_all(session, client, *, years) -> dict`
DB 내 모든 `kind="company"` 노드(attrs.dart_code 보유)에 대해 `years × {11011,11012,11013,11014}` 루프로 `ingest_financials_for_company` 호출. 회사별 try/except로 실패 수집. 반환: `{"facts": 총fact수, "companies": 처리회사수, "failed": [(corp, err)]}`.

### skip 플래그
`--skip-sync` / `--skip-structure` / `--skip-financials` / `--skip-export`. 기본 전부 실행. `stages` 인자는 skip 반영 후 실행할 단계 순서 리스트.

## 5. 에러 처리 · 출력

- **fail-fast:** DART 인증 실패(`DartAuthError`)·universe 로드 실패 등 설정성 오류는 즉시 exit≠0.
- **항목 관용:** structure는 `run_incremental`이 `failed` 리스트 반환(개별 보고서 실패 무시). financials는 회사별 try/except로 수집·계속.
- `PipelineResult` dataclass: `ran: list[str]`, `skipped: list[str]`, `structure: IncrementalRunResult|None`, `financials: dict|None`, `export: dict|None`. CLI는 단계별 한 줄 + 최종 요약 출력.
- `RateBudget`는 단일 인스턴스로 structure(+필요시 financials)에서 공유, 일일 캡 준수.

## 6. 테스트 전략

- **단위:** `derive_financial_years` — 엣지 시드(period "2023","2024",null,"2023") → `["2023","2024"]`. skip 플래그 → `ran`/`skipped` 분기.
- **단위:** `ingest_financials_all` — FakeClient(카세트) + company 노드 2개 + years=["2024"] → facts 적재 수·failed 처리.
- **통합:** `run_pipeline(stages 일부)` — FakeClient + stub extractor + 시드. 예: `--skip-sync --skip-structure` 로 financials+export만 → 재무 fact(도출 연도) + vault/graph 산출. 실 네트워크 불필요.
- **CLI:** `themek pipeline run --skip-sync --skip-structure --skip-financials --out-vault ... --out-graph ...` (export만) → exit 0 + vault/graph 생성.
- 기존 전체 스위트 회귀 0.

## 7. Acceptance Criteria

1. `derive_financial_years`가 코어 엣지 period에서 distinct 연도(4자리)만 정렬 반환, null/비연도 제외.
2. `ingest_financials_all`이 도출 연도 × 전 company × 4 reprt_code로 재무 적재, 회사별 실패 관용.
3. `run_pipeline`이 skip 플래그대로 단계 실행/생략, `PipelineResult`에 단계별 통계.
4. `themek pipeline run` 이 한 명령으로 4단계 구동, 재무 연도 자동(--years 불필요), exit 0.
5. 단계별·최종 요약 stdout 출력. 인증 실패 시 exit≠0.
6. 기존 전체 스위트 회귀 0.

## 8. Open Questions (구현 중 확정)
- universe 기본: incremental과 동일하게 `--universe-source file --universe-file <DEFAULT>` 계승.
- financials도 RateBudget 소비에 포함할지 — fnlttSinglAcntAll 호출 비용을 budget.consume에 반영(보수적). 구현 시 1콜=1 consume로 고정.
