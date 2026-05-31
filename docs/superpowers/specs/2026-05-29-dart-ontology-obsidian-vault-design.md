---
title: DART 온톨로지 → Obsidian Vault 생성기 — Design Spec
date: 2026-05-29
status: Draft v1 (brainstorming 합의 완료 — plan 작성 진입 대기)
scope: 적재된 DART 온톨로지(SQLite)를 Obsidian vault(markdown + wikilink)로 멱등 생성. 점검(QA) + 탐색(graph) 겸용. `themek vault build` 1개 명령.
decisions_locked:
  - 주 목적 = 점검 + 탐색 겸용 상시 도구 (재생성형)
  - 매체 = Obsidian vault (Graph View + Dataview)
  - 생성 범위 = 데이터가 있는 노드만 (사업보고서 적재된 회사 + 연결 엔티티). 빈 뼈대 회사 제외
  - 갱신 = 명령어 재생성 (`themek vault build`), 멱등
  - vault 위치 = 레포 내 전용 폴더 `vault/`
  - 미연결 고객사(buyer_raw) = 설명문 포함 전부 노드화, `kind: entity|descriptive` 분류 메타로 구분
---

# DART 온톨로지 → Obsidian Vault 생성기 — Design Spec

## 1. Vision & Goal

지금까지 Plan #1~#5 흐름으로 DART 사업보고서를 fetch → LLM 추출 → SQLite(`themek.db`)에 적재해 왔다. 현재 44개 사업보고서, 173개 세그먼트, 172개 고객관계, 64개 지역노출이 들어 있다. **그러나 이 데이터가 실제로 어떻게 적재됐고 그래프 노드가 어떻게 구성되는지를 사람이 친화적으로 보고·점검할 수단이 없다.** `query e5`는 종목 1개의 구조화 답을 주지만, 전체 적재 현황을 한눈에 둘러보거나 추출 품질 이슈를 찾기엔 부족하다.

이 도구는 그 병목을 푼다:

- 현재 DB 상태를 읽어 **Obsidian vault를 멱등 재생성**한다.
- 회사·세그먼트·고객사·지역·섹터를 노트로 만들고 `[[wikilink]]`로 연결 → Obsidian Graph View가 온톨로지 노드 망을 그대로 시각화.
- 데이터 품질 이슈(중복·합계 이상·미연결·누락)를 자동 검출해 `_qa-report.md`로 집계 → **점검** 수단.
- 백필이 진행돼 적재가 늘면 `themek vault build` 재실행만으로 새 노드가 자동 반영(멱등).

### 1.1 측정 가능한 성공

- `themek vault build` 1줄로 현재 DB(44개사)가 vault로 생성되고, Obsidian에서 "폴더를 vault로 열기"로 즉시 열린다.
- Graph View에서 회사–세그먼트–고객사–지역 노드 망이 보이고, 미연결 고객사(예: Apple Inc.)가 여러 회사로부터 백링크되는 공급망 허브로 드러난다.
- `_qa-report.md`가 알려진 이슈(삼성전자 지역 `미주` 중복 등)를 자동 검출해 나열한다.
- 백필 후 같은 명령을 재실행하면 새 회사 노드가 추가되고, 기존 vault는 깨끗이 교체된다(멱등).

### 1.2 측정 비대상 (out-of-scope)

- buyer_raw → Corporation **자동 매칭(resolved 채우기)** — 본 도구는 미연결을 *드러내는* 데까지. 매칭 로직은 별도 작업.
- 실시간 watch / 파일 변경 감지 / Obsidian 플러그인 자체 개발.
- 백필·ingest 명령에 vault 재생성을 자동 hook으로 묶기 (사용자가 명령어 재생성 선택). 단 미래 확장 여지는 남긴다.
- vault → DB 역방향 편집 반영 (vault는 read-only 산출물, 손으로 고쳐도 다음 build에서 덮어씀).
- 시계열/다기간 비교 뷰 (현재는 회사별 최신 보고서 1건 기준이 아니라 적재된 모든 보고서 반영하되, 비교 분석 UI는 비대상).

## 2. Why Obsidian Vault (대안 비교)

| 옵션 | 장점 | 단점 | 결정 |
|------|------|------|------|
| **Obsidian vault (markdown+wikilink)** | 사용자가 이미 사용 / Graph View가 노드 망 그대로 렌더 / dangling 노드로 미연결 가시화 / Dataview 표 / git 친화 / 플러그인 없이도 plain 동작 | 재생성 필요 / Graph View 노이즈 | ✅ 채택 |
| 단일 HTML 대시보드 (cytoscape/d3) | 설치 불필요 / 맞춤 시각화 | 처음부터 구현 / living doc 아님 / 사용자 워크플로 밖 | ❌ |
| CLI/TUI inspect 명령 | 가볍고 인프라 재사용 | "시각화·친화 환경" 요구 미충족 | ❌ (단 QA 로직은 공유 가능) |
| 그래프 DB(Neo4j 등) 도입 | 진짜 그래프 쿼리 | 인프라 과함 / MVP 부적합 / 현 SQLite 모델로 충분 | ❌ |

## 3. Scope

### 3.1 In-scope (이 작업)

- `src/themek/vault/` 신규 모듈 4개:
  - `model.py` — DB → 내부 그래프 dataclass(노드/엣지 정규화 + dedupe)
  - `qa.py` — 데이터 품질 검사 → 이슈 리스트 (순수 함수)
  - `render.py` — frontmatter/wikilink/표 렌더 + 파일명 안전화
  - `builder.py` — 오케스트레이션: DB 읽기 → model → 파일 쓰기 (멱등)
- CLI 명령 1개: `themek vault build [--out vault/] [--db <dsn>]`
- 생성 산출물:
  - `vault/_index.md` — 전체 회사 표(섹터/세그먼트 수/이슈 수) + 통계
  - `vault/_qa-report.md` — 전 회사 품질 이슈 집계
  - `vault/companies/<회사>.md` — DB 1:1 충실 노트
  - `vault/segments/<세그먼트>.md` — 이름 dedupe 개념 노드
  - `vault/customers/<고객사>.md` — buyer_raw 노드 (설명문 포함 전부)
  - `vault/regions/<지역>.md`, `vault/sectors/<섹터>.md`
  - `vault/.obsidian/graph.json` (선택) — Graph View 색상 그룹 프리셋
- 단위+통합 테스트 ~18-22 케이스 (in-memory SQLite 시드 기반)
- README "후속 Plan들"/도구 섹션 갱신

### 3.2 Out-of-scope (후속)

- buyer 자동 resolve, watch 모드, 백필 hook 자동화, 다기간 비교 뷰, HTML 대시보드 병행 (위 §1.2 참조).
- 회사 노트에 재무 수치/임원 등 E5 외 항목 (현 온톨로지 범위 밖).

## 4. 데이터 소스 (현 DB 구조 요약)

읽기 전용. 모델: `src/themek/db/models.py`. 읽기 패턴은 `src/themek/query/e5.py` 재사용.

핵심 노드 테이블:
- `corporations` (dart_code PK, name_ko, name_en, in_sector_id, belongs_to_id)
- `stocks` (ticker PK, market, issued_by_id→corp)
- `business_reports` (dart_rcept_no PK, corporation_id, period, report_type, url)
- `business_segments` (id PK, corporation_id, name_ko)
- `sectors` (fics_code PK, name_ko, parent_sector_id), `regions` (code PK, name_ko)

핵심 엣지 테이블:
- `revenue_compositions` (subject_corp_id ⊕ subject_segment_id, period, share_pct, source_report_id)
- `customer_relations` (seller_id→corp, buyer_corp_id|buyer_raw, resolved, tier, period, revenue_share_pct, source_report_id)
- `geographic_exposures` (subject_corp_id ⊕ subject_segment_id, region_id, period, share_pct, source_report_id)

"데이터 있는 노드" = `business_reports`가 적재된 corporation과, 그 corporation이 source가 된 엣지가 가리키는 엔티티. 즉 build 진입점은 **business_reports에 등장하는 corporation 집합**.

## 5. Architecture

### 5.1 파일 구조

```
themek/
├── src/themek/
│   └── vault/
│       ├── __init__.py
│       ├── model.py        # NEW: 노드/엣지 dataclass + dedupe + 분류
│       ├── qa.py           # NEW: 품질 검사 (순수 함수)
│       ├── render.py       # NEW: markdown 렌더 + 파일명 안전화
│       └── builder.py      # NEW: DB→model→파일 (멱등 오케스트레이션)
├── tests/
│   ├── test_vault_model.py
│   ├── test_vault_qa.py
│   ├── test_vault_render.py
│   └── test_vault_builder.py    # in-memory DB 시드 + 통합
└── vault/                       # 산출물 (build가 생성/교체)
    ├── _index.md
    ├── _qa-report.md
    ├── companies/  segments/  customers/  regions/  sectors/
    └── .obsidian/graph.json     # 선택
```

### 5.2 컴포넌트 의존성

```
cli.py (themek vault build)
   │
   ▼
builder.build_vault(session, out_dir) 
   │
   ├──▶ model.build_graph(session) → VaultGraph(nodes, edges)   (DB 읽기 + dedupe + 분류)
   │
   ├──▶ qa.detect_issues(VaultGraph | session) → list[Issue]
   │
   ├──▶ render.render_company(node) / render_segment(...) / ...  → (path, text)
   │
   ▼
   파일 쓰기: 생성 하위폴더 비우고 다시 씀 (멱등)
```

### 5.3 데이터 흐름

```
[user] uv run themek vault build
   │
   ▼
1. model.build_graph(session):
   - business_reports에 등장하는 corp 집합 수집
   - 각 corp: 세그먼트/매출비중/고객/지역 엣지 로드
   - 세그먼트·지역·섹터 노드 dedupe(정규화 name 기준)
   - customer 노드 dedupe(정규화 buyer_raw) + kind 분류(entity/descriptive)
   → VaultGraph
2. qa.detect_issues(graph): 중복/합계이상/미연결/누락 → [Issue(corp, severity, kind, detail)]
3. render.*: 각 노드 → (상대경로, markdown text), _index/_qa-report 생성
4. builder: out_dir/{companies,segments,customers,regions,sectors} 비우고 전부 재기록
   + _index.md, _qa-report.md 기록
   → stdout: "vault built: 44 companies, 173 segments, 6 regions, N customers, M issues → vault/"
```

## 6. 노드 → 노트 매핑 상세

### 6.1 회사 노트 `companies/<회사>.md` (DB 1:1 충실)

frontmatter (Dataview 쿼리용):
```yaml
---
type: company
dart_code: "00126380"
name_ko: 삼성전자
name_en: Samsung Electronics
ticker: "005930"        # 대표 보통주 (있으면)
market: KOSPI
sector: 반도체            # in_sector_id → name_ko (없으면 생략)
periods: ["2022", "2023"]
report_count: 2
segment_count: 7
issue_count: 3
tags: [company]
---
```
본문 섹션 (적재된 보고서 기준):
```markdown
# 삼성전자

> [[반도체]] · KOSPI 005930 · DART 00126380

## 세그먼트 (2023 사업보고서)
- [[메모리반도체]] — 42.5%
- [[DX 부문]] — 60.4%
...

## 고객사
- [[Apple Inc.]] (1차, 18%) ⚠️ 미연결
- [[주요 글로벌 IT 고객사 (비공개)]] (미연결, 설명문)

## 지역 노출
- [[미주]] — 35% ⚠️ 중복(아래 QA)
- [[중국]] — 25.8%

## 출처
- [사업보고서 2023](DART url)  ·  rcept_no 20240314...
```

### 6.2 세그먼트 노트 `segments/<세그먼트>.md` (이름 dedupe 개념 노드)

- dedupe 키: `name_ko` 정규화(trim + 공백 정리). 같은 이름이면 한 노트로 병합 → 여러 회사가 함께 링크.
- frontmatter: `type: segment`, `companies: [[[삼성전자]], [[SK하이닉스]]]`(역링크는 Obsidian 자동), `name_ko`.
- 본문: 이 세그먼트를 가진 회사 목록 + 회사별 매출비중. 백링크로 그래프 클러스터 형성.

### 6.3 고객사 노트 `customers/<고객사>.md` (전부 노드화 + 분류)

**모든 buyer_raw를 노드화** (설명문 포함). 처리 방식:

- dedupe 키: 정규화된 buyer_raw 전체 텍스트(소문자화·공백/괄호 정리). 동일 텍스트가 여러 seller에 걸리면 한 노드로 병합 → "여러 회사가 같은 보일러플레이트를 썼다"가 그래프에 드러남.
- 분류 `kind`:
  - `entity` — 짧고 고유명사형 (길이 ≤ 임계, "수요처/업체/제조업체/생산업체/고객사/비공개" 등 일반어 미포함). 예: "Apple Inc.", "Qualcomm".
  - `descriptive` — 길거나 일반어 포함. 예: "세계 유수의 Mobile 및 Computing 관련 전자 업체 (DRAM 수요처)".
  - 분류는 휴리스틱(§9). 향후 resolve 작업의 후보 우선순위로 활용.
- frontmatter:
  ```yaml
  ---
  type: customer
  resolved: false
  kind: entity            # | descriptive
  raw: "Apple Inc."       # 전체 원문 보존
  named_by: ["삼성전자", "현대자동차", "레인보우로보틱스"]
  tags: [unresolved, "unresolved/entity"]   # 또는 unresolved/descriptive
  ---
  ```
- 파일명 안전화: 정규화 + 특수문자 제거. 긴 설명문은 안정적 slug(앞 N자 + 원문 해시 짧은 접미)로 충돌 방지. 본문 제목과 `[[slug|전체 원문]]` 별칭에 전체 텍스트 보존.
- Graph View: `unresolved/entity` vs `unresolved/descriptive` 태그로 색상 그룹 구분 → 실제 회사 후보와 설명문이 한눈에 갈림.

### 6.4 지역 `regions/<지역>.md` / 섹터 `sectors/<섹터>.md`

- 지역: 6개 고정 노드. 본문에 이 지역에 노출된 회사+share 목록.
- 섹터: `parent_sector_id` 있으면 `[[상위섹터]]` 링크로 계층 표현. 본문에 소속 회사 목록.

### 6.5 멱등성

- build는 `out_dir`의 생성 하위폴더(`companies/ segments/ customers/ regions/ sectors/`)와 `_index.md`·`_qa-report.md`만 비우고 재기록한다. `.obsidian/`(사용자 설정)은 건드리지 않되 `graph.json` 프리셋은 없을 때만 생성(덮어쓰지 않음, `--reset-graph`로 강제).
- 같은 DB → 같은 출력(정렬 안정적, 비결정 요소 없음).

## 7. 점검(QA) — `_qa-report.md`

`qa.detect_issues`가 검출하는 항목 (severity: error / warn / info):

| kind | 조건 | severity | 예 |
|------|------|----------|----|
| geo_duplicate | 한 subject에 같은 region이 2회+ (다른 share_pct) | warn | 삼성 `미주` 35%/31.1% |
| revenue_sum_anomaly | 한 corp의 corp-level 세그먼트 share 합이 100±ε 크게 벗어남 | warn | 합 204.8% (그룹 중복?) |
| segment_no_revenue | 세그먼트에 revenue_composition 없음 | info | — |
| unresolved_customer | resolved=0 고객 (kind별 카운트) | info | 전 172건 |
| descriptive_customer | buyer_raw가 설명문(kind=descriptive) | info | "주요 글로벌 IT 고객사(비공개)" |
| missing_geo / missing_customer / missing_segment | 보고서에 해당 엣지 0건 | info | 한미반도체 세그먼트 1개뿐 |
| low_segment_count | 세그먼트 ≤1 (추출 빈약 가능) | warn | SK하이닉스 1개 |

`_qa-report.md` 구성:
- 상단 요약(전체 이슈 수, kind별 집계, 회사별 issue_count 표 → `[[회사]]` 링크).
- kind별 상세 리스트 (각 항목 `[[회사]]` 링크 + detail).
- 회사 노트 frontmatter `issue_count`와 `_index.md` 표에도 반영.

QA 로직은 순수 함수라 CLI inspect 등 다른 표면에서도 재사용 가능(미래).

## 8. Tech Stack

- Python 3.12+, 기존 의존성만 (신규 의존성 0 목표).
- DB 읽기: SQLAlchemy 2.0 세션 (`src/themek/db/engine.py` 재사용).
- YAML frontmatter: 직접 직렬화(간단) 또는 기존 의존 중 yaml 있으면 사용. **신규 의존 추가 회피** — frontmatter는 최소 직접 렌더(문자열). 값 이스케이프만 주의.
- 파일 IO: stdlib `pathlib`.
- CLI: typer (기존).
- 테스트: pytest + in-memory SQLite (`sqlite:///:memory:`) 시드.

## 9. 고객사 분류 휴리스틱 (kind)

`descriptive`로 판정하는 규칙(OR):
- 길이 > 20자(한글/영문 혼합 고려, 임계는 구현 시 튜닝)
- 일반어 포함: `수요처|업체|제조업체|생산업체|고객사|비공개|업체들|메이커|디바이스 제조` 등 (정규식 set, 구현 시 데이터로 보강)
- 쉼표/슬래시로 다수 항목 나열 ("합성수지, 플라스틱 가공업체, ...")

그 외 = `entity`. 휴리스틱은 보수적(애매하면 entity로 두되, descriptive 일반어가 명확하면 descriptive). 잘못 분류돼도 둘 다 노드로 존재하므로 손실 없음 — 분류는 색상/우선순위용.

## 10. CLI 설계

```bash
# 현재 DB 상태로 vault 멱등 재생성
uv run themek vault build
# stdout: "vault built: 44 companies, 173 segments, 6 regions, 41 customers, 28 issues → vault/"

# 출력 경로/DB 지정 (선택)
uv run themek vault build --out vault/ --db sqlite:///./themek.db

# (선택) Graph 색상 프리셋 강제 재기록
uv run themek vault build --reset-graph
```

기본 `--out`은 레포 `vault/`. 기본 `--db`는 settings의 `POSTGRES_DSN`.

## 11. Testing Strategy

in-memory SQLite에 알려진 픽스처를 시드하고 검증. 실 DART/LLM 호출 없음.

| 레이어 | 케이스 | 내용 |
|--------|--------|------|
| `model.build_graph` | 4 | 진입점=보고서 있는 corp만 / 세그먼트·고객 dedupe 병합 / 빈 회사 제외 / named_by 집계 |
| `model` customer 분류 | 3 | entity / descriptive(일반어) / descriptive(나열) |
| `qa.detect_issues` | 6 | geo_duplicate / revenue_sum_anomaly / unresolved 카운트 / missing_* / low_segment_count / 이슈 0건 클린 |
| `render` | 5 | frontmatter 직렬화 / wikilink 별칭 / 특수문자 파일명("CJ CGV","스마트폰/네트워크") / 긴 설명문 slug+해시 / 표 렌더 |
| `builder` 통합 | 3 | 시드 DB → 기대 파일 트리 생성 / 재실행 멱등(동일 출력·생성폴더만 교체) / `.obsidian` 보존 |

총 ~21개. 기존 테스트 스위트와 함께 통과.

## 12. Open Decisions Summary

| ID | 결정 사항 | 결정 | 비고 |
|----|----------|------|------|
| V1 | 매체 | ✅ Obsidian vault | brainstorming 합의 |
| V2 | 생성 범위 | ✅ 데이터 있는 노드만 (보고서 적재 corp + 연결 엔티티) | 빈 뼈대 제외 |
| V3 | 갱신 방식 | ✅ `themek vault build` 멱등 재생성 | 백필 hook 자동화는 후속 |
| V4 | vault 위치 | ✅ 레포 `vault/` | git tracked 가능 |
| V5 | 미연결 고객사 처리 | ✅ 전부 노드화 + `kind: entity\|descriptive` 분류 | 설명문도 노드, 색상 그룹 구분 |
| V6 | 세그먼트 dedupe | ✅ name_ko 정규화로 병합 (개념 노드) | 회사 간 연결 극대화 |
| V7 | 신규 의존성 | ✅ 0 (frontmatter 직접 렌더) | yaml 기존 있으면 사용 가능 |
| V8 | vault git tracked? | ⏳ plan 진입 시 확정 (권장: `vault/` tracked, `.obsidian/workspace*`는 ignore) | — |

## 13. Risks

- **파일명 충돌/특수문자** — 회사·고객 명에 `/ : * ?` 등. 안전화 + slug+해시로 대응. 테스트로 커버.
- **세그먼트 dedupe 과병합** — "기타" 같은 일반 세그먼트명이 무관한 회사를 묶을 수 있음. 완화: 일반어 세그먼트는 회사 prefix 유지 옵션 여지(우선 단순 dedupe, QA info로 노출). plan 진입 시 재검토.
- **Graph View 노이즈** — 노드 ~200개면 양호하나 customer 설명문이 많으면 복잡. 태그 색상 그룹 + 필터로 완화.
- **frontmatter 이스케이프** — 콜론/따옴표 포함 값. 직접 렌더 시 안전 인용 필요(테스트 케이스).
- **백필 증가 시 규모** — 수백 개사로 늘면 vault 노드 수천. 현 MVP는 44개 기준 충분, 규모 정책은 후속.

## 14. Acceptance Criteria

1. `uv run themek vault build`가 0 exit + `vault/`에 회사/세그먼트/고객/지역/섹터 노트 + `_index.md` + `_qa-report.md` 생성.
2. Obsidian으로 `vault/`를 열면 Graph View에 회사–세그먼트–고객–지역 노드 망이 보이고, Apple Inc.가 다수 회사로부터 백링크된다.
3. `_qa-report.md`가 삼성전자 지역 `미주` 중복을 포함한 알려진 이슈를 검출·나열한다.
4. 미연결 고객사가 설명문 포함 전부 노드로 존재하고 `kind`로 분류된다.
5. 같은 DB로 두 번 build 시 출력이 동일하고, 생성 하위폴더만 교체되며 `.obsidian/` 사용자 설정은 보존된다.
6. ~21개 신규 테스트 + 기존 스위트 통과.
7. README에 `themek vault build` 사용법 추가.

## 15. Plan 분기 (다음 단계)

`docs/superpowers/plans/2026-05-29-dart-ontology-obsidian-vault.md` 작성 — TDD 구조 예상 task:

- T0: `vault/` 위치/gitignore 정책 확정(V8) + 스캐폴딩(`src/themek/vault/__init__.py`)
- T1-T2: `model.py` — VaultGraph dataclass + build_graph(진입점·dedupe·named_by) + 테스트
- T3: customer `kind` 분류 휴리스틱 + 테스트
- T4-T5: `qa.py` — detect_issues 전 항목 + 테스트
- T6-T7: `render.py` — frontmatter/wikilink/파일명 안전화 + 표 + 테스트
- T8: `builder.py` — 멱등 오케스트레이션 + 통합 테스트
- T9: CLI `vault build` + 통합 테스트
- T10: 실 `themek.db`로 smoke build + Obsidian 육안 확인 메모(`docs/vault-smoke-notes.md`) + README 갱신
