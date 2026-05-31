# Track C1 — Vault Visibility (QA report + frontmatter + new metrics) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** vault 투영이 그래프의 무결성·메타·신규 재무 metric을 노출하도록 보강한다. (C9 QA 리포트 emit, C10 회사 frontmatter 보강, C12 B3 신규 metric 렌더)

**Architecture:** 전부 `src/themek/ontology/projection/vault.py` 국소 변경 — 순수 투영(읽기 전용). `build_vault` 시작부에서 `check_integrity(session)`를 **1회** 호출해 `issues`를 확보, C9(리포트)·C10(issue_count)에서 공유. 신규 순수 렌더 헬퍼(`_render_qa_report`, frontmatter 빌더)는 단위 테스트 가능하게 분리.

**Tech Stack:** Python, SQLAlchemy 2.x, pytest. 테스트는 인메모리 `ontology_session` 픽스처 + 합성 노드/엣지/fact.

**Spec:** `docs/superpowers/specs/2026-05-31-track-c-discovery-visibility-design.md` §3.1, §3.2, §3.4

---

## File Structure

- `src/themek/ontology/projection/vault.py` — **수정**: `_render_qa_report`(신규), `build_vault`(issues 1회 호출 + `_qa-report.md` emit + 반환 dict 확장), 회사 frontmatter 빌더 확장, `_render_financials`(현금흐름/주당 소표 추가).
- 테스트: `tests/ontology/test_projection_vault.py` — **수정/확장**.

---

## Task 1: C9 — `_qa-report.md` emit (check_integrity 재사용)

**Success gate (측정 가능):**
- `.venv/bin/python -m pytest tests/ontology/test_projection_vault.py` → 전 통과.
- `_render_qa_report([])` → "✅ 무결성 이슈 없음" 포함, frontmatter `type: "qa-report"`.
- 혼합 severity 입력 → error/warn/info 카운트 정확, severity 순 그룹, 각 그룹 markdown 표(`code | subject | message`).
- `build_vault` 실행 후 `out_dir/_qa-report.md` 파일 존재 + 반환 dict에 `issues` 키.

**Files:**
- Modify: `src/themek/ontology/projection/vault.py`
- Test: `tests/ontology/test_projection_vault.py`

- [ ] **Step 1: 실패 테스트 작성** — `_render_qa_report` 순수 함수(0건/혼합), `build_vault` emit 검증(합성 세션).
- [ ] **Step 2: 구현** — `from themek.ontology.validate import check_integrity, Issue`. `_render_qa_report(issues) -> str`. `build_vault` 시작부에서 `issues = check_integrity(session)` 1회, 노트 기록 후 `(out_dir/"_qa-report.md").write_text(_render_qa_report(issues))`. 반환 dict `{..., "issues": len(issues)}`.
- [ ] **Step 3: 검증** — 테스트 통과 + 실제 `themek ontology vault` 재생성 후 `_qa-report.md` 육안 확인.

---

## Task 2: C12 — 신규 metric(EPS·현금흐름·발행주식수) 렌더

**Success gate (측정 가능):**
- `_render_financials`가 `cf_operating/investing/financing`(억원), `eps`(원/주), `shares_outstanding`(주)를 **단위별 분리 표**로 렌더.
- 단위 혼동 없음: KPI 억원 표에 eps/shares 미포함.
- 해당 회사에 fact 없는 metric → 행/소표 생략(기존 `if not any(...)` 패턴).
- 인라인 Dataview 필드에 신규 metric 포함(`eps_2023FY:: ...`).
- 테스트 통과.

**Files:**
- Modify: `src/themek/ontology/projection/vault.py`
- Test: `tests/ontology/test_projection_vault.py`

- [ ] **Step 1: 실패 테스트 작성** — eps/cf_*/shares fact 합성 → 올바른 단위 표·인라인 필드. fact 없는 회사 → 소표 생략.
- [ ] **Step 2: 구현** — `_CF_ORDER`/`_CF_LABEL`, `_eok` 재사용한 현금흐름 소표. `eps`/`shares_outstanding`용 주당·주식 소표(`{:,.0f}원`/`{:,.0f}주`). 인라인 필드 루프에 신규 metric 추가.
- [ ] **Step 3: 검증** — 테스트 통과 + 삼성(005930) 노트에 EPS/현금흐름 표 육안 확인.

---

## Task 3: C10 — 회사 frontmatter 보강

**Success gate (측정 가능):**
- 회사 frontmatter에 `ticker`·`market`·`sector`·`periods`(YAML list)·`report_count`·`segment_count`·`customer_count`·`issue_count` 포함.
- `ticker`/`market`은 `ISSUES_STOCK`→stock 노드 attrs에서, `issue_count`는 Task1의 `issues` 중 `subject==c.id` 개수에서.
- 종목/재무 없는 회사 → 해당 필드 기본값(`""`/`[]`/`0`)으로 안전.
- 섹터명 등 특수문자 YAML escape(`_yaml_str`).
- 테스트 통과.

**Files:**
- Modify: `src/themek/ontology/projection/vault.py`
- Test: `tests/ontology/test_projection_vault.py`

- [ ] **Step 1: 실패 테스트 작성** — stock attrs·facts·edges 합성 → frontmatter 필드 정확. 빈 회사 → 기본값. issue_count = 합성 무결성 이슈 매칭 수.
- [ ] **Step 2: 구현** — `issues_by_company: dict[str,int]` 인덱스(Task1 `issues` 재사용). `_yaml_str` escape 헬퍼. 회사 루프에서 stock/sector/period/count 수집 → frontmatter parts 확장. `periods: [...]` 인라인 배열.
- [ ] **Step 3: 검증** — 테스트 통과 + 회사 노트 frontmatter 육안 + (선택) Obsidian Dataview 쿼리 동작.

---

## Done criteria

- [ ] 전체 테스트 통과(`.venv/bin/python -m pytest -q`).
- [ ] `themek ontology vault` 재생성 → `_qa-report.md` 생성·EPS/CF 표·보강된 frontmatter 확인.
- [ ] vault 재생성 산출물 커밋(`data(vault): ...`), 코드 커밋(`feat(vault): ...`) 분리.
