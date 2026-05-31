# Track C2 — Segment Namespace (over-merge mitigation) Implementation Plan

> **상태: ✅ 구현 완료** — main 반영됨(2026-05-31 기준, 테스트 314개 통과). 아래 체크박스는 실행 추적용 기록이며 갱신되지 않았을 수 있습니다.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** segment 노드를 회사 네임스페이스(`segment:{dart_code}:{slug}`) 기본으로 전환해, 서로 다른 회사의 동명 일반 세그먼트가 한 노드로 우발 병합되는 문제를 제거한다. 의도된 교차회사 canonical 병합은 alias 시드(`merge_segments`)로만 일어나도록 한다.

**Architecture:** `segment_id`에 옵션 `company_key` 추가(하위호환). `business_structure` ingest가 `HAS_SEGMENT` 생성 시 회사 키 사용 + segment 노드 attrs에 `{company, name}` 기록. 기존 전역 키로 적재된 데이터는 일회성 멱등 백필 스크립트(`scripts/renamespace_segments.py`)로 재네임스페이스. `merge_segments`/alias/`_repoint_edges`는 그대로 — canonical 타깃이 전역 노드면 의도된 병합이 됨.

**Tech Stack:** Python, SQLAlchemy 2.x, pytest. 테스트는 인메모리 `ontology_session` + 합성 노드/엣지.

**Spec:** `docs/superpowers/specs/2026-05-31-track-c-discovery-visibility-design.md` §3.3

**선행:** C1(vault visibility) 완료 권장 — 재네임스페이스 후 vault 재생성으로 백링크 분리 확인.

> **측정 규약:** 모든 gate는 복붙 실행 가능한 명령 + 정량 기대값으로 기술한다. 가상 "육안 확인"은 gate가 아니다(검증 단계는 grep/assert로 대체). 멱등·정합은 카운트 불변/`check_integrity` error 0으로 측정.

---

## File Structure

- `src/themek/ontology/core/ids.py` — **수정**: `segment_id(name_ko, company_key=None)`.
- `src/themek/ontology/ingest/business_structure.py` — **수정**: `HAS_SEGMENT`에 `company_key=dart_code` + segment attrs.
- `scripts/renamespace_segments.py` — **신규**: 일회성 멱등 재네임스페이스.
- 테스트: `tests/ontology/test_ids.py`(확장), `tests/ontology/test_business_structure.py`(확장), `tests/test_renamespace_segments.py`(신규).

---

## Task 1: segment_id 회사 네임스페이스 옵션

**Success gate (전부 자동 검증):**
1. `.venv/bin/pytest tests/ontology/test_ids.py -q` → exit 0, 신규 테스트 ≥ 1개 통과.
2. `segment_id("반도체") == "segment:반도체"`(기존 불변 — 하위호환 assert).
3. `segment_id("반도체", company_key="00126380") == "segment:00126380:반도체"`(정확 일치 assert).
4. 장문(>48자) name → 회사키 분기에서도 slug 해시 truncate 적용: `len(segment_id(long, company_key="x").split(":")[-1]) <= 48` **그리고** 두 다른 long name → 다른 id(충돌 0).
5. 기존 `test_ids.py` 회귀 통과(다른 `*_id` 함수 불변).

**Files:** Modify `src/themek/ontology/core/ids.py` · Test `tests/ontology/test_ids.py`

- [ ] **Step 1: 실패 테스트 작성** — gate 2~4 어서션.
- [ ] **Step 2: 구현** — `company_key` 분기(`f"segment:{company_key}:{slug(name_ko)}"`).
- [ ] **Step 3: 검증** — `.venv/bin/pytest tests/ontology/test_ids.py -q` exit 0.

---

## Task 2: business_structure가 회사 키로 segment 적재

**Success gate (전부 자동 검증):**
1. `.venv/bin/pytest tests/ontology/test_business_structure.py -q` → exit 0, 신규 테스트 ≥ 1개 통과.
2. 동명 세그먼트("기타")를 가진 회사 A(dartA)·B(dartB)를 각각 ingest → segment 노드 정확히 **2개**(`session.query(Node).filter(kind=="segment").count() == 2`), id가 `segment:{dartA}:기타` / `segment:{dartB}:기타`(둘 다 존재 assert).
3. 각 segment 노드 `attrs == {"company": dart_code, "name": "기타"}`(dict 일치 assert).
4. 동일 회사 A를 **2회** ingest → segment 노드 수·`HAS_SEGMENT` 엣지 수 불변(멱등: 1회차 카운트 == 2회차 카운트).
5. 기존 `test_business_structure.py` 회귀: 기대 segment id를 회사키 형식으로 갱신 후 전 통과(회귀 0).

**Files:** Modify `src/themek/ontology/ingest/business_structure.py` · Test `tests/ontology/test_business_structure.py`

- [ ] **Step 1: 실패 테스트 작성** — gate 2~4 어서션(두 회사 동명 → 별 노드, attrs, 멱등).
- [ ] **Step 2: 구현** — `segment_id(name, company_key=dart_code)` + `attrs={"company":dart_code,"name":name}`. 기존 테스트 기대 키 갱신.
- [ ] **Step 3: 검증** — `.venv/bin/pytest tests/ontology/test_business_structure.py -q` exit 0.

---

## Task 3: renamespace_segments 백필 스크립트 (일회성·멱등)

**Success gate (전부 자동 검증):**
1. `.venv/bin/pytest tests/test_renamespace_segments.py -q` → exit 0, 신규 테스트 ≥ 3개(`test_renamespace_splits`, `test_renamespace_idempotent`, `test_renamespace_integrity_clean`) 통과.
2. **분리:** 전역 `segment:기타` 1개를 회사 A·B가 공유(HAS_SEGMENT 2엣지) → 백필 후 `segment:{dartA}:기타`·`segment:{dartB}:기타` 2노드 존재, 각 회사 엣지가 자기 회사키 노드를 가리킴(object_id 일치 assert).
3. **고아 제거:** 백필 후 참조 0인 전역 `segment:기타` 노드 부재(`session.get(Node, "segment:기타") is None`) — 단, alias canonical 타깃으로 등록된 전역 노드는 보존(별 테스트).
4. **멱등:** 백필 2회 실행 → 2회차 반환 `repointed == 0` **그리고** 노드/엣지 총수 불변.
5. **정합:** 백필 후 `check_integrity(session)` 결과에 `severity == "error"` 0건(`[i for i in issues if i.severity=="error"] == []`).

**Files:** Create `scripts/renamespace_segments.py` · Test `tests/test_renamespace_segments.py`

- [ ] **Step 1: 실패 테스트 작성** — gate 2~5 어서션(공유 전역 노드 + 2회사 + alias-보존 케이스 + 멱등 + check_integrity).
- [ ] **Step 2: 구현** — company별 dart_code 조회, HAS_SEGMENT 순회, 회사키 노드 upsert(label·attrs 보존), `_repoint_edges` 재사용, 참조 0 전역 노드 정리(alias 타깃 제외). `__main__` 진입점(세션 + 요약 dict 출력).
- [ ] **Step 3: 검증** — pytest exit 0. 실 DB: `cp themek.db themek.db.pre-c2.bak && .venv/bin/python scripts/renamespace_segments.py` → exit 0, 출력 dict 확인.

---

## Task 4: 재투영 + 정합 검증

**Success gate (전부 자동 검증):**
1. 실 DB 백필 → `merge_segments` 재실행 → `.venv/bin/python -c "from ...validate import check_integrity; ...; assert not [i for i in check_integrity(s) if i.severity=='error']"` exit 0(error 0).
2. `.venv/bin/python -m themek ontology vault --out vault` → exit 0.
3. **분리 확인(측정):** 사전 충돌 사례 1건 선택(동명 세그먼트를 가진 두 회사) → 백필 후 `vault/segments/` 에 회사별 분리 노트 존재 또는 한 노트의 백링크 수가 사전 대비 감소(`grep -c "회사" vault/segments/<note>.md` before/after 비교, after < before).
4. **의도된 병합 유지:** alias 시드된 canonical 세그먼트(예: 메모리/메모리반도체) 노트의 백링크에 의도된 회사들이 그대로 존재(grep 매치 ≥ 시드 회사 수).
5. `.venv/bin/pytest -q` → exit 0(회귀 0).

- [ ] **Step 1:** `cp themek.db themek.db.pre-c2.bak` → `scripts/renamespace_segments.py` → `themek ontology resolve`(merge_segments 포함) → check_integrity error 0 측정.
- [ ] **Step 2:** vault 재생성 + gate 3·4 grep 측정.
- [ ] **Step 3:** 코드 커밋(`feat(ontology): ...`) + vault 산출물 커밋(`data(vault): ...`) 분리.

---

## Done criteria (전부 자동 검증)

- [ ] `.venv/bin/pytest -q` → exit 0(기존 + 신규 ≥ 5 통과, 회귀 0).
- [ ] 백필 멱등: 2회차 `repointed == 0`.
- [ ] 백필 후 `check_integrity` error 0건.
- [ ] 충돌 사례 백링크 분리(after < before), 의도된 alias 병합 유지.

## 한계

- 스크립트는 *기존* 전역 노드 가정 — 이후 ingest는 처음부터 회사 키 → 재실행 시 noop(gate 4 멱등으로 보장).
- 자동 의미 병합(임베딩) 비범위 — 교차회사 병합은 수동 alias 시드로만.
