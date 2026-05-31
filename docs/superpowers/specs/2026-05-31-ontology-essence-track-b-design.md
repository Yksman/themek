# Track B — 온톨로지 본질 (Ontology Essence) 설계

- 작성일: 2026-05-31
- 상태: 승인됨 (구현 플랜 B1/B2/B3로 분해)
- 범위: 그래프 연결성(#6) + 잔재 청소(#7) + 엔티티 해소(#5) + 재무 metric 확장(#8)

## 1. 배경 / 아키텍처 전제 (확정 사실)

리뷰 과정에서 코드·DB를 교차 확인한 결과:

- **graph-core가 이미 단일 정본**이다. 그래프는 다음 경로로 *파생*된다:
  - `DART 리포트 HTML → LLM 추출(BusinessExtraction) → ingest_business_structure → nodes/edges`
  - `DART fnlttSinglAcntAll → ingest_financials → financial_facts`
  - 수동 seed (`seed_core`) → 일부 company/stock/sector 노드 + IN_SECTOR/ISSUES_STOCK 엣지
- 관계형 온톨로지 테이블 4종(`business_segments`, `customer_relations`, `geographic_exposures`,
  `revenue_compositions`)은 `corp_models.py` 문서주석대로 **코어로 대체·제거**됐고, 현재 `src/`
  어디서도 참조되지 않는 **죽은 잔재**다(DB에 구 데이터만 잔존).
- 따라서 원래 리뷰의 "이중 write 경로"·"정본 모호" 우려는 해소된다. #7은 큰 결정이 아니라
  **잔재 테이블 청소**로 축소된다.

Track B는 이 그래프를 *연결되고(linked) 해소된(resolved)* 상태로 끌어올린다. 구현은 서로
독립적인 3개 plan으로 분해한다: **B1(연결성+청소) → B3(metric) → B2(해소)**.

### 의존성
- **Track A 선행 완료** (커밋 a88f411~068470d): `parse_financial_rows`의 `_FLOW`/`_STOCK` 분기,
  `check_integrity`, 엣지 UNIQUE(`ux_edge_spo`), `rebuild_financials`. B3는 `_FLOW`/`_STOCK`
  위에 얹히고, B1/B2는 `check_integrity`를 검증에 재사용한다.

## 2. 목표 / 비목표

### 목표
- **B1**: 백필된 39개 company에 `ISSUES_STOCK` 엣지 투영(기존 `stocks` 데이터) + DART
  `induty_code` fetch로 `IN_SECTOR` 채우기 + 잔재 테이블 DROP.
- **B2**: customer raw → 상장 corporation 정규화 exact 매칭 해소(SELLS_TO를 company로 재지정,
  customer 노드 제거, buyer_raw 보존) + segment alias 병합 + 큐레이션 별칭 시드 + 정규화 일원화.
- **B3**: `eps`, `cf_operating`/`cf_investing`/`cf_financing`, `shares_outstanding` metric 추가.

### 비목표
- `BELONGS_TO_GROUP` / 기업집단 — `groups` 0행, 소스 부재. 예약만(예외 처리 없이 미구현).
- Fuzzy/편집거리 자동 매칭 — 정규화 exact + 수동 별칭 시드로 한정(오매칭 차단).
- vault 렌더링 변경(EPS 단위 포맷 등) — Track C.
- 섹터 계층(`SUB_SECTOR_OF`) — induty 분류에 부모가 없으면 미구현(있으면 B1에 포함).

## 3. B1 — 그래프 연결성 + 잔재 청소 (#6, #7)

### 3.1 ISSUES_STOCK 투영 — `src/themek/ontology/ingest/linkage.py` (신규)
- `link_stocks(session) -> int`: company kind 노드를 순회, `attrs["dart_code"]`로 관계형
  `Stock`(`issued_by_id == dart_code`) 조회 → 각 stock에 대해 `stock` 노드 upsert(label=name_ko,
  attrs={ticker, market}) + `ISSUES_STOCK` 엣지 upsert(period=None,
  source_type="dart_api", method="api", confidence=1.0). 멱등. 생성 수 반환.
- 데이터 이미 존재(`stocks` 2657행, 전부 `issued_by_id` 채워짐) → fetch 불필요.

### 3.2 IN_SECTOR fetch — `src/themek/ontology/ingest/classification.py` (신규)
- 신규 client 메서드 `DartClient.fetch_company_profile(corp_code) -> dict` (DART `company.json`).
  응답의 `induty_code`(표준산업분류 코드) + `induty`(명) 사용.
- `link_sectors(session, client) -> int`: company 노드별 profile fetch → sector 노드
  upsert(`sector_id(induty_code)`, kind="sector", label=induty명) + `IN_SECTOR` 엣지 upsert.
  관계형 `Corporation.in_sector_id`도 함께 set(정합 유지). 멱등. rate budget 존중.
- induty 응답에 부모 분류가 있으면 `SUB_SECTOR_OF` 엣지도 생성(없으면 생략).

### 3.3 잔재 청소 — `migrations/versions/0006_drop_legacy_ontology_tables.py` (신규)
- DROP: `business_segments`, `customer_relations`, `geographic_exposures`,
  `revenue_compositions`, `products`(0행·미사용).
- 유지: `sectors`, `groups`(FK 타깃), 그 외 운영 테이블.
- `downgrade`는 0001/0002의 원 `create_table` 정의를 복원(재현 가능).

### 3.4 CLI — `themek ontology link` (`linkage` + `classification` 호출)

## 4. B2 — 엔티티 해소 (#5)

### 4.1 정규화 일원화 — `src/themek/ontology/core/resolve.py` (확장)
- `normalize_corp_name(s) -> str`: 소문자 + 공백 단일화 + 법인 접두/접미 제거
  (`(주)`, `㈜`, `주식회사`, 선·후행 `, Inc.`, `Co., Ltd.`, `Corp.` 등) + 구두점 정리.
- `ConceptAlias.alias_norm` 저장과 `resolve_concept` 조회가 **동일 함수** 경유하도록 정리
  (현 `normalize_alias`와의 불일치 제거 — `normalize_alias`는 `normalize_corp_name`으로 통합하거나
  위임).

### 4.2 별칭 시드 — `data/ontology/aliases.yaml` + `seed_aliases(session)` (`ingest/seeds.py` 확장)
- 큐레이션 매핑 두 종류:
  - customer 변형명 → corp dart_code (예: "삼성전자(주)", "Samsung Electronics" → 00126380)
  - segment 동의어 → canonical segment 라벨 (예: "메모리" / "메모리 반도체" → "메모리반도체")
- `seed_aliases`는 각 항목을 `ConceptAlias`(alias_norm = normalize_corp_name(변형명),
  node_id = 대상 노드 id, source="manual", confidence=1.0)로 upsert.

### 4.3 해소 배치 패스 — `src/themek/ontology/ingest/resolution.py` (신규, 재실행 안전)
- `resolve_customers(session) -> dict`:
  1. 모든 `customer` 노드 순회. label을 `normalize_corp_name`.
  2. 매칭 우선순위: (a) `ConceptAlias` 조회, (b) 정규화된 `Corporation.name_ko` 정확 일치.
  3. 매칭되면 대상 `company` 노드 id 확보. 그 customer를 object로 하는 모든 `SELLS_TO` 엣지의
     `object_id`를 company로 재지정하고, `qualifier["buyer_raw"]`에 원 라벨 보존. 재지정 결과
     동일 (subject,predicate,object,period) 충돌 시 멱등 병합(UNIQUE 제약 존중 — 기존 엣지에
     qualifier 합치고 중복 행 생성 안 함).
  4. 고아가 된 customer 노드 제거.
  5. 미매칭 customer는 `attrs["resolved"]=false` 표식 유지.
  - 반환: {resolved, unresolved, edges_repointed}.
- `merge_segments(session) -> dict`: 별칭 시드(segment 동의어)에 따라 비-canonical segment 노드를
  가리키는 `HAS_SEGMENT` 엣지를 canonical 노드로 재지정 + 고아 노드 제거. customer와 동일한
  멱등 재지정 로직 공유(`_repoint_edges` 헬퍼).
- 해소 후 `check_integrity(session)` 호출로 중복 엣지/고아 검증.

### 4.4 CLI — `themek ontology resolve` (seed_aliases → resolve_customers → merge_segments → 요약)

## 5. B3 — 재무 metric 확장 (#8)

### 5.1 metric_key 확장 — `src/themek/ontology/core/models.py`
- `METRIC_KEYS`에 추가: `eps`, `cf_operating`, `cf_investing`, `cf_financing`,
  `shares_outstanding`.

### 5.2 IS/CF 매핑 확장 — `src/themek/ontology/ingest/financials.py`
- `_ID_MAP`/`_NM_MAP` 추가:
  - `eps`: `ifrs-full_BasicEarningsLossPerShare` / "기본주당이익(손실)" (sj_div ∈ IS/CIS).
  - `cf_operating`: `ifrs-full_CashFlowsFromUsedInOperatingActivities` / "영업활동현금흐름" (sj_div=CF).
  - `cf_investing`: `ifrs-full_CashFlowsFromUsedInInvestingActivities` / "투자활동현금흐름" (CF).
  - `cf_financing`: `ifrs-full_CashFlowsFromUsedInFinancingActivities` / "재무활동현금흐름" (CF).
- `_METRIC_SJ`: eps→IS/CIS, cf_*→{"CF"}.
- `_FLOW`에 `eps`, `cf_operating`, `cf_investing`, `cf_financing` 추가(3개년 전개 적용).
- EPS 단위(원/주)는 amount 그대로 적재. 표기 포맷은 Track C.

### 5.3 발행주식수 — 별도 엔드포인트
- 신규 client 메서드 `DartClient.fetch_shares(corp_code, bsns_year, reprt_code) -> list[dict]`
  (DART `stockTotqySttus` 주식총수현황).
- `ingest/financials.py`에 `ingest_shares_for_company(...)`: 보통주 발행총수 →
  `shares_outstanding` fact(metric_key="shares_outstanding", fiscal_period=해당 보고서 period,
  fs_div="CFS" 고정 또는 N/A, currency=None/"SHR"). `shares_outstanding`은 **stock**
  (시점값) — 비교연도 전개 없이 당기만.
- `ingest_financials_all`이 회사·연도·reprt별로 `ingest_shares_for_company`도 호출.

## 6. 데이터 흐름 / 컴포넌트 경계

```
B1: stocks(관계형) ─ link_stocks ─▶ ISSUES_STOCK 엣지
    DART company.json ─ fetch_company_profile ─ link_sectors ─▶ IN_SECTOR 엣지 + sector 노드
    migration 0006 ─▶ 잔재 테이블 DROP

B2: aliases.yaml ─ seed_aliases ─▶ ConceptAlias
    customer 노드 ─ resolve_customers(normalize_corp_name + alias) ─▶ SELLS_TO 재지정·노드 제거
    segment 노드 ─ merge_segments ─▶ HAS_SEGMENT 재지정·노드 제거
    ─ check_integrity ─▶ 검증

B3: DART fnlttSinglAcntAll ─ parse(_FLOW 확장) ─▶ eps/cf_* facts
    DART stockTotqySttus ─ ingest_shares ─▶ shares_outstanding facts
```

- 모든 신규 ingest는 멱등 upsert + `source_type/method/confidence` 기록(기존 패턴 준수).
- 신규 파일은 단일 책임: `linkage.py`(관계형→엣지), `classification.py`(외부 fetch→섹터),
  `resolution.py`(해소 배치), 매핑은 기존 `financials.py` 확장.

## 7. 테스트 전략 (TDD)

- **B1**: `link_stocks`(관계형 stock→ISSUES_STOCK, fake 데이터), `link_sectors`(fake client
  induty 응답→IN_SECTOR + in_sector_id set), migration 0006 up/down 스모크.
- **B2**: `normalize_corp_name`(접두/접미·영문 케이스), `seed_aliases`(yaml→ConceptAlias),
  `resolve_customers`(alias·exact 매칭→SELLS_TO 재지정·customer 제거, 미매칭 유지, 멱등 충돌
  병합), `merge_segments`, 해소 후 `check_integrity` 무에러.
- **B3**: 신규 metric 파싱(eps/cf_*가 올바른 sj_div에서만, _FLOW 전개), `ingest_shares`(주식총수
  응답→shares_outstanding 당기만), 단위 처리.

## 8. 알려진 한계 / 후속

- Track A 후속: stock 비교열을 `fiscal_period==FY`일 때 유지하면 정당한 전년 연말 stock을 복원
  가능(현재 thstrm-only로 일부 FY 비교값 손실). Track B 범위 밖.
- 그룹(BELONGS_TO_GROUP)·섹터 계층은 소스 확보 시 별도 과제.
- 해소는 정규화 exact + 수동 별칭에 한정 — 재현율은 큐레이션 품질에 의존(의도된 보수적 선택).
