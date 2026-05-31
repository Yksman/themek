# Track C2 — Segment Namespace (over-merge mitigation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** segment 노드를 회사 네임스페이스(`segment:{dart_code}:{slug}`) 기본으로 전환해, 서로 다른 회사의 동명 일반 세그먼트가 한 노드로 우발 병합되는 문제를 제거한다. 의도된 교차회사 canonical 병합은 alias 시드(`merge_segments`)로만 일어나도록 한다.

**Architecture:** `segment_id`에 옵션 `company_key` 추가(하위호환). `business_structure` ingest가 `HAS_SEGMENT` 생성 시 회사 키 사용 + segment 노드 attrs에 `{company, name}` 기록. 기존 전역 키로 적재된 데이터는 일회성 멱등 백필 스크립트(`scripts/renamespace_segments.py`)로 재네임스페이스. `merge_segments`/alias/`_repoint_edges`는 그대로 — canonical 타깃이 전역 노드면 의도된 병합이 됨.

**Tech Stack:** Python, SQLAlchemy 2.x, pytest. 테스트는 인메모리 `ontology_session` + 합성 노드/엣지.

**Spec:** `docs/superpowers/specs/2026-05-31-track-c-discovery-visibility-design.md` §3.3

**선행:** C1(vault visibility) 완료 권장 — 재네임스페이스 후 vault 재생성으로 백링크 분리 확인.

---

## File Structure

- `src/themek/ontology/core/ids.py` — **수정**: `segment_id(name_ko, company_key=None)`.
- `src/themek/ontology/ingest/business_structure.py` — **수정**: `HAS_SEGMENT`에 `company_key=dart_code` + segment attrs.
- `scripts/renamespace_segments.py` — **신규**: 일회성 멱등 재네임스페이스.
- `src/themek/ontology/projection/vault.py` — **확인**: 회사별 분리 노드에서도 백링크/링크 정상(노드 label 표시명 유지 → 변경 최소).
- 테스트: `tests/ontology/test_ids.py`(확장), `tests/ontology/test_business_structure.py`(확장), `tests/test_renamespace_segments.py`(신규).

---

## Task 1: segment_id 회사 네임스페이스 옵션

**Success gate (측정 가능):**
- `segment_id("반도체")` == `segment:반도체`(기존 불변, 하위호환).
- `segment_id("반도체", company_key="00126380")` == `segment:00126380:반도체`.
- 장문 slug 해시 truncate 동작 유지.
- 테스트 통과.

**Files:**
- Modify: `src/themek/ontology/core/ids.py`
- Test: `tests/ontology/test_ids.py`

- [ ] **Step 1: 실패 테스트 작성** — 두 시그니처 + 장문.
- [ ] **Step 2: 구현** — `company_key` 분기.
- [ ] **Step 3: 검증** — 테스트 통과.

---

## Task 2: business_structure가 회사 키로 segment 적재

**Success gate (측정 가능):**
- 동명 세그먼트를 가진 두 회사 ingest → **별개** segment 노드 2개(`segment:{dartA}:...`, `segment:{dartB}:...`).
- segment 노드 `attrs == {"company": dart_code, "name": name_ko}`.
- 멱등 재실행 시 노드/엣지 수 불변.
- 기존 business_structure 테스트 회귀 통과(키 형식 변경 반영).

**Files:**
- Modify: `src/themek/ontology/ingest/business_structure.py`
- Test: `tests/ontology/test_business_structure.py`

- [ ] **Step 1: 실패 테스트 작성** — 두 회사 동명 세그먼트 → 별 노드. attrs 검증.
- [ ] **Step 2: 구현** — `segment_id(name, company_key=dart_code)` + attrs. 기존 테스트의 기대 키 갱신.
- [ ] **Step 3: 검증** — 테스트 통과.

---

## Task 3: renamespace_segments 백필 스크립트 (일회성·멱등)

**Success gate (측정 가능):**
- 기존 전역 `segment:{slug}` 노드를 가리키는 각 `HAS_SEGMENT` 엣지를 `segment:{subject_dart_code}:{slug}` 노드로 재지정(노드 upsert + `_repoint_edges` 재사용).
- 재지정 후 참조 없는 전역 segment 노드 제거(단, alias canonical 타깃은 보존).
- 멱등: 2회 실행 시 2회차 변경 0.
- 재실행 후 `check_integrity(session)` → error 0(중복 엣지·고아 없음).
- 동명 두 회사 → 백필 후 별 노드.

**Files:**
- Create: `scripts/renamespace_segments.py`
- Test: `tests/test_renamespace_segments.py`

- [ ] **Step 1: 실패 테스트 작성** — 전역 노드 + 2개 회사 HAS_SEGMENT 합성 → 백필 → 별 노드·고아 제거·멱등·check_integrity 무에러.
- [ ] **Step 2: 구현** — company 노드별 dart_code 조회, HAS_SEGMENT 순회, 회사키 노드 upsert(label·attrs 보존), `_repoint_edges`, 고아 전역 노드 정리. `__main__` 진입점(세션 오픈 + 요약 출력).
- [ ] **Step 3: 검증** — 테스트 통과 + 실 DB 백필 실행(백업 후) → `merge_segments` 재실행 → `check_integrity` 무에러.

---

## Task 4: 재투영 + 검증

**Success gate (측정 가능):**
- `themek ontology vault` 재생성 → 동명 세그먼트 노트가 회사별로 분리, 백링크 오염 없음.
- 의도된 alias 병합(예: "메모리"/"메모리 반도체" → canonical)은 그대로 동작.
- 전체 테스트 통과.

- [ ] **Step 1:** DB 백업 → `renamespace_segments` → `merge_segments` → `check_integrity`.
- [ ] **Step 2:** vault 재생성 + 육안 확인(분리/병합 의도대로).
- [ ] **Step 3:** 코드 커밋 + vault 재생성 산출물 커밋 분리.

---

## Done criteria

- [ ] 전체 테스트 통과(`.venv/bin/python -m pytest -q`).
- [ ] 백필 멱등 + `check_integrity` error 0.
- [ ] vault에서 동명 세그먼트 분리 확인, 의도된 병합 유지.

## 한계

- 스크립트는 *기존* 전역 노드 가정 — 이후 ingest는 처음부터 회사 키 → 재실행 시 noop.
- 자동 의미 병합(임베딩) 비범위 — 교차회사 병합은 수동 alias 시드로만.
