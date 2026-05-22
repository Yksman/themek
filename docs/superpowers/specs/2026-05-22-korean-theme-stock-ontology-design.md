---
title: 한국 테마주 시장 Ontology — Design Spec
date: 2026-05-22
status: Draft v1 (Steps 1–7 합의 완료)
scope: Ontology schema 본체 (구현 layer는 별도 plan으로 분리)
---

# 한국 테마주 Ontology — Design Spec

## 1. Vision & Product

**제품 정의:** 한국 테마주 시장에 최적화된 ontology를 1차 제품(정보 서비스의 핵심 자산)으로 보유·운영. 사용자는 자연어로 질의하고, 시스템은 ontology를 traversal해 LLM이 합성한 답을 인용·구조와 함께 반환.

**핵심 명제:** 한국 시장(특히 테마주)은 반복된다. 어떤 이벤트가 어떤 테마를 활성화시키고, 그 테마에서 어떤 종목이 어떤 narrative로 움직였는지가 텔레/블로그/팍스넷·DART에 기록되어 있다. 이 기록을 *2-layer grounded ontology*(social + structural)로 구조화한 결과물이 모트.

**모트의 위치:** 데이터 raw 자체가 아니라 그래프의 **링크 정확도·시간 축적·dual-grounding 검증 결과**. 후발주자가 6개월 늦으면 6개월치 link 형성 과정을 복원하지 못함.

**핵심 차별화 vs ChatGPT/Perplexity:** 모든 narrative가 (a) social source 인용 + (b) 사업보고서 구조 검증 양쪽으로 grounded. ChatGPT는 (b) 인프라가 없음.

**시간 무게중심:** 역사·구조형. 실시간 시그널은 비목표.

---

## 2. Scope

### 2.1 In-Scope

- 데이터 소스 4종: 텔레그램(선별 채널) · 네이버 블로그 · 팍스넷 종목토론방 · DART(공시 + 사업보고서/반기/분기보고서)
- 자연어 쿼리 → ontology traversal + LLM 합성
- 종목·테마·이벤트·인물·내러티브·사업구조의 dual-layered 지식 그래프
- "최신 + 1년 전" 2-snapshot 사업보고서 버전 관리
- 24개월 backfill (잠정 — 구현 단계 확정)

### 2.2 Out-of-Scope (의도적 비목표)

- 매수/매도 추천 또는 의견 표시 (자본시장법 회피)
- 실시간 시계열 데이터 (가격·거래량·수급)
- 큐레이터 마켓플레이스 / source 신뢰도 점수
- "주포가 누구야" 류 세력 추정
- 가격 magnitude 정보 (외부 price store와 join 시 별도 layer)
- 시장 국면 / 매크로 regime (후순위 확장)

---

## 3. Competency Questions

### 3.1 External CQs (사용자가 자연어로 던지는 질문)

| ID | 질문 패턴 (개미 자연어) | 의도 |
|---|---|---|
| E1 | "이거 왜 빠짐?" / "지금 [종목] 왜 오르냐?" | 현재 움직임의 원인 |
| E2 | "[뉴스/공시] 떴는데 호재 맞아? 어디 사야 함?" | 이벤트 해석 + 수혜주 |
| E3 | "지금 [테마] 대장주 누구? 2등주는?" | 테마 내 위계 |
| E4 | "예전에도 [이런 거] 있었나? 그때 어떻게 갔어?" | 과거 유사 사례 |
| E5 | "이 회사 뭐 만들어? 매출 어디서 남?" | 사업 구조 요약 |
| E6 | "[종목] 이 테마 진짜 수혜 맞아? 끼워 맞춘 거 아냐?" | narrative 검증 |
| E7 | "[종목]이랑 같이 움직이는 애들?" | co-mover discovery |
| E8 | "지금 뭐가 핫함? 시장 분위기?" | 현재 활성 테마 |

### 3.2 Internal Capabilities (E를 답하기 위한 내부 능력)

| ID | 능력 | 사용처 |
|---|---|---|
| I-1 | Event → 활성화 Themes 매칭 (semantic + structural) | E1, E2, E4 |
| I-2 | Theme → 구조적 노출 stocks (사업보고서 기반) | E2 정확도, E6 |
| I-3 | Theme → social 멤버십 stocks (텔레/블로그 기반) | E2, E3, E7 |
| I-4 | Narrative ↔ structural 사실 cross-check | E6 직접, E2 ranking |
| I-5 | Stock → BusinessReport summary | E5 |
| I-6 | Event analog 검색 | E4 직접, E1·E2 historical context |
| I-7 | Stock → recent Activation trigger 후보 | E1 |
| I-8 | Theme 활성화 시계열 집계 | E8, E3 role 변화 |
| I-9 | Corp BusinessReport 시계열 diff | 추후 신사업 진입 발굴용 |
| I-10 | Customer/Supplier 그래프 traversal | E2의 그룹/협력사 라인 정확도 |
| I-11 | Figure ↔ Theme 매핑 (정치테마) | E2, E4의 정치테마 답 정확도 |

---

## 4. Reused Ontologies & Standards

**Light-reuse 원칙(가)** 채택: 외부 표준의 class 정의·속성·식별자만 차용, OWL/SPARQL full conformance 강제 안 함. JSON-LD로 표현 가능한 수준.

| 표준 | 차용 정도 | 차용 부분 |
|---|---|---|
| FIBO | Light | Stock(EquitySecurity), Corporation, Listing 속성명 |
| KRX FICS | 직접 | Sector 분류 그대로 |
| DART 공시 분류체계 | 직접 | Disclosure.disclosure_type (200여 코드) |
| XBRL K-IFRS | 부분 | 재무·매출 segment 일부. 비정형 "사업의 내용"은 LLM 추출 |
| schema.org | 호환 | JSON-LD interop layer만 |
| Wikidata | 식별자 | Figure·Corporation QID cross-reference |
| ISIN / KRX Ticker | 직접 | 종목 primary key |
| GICS | 옵션 | 해외 이벤트 cross-reference 시 |
| BFO / DOLCE | 미사용 | overkill |

### 4.1 식별자 전략

| Entity | Primary | Secondary |
|---|---|---|
| Stock | KRX Ticker (6자리) | ISIN, FIBO URI |
| Corporation | DART 기업코드 (8자리) | Wikidata QID, 사업자등록번호, FIBO LEI |
| Disclosure / BusinessReport | DART rcept_no | URL |
| Figure | Wikidata QID | 내부 ID |
| Source (Post) | (channel/blog/board ID, post ID) | URL hash |
| Sector | KRX FICS code | — |
| Theme / Narrative / Activation / Membership / Revenue·Customer·Supply·Geographic | 내부 UUID | (외부 식별자 없음 — 우리 고유 layer) |

---

## 5. Term Inventory

7개 영역으로 도메인 term을 분류. 각 term이 **Class / Instance / Role / Attribute / Relation** 중 어디인지 명시.

### 5.1 Market Entities

| Term | 분류 | 비고 |
|---|---|---|
| 종목 | Class: `Stock` | |
| 삼성전자, 레인보우로보틱스 | Instance of Stock | |
| 보통주, 우선주 | `Stock.share_class` Attribute | MVP는 common만 |
| 기업 (법인) | Class: `Corporation` | Stock과 분리된 entity |
| 그룹, 재벌 | Class: `Group` | ★ 신규 (한국 고유) |
| 자회사·계열사·모회사 | Relation Attribute `Corp ─owns→ Corp`의 `affiliation_type` | 클래스 아님 |
| 인물 | Class: `Figure` | sub-class: Politician/BusinessLeader/Bureaucrat/Academic |
| 섹터·업종 | Class: `Sector` | KRX FICS 그대로 |
| 거래소 | `Stock.market` Attribute | KOSPI/KOSDAQ/KONEX |

### 5.2 Events

| Term | 분류 | 비고 |
|---|---|---|
| 이벤트 | Class: `Event` (abstract) | |
| 공시 | sub-class: `Disclosure` | DART rcept_no 키 |
| 뉴스 | sub-class: `NewsEvent` | |
| 정책·외교·매크로 | sub-class: `MacroEvent` | |
| 가상 시나리오 | sub-class: `HypotheticalScenario` | flagged_hypothetical=true |
| 정기/발행/지분/기타 공시 | `Disclosure.disclosure_type` Attribute | DART 코드 |
| 호재·악재 | **Role** in (Event, Stock 또는 Theme) | 클래스 아님 |

### 5.3 Themes (★ 신규 layer 핵심)

| Term | 분류 | 비고 |
|---|---|---|
| 테마 | Class: `Theme` (abstract) | ★ |
| 정치/정책/섹터/그룹주/기술 테마 | Theme의 **sub-class** | |
| "로보틱스", "휴머노이드", "이재명 테마" | Instance of (sub-class of) Theme | |
| 테마 활성화 | Class: `Activation` (reified) | |
| 테마주 | **Role** | Stock이 Theme에 Membership 가질 때 |

### 5.4 ⚠ Roles (Classes로 착각하기 쉬운 안티패턴)

다음 모두 **Membership / Event 컨텍스트의 attribute**:

| Term | 진짜 정체 |
|---|---|
| 대장주 / 2등주 / 잡주 / 관련주 | `Membership.role` 값 |
| 수혜주 / 피해주 | (Event, Stock) 컨텍스트의 평가 결과 |
| 테마주 | Stock이 Theme에 Membership 가지면 부여되는 술어 |
| 고객사 / 협력사 / 1차·2차 협력사 | `CustomerRelation` / `SupplyRelation`의 attribute |
| 작전주, 우량주, 가치주, 성장주 | 비목표 (혼란·법적 회색지대) |

### 5.5 Narrative & Membership Layer (★ 신규 핵심)

| Term | 분류 |
|---|---|
| 해석·주장·의견 | Class: `Narrative` (reified) |
| 근거·인용 (social) | `Narrative ─grounded-in-social→ Source` |
| 사업적 근거 (structural) | `Narrative ─grounded-in-structural→ BusinessReport / Segment / Product / Revenue / Customer / Geographic` |
| 검증 결과 | `Narrative.structural_consistency` ∈ {verified, contradicted, unverified, weak} |
| 소속·멤버십 | Class: `Membership` (reified, dual: social + structural + both) |
| 활성화 | Class: `Activation` (reified) |

### 5.6 Sources

| Term | 분류 |
|---|---|
| 출처·원문 | Class: `Source` (abstract) |
| 텔레그램 / 블로그 / 팍스넷 / 뉴스 / 사업보고서 | sub-class: TelegramPost / BlogPost / BoardPost / NewsArticle / BusinessReport |
| 공시 원문 | `Disclosure` (Event + Source 다중 부모) |
| 작성자 | `Source.author` Attribute (단순 string 식별자, 클래스 아님) |

### 5.7 Business Structure (사업보고서 layer)

| Term | 분류 |
|---|---|
| 사업부문·세그먼트 | Class: `BusinessSegment` (part-of Corporation) |
| 제품·서비스·부품 | Class: `Product` |
| 매출 비중 | Class: `RevenueComposition` (reified) |
| 매출처·고객사 | **Role** in `CustomerRelation` (reified) |
| 공급사·협력사 | **Role** in `SupplyRelation` (reified) |
| 지역·국가 | Class: `Region` (enum) |
| 지역별 매출 노출 | Class: `GeographicExposure` (reified) |

---

## 6. Class Hierarchy

5종 관계를 명시적으로 분리:

| 관계 | 기호 | 의미 |
|---|---|---|
| instance-of | `:` | 인스턴스 → 클래스 |
| is-a | `⊑` | sub-class → super-class |
| part-of | `⊂` | 부분 → 전체 |
| member-of | `∈` | 멤버십 (reified mediator 경유) |
| has-role | `↪` | 컨텍스트 역할 |
| narrower-than | `≺` | Theme 인스턴스 specialization |
| similar-to | `≈` | semantic vector 유사 |

### 6.1 Native Class is-a DAG

```
Event (abstract)
├── Disclosure              ⊑ Event, ⊑ Source     (다중 부모)
├── NewsEvent               ⊑ Event, ⊑ Source     (다중 부모)
├── MacroEvent              ⊑ Event
└── HypotheticalScenario    ⊑ Event

Source (abstract)
├── TelegramPost / BlogPost / BoardPost / NewsArticle
├── BusinessReport          ⊑ Source
├── Disclosure              (Event + Source)
└── NewsEvent               (Event + Source)

Theme (abstract)
├── PoliticalTheme
├── PolicyTheme
├── SectorTheme
├── GroupTheme
└── TechTheme

Figure (abstract)
├── Politician / BusinessLeader / Bureaucrat / Academic

Stock           (단일, share_class attribute)
Corporation
Group
Sector          (KRX FICS)
Region          (enum: KR / US / EU / CN / JP / ROW)
Product
BusinessSegment
```

### 6.2 Reified Mediating Classes (1급 객체, is-a 트리 밖)

| Class | 매개 entity 쌍 | Key attributes |
|---|---|---|
| `Narrative` | (Stock, Theme) | claim_text, structural_consistency, dual-grounding |
| `Activation` | (Event, Theme) | strength, timestamp, evidence |
| `Membership` | (Stock, Theme) | type {social/structural/both}, role, strength, valid period |
| `RevenueComposition` | (Corp 또는 Segment, period) | share_pct |
| `CustomerRelation` | (Seller Corp, Buyer Corp\|str, period) | revenue_share_pct, tier |
| `SupplyRelation` | (Buyer Corp, Seller Corp\|str, period) | purchase_share_pct |
| `GeographicExposure` | (Corp 또는 Segment, Region, period) | share_pct |

### 6.3 핵심 다중 부모 케이스

| Entity | 다중 부모 | 이유 |
|---|---|---|
| Disclosure | ⊑ Event AND ⊑ Source | 사건이자 인용 출처 |
| NewsEvent | ⊑ Event AND ⊑ Source | 동상 |
| "RV reducer" (Theme instance) | ≺ "로보틱스" AND ≺ "휴머노이드" | sub-theme 다중 부모 |
| 한 Stock | ∈ "로보틱스" AND ∈ "현대차그룹주" AND ∈ "휴머노이드" | Membership 인스턴스 여러 개 동시 보유 |

---

## 7. Slot Schema

### 7.1 핵심 설계 결정

| # | 결정 | 적용 |
|---|---|---|
| D1 | 시간 표현 3종 | ① timestamp(단일 사건) ② valid_from/valid_to(구간) ③ period(분기/연 스냅샷) |
| D2 | Reified mediator는 내부 UUID PK | (외부 식별자 없는 우리 고유 layer) |
| D3 | CustomerRelation buyer = `Union[Corporation, string]` + `resolved` flag | 사업보고서 회사명만 적혀 매핑 실패 시 string fallback |
| D4 | Embedding slot | Theme.narrative_embedding, Event.semantic_embedding (별도 vector store에서 join) |

### 7.2 Native Class Attributes (요약)

**Stock**: `ticker(PK), isin, name_ko, name_en, share_class, market, issued_by→Corporation`

**Corporation**: `dart_code(PK), wikidata_qid, name_ko, belongs_to→Group(0..1), in_sector→Sector(0..1), ceo→Figure(0..1)`

**Group**: `name_ko(unique), chairman→Figure(0..1)`

**Sector**: `fics_code(PK), name_ko, parent_sector→Sector(0..1)`

**Region**: `code enum {KR, US, EU, CN, JP, ROW}` (PK)

**Figure**: `name_ko, wikidata_qid, birth_date` + sub-class slots (Politician.party 등)

**Product**: `name_ko, category(free-form)`

**BusinessSegment**: `corporation→Corporation(1..1), name_ko, description`

**Event (abstract)**: `timestamp(1..1), semantic_description(text), semantic_embedding(vector, computed)`

| Sub-class | 추가 슬롯 |
|---|---|
| Disclosure | dart_rcept_no(PK), corporation→Corp, disclosure_type, title, corporate_action_type(0..1) |
| NewsEvent | title, url, media_source |
| MacroEvent | title, region→Region(0..1) |
| HypotheticalScenario | description, generator, flagged_hypothetical(=true) |

**Source (abstract)**: `timestamp(1..1), text(1..1), author(string, 0..1)` + sub-class composite keys

**BusinessReport**: `dart_rcept_no, corporation→Corp, report_type ∈ {사업, 반기, 분기}, period, filing_date, url`

**Theme (abstract)**: `name_ko(unique within sub-class), narrative_definition(text), structural_definition(text, 0..1), structural_keywords(string[]), narrative_embedding(vector, computed), first_observed_at(date, 0..1)`

| Sub-class | 추가 슬롯 |
|---|---|
| PoliticalTheme | subject_figures→Figure[](1..N) |
| PolicyTheme | related_policy_text |
| SectorTheme | sector→Sector(1..1) |
| GroupTheme | group→Group(1..1) |
| TechTheme | technology_keywords(string[]) |

### 7.3 Inter-class Relationships (reify 안 한 단순 edge)

| Relationship | Domain | Range | Cardinality | 추가 slot |
|---|---|---|---|---|
| issued-by | Stock | Corporation | N:1 | — |
| belongs-to (Group) | Corporation | Group | N:1 | — |
| owns | Corporation | Corporation | N:N | stake_pct, affiliation_type ∈ {자회사, 계열사, 관계회사} |
| has-segment | Corporation | BusinessSegment | 1:N | — |
| produces | BusinessSegment | Product | N:N | — |
| sub-theme-of (narrower) | Theme | Theme | N:N (DAG) | — |
| similar-to | Event | Event | N:N | similarity_score |
| in-sector | Corporation or Stock | Sector | N:1 | — |
| subject-of | PoliticalTheme | Figure | N:N (1..N from Theme side) | — |

### 7.4 Reified Mediator 슬롯 상세

**Narrative**

| Slot | Type | Card |
|---|---|---|
| stock | →Stock | 1..1 |
| theme | →Theme | 1..1 |
| claim_text | text | 1..1 |
| structural_consistency | enum {verified, contradicted, unverified, weak} | 1..1 |
| grounded_in_social | →Source[] | 0..N |
| grounded_in_structural | →(BusinessReport \| BusinessSegment \| Product \| RevenueComposition \| CustomerRelation \| GeographicExposure)[] | 0..N |
| asserter_ref | string | 0..1 |
| valid_from | datetime | 1..1 |
| valid_to | datetime | 0..1 (null=현재 유효) |
| confidence | float (0~1) | 0..1 |

**Activation**

| Slot | Type | Card |
|---|---|---|
| event | →Event | 1..1 |
| theme | →Theme | 1..1 |
| strength | float (0~1) | 1..1 |
| timestamp | datetime | 1..1 |
| evidence_refs | →Source[] | 0..N |

**Membership**

| Slot | Type | Card |
|---|---|---|
| stock | →Stock | 1..1 |
| theme | →Theme | 1..1 |
| type | enum {social, structural, both} | 1..1 |
| role | enum {대장주, 2등주, 관련주, 잡주} | 0..1 |
| strength | float (0~1) | 1..1 |
| valid_from | datetime | 1..1 |
| valid_to | datetime | 0..1 |
| evidence_refs | →(Source \| BusinessReport \| RevenueComposition \| CustomerRelation \| GeographicExposure)[] | 0..N |

**RevenueComposition**

| Slot | Type | Card |
|---|---|---|
| subject | →(Corporation \| BusinessSegment) | 1..1 |
| period | string (e.g., "2024", "2024Q3") | 1..1 |
| share_pct | float (0~100) | 1..1 |
| absolute_value | decimal | 0..1 |
| source_report | →BusinessReport | 1..1 |

**CustomerRelation** (SupplyRelation은 buyer/seller 대칭)

| Slot | Type | Card |
|---|---|---|
| seller | →Corporation | 1..1 |
| buyer | →Corporation \| string | 1..1 |
| resolved | boolean | 1..1 |
| period | string | 1..1 |
| revenue_share_pct | float (0~100) | 0..1 |
| tier | enum {1차, 2차, unknown}, default=unknown | 1..1 |
| source_report | →BusinessReport | 1..1 |

**GeographicExposure**

| Slot | Type | Card |
|---|---|---|
| subject | →(Corporation \| BusinessSegment) | 1..1 |
| region | →Region | 1..1 |
| period | string | 1..1 |
| share_pct | float (0~100) | 1..1 |
| source_report | →BusinessReport | 1..1 |

### 7.5 Enum 일람

| Enum | Values |
|---|---|
| Stock.share_class | common, preferred |
| Stock.market | KOSPI, KOSDAQ, KONEX |
| BusinessReport.report_type | 사업보고서, 반기보고서, 분기보고서 |
| Disclosure.disclosure_type | (DART 약 200여 코드 그대로) |
| Region.code | KR, US, EU, CN, JP, ROW |
| Narrative.structural_consistency | verified, contradicted, unverified, weak |
| Membership.type | social, structural, both |
| Membership.role | 대장주, 2등주, 관련주, 잡주 |
| CustomerRelation.tier | 1차, 2차, unknown |
| Corporation.owns.affiliation_type | 자회사, 계열사, 관계회사 |

### 7.6 Temporal Model 시각화

```
① timestamp (단일 사건)
   Event, Activation, Source(post timestamp)

② valid_from / valid_to (구간, null=현재)
   Membership, Narrative
   같은 (Stock, Theme) 쌍에 시점별 여러 instance 공존 가능 (chain)

③ period (분기/연 스냅샷)
   BusinessReport, Revenue·Customer·Supply·Geographic
   MVP: "최신" + "1년 전" 2-snapshot 유지 (R8)
```

---

## 8. Reification & Lifecycle 룰

### 8.1 대원칙: Append-Only + Bi-temporal

"기존 instance를 수정하지 않는다. 의미가 변하면 close + 새 instance. evidence만 늘면 in-place update."

### 8.2 8개 Lifecycle 룰

| # | 룰 | 적용 |
|---|---|---|
| R1 | 정체성 불변 | 각 reified의 "정체성 필드"는 한번 정해지면 변경 불가 |
| R2 | Evidence reinforcement만 in-place | `evidence_refs` 추가, `structural_consistency` 재평가 OK |
| R3 | 정체성 변경 시 close + 새 instance | `valid_to` 기록, `supersedes` chain 유지 |
| R4 | Idempotent ingestion | 동일 source 재처리해도 결과 동일, evidence_ref dedup |
| R5 | Semantic dedup (Narrative) | similarity ≥ 0.85 → 같은 instance에 evidence 추가; 미만 → 새 instance |
| R6 | Conflict tolerance | 같은 (Stock, Theme)에 contradicting Narrative 공존 OK |
| R7 | 시간 순 ingestion | source/event timestamp 순으로 처리 |
| R8 | Period 2-snapshot | 같은 (subject, period) 1 instance; period 정렬 후 oldest > 2 초과분 archive |

### 8.3 각 Reified의 Lifecycle

| Reified | 정체성 필드 | 생성 trigger | Update 허용 | Close trigger |
|---|---|---|---|---|
| Narrative | (stock, theme, claim semantic identity) | LLM이 (Stock,Theme) 새 claim 추출 | evidence·consistency 재평가 | semantic identity 변경 (드묾) |
| Activation | (event, theme) | Event가 Theme 활성화시키는 첫 시점 | evidence/strength 재계산 | 닫지 않음 (1회성) |
| Membership | (stock, theme, type) | (Stock,Theme,type) 신규 멤버십 | evidence 추가 | role/strength 5%↑ 변동 |
| Revenue/Customer/Supply/Geographic | (subject, period 등) | 새 BusinessReport 신규 (subject, period) | 재제출 일관성 검증 | R8 archive |

### 8.4 Schema 보강 (시계열 chain)

모든 reified에 추가:

| Slot | Type | Card |
|---|---|---|
| supersedes | →SameClass | 0..1 (이전 instance) |
| superseded_by | →SameClass | 0..1 (다음 instance) |
| close_reason | enum {identity_change, evidence_contradicted, archived, manual} | 0..1 |

### 8.5 Walkthrough — 레인보우로보틱스 시계열

```
t1 (2024-03): 첫 텔레 post
  → Narrative N1 (stock=레인보우, theme=로보틱스, claim="현대차 인수 + 로보틱스 핵심",
                  consistency=unverified, social=[post1], structural=[])
  → Membership M1 (type=social, role=null, strength=0.4)

t2 (2024-08): 반기보고서 RV reducer 매출 80%
  → RevenueComposition RC1 (subject=레인보우-로봇사업부, period=2024H1, share=80)
  → N1 in-place update: grounded_in_structural += [RC1], consistency = "verified"
  → M1 close (valid_to=t2, close_reason=identity_change)
  → M2 (type=both, strength=0.85, supersedes=M1, valid_from=t2)

t3 (2024-12): 현대차 로보틱스 투자 공시
  → Disclosure D1
  → Activation A1 (event=D1, theme=로보틱스, strength=0.9, t=t3)
  → 새 Narrative N2 (similarity to N1 < 0.85 → 신규)
  → M2 close → M3 (role=대장주, strength=0.95, supersedes=M2, valid_from=t3)

t4 (2025-04): 2025Q1 보고서
  → RevenueComposition RC2 (period=2025Q1, share=85)
  → period 정렬 [2024H1, 2025Q1] — 2개라 archive 미발생
  (다음 분기 들어오면 2024H1 archive)
```

---

## 9. CQ Traversal Validation

8개 External CQ가 모두 위 schema로 traversal 가능함을 확인. (자세한 walkthrough는 별도 — Step 7 산출물 참조)

### 9.1 External CQ 매핑 요약

| CQ | 핵심 traversal | OK? |
|---|---|---|
| E1 | Membership(stock,valid_to=NULL) → Theme → Activation in window → Event + Narrative + 인용 | ✓ |
| E2 | Event/text → similar Events / activated Themes → dual Memberships → ranked + analogs | ✓ |
| E3 | Membership(theme, valid_to=NULL) group by role, sort by strength | ✓ |
| E4 | Event similar-to → past Events → bi-temporal Membership/Narrative reconstruction | ✓ (가격 magnitude는 외부) |
| E5 | Stock→Corp→has-segment + Revenue/Customer/Geographic latest period | ✓ |
| E6 | dual Membership 존재 여부 + Narrative.structural_consistency + structural evidence detail | ✓ |
| E7 | Stock → Membership.theme set → 같은 theme의 다른 stocks (overlap × strength) | ✓ |
| E8 | Activation in window → group by theme, aggregate strength → rank | ✓ |

### 9.2 Internal Capability 매트릭스

I-1 ~ I-11 모두 위 schema의 class·relation·reified mediator 조합으로 직접 매핑됨. (Step 7 산출물 참조)

---

## 10. Gaps & Out-of-Scope

| # | 항목 | 분류 | 처리 |
|---|---|---|---|
| G1 | 가격 magnitude 답 못 함 (E4 일부) | 의도된 비목표 | 외부 price store와 join 시 답 가능 |
| G2 | "[Theme] 끝물?" 사이클 위치 | 후순위 | 가격 시계열과 결합 필요. 우선순위 낮음 |
| G3 | MacroRegime / 시장국면 | 후순위 확장 | 미래 schema 확장 |
| G4 | LLM 비결정성으로 dedup 깨짐 (R5) | 운영 이슈 | temperature=0 + 정규화 prompt + embedding hash dedup |
| G5 | 수급·주포·세력 | 명시적 비목표 | 자본시장법 + 데이터 부재 |
| G6 | Coverage scope (Stock 수, Theme 수, backfill 기간) | 다음 단계 결정 | 잠정: ~500 stocks × 50~80 themes × 24개월. 구현 plan에서 확정 |
| G7 | Membership decay (자동 close 룰) | MVP 보류 | 명시적 contradicting evidence만 close. 자동 decay는 평가 후 추가 |

---

## 11. Open Questions (구현 단계로 이월)

다음 spec 또는 plan에서 결정:

1. **저장 시스템**: graph DB(Neo4j/TigerGraph) vs property + vector hybrid vs custom?
2. **추출 파이프라인**: LLM 호출 batching·캐싱 전략, temperature·prompt 표준
3. **합성 layer**: 쿼리 → traversal plan → LLM 답변 합성의 정확한 흐름
4. **콜드 스타트**: 24개월 backfill의 우선순위 (Theme 먼저? Stock 먼저? Source 먼저?)
5. **평가 rubric**: 답변 품질을 측정할 정량/정성 기준 (E1~E8별)
6. **운영 비용 모델**: LLM 호출량·저장량 추정 → 단가
7. **법무 검토**: 텔레/블로그/팍스넷 콘텐츠 활용 범위 (요약·인용·재배포)
8. **사용자 인터페이스**: 자연어 쿼리 UX, 인용·구조 시각화 방식

---

## Appendix A. 5종 관계 vs 흔한 혼동

| 헷갈림 | 명확화 |
|---|---|
| "휴머노이드는 로보틱스의 부분?" | **narrower-than (≺)**, part-of 아님 |
| "사업부는 회사의 부분?" | **part-of (⊂)** |
| "자회사는 모회사의 부분?" | **owned-by (지분)**, part-of 아님 |
| "Stock이 Theme의 sub-class?" | **member-of (∈)**, is-a 아님 |
| "대장주는 Stock의 sub-class?" | **has-role (↪)**, is-a 아님 |
| "협력사는 Corp의 sub-class?" | **has-role (↪) in CustomerRelation**, is-a 아님 |

---

## Appendix B. Step별 합의 이력

이 spec은 다음 7단계 합의 과정을 거쳐 작성됨:

- Step 1: Competency Questions 형식화 (External 8 + Internal 11)
- Step 2: 재사용 ontology 매핑 (FIBO light reuse)
- Step 3: Term 인벤토리 + Class/Instance 구분 (7개 영역)
- Step 4: Class hierarchy DAG + 5종 관계 명시
- Step 5: Slot/relationship domain·range·cardinality 명세
- Step 6: Reification lifecycle 8개 룰 (append-only bi-temporal)
- Step 7: 완성 schema로 CQ 전수 검증

---

## Status

**Draft v1 (2026-05-22).** Ontology schema design 완료. 구현 layer(저장·추출·합성·UI·평가)는 별도 plan으로 분리하여 작성 예정.
