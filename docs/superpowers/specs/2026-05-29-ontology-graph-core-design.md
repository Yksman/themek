# 온톨로지 graph-ready 코어 + 재무 pilot — Design Spec

> **Status:** Draft (브레인스토밍 합의 완료, 사용자 검토 대기)
> **Date:** 2026-05-29
> **Author:** themek + Claude (brainstorming)
> **다음 단계:** 이 spec 승인 후 `writing-plans`로 구현 plan 작성

## 1. 배경 · 문제

현재 themek은 DART 사업보고서에서 **사업구조(세그먼트·고객·지역)** 만 LLM으로 추출해 관계형 DB에 적재하고, Obsidian vault로 투영한다. 다음 두 한계가 있다:

1. **정량 데이터 부재** — 실적/재무제표가 온톨로지에 없다. "2Q.25부터 지속 흑자인 기업" 같은 정량 시계열 질의에 답할 수 없다.
2. **질의 표현 부재** — 교차-회사 분석 질의 인터페이스가 없다(현재 `query e5`는 회사별 조회만). 어떤 서비스를 올려도 "유의한 응답"을 줄 안정적 계약이 없다.

사용자는 곧 **전 상장사(~2,800) DART 적재 + 소셜 데이터 적재**로 확장할 계획이다. 따라서 지금 **재무를 단발성으로 붙이는 것이 아니라**, 향후 모든 vertical(재무·지분·소셜)이 동일 규약으로 꽂히고 어떤 서비스에도 질의 가능한 **graph-ready 온톨로지 코어**를 설계한다. 재무는 이 코어를 검증하는 **첫 pilot vertical**이다.

현재 데이터(44개사)는 샘플링/검증용이며 **언제든 재수집 가능** → 데이터 보존 마이그레이션 없이 **전면 클린 재설계**한다.

## 2. 목표 · 비목표

### 목표
- 엔티티·관계·정량 fact를 **타입 명확 + 관계 명시 + 안정적 질의 인터페이스**로 표현하는 코어 스키마.
- 향후 graph DB(Neo4j)/RDF로 **재설계 없이 export** 가능한 graph-native 규약(안정 ID·균일 엣지·provenance·개념 정규화).
- 재무 pilot: DART 정형 API로 핵심 KPI 시계열 적재.
- competency-query 레이어로 예시 질의를 **실제로 답함**을 end-to-end 증명.
- vault projection + graph export 두 갈래로 projection 경계를 증명.

### 비목표 (deferred — 규약은 수용하도록 설계하되 이번 구현 제외)
- 소셜 데이터 vertical, 지분관계 vertical.
- 제품(product) 1급 concept 승격, 대량 LLM 개념 정규화(군집).
- KPI 외 전체 재무계정 line item.
- Neo4j/RDF 실시간 스토어(이번엔 export 산출로 graph-readiness만 증명).
- 분기/반기 손익의 단기(3개월) 환산.

## 3. 핵심 원칙

> "온톨로지"의 본질은 저장 엔진이 아니라 **타입 있는 엔티티 + 명시적 관계 + 안정적 질의 인터페이스**다.

- **관계형 = system-of-record**, graph-native 규약 준수 → graph/RDF는 다운스트림 export.
- 서비스(미래 API/MCP 포함)는 **competency-query 레이어**만 의존 → 저장 진화 가능.
- 모든 fact/edge에 **provenance + confidence** → 정형 DART와 노이즈 큰 소셜 데이터 혼합 대비.

## 4. 아키텍처

```
DART API / (향후)소셜  →  ingest (provenance 부착)  →  ┌─ 코어 저장소 (관계형, graph-ready) ─┐
                                                      │  nodes · edges · financial_facts   │
                                                      │  concept_aliases                   │
                                                      └────────────────────────────────────┘
                                                                    │
                        ┌───────────────────────────┬──────────────┴───────────────┐
                competency-query 레이어        projection: vault(md)        projection: graph export
                (SQL/SQLAlchemy, 안정 계약)      (Obsidian)                   (nodes.json/edges.json)
```

신규 패키지 `src/themek/ontology/`:
- `core/models.py` — nodes·edges·financial_facts·concept_aliases ORM
- `core/ids.py` — 안정 ID 스킴 (`{kind}:{natural_key}`)
- `core/resolve.py` — concept resolver (정확일치 + 수동 별칭)
- `ingest/business_structure.py` — LLM 추출 결과 → nodes/edges
- `ingest/financials.py` — DART 재무 API → financial_facts
- `projection/vault.py` — 코어 → Obsidian markdown (기존 `vault/` 대체)
- `projection/graph_export.py` — 코어 → nodes.json/edges.json
- `query/screen.py` — competency 스크리닝 함수

의존 방향: `cli → {ingest, projection, query} → core`. projection·query·ingest는 core에만 의존.

## 5. 코어 스키마 (하이브리드: 프로퍼티그래프 + 정형 fact)

### 5.1 `nodes` — 그래프 노드(정체성)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | str PK | 전역 안정 ID `{kind}:{natural_key}` |
| `kind` | enum | company·stock·sector·region·segment·customer·period·metric·group (향후 person·social_topic 확장) |
| `label` | str | 표준 표시명(ko) |
| `attrs` | JSON | kind별 소규모 속성 (name_en, market, ticker 등) |

**ID 예:** `company:00126380`, `stock:005930`, `sector:G2520`, `region:US`, `period:2025Q2`, `segment:hbm`, `customer:apple-inc`, `metric:operating_income`.
- 자연키 있는 종류(company=dart_code, stock=ticker, sector=fics, region=code)는 자연키 사용.
- 개념 노드(segment·customer)는 정규화 라벨 slug. 충돌/장문은 slug+해시(기존 `customer_slug` 규칙 재사용).

### 5.2 `edges` — 정성 관계(균일 형태)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | PK | |
| `subject_id` | FK→nodes | |
| `predicate` | enum | HAS_SEGMENT·SELLS_TO·EXPOSED_TO·IN_SECTOR·ISSUES_STOCK·BELONGS_TO_GROUP·SUB_SECTOR_OF |
| `object_id` | FK→nodes | |
| `period` | str? | 시점 qualifier (`2023`·`2025Q2`), nullable |
| `qualifier` | JSON | 관계 속성 (share_pct·tier 등) |
| `source_type` | enum | dart_api·dart_report·social·llm·manual |
| `source_ref` | str? | rcept_no / url |
| `method` | enum | api·llm·manual |
| `confidence` | float | 0.0~1.0 |
| `extracted_at` | datetime | |

관계 예: `company:00126380 -HAS_SEGMENT{period:2023, share_pct:42.5}-> segment:메모리반도체`.

### 5.3 `financial_facts` — 정량 시계열(typed, SQL 집계)
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `id` | PK | |
| `company_id` | FK→nodes | |
| `bsns_year` | str | `2024` |
| `fiscal_period` | enum | FY·Q1·H1·Q3 |
| `fs_div` | enum | CFS(연결)·OFS(별도) |
| `metric_key` | enum | revenue·operating_income·net_income·assets·liabilities·equity |
| `amount` | Numeric | |
| `currency` | str | 기본 KRW |
| provenance | (위 5필드 동일) | source_type=dart_api, method=api, confidence=1.0 |

유니크: `(company_id, bsns_year, fiscal_period, fs_div, metric_key)`.
- 파생비율(영업이익률·부채비율·ROE)은 **저장 안 함** — 렌더/쿼리 시점 계산.
- 분기/반기 손익은 YTD 누적 그대로 저장, `fiscal_period`로 구분(단기 환산은 deferred).

### 5.4 `concept_aliases` — 개념 정규화
| 컬럼 | 타입 | 설명 |
|------|------|------|
| `alias_norm` | str | 정규화 텍스트(소문자·공백단일화) |
| `node_id` | FK→nodes | 표준 concept 노드 |
| `source` | enum | manual·exact·llm(향후) |
| `confidence` | float | |

이번 구현: 정확일치 + 수동 별칭 resolver만. "HBM" 등은 세그먼트 개념 alias로 해소. 대량 자동 정규화는 deferred.

## 6. 재무 pilot (DART 정형 API)

### 6.1 DART client
신규 메서드 `fetch_financials(corp_code, bsns_year, reprt_code, fs_div) -> dict` — `fnlttSinglAcntAll.json`.
- `reprt_code`: 11011(FY)·11012(H1)·11013(Q1)·11014(Q3)
- `fs_div`: **CFS 우선 → 비어있으면 OFS fallback**
- 응답 행: `account_id`·`account_nm`·`sj_div`(BS/IS/CIS/CF)·`thstrm_amount`(당기)·`frmtrm_amount`(전기)·`bfefrmtrm_amount`(전전기)·`rcept_no`
- **1콜 = 3개년** → 자동 시계열.

### 6.2 account → metric 매핑
`account_id`(IFRS 표준ID) 우선, `account_nm` fallback:
| metric_key | account_id 후보 | account_nm 후보 |
|-----------|----------------|----------------|
| revenue | ifrs-full_Revenue | 매출액·수익(매출액) |
| operating_income | dart_OperatingIncomeLoss | 영업이익 |
| net_income | ifrs-full_ProfitLoss | 당기순이익 |
| assets | ifrs-full_Assets | 자산총계 |
| liabilities | ifrs-full_Liabilities | 부채총계 |
| equity | ifrs-full_Equity | 자본총계 |

매핑 안 되는 계정은 무시(KPI 세트만).

### 6.3 ingest
`ontology/ingest/financials.py`:
- 회사×reprt_code 루프 → API 호출(CFS→OFS fallback) → 파싱 → 3개년 `financial_facts` upsert + 해당 `period`·`metric` 노드 보장(graph export·query가 참조).
- CLI: `themek ingest financials --years 2022-2024 [--corp <code>]`.

## 7. Projection

### 7.1 vault (기존 `vault/` 대체)
코어(nodes/edges/financial_facts) 읽어 markdown 렌더. 기존 vault 기능 유지 + 회사 노트에 추가:
- `## 재무 (연결, 단위 원)` — 기간×KPI 시계열 표 + 파생비율(영업이익률·부채비율·ROE, 렌더 시점 계산).
- 기간별 KPI를 **Dataview 인라인 필드**로도 emit(`operating_income_2025Q2:: ...`) → Obsidian 내 경량 질의.
- 멱등성 유지(기존 규약).

### 7.2 graph export
`ontology/projection/graph_export.py` → `nodes.json` + `edges.json`. financial_facts는 measurement 엣지(`company -REPORTS{period, metric, fs_div, amount}-> metric`)로 투영. Neo4j 인프라 없이 graph-readiness 증명. CLI: `themek ontology export-graph --out graph/`.

## 8. competency-query 레이어

`ontology/query/screen.py` — 안정 계약 함수(서비스가 의존):
- `companies_with_segment_concept(concept_id) -> set[company_id]` — HAS_SEGMENT + concept alias 해소.
- `primary_segment(company_id, period) -> segment_id` — **주력 = 해당 회사/기간 share_pct 최대 HAS_SEGMENT**.
- `consecutive_positive(metric_key, since_period, fs_div) -> set[company_id]` — `financial_facts` 위 SQL window로 "since_period부터 연속 양수".
- 조합 데모 CLI: `themek query screen --segment hbm --metric operating_income --positive-since 2025Q2`
  → "주력 세그먼트가 HBM 개념에 매칭 + 영업이익 2025Q2부터 연속 흑자" 회사 집합 반환.

**"주력" 정의(확정):** 최대 매출비중 세그먼트(top-1 share_pct). "HBM" 등 키워드 = 세그먼트 개념 alias 매칭. 제품 단위 정밀도(B안)는 deferred.

## 9. 마이그레이션 범위 · plan 단계

**영향권(전면 재설계, 데이터 미보존 → 재적재):**
- 교체: `db/models.py` → 코어 모델, `seeds`
- 재작성: `ingest/business_report.py`(→ nodes/edges), 신규 `ontology/ingest/financials.py`
- 재작성: `vault/*` → `ontology/projection/vault.py`, 신규 `graph_export.py`
- 재작성/대체: `query/e5.py` → `ontology/query/*`, `eval/*` 적응, `cli.py`
- 신규 client 메서드(financials) + DART 재무 카세트

**plan 단계화(writing-plans가 시퀀싱):**
1. 코어 스키마 + 모델 + ID/resolver/provenance 규약 (+단위테스트)
2. ingest 재작성: 사업구조(nodes/edges) + 재무(financial_facts) + 재적재
3. projection: vault 재작성 + graph export
4. competency-query + CLI(screen 데모)
5. 실 DART 44개사 재적재 + 예시질의 end-to-end 검증

## 10. 테스트 전략

- **단위:** ID 스킴 · concept resolver(정확일치/별칭) · account→metric 매핑 · 파생비율 · `consecutive_positive` window 로직(in-memory SQLite 시드).
- **통합:** `fnlttSinglAcntAll` 카세트 → financial_facts 적재 · vault projection 멱등 · graph export 노드/엣지 무결성.
- **end-to-end (핵심 acceptance):** 시드 데이터로 "HBM 주력 + 2025Q2부터 연속 흑자" 스크리닝이 정답 회사 집합 반환 → 예시질의가 *실제로 답됨* 검증.
- 기존 전체 스위트 회귀 0 유지(대체된 모듈은 신규 테스트로 교체).

## 11. Acceptance Criteria

1. 코어 4테이블(nodes·edges·financial_facts·concept_aliases) 생성 + 안정 ID 규약 단위테스트 통과.
2. DART 재무 API 카세트로 1개사 3개년 KPI 적재(CFS→OFS fallback 동작).
3. vault 회사 노트에 재무 시계열 표 + 파생비율 렌더, 멱등.
4. graph export가 nodes.json/edges.json 생성, financial_facts measurement 엣지 포함, 깨진 참조 0.
5. `themek query screen` 이 예시질의("HBM 주력 + 2025Q2부터 연속 흑자")에 정답 집합 반환(e2e 테스트).
6. 실 DART 44개사 재적재 후 전체 스위트 회귀 0.

## 12. Open Questions (구현 중 확정)
- DART `fnlttSinglAcntAll` 무료 키 호출 한도/레이트 — 기존 rate_budget 재사용 여부.
- `period` 노드 라벨 규약(`2025Q2` vs `2025-Q2`) — 구현 시 1개로 고정.
- Dataview 인라인 필드 키 네이밍 — 구현 시 확정.
