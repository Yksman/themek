# Track C — 탐색 가시성 (Discovery Visibility) 설계

- 작성일: 2026-05-31
- 상태: 초안 (리뷰 대기)
- 범위: vault QA 리포트(#9) + 회사 frontmatter 보강(#10) + segment 과병합 완화(#11)
  + B3 신규 metric vault 렌더(#12, B3 후속 갭)
- 선행: Track A·B 완료 (커밋 a88f411~e0363f6). `check_integrity`(A), `ISSUES_STOCK`/
  `IN_SECTOR`(B1), `resolve_customers`/`merge_segments`(B2), eps/cf_*/shares_outstanding
  facts(B3)가 모두 존재한다는 전제.

## 1. 배경 / 문제

Track A·B로 그래프는 *정합·연결·해소*된 상태가 됐지만, **탐색 표면(Obsidian vault)이
이를 따라오지 못한다**:

- `build_vault`는 stale `_qa-report.md`를 **삭제만 하고 다시 emit하지 않는다**
  (`vault.py` _GENERATED_DIRS 정리 루프). 무결성 상태를 vault에서 확인할 길이 없다.
- 회사 frontmatter는 `type/dart_code/name/tags`뿐 — ticker·market·섹터·재무기간·세그먼트
  수 등 Dataview로 질의/필터할 메타가 없다. 탐색이 본문 스캔에 의존한다.
- segment 노드는 `segment:{slug(name_ko)}` **전역 키**다. 서로 다른 회사의 동명 일반
  세그먼트("기타", "상품", "기타부문")가 **한 노드로 강제 병합**되어, 해당 노드의 백링크가
  무관한 회사들로 오염된다(의도된 alias 병합과 우발적 슬러그 충돌이 구분 안 됨).
- B3가 `eps`·`cf_operating/investing/financing`·`shares_outstanding` fact를 적재했지만
  `_render_financials`는 6개 KPI(`_KPI_ORDER`)만 렌더한다 → **적재했으나 vault에 안 보이는
  죽은 데이터**. spec(financial-integrity §2)이 "EPS 단위 포맷은 Track C"로 명시 위임함.

## 2. 목표 / 비목표

### 목표
- **C9**: `build_vault`가 `check_integrity(session)` 결과를 `_qa-report.md`로 emit
  (severity별 그룹 + 회사별 집계). 무결성을 vault에서 직접 확인.
- **C10**: 회사 frontmatter에 `ticker`·`market`·`sector`·`periods`·`report_count`·
  `segment_count`·`customer_count`·`issue_count` 추가. Dataview 질의 가능.
- **C11**: segment 노드를 **회사 네임스페이스 기본**으로 전환(`segment:{dart_code}:{slug}`).
  우발적 동명 충돌 제거. alias 시드 기반 *의도된* canonical 병합은 그대로 동작.
- **C12**: `_render_financials`에 EPS(원/주)·현금흐름(억원)·발행주식수(주) 표·인라인 필드
  추가. 단위 구분 렌더.

### 비목표
- segment **자동** 의미 병합(임베딩/유사도) — C11은 네임스페이스 분리 + 기존 수동 alias
  병합만. 자동 병합은 별도 과제.
- vault 그래프 시각화/Dataview 쿼리 노트 자체 작성 — frontmatter 필드 제공까지(소비는 사용자).
- 신규 DART 데이터 fetch — C는 *기존 코어 → vault 투영*만. B3 fact가 없는 회사는 해당 행 생략.
- BS 비교열 복원·flow YTD 의미 구분 — Track A 한계(별도 과제) 그대로.

## 3. 설계

### 3.1 C9 · QA 리포트 emit — `src/themek/ontology/projection/vault.py`

- 신규 `_render_qa_report(issues: list[Issue]) -> str`(순수 함수):
  - 헤더 + 요약 카운트(`error`/`warn`/`info` 개수).
  - severity 순(error→warn→info)으로 그룹, 각 그룹을 markdown 표(`code | subject | message`).
  - 이슈 0건이면 "✅ 무결성 이슈 없음" 단문.
- `build_vault`는 회사/개념 노트 기록 후 `check_integrity(session)` 호출 →
  `_render_qa_report` 결과를 `out_dir/_qa-report.md`에 기록. 기존 stale 삭제 루프는 유지
  (재생성이므로 안전). frontmatter `type: "qa-report"` 부여.
- `build_vault` 반환 dict에 `issues: len(issues)` 추가.

### 3.2 C10 · 회사 frontmatter 보강 — `vault.py`

회사 루프에서 이미 수집하는 edges·financials를 재사용(추가 쿼리 최소화):

- `ticker`/`market`: `ISSUES_STOCK` 엣지 → object stock 노드 `attrs["ticker"|"market"]`.
  복수 종목이면 첫 보통주(또는 ticker 정렬 첫째) 1개. 없으면 필드 생략 또는 `""`.
- `sector`: 기존 `sector` 엣지의 `_lbl(object_id)`.
- `periods`: `_company_financials` 키에서 `"{year}{fp}"` 정렬 리스트(YAML list).
- `report_count`: distinct period 수.
- `segment_count`/`customer_count`: dedup 후 `seg`/`cust` 길이.
- `issue_count`: `check_integrity` 결과 중 `subject == c.id`(또는 dart_code) 개수.
  → C9에서 한 번 계산한 `issues`를 회사 루프 전에 구해 `{company_id: count}`로 인덱싱
  (중복 호출 방지: `build_vault` 시작부에서 `issues = check_integrity(session)` 1회).
- frontmatter 직렬화는 기존 수기 문자열 조합 유지(YAML 라이브러리 미도입). list 필드는
  `periods: [2021FY, 2022FY, 2023FY]` 인라인 배열. 라벨에 `"`·개행 없으니 안전(섹터명은
  KSIC/한글 — 따옴표 escape 헬퍼 `_yaml_str`로 방어).

### 3.3 C11 · segment 네임스페이스 — `ids.py` + `business_structure.py`

**핵심 변경**: 세그먼트 노드 키를 회사별로 분리.

- `ids.py`: `segment_id(name_ko, company_key: str | None = None) -> str`
  - `company_key` 주어지면 `segment:{company_key}:{slug(name_ko)}`, 아니면 기존 `segment:{slug}`
    (하위호환 — 다른 호출부 영향 없음).
- `ingest/business_structure.py`: `HAS_SEGMENT` 생성 시 `segment_id(name, company_key=dart_code)`
  사용 + segment 노드 `attrs`에 `{company: dart_code, name: name_ko}` 기록. label은 표시명 유지.
- `merge_segments`(resolution.py)와 alias 시드: canonical 타깃은 의도적으로 전역
  `segment:{slug}` 유지 가능 → 회사-네임스페이스 노드를 alias로 canonical 전역 노드에 병합하면
  *의도된* 교차회사 병합이 됨(우발 ≠ 의도 구분 달성). `_repoint_edges`는 그대로 재사용.
- **데이터 영향**: 기존 `HAS_SEGMENT` 엣지·segment 노드가 전역 키로 적재돼 있음 →
  **재투영 필요**. business_structure는 캐시된 LLM 추출(BusinessExtraction)에서 재적재 가능
  (재추출 불요). 마이그레이션 전략:
  - (a) 일회성 백필 스크립트 `scripts/renamespace_segments.py`: 각 `HAS_SEGMENT` 엣지의
    object segment 노드를 `segment:{subject_dart_code}:{slug}`로 복제·재지정, 고아 전역 노드
    제거. 멱등. 또는
  - (b) `rebuild` 류 재투영(business_structure 재적재) — 캐시 의존.
  - 본 plan은 **(a) 백필 스크립트 + 멱등 보장**을 채택(재추출 비용 0, 검증 용이).
- 재투영 후 `merge_segments` + `check_integrity` 재실행으로 정합 확인.

### 3.4 C12 · 신규 metric 렌더 — `vault.py` `_render_financials`

- `_company_financials`는 metric_key 무관 적재 → 이미 eps/cf_*/shares 포함됨(쿼리 변경 불요).
- 렌더 분리(단위가 달라 같은 "억원" 표에 못 섞음):
  - 기존 KPI 표(억원): 그대로.
  - **현금흐름 표**(억원): `cf_operating/investing/financing` — `_eok` 재사용, 별도 소표.
  - **주당·주식 표**: `eps`(원/주, `{amount:,.0f}원`), `shares_outstanding`(주, `{amount:,.0f}주`
    또는 백만주 환산). 별도 소표 또는 인라인 필드.
- 인라인 Dataview 필드도 신규 metric 추가(`eps_2023FY:: 8057` 등).
- 해당 회사에 fact 없으면 표/행 생략(기존 `if not any(...)` 패턴 준수).

## 4. 데이터 흐름 / 컴포넌트 경계

```
C9:  check_integrity(session) ─ _render_qa_report ─▶ vault/_qa-report.md
C10: ISSUES_STOCK→stock.attrs / IN_SECTOR / facts / issues[c.id] ─▶ company frontmatter
C11: business_structure(재투영) ─ segment_id(company_key) ─▶ segment:{dart}:{slug} 노드
     scripts/renamespace_segments.py ─ 기존 전역 노드 재네임스페이스(일회성, 멱등)
     merge_segments(alias) ─▶ 의도된 canonical 병합만
C12: financial_facts(eps/cf_*/shares) ─ _render_financials(단위 분리) ─▶ company 노트 표
```

- C9·C10·C12는 **순수 투영 변경**(읽기 전용, vault.py 국소) — 저위험.
- C11은 **노드 키 스킴 변경 + 데이터 재네임스페이스** — 중위험, 백필 스크립트로 격리.

## 5. 테스트 전략 (TDD)

- **C9**: `_render_qa_report` — 이슈 0건(✅ 단문), 혼합 severity(그룹·카운트), 표 형식.
  `build_vault`가 `_qa-report.md`를 실제 생성하는지(인메모리 세션 + 합성 노드).
- **C10**: frontmatter에 ticker/market/sector/periods/report_count/segment_count/
  issue_count가 정확히 들어가는지(stock attrs·facts 합성). 종목/재무 없는 회사 → 필드 생략·기본값.
  YAML 특수문자(따옴표) escape.
- **C11**: `segment_id(name, company_key)` 키 형식. business_structure 재투영이 회사별
  분리 노드 생성(동명 두 회사 → 별 노드). alias 시드로 canonical 병합 시 의도된 교차회사 병합
  동작. `renamespace_segments` 멱등 + 고아 제거 + 재실행 안전. 재투영 후 `check_integrity` 무에러.
- **C12**: eps/cf_*/shares가 올바른 단위 표에 렌더(억원 vs 원 vs 주). fact 없는 회사 행 생략.
  인라인 필드 생성.
- 기존 `tests/ontology/test_projection_vault.py` 회귀 — 골든 스냅샷/구조 어서션 갱신.

## 6. CLI / 산출

- 신규 CLI 없음(`themek ontology vault` 기존 경로 재사용, cli.py:769). C11 백필만 일회성
  스크립트(`scripts/renamespace_segments.py`) 또는 `themek ontology renamespace-segments` 보조
  커맨드(논의).
- `build_vault` 반환 dict 확장: `{companies, concepts, issues}`.

## 7. 구현 순서 (저위험 → 고위험)

1. **C9** (_qa-report emit) — 독립, 가장 단순.
2. **C12** (신규 metric 렌더) — 독립, vault.py 국소.
3. **C10** (frontmatter 보강) — C9의 `issues` 재사용(issue_count).
4. **C11** (segment 네임스페이스) — 키 스킴 + 백필, 마지막. 재투영 후 vault 재생성.

→ C9·C12·C10을 한 plan(C-vault), C11을 별 plan(C-segments)으로 분해 권장.

## 8. 알려진 한계 / 후속

- C11 재네임스페이스는 *기존* 전역 segment 노드 가정. 향후 ingest는 처음부터 회사 키 사용 →
  스크립트는 일회성(이후 멱등 noop).
- frontmatter `ticker`는 복수 상장(우선주 등) 시 대표 1개만 — 전체 종목은 본문/엣지 참조.
- QA 리포트는 `check_integrity` 4종 코드에 한정 — 새 무결성 규칙 추가 시 자동 반영(재사용).
- EPS는 DART 응답 단위(원/주) 그대로 — 액면분할 등 비교 보정 없음(별도 과제).
