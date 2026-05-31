# Track C1 — Vault Visibility (QA report + frontmatter + new metrics) Implementation Plan

> **상태: ✅ 구현 완료** — main 반영됨(2026-05-31 기준, 테스트 314개 통과). 아래 체크박스는 실행 추적용 기록이며 갱신되지 않았을 수 있습니다.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** vault 투영이 그래프의 무결성·메타·신규 재무 metric을 노출하도록 보강한다. (C9 QA 리포트 emit, C10 회사 frontmatter 보강, C12 B3 신규 metric 렌더)

**Architecture:** 전부 `src/themek/ontology/projection/vault.py` 국소 변경 — 순수 투영(읽기 전용). `build_vault` 시작부에서 `check_integrity(session)`를 **1회** 호출해 `issues`를 확보, C9(리포트)·C10(issue_count)에서 공유. 신규 순수 렌더 헬퍼(`_render_qa_report`, frontmatter 빌더)는 단위 테스트 가능하게 분리.

**Tech Stack:** Python, SQLAlchemy 2.x, pytest. 테스트는 인메모리 `ontology_session` 픽스처 + 합성 노드/엣지/fact.

**Spec:** `docs/superpowers/specs/2026-05-31-track-c-discovery-visibility-design.md` §3.1, §3.2, §3.4

> **측정 규약:** 모든 gate는 복붙 실행 가능한 명령 + 정량 기대값으로 기술한다. 가상 "육안 확인"은 gate가 아니다(검증 단계는 grep/assert로 대체). 명령 prefix: `V=.venv/bin/python` (테스트), `T=.venv/bin/pytest`.

---

## File Structure

- `src/themek/ontology/projection/vault.py` — **수정**: `_render_qa_report`(신규), `build_vault`(issues 1회 호출 + `_qa-report.md` emit + 반환 dict 확장), 회사 frontmatter 빌더 확장, `_render_financials`(현금흐름/주당 소표 추가).
- 테스트: `tests/ontology/test_projection_vault.py` — **수정/확장**.

---

## Task 1: C9 — `_qa-report.md` emit (check_integrity 재사용)

**Success gate (전부 자동 검증):**
1. `.venv/bin/pytest tests/ontology/test_projection_vault.py -q` → exit 0, **신규 테스트 ≥ 3개**(`test_qa_report_empty`, `test_qa_report_mixed_severity`, `test_build_vault_emits_qa_report`) 포함 전 통과.
2. `_render_qa_report([])` 반환 문자열이 `'type: "qa-report"'` **그리고** `"무결성 이슈 없음"`을 포함(assert 2건).
3. 혼합 입력 `[Issue("duplicate_edge","error",...), Issue("orphan_fact","warn",...), Issue("negative_or_zero_equity","info",...)]` → 출력에 `"error: 1"`,`"warn: 1"`,`"info: 1"` 카운트 문자열 존재 **그리고** error 그룹 헤더가 warn 그룹 헤더보다 앞(인덱스 비교 assert).
4. 각 severity 그룹에 markdown 표 헤더 행 `"| code | subject | message |"` 정확히 1회씩 존재(`.count(...)` assert).
5. `build_vault(session, tmp_path)` 호출 후: `(tmp_path/"_qa-report.md").exists() is True` **그리고** 반환 dict에 `"issues"` 키가 있고 `== len(check_integrity(session))`.

**Files:** Modify `src/themek/ontology/projection/vault.py` · Test `tests/ontology/test_projection_vault.py`

- [ ] **Step 1: 실패 테스트 작성** — 위 gate 1~5를 그대로 어서션으로 코딩. (RED: 함수 미존재로 ImportError/AssertionError)
- [ ] **Step 2: 구현** — `from themek.ontology.validate import check_integrity, Issue`. `_render_qa_report(issues) -> str`. `build_vault` 시작부 `issues = check_integrity(session)` 1회 → `(out_dir/"_qa-report.md").write_text(_render_qa_report(issues))` → 반환 `{..., "issues": len(issues)}`.
- [ ] **Step 3: 검증** — `.venv/bin/pytest tests/ontology/test_projection_vault.py -q` exit 0. 실데이터 확인은 측정 명령으로: `.venv/bin/python -m themek ontology vault --out vault && test -f vault/_qa-report.md && grep -q 'type: "qa-report"' vault/_qa-report.md` → exit 0.

---

## Task 2: C12 — 신규 metric(EPS·현금흐름·발행주식수) 렌더

**Success gate (전부 자동 검증):**
1. `.venv/bin/pytest tests/ontology/test_projection_vault.py -q` → exit 0, **신규 테스트 ≥ 2개**(`test_render_cashflow_and_eps`, `test_metric_omitted_when_absent`) 통과.
2. `cf_operating/investing/financing` fact(억 단위 amount) 합성 → `_render_financials` 출력에 헤더 `"## 현금흐름"` 1회 **그리고** 세 라벨(영업/투자/재무활동현금흐름) 각 1행, 값은 `_eok` 포맷(`"억"` 접미 포함).
3. `eps` fact 합성 → 출력에 `"원/주"` 또는 EPS 라벨 행 존재 **그리고** 값이 `,`-천단위 + `"원"` 형식(`re.search(r"[\d,]+원", out)`).
4. `shares_outstanding` fact 합성 → 출력에 주식수 행 존재 **그리고** `"주"` 단위 + 천단위(`re.search(r"[\d,]+주", out)`).
5. **단위 격리:** KPI 억원 표 헤더(`"## 재무"`) 블록 안에 `"원/주"`/`eps`/`shares` 라벨 미포함(assert `not in`).
6. eps/cf/shares fact 없는 회사 → 해당 소표 헤더 문자열 출력에 **부재**(assert `"## 현금흐름" not in out`).
7. 인라인 필드: 출력에 `re.search(r"eps_\d{4}(Q1|H1|Q3|FY)::", out)` 매치 ≥ 1.

**Files:** Modify `src/themek/ontology/projection/vault.py` · Test `tests/ontology/test_projection_vault.py`

- [ ] **Step 1: 실패 테스트 작성** — gate 1~7 어서션 코딩(eps/cf_*/shares fact + fact-없는 케이스).
- [ ] **Step 2: 구현** — `_CF_ORDER`/`_CF_LABEL`(억원, `_eok`), eps/shares 소표(`{:,.0f}원`/`{:,.0f}주`). 인라인 필드 루프 확장. 기존 `if not any(...)` 생략 패턴 준수.
- [ ] **Step 3: 검증** — pytest exit 0. 실데이터: `.venv/bin/python -m themek ontology vault --out vault && grep -lq '## 현금흐름' vault/companies/삼성전자.md` → exit 0(삼성은 cf fact 보유).

---

## Task 3: C10 — 회사 frontmatter 보강

**Success gate (전부 자동 검증):**
1. `.venv/bin/pytest tests/ontology/test_projection_vault.py -q` → exit 0, **신규 테스트 ≥ 3개**(`test_frontmatter_full`, `test_frontmatter_empty_company_defaults`, `test_frontmatter_issue_count`) 통과.
2. stock(attrs ticker/market)·sector·facts·segment/customer 엣지를 갖춘 합성 회사 노트 frontmatter에 8개 키 전부 존재: `ticker`,`market`,`sector`,`periods`,`report_count`,`segment_count`,`customer_count`,`issue_count`(`for k: assert f"{k}:" in fm`).
3. `ticker`/`market` 값 == 합성 stock 노드 attrs 값(정확 일치 assert). `sector` == IN_SECTOR object label.
4. `periods` == 합성 fact의 정렬된 `"{year}{fp}"` YAML 리스트(예: `periods: [2022FY, 2023FY]`), `report_count` == distinct period 수(int 일치), `segment_count`/`customer_count` == dedup 후 엣지 수.
5. `issue_count` == `check_integrity` 결과 중 `subject == c.id`인 개수(합성 중복엣지 1개 주입 → 해당 회사 `issue_count: 1`, 무관 회사 `issue_count: 0`).
6. 종목·재무·엣지 0인 빈 회사 → `ticker: ""`,`market: ""`,`periods: []`,`report_count: 0`,`segment_count: 0`,`customer_count: 0`,`issue_count: 0`(전부 기본값 assert, KeyError/None 없음).
7. 특수문자: label에 `"` 포함 섹터 → frontmatter가 유효(escape됨) — `_yaml_str('a"b')` 결과에 raw 미escaped `"` 없음.

**Files:** Modify `src/themek/ontology/projection/vault.py` · Test `tests/ontology/test_projection_vault.py`

- [ ] **Step 1: 실패 테스트 작성** — gate 1~7 어서션(합성 stock attrs·facts·중복엣지·빈 회사·특수문자).
- [ ] **Step 2: 구현** — `issues_by_company: dict[str,int]`(Task1 `issues` 재사용). `_yaml_str` escape 헬퍼. 회사 루프에서 stock/sector/period/count 수집 → frontmatter parts 확장(`periods: [...]` 인라인).
- [ ] **Step 3: 검증** — pytest exit 0. 실데이터: `.venv/bin/python -m themek ontology vault --out vault && grep -Eq '^ticker: ' vault/companies/삼성전자.md && grep -Eq '^periods: \[' vault/companies/삼성전자.md` → exit 0.

---

## Done criteria (전부 자동 검증)

- [ ] `.venv/bin/pytest -q` → exit 0, 회귀 0(기존 297 + 신규 ≥ 8 통과).
- [ ] `.venv/bin/python -m themek ontology vault --out vault` → exit 0, stdout 반환 dict에 `issues` 키.
- [ ] `test -f vault/_qa-report.md` exit 0 · `grep -lq '## 현금흐름' vault/companies/삼성전자.md` exit 0 · `grep -Eq '^issue_count: ' vault/companies/삼성전자.md` exit 0.
- [ ] 커밋 분리: 코드(`feat(vault): ...`) + 재생성 산출물(`data(vault): ...`).
