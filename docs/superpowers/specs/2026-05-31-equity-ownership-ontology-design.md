# 지분구조(Equity Ownership) 온톨로지 설계

- 작성일: 2026-05-31
- 상태: 확정 (브레인스토밍 합의 완료)
- 선행 스펙: [`2026-05-22-korean-theme-stock-ontology-design.md`](2026-05-22-korean-theme-stock-ontology-design.md) — 원래 `owns` 관계(Corp→Corp, `stake_pct`, `affiliation_type ∈ {자회사, 계열사, 관계회사}`)를 명세했으나 미구현. 본 스펙이 이를 계승·확장한다.
- 선행 코어: [`2026-05-29-ontology-graph-core-design.md`](2026-05-29-ontology-graph-core-design.md) — Node/Edge/append-only bi-temporal 코어.

## 1. 목적과 배경

한국 테마주 시장에서 **지분구조는 주가에 직접 영향을 주는 1차 구조 사실(structural fact)**이다:
- 오너 일가/지주사의 지배 지분율과 그 변동(경영권 분쟁·승계·담보·매각).
- 같은 그룹 계열 묶임(한 테마가 계열사로 전이).
- 최대주주 변경(인수·합병 시그널).

현재 코어는 segment/customer/geographic/financial까지만 적재하며 **지분(ownership) 관계는 전무**하다. 본 작업은 DART 정형 API 2종을 소스로 회사 간·개인↔회사 지분 관계를 graph core에 적재한다.

## 2. 범위

### In Scope
- **최대주주·특수관계인 지분** (개인 오너 포함) — DART `hyslrSttus.json`
- **계열사·자회사 타법인 출자구조** (Corp→Corp) — DART `otrCprInvstmntSttus.json`
- 개인 주주를 위한 `person` 노드 신설.
- 연도별 스냅샷 시계열(append-only 엣지) — 변동은 연도 간 diff로 파생.
- 하이브리드 엔티티 해소(기본 회사별 + 시드 병합).
- Vault 투영 + 신규 CQ.

### Out of Scope (후속)
- 5%이상 대량보유·소액주주 분산도 (`mrhlSttus`).
- 임원·주요주주 소유보고 이벤트 (`elestock`).
- 최대주주 변동현황 전용 엔드포인트(`hyslrChgSttus`) — 연도 diff로 대체.
- 동명이인 자동 병합(전면 자동 resolution) — 오결합 위험으로 제외, 시드 기반만.

## 3. 데이터 소스 — DART 정형 API 2종 신규

기존 `DartClient.fetch_shares`(stockTotqySttus)와 동일 패턴(`method=api`, `status != "000" → []`)으로 메서드 2개 추가.

| 신규 메서드 | 엔드포인트 | 방향 | 핵심 필드(잠정) |
|---|---|---|---|
| `fetch_largest_shareholders` | `hyslrSttus.json` | 주주 → 보고회사 | `nm`(성명), `relate`(관계), `stock_knd`(주식종류), `trmend_posesn_stock_co`(기말 소유주식수), `trmend_posesn_stock_qota_rt`(기말 지분율) |
| `fetch_other_corp_investments` | `otrCprInvstmntSttus.json` | 보고회사 → 피출자회사 | `inv_prm`(법인명), `invstmnt_purps`(출자목적), `trmend_blce_qy`(기말잔액 수량), `trmend_blce_qota_rt`(기말 지분율) |

> 필드명은 DART OpenAPI 명세 기준의 **잠정값**이며, 구현 첫 단계에서 실 API 응답 픽스처로 정확히 확정한다(Recon task). 파라미터는 `crtfc_key, corp_code, bsns_year, reprt_code` 공통.

## 4. 노드 모델 — `person` 종류 신설

`NODE_KINDS`에 `"person"` 추가(migration으로 enum 확장). ID 스킴:

- **개인 주주(오너)**: `person:{slug(성명)}` — `ids.person_id(name)` 신설.
- **법인 주주 / 피출자회사**:
  - universe(corp_code 보유)에 있으면 → 기존 `company:{dart_code}`.
  - universe 밖 외부 법인 → `company:ext:{slug(법인명)}` — `ids.external_company_id(name)` 신설. customer와 동일 발상의 이름-slug 노드. 이후 `normalize_corp_name` + ConceptAlias로 universe 회사에 resolve 가능.
- **사람 vs 법인 판별 휴리스틱**:
  1. 법인 접미사 매치(`(주)`, `㈜`, `주식회사`, `유한회사`, `Inc`, `Corp`, `Co.,Ltd`, `Ltd`, `LLC`, `홀딩스` 등) → company.
  2. `relate`(관계)가 명백한 법인 관계(`계열회사`, `법인` 등) → company.
  3. 그 외(본인/배우자/자녀/친인척 등 개인 관계, 또는 접미사 없음) → person.
  - 판별 규칙은 단위 테스트로 고정.

## 5. 엣지 모델 — 단일 술어 `OWNS_STAKE_IN` (보유자 → 피보유 회사)

`PREDICATES`에 `"OWNS_STAKE_IN"` 추가(migration). 방향은 **항상 보유자(holder) → 피보유(held company)**, 두 케이스를 하나의 술어로 통일한다.

- 최대주주: `person|company ──OWNS_STAKE_IN──▶ company`(보고회사)
- 타법인출자: `company ──OWNS_STAKE_IN──▶ company`(피출자회사)

`qualifier`(JSON) 필드:
| 키 | 타입 | 케이스 | 설명 |
|---|---|---|---|
| `stake_pct` | float\|null | 공통 | 기말 지분율(%) |
| `shares` | int\|null | 공통 | 기말 소유/보유 주식수 |
| `relation` | str\|null | 최대주주 | `relate` 원문(본인/배우자/계열회사 등) |
| `affiliation_type` | str\|null | 타법인출자 | 출자목적 기반 분류 `자회사`/`계열사`/`관계회사`/`기타`(원래 스펙 `owns.affiliation_type` 계승) |
| `is_largest` | bool | 최대주주 | 해당 보고서 최대주주 그룹 본인 여부(`relate`가 본인/최대주주) |

- `period`: 사업연도(`"2023FY"` 형식, 기존 컨벤션).
- `source_type=dart_api`, `method=api`, `confidence=1.0`.
- append-only + 기존 `ux_edge_spo`(subject·predicate·object·coalesce(period)) 유니크로 **멱등**.
- **변동 파생**: 동일 (holder, held)에 대해 연도별 엣지를 쌓으면 `stake_pct` 시계열이 생기고, 연도 간 diff로 최대주주 변경·지분율 변동을 파생 질의한다. 별도 엔드포인트 불필요.

## 6. Ingest 파이프라인

`src/themek/ontology/ingest/equity.py` 신설 — `financials.py` ingest와 형제 구조.

- `ingest_largest_shareholders(session, *, corp_code, bsns_year, rows, source_ref) -> int`
  - 각 row: 판별→person|company 노드 upsert → `OWNS_STAKE_IN` 엣지 upsert. 적재 엣지 수 반환.
- `ingest_other_corp_investments(session, *, corp_code, bsns_year, rows, source_ref) -> int`
  - 각 row: 피출자 법인 노드(universe면 company, 아니면 company:ext) upsert → `OWNS_STAKE_IN` 엣지 upsert. 적재 엣지 수 반환.
- 멱등: 동일 입력 재적재 시 엣지 수 불변.

### CLI / 오케스트레이션
- `themek equity ingest --ticker <6자리> --period <YYYY>` — 단종목 fetch+ingest.
- `themek pipeline`에 equity 단계 편입(재무 적재와 같은 연도 도출 로직 재사용).
- DART 호출은 기존 `cache` + `RateBudget` 인프라 경유.

## 7. 엔티티 해소 — 하이브리드 (기존 패턴 재사용)

- 기본: 회사별 `person`/`company:ext` 노드로 안전 적재(자동 병합 없음).
- `seed_aliases`(기존)에 **오너 시드**(예: 핵심 오너 성명→정규 person 노드)와 **외부 법인 시드**(외부 법인명→universe company) 추가.
- `resolve` 단계에서 ConceptAlias로 병합 — 기존 `resolve_customers`/`merge_segments`/`normalize_corp_name` 인프라 그대로 확장(신규 resolution 함수가 person/external-company에도 적용되도록 일반화).
- 오너 지배구조 맵은 시드된 person의 `OWNS_STAKE_IN` fan-out으로 응답.

## 8. Vault 투영 + 쿼리

- **회사 markdown**: 「지분구조」 섹션 렌더.
  - 최대주주·특수관계인 표(보유자 `[[wikilink]]` + 지분율, 관계).
  - 타법인출자 목록(피출자 `[[wikilink]]` + 지분율 + affiliation_type).
  - frontmatter 보강: `largest_shareholder`, `owner_stake_pct`.
- **person 노드 투영**: `vault/people/{성명}.md` 신설 → 오너별 보유 회사 backlink → Obsidian 그래프뷰에 지배구조 자연 표출.
- **신규 CQ**:
  - "이 회사 최대주주 누구?" — held=회사인 `OWNS_STAKE_IN` 역방향.
  - "이 오너가 지배하는 상장사들?" — person의 `OWNS_STAKE_IN` fan-out.
  - "이 회사가 출자한 계열사?" — holder=회사인 `OWNS_STAKE_IN` 정방향.

## 9. 검증 (프로덕션 적재)

구현 후 **실 DART API로 약 40개사 × 직전 사업연도** 적재하고 의도대로 들어갔는지 검증한다(상세는 구현 플랜의 검증 task).
- 적재 종목 수·엣지 수·person/company:ext 노드 수 카운트.
- 지분율 합 sanity(최대주주 그룹 ≤ 100%), null/이상치 비율.
- 표본 수기 대조(예: 삼성전자 최대주주, 지주사 출자구조)로 정확도 확인.
- vault 렌더 + CQ 질의 실제 동작 확인.

## 10. 테스트 전략 (TDD)

`tests/ontology/`·`tests/dart/` 컨벤션 준수:
- client fetch — 픽스처 JSON 기반 파싱/비정상 status.
- person/company 판별 휴리스틱 단위 테스트.
- `OWNS_STAKE_IN` 멱등 적재(person→company, company→company, company:ext).
- 외부법인 resolve(시드 alias → universe company 병합).
- vault 렌더(지분구조 섹션 + people 노드).
- 연도 diff 파생(2개 연도 적재 → 지분율 변동 검출).

## 11. 마이그레이션 영향

- enum 확장 2건: `node_kind`에 `person`, `edge_predicate`에 `OWNS_STAKE_IN`.
- SQLite는 enum이 문자열이라 무해, PostgreSQL은 `ALTER TYPE ... ADD VALUE` 마이그레이션 필요(기존 0007 metric enum 확장 선례 따름).
- 신규 테이블 없음 — 기존 Node/Edge/ConceptAlias 재사용.
