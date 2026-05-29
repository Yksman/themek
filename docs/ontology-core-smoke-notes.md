# 온톨로지 코어 smoke build notes (2026-05-29)

graph-ready 코어(`themek.ontology`) cutover 후 실제 DB(`themek.db`)에 대한 smoke
검증 기록. Task 5.2 measurable gate의 실행 수치다.

## 환경

- DB: `sqlite:///./themek.db` (cutover 전 `themek.db.pre-core.bak`로 백업)
- 코어 테이블 생성: `Base.metadata.create_all` (additive) → `nodes`/`edges`/
  `financial_facts`/`concept_aliases` 생성
- DART_API_KEY: 미설정 → 실 재무 적재는 best-effort(게이트 아님)로 skip

## 실행 결과 (Step 1–4)

| 단계 | 명령 | 결과 |
|------|------|------|
| seed | `themek seed` | exit 0, company 노드 **3** (삼성전자/현대자동차/레인보우로보틱스) |
| vault | `themek vault build --out vault` | exit 0, `vault/companies/*.md` **3개** |
| export | `themek ontology export-graph --out graph` | exit 0, **nodes=15, edges=6** |
| 무결성 | nodes/edges 참조 점검 스크립트 | `nodes=15 edges=6 broken_refs=0` |
| screen | `themek query screen --segment 반도체 --metric operating_income --positive-since 2023FY` | exit 0, `matched: 0` |

`broken_refs=0` — 모든 엣지 endpoint가 노드 집합에 존재(graph-readiness 충족).

`screen` matched=0 은 정상이다: 시드만 적재한 상태로 `financial_facts`가 비어 있어
연속 흑자 조건을 만족하는 회사가 없다. exit code(0)만 게이트 대상.

## 실 DART 재무 적재 (Step 2, 게이트 아님)

`themek ingest financials --years 2022-2024`는 DART_API_KEY/네트워크 의존이라
환경에 따라 결과가 달라져 **measurable gate에서 제외**한다. 재무 파서/적재의
결정론적 검증은 카세트 기반 단위테스트로 이미 충족:

- `tests/test_dart_financials.py` (2 passed)
- `tests/ontology/test_financials_parse.py` (3 passed)
- `tests/ontology/test_financials_ingest.py` (3 passed)

키가 있는 환경에서 `themek ingest financials --years 2022-2024` 실행 후 적재량 N과
`themek query screen` 결과를 본 메모에 추가 기록할 것.

## 전체 테스트 스위트

`uv run pytest -q` → **260 passed** (구 온톨로지 테스트 제거 후, 신규 ontology
테스트 34개 포함, 백필/KRX 서브시스템 테스트 유지).

## cutover 메모

- 구 `themek.db.models`는 운영 모델(Corporation/Stock/BusinessReport/
  BackfillTarget + FK 대상 Sector/Group)을 `themek.db.corp_models`로 분리하고
  나머지(구 온톨로지 모델)는 제거했다 — 활성 백필/KRX 서브시스템 보존.
- `ingest_business_report`는 `BusinessReport` 행(incremental dedup용)을 유지하면서
  사업 구조는 코어 `ingest_business_structure`로 적재하도록 재배선.
