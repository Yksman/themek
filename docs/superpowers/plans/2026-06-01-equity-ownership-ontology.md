# 지분구조(Equity Ownership) 온톨로지 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DART 정형 API(최대주주현황·타법인출자현황)에서 지분 관계를 추출해 graph core에 `OWNS_STAKE_IN` 엣지 + `person` 노드로 적재하고, 약 40개사 실데이터를 적재·검증한다.

**Architecture:** 기존 `method=api` 재무 적재 패턴(`ingest_financials_for_company`)을 형제 구조로 복제. 보유자(person|company) → 피보유(company) 방향 단일 술어 `OWNS_STAKE_IN`. 개인 주주는 회사 네임스페이스 person 노드로 안전 적재 후 시드 alias로 병합(C2 segment 네임스페이스 선례). 외부 법인은 `company:ext:` 노드로 적재 후 universe company에 resolve(resolve_customers 선례). append-only 엣지에 연도별 스냅샷 → 연도 diff로 변동 파생.

**Tech Stack:** Python 3.12, SQLAlchemy ORM(Node/Edge/ConceptAlias), Alembic(batch_alter_table enum 확장), Typer CLI, pytest + httpx.MockTransport.

**선행 스펙:** `docs/superpowers/specs/2026-05-31-equity-ownership-ontology-design.md`

**규약(전 task 공통):**
- 테스트: `uv run pytest <path> -v`. 린트: `uv run ruff check <path>`.
- 엣지 `period`는 **4자리 사업연도 문자열**(`"2023"`) — 기존 structure 엣지·`company_report_years`(`^\d{4}$`)와 일치. 최대주주/타법인출자 모두 **사업보고서(reprt_code=11011)** 에서만 적재(분기보고서가 연간 스냅샷을 덮어쓰지 않도록).
- 커밋 메시지는 기존 컨벤션(`feat(ontology):`, `chore(db):`, `test(...)`) 따름.

---

## File Structure

- `migrations/versions/0008_equity_ownership.py` (생성) — node_kind에 `person`, edge_predicate에 `OWNS_STAKE_IN` 추가.
- `src/themek/ontology/core/models.py` (수정) — `NODE_KINDS`, `PREDICATES` 상수 확장.
- `src/themek/ontology/core/ids.py` (수정) — `person_id`, `canonical_person_id`, `external_company_id` 추가.
- `src/themek/dart/client.py` (수정) — `fetch_largest_shareholders`, `fetch_other_corp_investments` 추가.
- `src/themek/ontology/ingest/equity.py` (생성) — 분류 휴리스틱 + 2개 ingest 함수 + 회사 단위 오케스트레이터.
- `src/themek/ontology/ingest/resolution.py` (수정) — `_repoint_subject_edges`, `resolve_external_companies`, `resolve_owners`.
- `src/themek/ontology/ingest/seeds.py` (수정) — aliases.json의 `owners`/`external_companies` 시드.
- `src/themek/ontology/pipeline.py` (수정) — `ingest_equity_all` + `run_pipeline` equity 단계 + skip 플래그.
- `src/themek/ontology/query/equity.py` (생성) — 최대주주/지배회사/지분 시계열·변동 질의.
- `src/themek/ontology/projection/vault.py` (수정) — 지분구조 섹션 + `people/` 노트 + frontmatter.
- `src/themek/ontology/verify_equity.py` (생성) — 프로덕션 적재 검증(측정 게이트).
- `src/themek/cli.py` (수정) — `themek equity ingest` / `themek equity verify` + pipeline/resolve 배선.
- `tests/ontology/test_equity_*.py`, `tests/test_dart_equity.py`, `tests/fixtures/dart_cassettes/*.json` (생성).

---

## Task 1: 마이그레이션 — node_kind(`person`) + edge_predicate(`OWNS_STAKE_IN`) 확장

**Files:**
- Create: `migrations/versions/0008_equity_ownership.py`
- Modify: `src/themek/ontology/core/models.py:14-21`
- Test: `tests/ontology/test_equity_migration.py`

- [ ] **Step 1: 상수 확장 (models.py)**

`src/themek/ontology/core/models.py`의 `NODE_KINDS`, `PREDICATES`를 교체:

```python
NODE_KINDS = (
    "company", "stock", "sector", "region", "segment",
    "customer", "period", "metric", "group", "person",
)
PREDICATES = (
    "HAS_SEGMENT", "SELLS_TO", "EXPOSED_TO", "IN_SECTOR",
    "ISSUES_STOCK", "BELONGS_TO_GROUP", "SUB_SECTOR_OF",
    "OWNS_STAKE_IN",
)
```

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/ontology/test_equity_migration.py
"""0008 마이그레이션 후 person 노드 + OWNS_STAKE_IN 엣지 적재 가능."""
from themek.ontology.core.models import Node, Edge, NODE_KINDS, PREDICATES
from themek.ontology.core.resolve import upsert_node, upsert_edge


def test_constants_expanded():
    assert "person" in NODE_KINDS
    assert "OWNS_STAKE_IN" in PREDICATES


def test_can_persist_person_and_owns_edge(session):
    upsert_node(session, "person:p1:hong", "person", "홍길동")
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_edge(session, subject_id="person:p1:hong", predicate="OWNS_STAKE_IN",
                object_id="company:00126380", period="2023",
                qualifier={"stake_pct": 1.23}, source_type="dart_api",
                source_ref=None, method="api", confidence=1.0)
    session.flush()
    e = session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").one()
    assert e.subject_id == "person:p1:hong"
    assert e.qualifier["stake_pct"] == 1.23
    assert session.get(Node, "person:p1:hong").kind == "person"
```

> `session` 픽스처는 기존 `tests/ontology/conftest.py`의 것을 사용(인메모리/격리 DB + `Base.metadata.create_all`). 신규 enum 값은 `create_all`로 만든 스키마에 이미 반영되므로 이 테스트는 상수 반영만으로 통과한다. 마이그레이션 자체는 Step 4에서 검증.

- [ ] **Step 3: 테스트 실행(상수 미반영 시 FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_migration.py -v`
Expected: Step 1 미적용이면 `test_constants_expanded` FAIL. Step 1 적용 후 PASS.

- [ ] **Step 4: 마이그레이션 파일 작성**

```python
# migrations/versions/0008_equity_ownership.py
"""expand node_kind(person) + edge_predicate(OWNS_STAKE_IN)

Revision ID: 0008_equity_ownership
Revises: 0007_expand_metrics
Create Date: 2026-06-01 00:00:00.000000

SQLite는 CHECK 제약을 in-place ALTER 못 함 → batch_alter_table로 테이블 재생성.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_equity_ownership"
down_revision: Union[str, Sequence[str], None] = "0007_expand_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KIND_OLD = ("company", "stock", "sector", "region", "segment",
             "customer", "period", "metric", "group")
_KIND_NEW = _KIND_OLD + ("person",)
_PRED_OLD = ("HAS_SEGMENT", "SELLS_TO", "EXPOSED_TO", "IN_SECTOR",
             "ISSUES_STOCK", "BELONGS_TO_GROUP", "SUB_SECTOR_OF")
_PRED_NEW = _PRED_OLD + ("OWNS_STAKE_IN",)


def upgrade() -> None:
    with op.batch_alter_table("nodes") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*_KIND_OLD, name="node_kind"),
            type_=sa.Enum(*_KIND_NEW, name="node_kind"),
            existing_nullable=False,
        )
    with op.batch_alter_table("edges") as batch:
        batch.alter_column(
            "predicate",
            existing_type=sa.Enum(*_PRED_OLD, name="edge_predicate"),
            type_=sa.Enum(*_PRED_NEW, name="edge_predicate"),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("edges") as batch:
        batch.alter_column(
            "predicate",
            existing_type=sa.Enum(*_PRED_NEW, name="edge_predicate"),
            type_=sa.Enum(*_PRED_OLD, name="edge_predicate"),
            existing_nullable=False,
        )
    with op.batch_alter_table("nodes") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.Enum(*_KIND_NEW, name="node_kind"),
            type_=sa.Enum(*_KIND_OLD, name="node_kind"),
            existing_nullable=False,
        )
```

- [ ] **Step 5: 마이그레이션 정합성 검증**

Run:
```bash
uv run alembic heads
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: heads가 `0008_equity_ownership (head)` 단일. upgrade/downgrade/upgrade 무오류.

- [ ] **Step 6: 테스트 통과 + 커밋**

Run: `uv run pytest tests/ontology/test_equity_migration.py -v` → PASS
```bash
git add migrations/versions/0008_equity_ownership.py src/themek/ontology/core/models.py tests/ontology/test_equity_migration.py
git commit -m "chore(db): migration 0008 — person node kind + OWNS_STAKE_IN predicate"
```

**Success gate:** `alembic heads`가 `0008_equity_ownership` 단일 head를 반환하고, upgrade→downgrade→upgrade 사이클이 0 오류로 완료되며, `test_equity_migration.py` 2개 테스트 PASS.

---

## Task 2: ID 헬퍼 — person / canonical person / external company

**Files:**
- Modify: `src/themek/ontology/core/ids.py` (끝에 추가)
- Test: `tests/ontology/test_equity_ids.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/ontology/test_equity_ids.py
from themek.ontology.core.ids import (
    person_id, canonical_person_id, external_company_id)


def test_person_id_is_company_namespaced():
    assert person_id("이재용", "00126380") == "person:00126380:이재용"


def test_canonical_person_id_is_global():
    assert canonical_person_id("이재용") == "person:이재용"


def test_canonical_differs_from_namespaced():
    assert person_id("이재용", "00126380") != canonical_person_id("이재용")


def test_external_company_id_prefixed():
    assert external_company_id("삼성생명보험(주)") == "company:ext:삼성생명보험-주"
```

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_ids.py -v`
Expected: FAIL — `ImportError: cannot import name 'person_id'`.

- [ ] **Step 3: 구현 (ids.py 끝에 추가)**

```python
def person_id(name: str, company_key: str) -> str:
    """개인 주주 노드 ID. 기본은 회사 네임스페이스(`person:{company_key}:{slug}`)로
    동명이인 우발 병합 방지(C2 segment 선례). 시드 alias로 canonical에 병합."""
    return f"person:{company_key}:{slug(name)}"


def canonical_person_id(name: str) -> str:
    """오너 병합 대상 전역 person 노드(`person:{slug}`)."""
    return f"person:{slug(name)}"


def external_company_id(name: str) -> str:
    """universe 밖 법인(최대주주 법인/피출자사) 노드(`company:ext:{slug}`).
    이후 resolve_external_companies가 universe company로 병합 가능."""
    return f"company:ext:{slug(name)}"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_equity_ids.py -v`
Expected: 4 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/ontology/core/ids.py tests/ontology/test_equity_ids.py
git commit -m "feat(ontology): person/external-company node id helpers"
```

**Success gate:** `test_equity_ids.py` 4개 PASS. `person_id`는 콜론 2개(네임스페이스), `canonical_person_id`는 콜론 1개로 구조적으로 구분됨.

---

## Task 3: DART 클라이언트 — 최대주주현황 + 타법인출자현황 fetch

**Files:**
- Modify: `src/themek/dart/client.py` (`fetch_shares` 아래, `_raise_on_error` 위)
- Create: `tests/fixtures/dart_cassettes/hyslrSttus_sample.json`, `tests/fixtures/dart_cassettes/otrCprInvstmntSttus_sample.json`
- Test: `tests/test_dart_equity.py`

- [ ] **Step 0: 실 API 필드 정찰(권장, 1회)**

DART_API_KEY가 있으면 실제 응답 1건을 저장해 필드명을 확정한다(스펙의 필드명은 잠정):
```bash
uv run python -c "import os,httpx,json; k=os.environ['DART_API_KEY']; \
print(json.dumps(httpx.get('https://opendart.fss.or.kr/api/hyslrSttus.json', \
params={'crtfc_key':k,'corp_code':'00126380','bsns_year':'2023','reprt_code':'11011'}).json(), ensure_ascii=False, indent=2)[:2000])"
```
응답의 `list[0]` 키가 아래 fixture 키(`nm,relate,stock_knd,trmend_posesn_stock_co,trmend_posesn_stock_qota_rt`)와 다르면, fixture와 Step 5 ingest 코드의 키 상수를 실제 키로 교정한다. 키 없으면 fixture 가정값으로 진행(프로덕션 Task 14에서 재검증).

- [ ] **Step 1: fixture 작성**

```json
// tests/fixtures/dart_cassettes/hyslrSttus_sample.json
{
  "status": "000",
  "message": "정상",
  "list": [
    {"corp_code": "00126380", "nm": "이재용", "relate": "최대주주 본인",
     "stock_knd": "보통주", "bsis_posesn_stock_co": "12345678",
     "bsis_posesn_stock_qota_rt": "1.50", "trmend_posesn_stock_co": "12345678",
     "trmend_posesn_stock_qota_rt": "1.63", "rm": "-"},
    {"corp_code": "00126380", "nm": "삼성생명보험(주)", "relate": "계열회사",
     "stock_knd": "보통주", "bsis_posesn_stock_co": "50000000",
     "bsis_posesn_stock_qota_rt": "8.51", "trmend_posesn_stock_co": "50000000",
     "trmend_posesn_stock_qota_rt": "8.51", "rm": "-"}
  ]
}
```

```json
// tests/fixtures/dart_cassettes/otrCprInvstmntSttus_sample.json
{
  "status": "000",
  "message": "정상",
  "list": [
    {"corp_code": "00126380", "inv_prm": "삼성디스플레이(주)",
     "invstmnt_purps": "경영참여(지배)", "trmend_blce_qy": "100000000",
     "trmend_blce_qota_rt": "84.78", "trmend_blce_acntbk_amount": "1000000000000"},
    {"corp_code": "00126380", "inv_prm": "삼성SDI(주)",
     "invstmnt_purps": "일반투자", "trmend_blce_qy": "13000000",
     "trmend_blce_qota_rt": "19.58", "trmend_blce_acntbk_amount": "500000000000"}
  ]
}
```

- [ ] **Step 2: 실패 테스트 작성**

```python
# tests/test_dart_equity.py
"""DART 최대주주/타법인출자 fetch 단위 테스트 (httpx transport mock)."""
import json
from pathlib import Path

import httpx

from themek.dart.client import DartClient

_HYSLR = Path("tests/fixtures/dart_cassettes/hyslrSttus_sample.json")
_OTR = Path("tests/fixtures/dart_cassettes/otrCprInvstmntSttus_sample.json")


def _client_with(payload: dict, capture: dict | None = None) -> DartClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["params"] = dict(request.url.params)
            capture["url"] = str(request.url)
        return httpx.Response(200, json=payload)
    c = DartClient(api_key="dummy")
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_fetch_largest_shareholders_rows_and_params():
    cap = {}
    c = _client_with(json.loads(_HYSLR.read_text(encoding="utf-8")), cap)
    rows = c.fetch_largest_shareholders(corp_code="00126380", bsns_year="2023",
                                        reprt_code="11011")
    assert len(rows) == 2
    assert rows[0]["nm"] == "이재용"
    assert "hyslrSttus.json" in cap["url"]
    assert cap["params"]["corp_code"] == "00126380"


def test_fetch_largest_shareholders_empty_status():
    c = _client_with({"status": "013", "message": "데이타 없음"})
    assert c.fetch_largest_shareholders(corp_code="x", bsns_year="2023",
                                        reprt_code="11011") == []


def test_fetch_other_corp_investments_rows():
    c = _client_with(json.loads(_OTR.read_text(encoding="utf-8")))
    rows = c.fetch_other_corp_investments(corp_code="00126380",
                                          bsns_year="2023", reprt_code="11011")
    assert len(rows) == 2
    assert rows[0]["inv_prm"] == "삼성디스플레이(주)"


def test_fetch_other_corp_investments_empty_status():
    c = _client_with({"status": "020", "message": "사용한도 초과"})
    assert c.fetch_other_corp_investments(corp_code="x", bsns_year="2023",
                                          reprt_code="11011") == []
```

- [ ] **Step 3: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/test_dart_equity.py -v`
Expected: FAIL — `AttributeError: 'DartClient' object has no attribute 'fetch_largest_shareholders'`.

- [ ] **Step 4: 구현 (client.py — `fetch_shares` 다음에 추가)**

```python
    def fetch_largest_shareholders(self, *, corp_code: str, bsns_year: str,
                                   reprt_code: str) -> list[dict]:
        """최대주주 현황(hyslrSttus.json). 비정상 status는 빈 리스트."""
        params = {"crtfc_key": self._key, "corp_code": corp_code,
                  "bsns_year": bsns_year, "reprt_code": reprt_code}
        r = self._client.get(f"{self._base}/hyslrSttus.json", params=params)
        self._raise_on_error(r)
        payload = r.json()
        if payload.get("status") != "000":
            return []
        return payload.get("list", [])

    def fetch_other_corp_investments(self, *, corp_code: str, bsns_year: str,
                                     reprt_code: str) -> list[dict]:
        """타법인 출자현황(otrCprInvstmntSttus.json). 비정상 status는 빈 리스트."""
        params = {"crtfc_key": self._key, "corp_code": corp_code,
                  "bsns_year": bsns_year, "reprt_code": reprt_code}
        r = self._client.get(f"{self._base}/otrCprInvstmntSttus.json",
                             params=params)
        self._raise_on_error(r)
        payload = r.json()
        if payload.get("status") != "000":
            return []
        return payload.get("list", [])
```

- [ ] **Step 5: 테스트 통과 + 커밋**

Run: `uv run pytest tests/test_dart_equity.py -v` → 4 PASS
```bash
git add src/themek/dart/client.py tests/test_dart_equity.py tests/fixtures/dart_cassettes/hyslrSttus_sample.json tests/fixtures/dart_cassettes/otrCprInvstmntSttus_sample.json
git commit -m "feat(dart): fetch_largest_shareholders + fetch_other_corp_investments"
```

**Success gate:** `test_dart_equity.py` 4개 PASS — 정상 응답 행 파싱 + 호출 엔드포인트/파라미터 정확 + 비정상 status(`013`,`020`) → `[]`.

---

## Task 4: 주주 분류 휴리스틱 (person vs company)

**Files:**
- Create: `src/themek/ontology/ingest/equity.py`
- Test: `tests/ontology/test_equity_classify.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/ontology/test_equity_classify.py
from themek.ontology.ingest.equity import classify_shareholder, affiliation_from_stake


def test_corp_suffix_is_company():
    assert classify_shareholder("삼성생명보험(주)", "계열회사") == "company"
    assert classify_shareholder("㈜케이씨씨", "") == "company"
    assert classify_shareholder("ABC Corp", "") == "company"
    assert classify_shareholder("미래에셋자산운용", "기관") == "company"  # 운용/투신 키워드


def test_relate_corp_keyword_is_company():
    assert classify_shareholder("국민연금공단", "계열회사") == "company"


def test_personal_name_is_person():
    assert classify_shareholder("이재용", "최대주주 본인") == "person"
    assert classify_shareholder("홍길동", "배우자") == "person"


def test_affiliation_from_stake_thresholds():
    assert affiliation_from_stake(84.78) == "자회사"   # >=50
    assert affiliation_from_stake(19.58) == "관계회사"  # 20<= <50 → 관계회사 경계 아래는 기타
    assert affiliation_from_stake(25.0) == "관계회사"
    assert affiliation_from_stake(5.0) == "기타"
    assert affiliation_from_stake(None) == "기타"
```

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: themek.ontology.ingest.equity`.

- [ ] **Step 3: 구현 (equity.py 생성 — 분류부만)**

```python
"""DART 최대주주현황·타법인출자현황 → OWNS_STAKE_IN 엣지 적재 (method=api)."""
from __future__ import annotations

import re

# 법인 식별: 법인 형태 접미/접두 + 기관성 키워드
_CORP_AFFIX = re.compile(
    r"\(주\)|㈜|주식회사|유한회사|유한책임회사|합자회사|재단|"
    r"\bco\.?,?\s*ltd\.?|\bltd\.?|\binc\.?|\bcorp\.?|\bcorporation\b|\bllc\b",
    re.IGNORECASE,
)
_CORP_KEYWORD = re.compile(
    r"홀딩스|지주|투자|운용|자산운용|투신|증권|보험|은행|캐피탈|"
    r"공단|연금|펀드|파트너스|벤처스|인베스트먼트|기금|조합")
_RELATE_CORP = re.compile(r"계열회사|법인|기관")


def classify_shareholder(nm: str, relate: str) -> str:
    """주주 성명/관계로 person|company 판별. 법인 신호 우선, 기본 person."""
    name = (nm or "").strip()
    rel = (relate or "").strip()
    if _CORP_AFFIX.search(name) or _CORP_KEYWORD.search(name):
        return "company"
    if _RELATE_CORP.search(rel):
        return "company"
    return "person"


def affiliation_from_stake(stake_pct: float | None) -> str:
    """K-IFRS 지분율 기준 분류: >=50 자회사, >=20 관계회사, 그외 기타."""
    if stake_pct is None:
        return "기타"
    if stake_pct >= 50:
        return "자회사"
    if stake_pct >= 20:
        return "관계회사"
    return "기타"
```

- [ ] **Step 4: 테스트 통과 + 커밋**

Run: `uv run pytest tests/ontology/test_equity_classify.py -v` → PASS
```bash
git add src/themek/ontology/ingest/equity.py tests/ontology/test_equity_classify.py
git commit -m "feat(ontology): shareholder person/company classifier + affiliation by stake"
```

**Success gate:** `test_equity_classify.py` 9개 assert PASS — 법인 접미사/키워드/관계 → company, 그 외 → person, 지분율 임계값별 affiliation 정확.

---

## Task 5: 최대주주현황 적재 — `ingest_largest_shareholders`

**Files:**
- Modify: `src/themek/ontology/ingest/equity.py`
- Test: `tests/ontology/test_equity_ingest.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/ontology/test_equity_ingest.py
from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.equity import ingest_largest_shareholders

_ROWS = [
    {"nm": "이재용", "relate": "최대주주 본인", "trmend_posesn_stock_co": "12345678",
     "trmend_posesn_stock_qota_rt": "1.63"},
    {"nm": "삼성생명보험(주)", "relate": "계열회사", "trmend_posesn_stock_co": "50000000",
     "trmend_posesn_stock_qota_rt": "8.51"},
]


def _company(session):
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})


def test_ingest_creates_person_and_company_holders(session):
    _company(session)
    n = ingest_largest_shareholders(session, corp_code="00126380",
                                    bsns_year="2023", rows=_ROWS, source_ref="r1")
    session.flush()
    assert n == 2
    person = session.get(Node, "person:00126380:이재용")
    assert person is not None and person.kind == "person"
    extco = session.get(Node, "company:ext:삼성생명보험-주")
    assert extco is not None and extco.kind == "company"
    edges = session.query(Edge).filter_by(predicate="OWNS_STAKE_IN",
                                          object_id="company:00126380").all()
    assert len(edges) == 2
    owner = next(e for e in edges if e.subject_id == "person:00126380:이재용")
    assert owner.period == "2023"
    assert owner.qualifier["stake_pct"] == 1.63
    assert owner.qualifier["is_largest"] is True
    assert owner.qualifier["relation"] == "최대주주 본인"
    assert owner.qualifier["shares"] == 12345678


def test_ingest_is_idempotent(session):
    _company(session)
    ingest_largest_shareholders(session, corp_code="00126380",
                                bsns_year="2023", rows=_ROWS, source_ref="r1")
    session.flush()
    ingest_largest_shareholders(session, corp_code="00126380",
                                bsns_year="2023", rows=_ROWS, source_ref="r1")
    session.flush()
    assert session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").count() == 2
```

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_ingest.py -v`
Expected: FAIL — `ImportError: cannot import name 'ingest_largest_shareholders'`.

- [ ] **Step 3: 구현 (equity.py 에 추가)**

```python
from sqlalchemy.orm import Session  # noqa: E402

from themek.ontology.core.ids import (  # noqa: E402
    company_id, person_id, external_company_id)
from themek.ontology.core.resolve import upsert_node, upsert_edge  # noqa: E402

_IS_LARGEST = re.compile(r"본인|최대주주")


def _to_pct(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", "").replace("%", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(raw) -> int | None:
    f = _to_pct(raw)
    return int(f) if f is not None else None


def ingest_largest_shareholders(session: Session, *, corp_code: str,
                                bsns_year: str, rows: list[dict],
                                source_ref: str) -> int:
    """최대주주현황 행 → holder(person|company:ext) ──OWNS_STAKE_IN──▶ 보고회사.
    period=bsns_year(4자리). 멱등. 적재 엣지 수 반환."""
    held = company_id(corp_code)
    n = 0
    for row in rows:
        name = (row.get("nm") or "").strip()
        if not name:
            continue
        relate = (row.get("relate") or "").strip()
        kind = classify_shareholder(name, relate)
        if kind == "person":
            hid = person_id(name, corp_code)
            upsert_node(session, hid, "person", name)
        else:
            hid = external_company_id(name)
            upsert_node(session, hid, "company", name, {"external": True})
        pct = _to_pct(row.get("trmend_posesn_stock_qota_rt"))
        q = {
            "stake_pct": pct,
            "shares": _to_int(row.get("trmend_posesn_stock_co")),
            "relation": relate or None,
            "is_largest": bool(_IS_LARGEST.search(relate)),
        }
        upsert_edge(session, subject_id=hid, predicate="OWNS_STAKE_IN",
                    object_id=held, period=bsns_year, qualifier=q,
                    source_type="dart_api", source_ref=source_ref,
                    method="api", confidence=1.0)
        n += 1
    return n
```

- [ ] **Step 4: 테스트 통과 + 커밋**

Run: `uv run pytest tests/ontology/test_equity_ingest.py -v` → 2 PASS
```bash
git add src/themek/ontology/ingest/equity.py tests/ontology/test_equity_ingest.py
git commit -m "feat(ontology): ingest_largest_shareholders → OWNS_STAKE_IN edges"
```

**Success gate:** `test_equity_ingest.py` 2개 PASS — person/external-company 노드 정확 생성, qualifier(stake_pct/shares/relation/is_largest) 정확, 2회 적재 시 엣지 수 불변(멱등).

---

## Task 6: 타법인출자현황 적재 — `ingest_other_corp_investments`

**Files:**
- Modify: `src/themek/ontology/ingest/equity.py`
- Test: `tests/ontology/test_equity_ingest_invest.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/ontology/test_equity_ingest_invest.py
from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.equity import ingest_other_corp_investments

_ROWS = [
    {"inv_prm": "삼성디스플레이(주)", "invstmnt_purps": "경영참여(지배)",
     "trmend_blce_qy": "100000000", "trmend_blce_qota_rt": "84.78"},
    {"inv_prm": "삼성SDI(주)", "invstmnt_purps": "일반투자",
     "trmend_blce_qy": "13000000", "trmend_blce_qota_rt": "19.58"},
]


def test_ingest_creates_outbound_ownership(session):
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    n = ingest_other_corp_investments(session, corp_code="00126380",
                                      bsns_year="2023", rows=_ROWS,
                                      source_ref="r1")
    session.flush()
    assert n == 2
    edges = session.query(Edge).filter_by(
        predicate="OWNS_STAKE_IN", subject_id="company:00126380").all()
    assert len(edges) == 2
    sub = next(e for e in edges
               if e.object_id == "company:ext:삼성디스플레이-주")
    assert sub.qualifier["stake_pct"] == 84.78
    assert sub.qualifier["affiliation_type"] == "자회사"
    assert sub.period == "2023"
    rel = next(e for e in edges if e.object_id == "company:ext:삼성sdi-주")
    assert rel.qualifier["affiliation_type"] == "기타"  # 19.58 < 20


def test_ingest_invest_idempotent(session):
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    ingest_other_corp_investments(session, corp_code="00126380",
                                  bsns_year="2023", rows=_ROWS, source_ref="r1")
    session.flush()
    ingest_other_corp_investments(session, corp_code="00126380",
                                  bsns_year="2023", rows=_ROWS, source_ref="r1")
    session.flush()
    assert session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").count() == 2
```

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_ingest_invest.py -v`
Expected: FAIL — `ImportError: cannot import name 'ingest_other_corp_investments'`.

- [ ] **Step 3: 구현 (equity.py 에 추가)**

```python
def ingest_other_corp_investments(session: Session, *, corp_code: str,
                                  bsns_year: str, rows: list[dict],
                                  source_ref: str) -> int:
    """타법인출자현황 행 → 보고회사 ──OWNS_STAKE_IN──▶ 피출자(company:ext).
    피출자는 항상 company:ext로 적재(resolve가 universe로 승격). 멱등. 엣지 수 반환."""
    holder = company_id(corp_code)
    n = 0
    for row in rows:
        name = (row.get("inv_prm") or "").strip()
        if not name:
            continue
        oid = external_company_id(name)
        upsert_node(session, oid, "company", name, {"external": True})
        pct = _to_pct(row.get("trmend_blce_qota_rt"))
        q = {
            "stake_pct": pct,
            "shares": _to_int(row.get("trmend_blce_qy")),
            "affiliation_type": affiliation_from_stake(pct),
            "purpose": (row.get("invstmnt_purps") or "").strip() or None,
        }
        upsert_edge(session, subject_id=holder, predicate="OWNS_STAKE_IN",
                    object_id=oid, period=bsns_year, qualifier=q,
                    source_type="dart_api", source_ref=source_ref,
                    method="api", confidence=1.0)
        n += 1
    return n
```

- [ ] **Step 4: 테스트 통과 + 커밋**

Run: `uv run pytest tests/ontology/test_equity_ingest_invest.py -v` → 2 PASS
```bash
git add src/themek/ontology/ingest/equity.py tests/ontology/test_equity_ingest_invest.py
git commit -m "feat(ontology): ingest_other_corp_investments (outbound OWNS_STAKE_IN)"
```

**Success gate:** `test_equity_ingest_invest.py` 2개 PASS — 보고회사 정방향 엣지, affiliation_type 임계값 정확(84.78→자회사, 19.58→기타), 멱등.

---

## Task 7: 회사 단위 오케스트레이터 — `ingest_equity_for_company`

**Files:**
- Modify: `src/themek/ontology/ingest/equity.py`
- Test: `tests/ontology/test_equity_for_company.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/ontology/test_equity_for_company.py
from themek.ontology.core.models import Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.equity import ingest_equity_for_company


class _FakeClient:
    def fetch_largest_shareholders(self, *, corp_code, bsns_year, reprt_code):
        return [{"nm": "이재용", "relate": "최대주주 본인",
                 "trmend_posesn_stock_co": "100", "trmend_posesn_stock_qota_rt": "1.6"}]

    def fetch_other_corp_investments(self, *, corp_code, bsns_year, reprt_code):
        return [{"inv_prm": "삼성디스플레이(주)", "invstmnt_purps": "지배",
                 "trmend_blce_qy": "100", "trmend_blce_qota_rt": "84.8"}]


def test_ingest_equity_for_company_loads_both_sides(session):
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    n = ingest_equity_for_company(session, _FakeClient(), corp_code="00126380",
                                  bsns_year="2023")
    session.flush()
    assert n == 2
    inbound = session.query(Edge).filter_by(
        predicate="OWNS_STAKE_IN", object_id="company:00126380").count()
    outbound = session.query(Edge).filter_by(
        predicate="OWNS_STAKE_IN", subject_id="company:00126380").count()
    assert inbound == 1 and outbound == 1
```

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_for_company.py -v`
Expected: FAIL — `ImportError: cannot import name 'ingest_equity_for_company'`.

- [ ] **Step 3: 구현 (equity.py 에 추가)**

```python
def ingest_equity_for_company(session: Session, client, *, corp_code: str,
                              bsns_year: str, reprt_code: str = "11011") -> int:
    """회사 1건 지분구조 적재(사업보고서 기준). 최대주주 + 타법인출자 엣지 수 합 반환."""
    source_ref = f"dart:{corp_code}:{bsns_year}:{reprt_code}"
    sh = client.fetch_largest_shareholders(
        corp_code=corp_code, bsns_year=bsns_year, reprt_code=reprt_code)
    inv = client.fetch_other_corp_investments(
        corp_code=corp_code, bsns_year=bsns_year, reprt_code=reprt_code)
    n = ingest_largest_shareholders(session, corp_code=corp_code,
                                    bsns_year=bsns_year, rows=sh,
                                    source_ref=source_ref)
    n += ingest_other_corp_investments(session, corp_code=corp_code,
                                       bsns_year=bsns_year, rows=inv,
                                       source_ref=source_ref)
    return n
```

- [ ] **Step 4: 테스트 통과 + 커밋**

Run: `uv run pytest tests/ontology/test_equity_for_company.py -v` → PASS
```bash
git add src/themek/ontology/ingest/equity.py tests/ontology/test_equity_for_company.py
git commit -m "feat(ontology): ingest_equity_for_company orchestrator"
```

**Success gate:** `test_equity_for_company.py` PASS — 단일 호출로 inbound 1 + outbound 1 엣지 적재, 반환값 2.

---

## Task 8: 파이프라인 통합 — `ingest_equity_all` + run_pipeline equity 단계

**Files:**
- Modify: `src/themek/ontology/pipeline.py`
- Modify: `src/themek/cli.py` (pipeline_run_cmd에 `--skip-equity` 배선)
- Test: `tests/ontology/test_equity_pipeline.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/ontology/test_equity_pipeline.py
from themek.ontology.core.models import Edge, Node
from themek.ontology.core.resolve import upsert_node
from themek.ontology.pipeline import ingest_equity_all


class _FakeClient:
    def fetch_largest_shareholders(self, *, corp_code, bsns_year, reprt_code):
        if reprt_code != "11011":
            return []
        return [{"nm": "오너", "relate": "본인", "trmend_posesn_stock_co": "10",
                 "trmend_posesn_stock_qota_rt": "5.0"}]

    def fetch_other_corp_investments(self, *, corp_code, bsns_year, reprt_code):
        return []


def test_ingest_equity_all_iterates_companies_annual_only(session):
    upsert_node(session, "company:A", "company", "에이", {"dart_code": "A"})
    upsert_node(session, "company:B", "company", "비", {"dart_code": "B"})
    res = ingest_equity_all(session, _FakeClient(), years=["2023"])
    session.flush()
    assert res["companies"] == 2
    assert res["edges"] == 2  # 회사당 최대주주 1행 (사업보고서 1회)
    assert session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").count() == 2


def test_ingest_equity_all_skips_companies_without_dart_code(session):
    upsert_node(session, "company:ext:foo", "company", "외부", {"external": True})
    res = ingest_equity_all(session, _FakeClient(), years=["2023"])
    assert res["companies"] == 0
```

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_pipeline.py -v`
Expected: FAIL — `ImportError: cannot import name 'ingest_equity_all'`.

- [ ] **Step 3: 구현 (pipeline.py — `ingest_financials_all` 아래에 추가)**

```python
def ingest_equity_all(session: Session, client, *,
                      years: list[str] | None = None,
                      today: "date | None" = None, floor_n: int = 3) -> dict:
    """전 회사 지분구조 적재(사업보고서 11011만). 재무와 동일한 연도 도출 전략:
    years 명시 시 강제, 아니면 회사별 제출연도 ∪ 최신화 floor."""
    from themek.ontology.ingest.equity import ingest_equity_for_company

    floor = (set() if years is not None
             else set(recent_fiscal_years(today or date.today(), floor_n)))
    companies = session.execute(
        select(Node).where(Node.kind == "company")
    ).scalars().all()
    edges = 0
    processed = 0
    failed: list[tuple[str, str]] = []
    for node in companies:
        dart_code = node.attrs.get("dart_code")
        if not dart_code:
            continue
        processed += 1
        company_years = (years if years is not None else sorted(
            set(company_report_years(session, node.id)) | floor))
        for yr in company_years:
            try:
                edges += ingest_equity_for_company(
                    session, client, corp_code=dart_code, bsns_year=yr)
            except Exception as e:  # 회사별 관용
                failed.append((dart_code, f"{yr}: {e}"))
    return {"companies": processed, "edges": edges, "failed": failed}
```

`run_pipeline` 시그니처에 `skip_equity: bool` 추가하고, financials 단계 다음(export 전)에 삽입:

```python
def run_pipeline(
    session: Session, client, *, cache,
    skip_sync: bool, skip_structure: bool, skip_financials: bool,
    skip_equity: bool, skip_export: bool,
    since, until, universe, rate_budget, extractor,
    out_vault, out_graph,
) -> PipelineResult:
```

financials 블록(line 156-163) 다음에:
```python
    # 3b. equity (지분구조 — 사업보고서 기준)
    if skip_equity:
        result.skipped.append("equity")
    else:
        result.equity = ingest_equity_all(session, client)
        result.ran.append("equity")
```

`PipelineResult` dataclass에 `equity: dict | None = None` 필드 추가.

- [ ] **Step 4: CLI 배선 (cli.py)**

`pipeline_run_cmd`에 옵션 추가(`skip_financials` 옆):
```python
    skip_equity: bool = typer.Option(False, "--skip-equity"),
```
`if not (skip_sync and skip_structure and skip_financials):` 조건을 `... and skip_equity)` 포함하도록 수정. `run_pipeline(...)` 호출에 `skip_equity=skip_equity,` 추가. 결과 출력 루프(`for stage in result.ran:`)에 분기 추가:
```python
        elif stage == "equity":
            e = result.equity
            typer.echo(f"[equity] companies={e['companies']} edges={e['edges']} "
                       f"failed={len(e['failed'])}")
```

- [ ] **Step 5: 테스트 통과 + 커밋**

Run: `uv run pytest tests/ontology/test_equity_pipeline.py tests/ontology/test_pipeline.py tests/ontology/test_cli_pipeline.py -v`
Expected: 신규 2 PASS + 기존 파이프라인 테스트(시그니처 변경 영향) PASS.
> 기존 `test_pipeline.py`/`test_cli_pipeline.py`가 `run_pipeline`을 직접 호출하면 `skip_equity` 인자 누락으로 깨질 수 있다. 깨지면 해당 호출에 `skip_equity=True`를 추가해 기존 동작을 보존하라.
```bash
git add src/themek/ontology/pipeline.py src/themek/cli.py tests/ontology/test_equity_pipeline.py
git commit -m "feat(ontology): pipeline equity stage (ingest_equity_all) + --skip-equity"
```

**Success gate:** 신규 2개 PASS(전 회사 순회·사업보고서만·dart_code 없는 회사 skip) + 기존 파이프라인 테스트 전부 PASS(회귀 0).

---

## Task 9: CLI — `themek equity ingest`

**Files:**
- Modify: `src/themek/cli.py` (equity_app 신설 + 명령)
- Test: `tests/test_cli_equity.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_cli_equity.py
"""themek equity ingest CLI smoke (DartClient monkeypatched)."""
from typer.testing import CliRunner

from themek.cli import app
from themek.ontology.core.models import Edge

runner = CliRunner()


class _FakeClient:
    def __init__(self, *a, **k): pass
    def fetch_largest_shareholders(self, *, corp_code, bsns_year, reprt_code):
        return [{"nm": "오너", "relate": "본인", "trmend_posesn_stock_co": "10",
                 "trmend_posesn_stock_qota_rt": "5.0"}]
    def fetch_other_corp_investments(self, *, corp_code, bsns_year, reprt_code):
        return []


def test_equity_ingest_cmd(monkeypatch, seeded_db_env):
    # seeded_db_env: 삼성전자(00126380) company 노드가 존재하는 DB를 가리키는 픽스처
    import themek.cli as cli
    monkeypatch.setattr(cli, "DartClient", _FakeClient)
    res = runner.invoke(app, ["equity", "ingest", "--corp", "00126380",
                              "--years", "2023"])
    assert res.exit_code == 0, res.output
    assert "ingested" in res.output
```

> `seeded_db_env` 픽스처가 없으면 기존 `tests/test_cli_dart.py`의 DB 환경 셋업 패턴(임시 sqlite + `THEMEK_DATABASE_URL` env + `alembic upgrade head` + 삼성전자 company 노드 seed)을 conftest에 복제해 추가하라. 기존 CLI 테스트가 쓰는 픽스처 이름을 그대로 재사용하는 것이 가장 안전하다.

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/test_cli_equity.py -v`
Expected: FAIL — `No such command 'equity'`.

- [ ] **Step 3: 구현 (cli.py)**

다른 `add_typer` 옆에:
```python
equity_app = typer.Typer()
app.add_typer(equity_app, name="equity")
```

명령 추가(기존 `ingest_financials_cmd` 패턴 미러):
```python
@equity_app.command("ingest")
def equity_ingest_cmd(
    years: str = typer.Option(..., "--years", help="예: 2022-2024 또는 2024"),
    corp: Optional[str] = typer.Option(None, "--corp", help="단일 corp_code"),
):
    """DART 최대주주현황 + 타법인출자현황을 OWNS_STAKE_IN 엣지로 적재."""
    from themek.ontology.ingest.equity import ingest_equity_for_company
    if "-" in years:
        lo, hi = years.split("-", 1)
        year_list = [str(y) for y in range(int(lo), int(hi) + 1)]
    else:
        year_list = [years]
    client = DartClient(api_key=get_settings().dart_api_key)
    total = 0
    with _session() as s:
        if corp:
            corp_codes = [corp]
        else:
            corp_codes = [
                n.attrs.get("dart_code")
                for n in s.execute(select(Node).where(Node.kind == "company"))
                .scalars().all() if n.attrs.get("dart_code")
            ]
        for code in corp_codes:
            for yr in year_list:
                total += ingest_equity_for_company(
                    s, client, corp_code=code, bsns_year=yr)
        s.commit()
    typer.echo(f"ingested {total} ownership edges")
```

- [ ] **Step 4: 테스트 통과 + 커밋**

Run: `uv run pytest tests/test_cli_equity.py -v` → PASS
```bash
git add src/themek/cli.py tests/test_cli_equity.py
git commit -m "feat(cli): themek equity ingest"
```

**Success gate:** `test_cli_equity.py` PASS — `themek equity ingest --corp --years` exit_code 0, "ingested N ownership edges" 출력, DB에 OWNS_STAKE_IN 엣지 ≥1.

---

## Task 10: 엔티티 해소 — 외부법인 → universe, 오너 시드 병합

**Files:**
- Modify: `src/themek/ontology/ingest/resolution.py`
- Modify: `src/themek/ontology/ingest/seeds.py`
- Modify: `src/themek/cli.py` (`ontology_resolve_cmd`에 배선)
- Modify: `data/ontology/aliases.json` (owners/external_companies 섹션 — 없으면 생성)
- Test: `tests/ontology/test_equity_resolution.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/ontology/test_equity_resolution.py
from themek.db.corp_models import Corporation
from themek.ontology.core.models import Node, Edge, ConceptAlias
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.ingest.resolution import (
    resolve_external_companies, resolve_owners)


def _owns(session, subj, obj, period="2023", q=None):
    upsert_edge(session, subject_id=subj, predicate="OWNS_STAKE_IN",
                object_id=obj, period=period, qualifier=q or {},
                source_type="dart_api", source_ref=None, method="api",
                confidence=1.0)


def test_resolve_external_company_to_universe(session):
    # universe corp + company 노드
    session.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_node(session, "company:00100", "company", "출자모회사",
                {"dart_code": "00100"})
    # 출자모회사 → 외부노드(삼성전자 (주)) — universe와 매칭되어야 함
    upsert_node(session, "company:ext:삼성전자-주", "company", "삼성전자(주)",
                {"external": True})
    _owns(session, "company:00100", "company:ext:삼성전자-주",
          q={"stake_pct": 30.0})
    session.flush()
    res = resolve_external_companies(session)
    session.flush()
    assert res["resolved"] == 1
    assert session.get(Node, "company:ext:삼성전자-주") is None
    e = session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").one()
    assert e.object_id == "company:00126380"


def test_resolve_owner_seed_merge(session):
    # canonical 오너 노드 + alias 시드
    upsert_node(session, "person:이재용", "person", "이재용")
    session.add(ConceptAlias(alias_norm="이재용", node_id="person:이재용",
                             source="manual", confidence=1.0))
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    # 회사 네임스페이스 person → canonical로 병합되어야 함
    upsert_node(session, "person:00126380:이재용", "person", "이재용")
    _owns(session, "person:00126380:이재용", "company:00126380",
          q={"stake_pct": 1.6})
    session.flush()
    res = resolve_owners(session)
    session.flush()
    assert res["merged"] == 1
    assert session.get(Node, "person:00126380:이재용") is None
    e = session.query(Edge).filter_by(predicate="OWNS_STAKE_IN").one()
    assert e.subject_id == "person:이재용"
```

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_resolution.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_external_companies'`.

- [ ] **Step 3: 구현 (resolution.py 에 추가)**

```python
def _repoint_subject_edges(session: Session, *, old_subject_id: str,
                           new_subject_id: str) -> int:
    """old_subject_id를 subject로 하는 엣지를 new_subject_id로 재지정.
    동일 (subject,predicate,object,period) 충돌 시 source 삭제(병합)."""
    edges = session.execute(
        select(Edge).where(Edge.subject_id == old_subject_id)
    ).scalars().all()
    moved = 0
    for e in edges:
        existing = session.execute(
            select(Edge).where(
                Edge.subject_id == new_subject_id,
                Edge.predicate == e.predicate,
                Edge.object_id == e.object_id,
                Edge.period.is_(None) if e.period is None
                else Edge.period == e.period,
            )
        ).scalars().first()
        if existing is not None and existing.id != e.id:
            session.delete(e)
        else:
            e.subject_id = new_subject_id
        moved += 1
    session.flush()
    return moved


def resolve_external_companies(session: Session) -> dict:
    """company:ext 노드를 정규화 exact(별칭 우선)로 universe company에 해소.
    매칭 시 OWNS_STAKE_IN object 재지정 + ext 노드 제거."""
    corp_index = {
        normalize_corp_name(c.name_ko): company_id(c.dart_code)
        for c in session.execute(select(Corporation)).scalars().all()
    }
    ext = session.execute(
        select(Node).where(Node.kind == "company",
                           Node.id.like("company:ext:%"))
    ).scalars().all()
    resolved = unresolved = repointed = 0
    for node in ext:
        norm = normalize_corp_name(node.label)
        target = None
        alias = session.get(ConceptAlias, norm)
        if alias is not None and alias.node_id.startswith("company:") \
                and not alias.node_id.startswith("company:ext:"):
            target = alias.node_id
        elif norm in corp_index:
            target = corp_index[norm]
        if target is None or session.get(Node, target) is None:
            unresolved += 1
            continue
        repointed += _repoint_edges(session, old_object_id=node.id,
                                    new_object_id=target)
        session.delete(node)
        resolved += 1
    session.flush()
    return {"resolved": resolved, "unresolved": unresolved,
            "edges_repointed": repointed}


def resolve_owners(session: Session) -> dict:
    """회사 네임스페이스 person 노드를 alias 시드에 따라 canonical person으로 병합.
    OWNS_STAKE_IN subject 재지정 + 네임스페이스 노드 제거. ConceptAlias는
    normalize_alias 키. canonical 노드(`person:{slug}`)가 존재할 때만 병합."""
    from themek.ontology.core.resolve import normalize_alias
    persons = session.execute(
        select(Node).where(Node.kind == "person")
    ).scalars().all()
    merged = 0
    for p in persons:
        alias = session.get(ConceptAlias, normalize_alias(p.label))
        if alias is None or alias.node_id == p.id:
            continue
        if not alias.node_id.startswith("person:") \
                or session.get(Node, alias.node_id) is None:
            continue
        _repoint_subject_edges(session, old_subject_id=p.id,
                               new_subject_id=alias.node_id)
        session.delete(p)
        merged += 1
    session.flush()
    return {"merged": merged}
```

- [ ] **Step 4: 시드 확장 (seeds.py — `seed_aliases`에 owners/external 추가)**

`seed_aliases` 함수 본문, segment 루프 다음에 추가:
```python
    from themek.ontology.core.ids import canonical_person_id
    for entry in data.get("owners", []):
        target = canonical_person_id(entry["canonical"])
        # canonical person 노드 보장(없으면 생성) 후 변형 alias 등록
        upsert_node(session, target, "person", entry["canonical"])
        for variant in entry["variants"]:
            if _upsert_alias(session, normalize_alias(variant), target):
                n += 1
    for entry in data.get("external_companies", []):
        target = company_id(entry["corp"])
        for variant in entry["variants"]:
            if _upsert_alias(session, normalize_corp_name(variant), target):
                n += 1
```
(`upsert_node`는 이미 seeds.py에서 import 됨.)

`data/ontology/aliases.json`에 키 추가(파일 없으면 `{"customers": [], "segments": []}` 기반으로 생성). 예시:
```json
{
  "owners": [
    {"canonical": "이재용", "variants": ["이재용", "李在鎔"]}
  ],
  "external_companies": [
    {"corp": "00126380", "variants": ["삼성전자", "삼성전자(주)", "삼성전자주식회사"]}
  ]
}
```

- [ ] **Step 5: CLI 배선 (cli.py `ontology_resolve_cmd`)**

import에 `resolve_external_companies, resolve_owners` 추가, 본문에:
```python
        ext = resolve_external_companies(s)
        owners = resolve_owners(s)
```
출력에 추가:
```python
    typer.echo(f"external companies resolved: {ext['resolved']}, "
               f"unresolved: {ext['unresolved']}")
    typer.echo(f"owners merged: {owners['merged']}")
```
(check_integrity 호출 이전에 두 resolve를 실행.)

- [ ] **Step 6: 테스트 통과 + 커밋**

Run: `uv run pytest tests/ontology/test_equity_resolution.py tests/ontology/test_resolution.py tests/ontology/test_seeds.py -v`
Expected: 신규 2 PASS + 기존 resolution/seeds 테스트 PASS(회귀 0).
```bash
git add src/themek/ontology/ingest/resolution.py src/themek/ontology/ingest/seeds.py src/themek/cli.py data/ontology/aliases.json tests/ontology/test_equity_resolution.py
git commit -m "feat(ontology): resolve external companies + owner seed merge"
```

**Success gate:** `test_equity_resolution.py` 2개 PASS — 외부법인이 universe company로 병합되며 OWNS_STAKE_IN object 재지정·ext 노드 제거, 네임스페이스 person이 canonical로 병합되며 subject 재지정. 기존 resolution/seeds 테스트 회귀 0.

---

## Task 11: 지분 질의 — 최대주주 / 지배회사 / 지분 시계열·변동

**Files:**
- Create: `src/themek/ontology/query/equity.py`
- Test: `tests/ontology/test_equity_query.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/ontology/test_equity_query.py
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.query.equity import (
    largest_shareholders, owned_companies, stake_changes)


def _owns(session, subj, obj, period, pct, is_largest=False):
    upsert_edge(session, subject_id=subj, predicate="OWNS_STAKE_IN",
                object_id=obj, period=period,
                qualifier={"stake_pct": pct, "is_largest": is_largest},
                source_type="dart_api", source_ref=None, method="api",
                confidence=1.0)


def test_largest_shareholders_latest_period_sorted(session):
    upsert_node(session, "company:C", "company", "씨", {"dart_code": "C"})
    upsert_node(session, "person:이씨", "person", "이씨")
    upsert_node(session, "person:박씨", "person", "박씨")
    _owns(session, "person:이씨", "company:C", "2023", 5.0, True)
    _owns(session, "person:박씨", "company:C", "2023", 8.0)
    session.flush()
    rows = largest_shareholders(session, "company:C")
    assert [r["holder_id"] for r in rows] == ["person:박씨", "person:이씨"]  # 지분율 내림차순
    assert rows[0]["stake_pct"] == 8.0


def test_owned_companies_fanout(session):
    upsert_node(session, "person:오너", "person", "오너")
    upsert_node(session, "company:X", "company", "엑스", {"dart_code": "X"})
    upsert_node(session, "company:Y", "company", "와이", {"dart_code": "Y"})
    _owns(session, "person:오너", "company:X", "2023", 30.0)
    _owns(session, "person:오너", "company:Y", "2023", 12.0)
    session.flush()
    held = {r["company_id"] for r in owned_companies(session, "person:오너")}
    assert held == {"company:X", "company:Y"}


def test_stake_changes_year_diff(session):
    upsert_node(session, "company:C", "company", "씨", {"dart_code": "C"})
    upsert_node(session, "person:이씨", "person", "이씨")
    _owns(session, "person:이씨", "company:C", "2022", 5.0)
    _owns(session, "person:이씨", "company:C", "2023", 7.5)
    session.flush()
    changes = stake_changes(session, "company:C")
    row = next(c for c in changes if c["holder_id"] == "person:이씨")
    assert row["from_pct"] == 5.0 and row["to_pct"] == 7.5
    assert row["delta"] == 2.5
```

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_query.py -v`
Expected: FAIL — `ModuleNotFoundError: themek.ontology.query.equity`.

- [ ] **Step 3: 구현 (query/equity.py 생성)**

```python
"""지분 질의: 최대주주·지배회사·지분 시계열/변동."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Edge


def _latest_period(session: Session, company_id: str) -> str | None:
    rows = session.execute(
        select(Edge.period).where(
            Edge.predicate == "OWNS_STAKE_IN",
            Edge.object_id == company_id, Edge.period.is_not(None))
    ).scalars().all()
    return max(rows) if rows else None


def largest_shareholders(session: Session, company_id: str) -> list[dict]:
    """회사의 최신 사업연도 주주 목록(지분율 내림차순)."""
    period = _latest_period(session, company_id)
    if period is None:
        return []
    edges = session.execute(
        select(Edge).where(
            Edge.predicate == "OWNS_STAKE_IN",
            Edge.object_id == company_id, Edge.period == period)
    ).scalars().all()
    rows = [{"holder_id": e.subject_id,
             "stake_pct": e.qualifier.get("stake_pct"),
             "relation": e.qualifier.get("relation"),
             "is_largest": e.qualifier.get("is_largest", False),
             "period": e.period} for e in edges]
    rows.sort(key=lambda r: (r["stake_pct"] is None, -(r["stake_pct"] or 0)))
    return rows


def owned_companies(session: Session, holder_id: str) -> list[dict]:
    """보유자가 지분을 가진 회사 목록(최신 period 우선, object별 1건)."""
    edges = session.execute(
        select(Edge).where(Edge.predicate == "OWNS_STAKE_IN",
                           Edge.subject_id == holder_id)
    ).scalars().all()
    best: dict[str, Edge] = {}
    for e in edges:
        cur = best.get(e.object_id)
        if cur is None or (e.period or "") > (cur.period or ""):
            best[e.object_id] = e
    return [{"company_id": oid,
             "stake_pct": e.qualifier.get("stake_pct"),
             "affiliation_type": e.qualifier.get("affiliation_type"),
             "period": e.period} for oid, e in best.items()]


def stake_changes(session: Session, company_id: str) -> list[dict]:
    """holder별 직전 연도 대비 지분율 변동(append-only 엣지 연도 diff)."""
    edges = session.execute(
        select(Edge).where(Edge.predicate == "OWNS_STAKE_IN",
                           Edge.object_id == company_id,
                           Edge.period.is_not(None))
    ).scalars().all()
    by_holder: dict[str, dict[str, float | None]] = {}
    for e in edges:
        by_holder.setdefault(e.subject_id, {})[e.period] = \
            e.qualifier.get("stake_pct")
    out = []
    for holder, series in by_holder.items():
        periods = sorted(series.keys())
        if len(periods) < 2:
            continue
        frm, to = periods[-2], periods[-1]
        a, b = series[frm], series[to]
        delta = (b - a) if (a is not None and b is not None) else None
        out.append({"holder_id": holder, "from_period": frm, "to_period": to,
                    "from_pct": a, "to_pct": b, "delta": delta})
    return out
```

- [ ] **Step 4: 테스트 통과 + 커밋**

Run: `uv run pytest tests/ontology/test_equity_query.py -v` → 3 PASS
```bash
git add src/themek/ontology/query/equity.py tests/ontology/test_equity_query.py
git commit -m "feat(ontology): equity queries — largest_shareholders/owned_companies/stake_changes"
```

**Success gate:** `test_equity_query.py` 3개 PASS — 최대주주 지분율 내림차순 정렬, 오너 fan-out 정확, 2개 연도 적재 시 delta(=to-from) 정확 산출.

---

## Task 12: Vault 투영 — 지분구조 섹션 + people/ 노트

**Files:**
- Modify: `src/themek/ontology/projection/vault.py`
- Test: `tests/ontology/test_equity_vault.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/ontology/test_equity_vault.py
from pathlib import Path

from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.projection.vault import build_vault


def _setup(session):
    upsert_node(session, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_node(session, "person:이재용", "person", "이재용")
    upsert_node(session, "company:ext:삼성디스플레이-주", "company",
                "삼성디스플레이(주)", {"external": True})
    # 최대주주: 이재용 → 삼성전자
    upsert_edge(session, subject_id="person:이재용", predicate="OWNS_STAKE_IN",
                object_id="company:00126380", period="2023",
                qualifier={"stake_pct": 1.63, "is_largest": True,
                           "relation": "최대주주 본인"},
                source_type="dart_api", source_ref=None, method="api",
                confidence=1.0)
    # 타법인출자: 삼성전자 → 삼성디스플레이
    upsert_edge(session, subject_id="company:00126380",
                predicate="OWNS_STAKE_IN", object_id="company:ext:삼성디스플레이-주",
                period="2023",
                qualifier={"stake_pct": 84.78, "affiliation_type": "자회사"},
                source_type="dart_api", source_ref=None, method="api",
                confidence=1.0)


def test_company_note_has_ownership_section(session, tmp_path):
    _setup(session)
    session.flush()
    build_vault(session, tmp_path)
    note = (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8")
    assert "## 지분구조" in note
    assert "[[이재용]]" in note
    assert "1.63%" in note
    assert "[[삼성디스플레이(주)]]" in note or "삼성디스플레이" in note
    assert "84.78%" in note


def test_person_note_created_with_backlink(session, tmp_path):
    _setup(session)
    session.flush()
    build_vault(session, tmp_path)
    pnote = tmp_path / "people" / "이재용.md"
    assert pnote.exists()
    body = pnote.read_text(encoding="utf-8")
    assert "[[삼성전자]]" in body
```

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_vault.py -v`
Expected: FAIL — `## 지분구조` 없음 / `people/이재용.md` 없음.

- [ ] **Step 3: 구현 (vault.py)**

(a) 상단 상수 확장:
```python
_GENERATED_DIRS = ("companies", "segments", "customers", "regions", "sectors",
                   "people")
_KIND_DIR = {"segment": "segments", "customer": "customers",
             "region": "regions", "sector": "sectors"}
```
(`person`은 별도 처리 — `_KIND_DIR`에 넣지 않음.)

(b) 회사 루프 안, `parts += _render_financials(fin)` 직전에 지분구조 섹션 추가:
```python
        # 지분구조 — 인바운드(주주) + 아웃바운드(타법인출자)
        inbound = session.execute(
            select(Edge).where(Edge.predicate == "OWNS_STAKE_IN",
                               Edge.object_id == c.id)
        ).scalars().all()
        outbound = [e for e in edges if e.predicate == "OWNS_STAKE_IN"]
        parts.append("\n## 지분구조\n")
        parts.append("\n### 주주 (최대주주·특수관계인)\n")
        inbound_latest = _dedup_latest_stake(inbound)
        for sid, pct, rel in inbound_latest:
            suffix = f" — {pct:g}%" if pct is not None else ""
            relpart = f" ({rel})" if rel else ""
            parts.append(f"- {_wikilink(_lbl(sid))}{relpart}{suffix}")
            people_backlinks.setdefault(sid, []).append((c.label, pct))
        if not inbound_latest:
            parts.append("- (없음)")
        parts.append("\n### 타법인 출자\n")
        out_latest = _dedup_latest_stake(outbound)
        for oid, pct, aff in out_latest:
            suffix = f" — {pct:g}%" if pct is not None else ""
            affpart = f" [{aff}]" if aff else ""
            parts.append(f"- {_wikilink(_lbl(oid))}{affpart}{suffix}")
        if not out_latest:
            parts.append("- (없음)")
```

(c) `_dedup_latest` 옆에 stake 전용 헬퍼 추가(qualifier 키가 `stake_pct`이고 relation/affiliation도 같이 반환):
```python
def _dedup_latest_stake(edges):
    """OWNS_STAKE_IN 엣지를 상대 노드별 최신 period 1건으로. 인바운드는 subject_id,
    아웃바운드는 object_id를 키로 쓰도록 (node_id, pct, extra) 튜플 반환.
    인바운드/아웃바운드 판정은 호출부 컨텍스트에 맡기되 여기선 상대 노드 id를 자동 선택:
    같은 컬렉션 내에서 고정된 한쪽만 들어오므로 object_id≠None 우선 키 사용."""
    best = {}
    for e in edges:
        # 인바운드(주주): 상대=subject, extra=relation / 아웃바운드: 상대=object, extra=affiliation
        rel = e.qualifier.get("relation")
        aff = e.qualifier.get("affiliation_type")
        if rel is not None or e.qualifier.get("is_largest") is not None:
            key, extra = e.subject_id, rel
        else:
            key, extra = e.object_id, aff
        pk = e.period or ""
        cur = best.get(key)
        if cur is None or pk > cur[0]:
            best[key] = (pk, e.qualifier.get("stake_pct"), extra)
    return [(k, v[1], v[2]) for k, v in best.items()]
```
> 인바운드/아웃바운드를 한 헬퍼에서 키가 섞일 위험을 피하려면, 호출부에서 인바운드는 `e.subject_id`, 아웃바운드는 `e.object_id`로 명시적으로 분리하는 편이 안전하다. 위 구현이 모호하면 두 개의 단순 헬퍼(`_inbound_holders`, `_outbound_holdings`)로 나눠라 — 각자 키를 고정한다. 테스트(Step 1)가 통과하면 충분.

(d) 회사 루프 시작 전에 people 백링크 수집 dict 초기화:
```python
    people_backlinks: dict[str, list[tuple[str, float | None]]] = {}
```
(e) concept 노드 루프(`_KIND_DIR`) 다음에 person 노트 생성:
```python
    persons = session.execute(
        select(Node).where(Node.kind == "person").order_by(Node.label)
    ).scalars().all()
    for p in persons:
        refs = people_backlinks.get(p.id, [])
        parts = ["---", 'type: "person"', f"name: {_yaml_str(p.label)}",
                 f"owned_count: {len(refs)}", "tags: [person]", "---",
                 f"# {p.label}\n", f"\n## 보유 회사 ({len(refs)})\n"]
        for comp_label, pct in sorted(set(refs)):
            suffix = f" — {pct:g}%" if pct is not None else ""
            parts.append(f"- {_wikilink(comp_label)}{suffix}")
        if not refs:
            parts.append("- (없음)")
        (out_dir / "people" / f"{_note_name(p.label)}.md").write_text(
            "\n".join(parts) + "\n", encoding="utf-8")
```
(f) 반환 dict에 `"people": len(persons)` 추가.

- [ ] **Step 4: 테스트 통과 + 회귀 확인 + 커밋**

Run: `uv run pytest tests/ontology/test_equity_vault.py tests/ontology/test_projection_vault.py -v`
Expected: 신규 2 PASS + 기존 vault 테스트 PASS.
```bash
git add src/themek/ontology/projection/vault.py tests/ontology/test_equity_vault.py
git commit -m "feat(vault): 지분구조 section + people/ notes with backlinks"
```

**Success gate:** `test_equity_vault.py` 2개 PASS — 회사 노트에 `## 지분구조` + 주주 `[[이재용]]`(1.63%) + 타법인출자(84.78%), `people/이재용.md` 생성 + `[[삼성전자]]` 백링크. 기존 vault 테스트 회귀 0.

---

## Task 13: 프로덕션 검증 함수 + `themek equity verify`

**Files:**
- Create: `src/themek/ontology/verify_equity.py`
- Modify: `src/themek/cli.py` (equity_app에 verify 명령)
- Test: `tests/ontology/test_equity_verify.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/ontology/test_equity_verify.py
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.verify_equity import verify_equity


def _company(session, code):
    upsert_node(session, f"company:{code}", "company", code, {"dart_code": code})


def _owns(session, subj, obj, pct, is_largest=False, period="2023"):
    upsert_edge(session, subject_id=subj, predicate="OWNS_STAKE_IN",
                object_id=obj, period=period,
                qualifier={"stake_pct": pct, "is_largest": is_largest},
                source_type="dart_api", source_ref=None, method="api",
                confidence=1.0)


def test_verify_reports_coverage_and_checks(session):
    _company(session, "A")
    _company(session, "B")  # 엣지 없음 → 커버리지 1/2
    upsert_node(session, "person:o", "person", "오너")
    _owns(session, "person:o", "company:A", 40.0, True)
    session.flush()
    rep = verify_equity(session)
    assert rep["companies_total"] == 2
    assert rep["companies_with_ownership"] == 1
    assert rep["coverage"] == 0.5
    assert rep["owns_edges"] == 1
    assert rep["person_nodes"] == 1
    assert rep["overstake_companies"] == 0  # 40 <= 100
    assert isinstance(rep["ok"], bool)


def test_verify_flags_overstake(session):
    _company(session, "A")
    upsert_node(session, "person:x", "person", "엑스")
    upsert_node(session, "person:y", "person", "와이")
    _owns(session, "person:x", "company:A", 70.0, True)
    _owns(session, "person:y", "company:A", 60.0, True)  # 본인그룹 합 130 > 100
    session.flush()
    rep = verify_equity(session)
    assert rep["overstake_companies"] == 1
```

- [ ] **Step 2: 테스트 실행(FAIL 확인)**

Run: `uv run pytest tests/ontology/test_equity_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: themek.ontology.verify_equity`.

- [ ] **Step 3: 구현 (verify_equity.py 생성)**

```python
"""지분구조 적재 검증 — 측정 가능한 게이트 산출."""
from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from themek.ontology.core.models import Node, Edge

# 게이트 임계값
MIN_COVERAGE = 0.85        # 회사 중 지분 엣지 보유 비율
OVERSTAKE_TOLERANCE = 100.5  # is_largest 그룹 지분율 합 상한(반올림 여유)


def verify_equity(session: Session) -> dict:
    companies = session.execute(
        select(Node).where(Node.kind == "company",
                           ~Node.id.like("company:ext:%"))
    ).scalars().all()
    universe = [c for c in companies if c.attrs.get("dart_code")]
    total = len(universe)

    owns = session.execute(
        select(Edge).where(Edge.predicate == "OWNS_STAKE_IN")
    ).scalars().all()
    with_ownership = {c.id for c in universe} & {
        e.object_id for e in owns} | (
        {c.id for c in universe} & {e.subject_id for e in owns})

    person_nodes = session.execute(
        select(func.count()).select_from(Node).where(Node.kind == "person")
    ).scalar_one()
    ext_nodes = session.execute(
        select(func.count()).select_from(Node).where(
            Node.id.like("company:ext:%"))
    ).scalar_one()

    # is_largest 그룹 지분율 합이 상한 초과인 회사 카운트(최신 period 기준)
    by_company: dict[str, dict[str, float]] = {}
    for e in owns:
        if not e.qualifier.get("is_largest"):
            continue
        pct = e.qualifier.get("stake_pct")
        if pct is None:
            continue
        by_company.setdefault(e.object_id, {})
        # 최신 period만
        key = e.period or ""
        by_company[e.object_id].setdefault(key, 0.0)
        by_company[e.object_id][key] += pct
    overstake = 0
    for comp, per_period in by_company.items():
        latest = max(per_period.keys()) if per_period else None
        if latest is not None and per_period[latest] > OVERSTAKE_TOLERANCE:
            overstake += 1

    null_pct = sum(1 for e in owns if e.qualifier.get("stake_pct") is None)
    coverage = (len(with_ownership) / total) if total else 0.0
    ok = (coverage >= MIN_COVERAGE and overstake == 0)
    return {
        "companies_total": total,
        "companies_with_ownership": len(with_ownership),
        "coverage": round(coverage, 4),
        "owns_edges": len(owns),
        "person_nodes": person_nodes,
        "external_company_nodes": ext_nodes,
        "null_stake_pct_edges": null_pct,
        "overstake_companies": overstake,
        "ok": ok,
    }
```

- [ ] **Step 4: CLI 배선 (cli.py — equity_app)**

```python
@equity_app.command("verify")
def equity_verify_cmd():
    """지분구조 적재 검증(측정 게이트). 게이트 미달 시 exit code 1."""
    from themek.ontology.verify_equity import verify_equity
    with _session() as s:
        rep = verify_equity(s)
    for k, v in rep.items():
        typer.echo(f"{k}: {v}")
    if not rep["ok"]:
        raise typer.Exit(code=1)
```

- [ ] **Step 5: 테스트 통과 + 커밋**

Run: `uv run pytest tests/ontology/test_equity_verify.py -v` → 2 PASS
```bash
git add src/themek/ontology/verify_equity.py src/themek/cli.py tests/ontology/test_equity_verify.py
git commit -m "feat(ontology): verify_equity + themek equity verify (measurable gates)"
```

**Success gate:** `test_equity_verify.py` 2개 PASS — 커버리지/엣지수/person수 카운트 정확, is_largest 그룹 지분율 합 초과(>100.5) 회사를 정확히 플래그.

---

## Task 14: 프로덕션 적재 — 약 40개사 실데이터 + 검증

> 이 task는 실 DART API 호출을 포함한다. `DART_API_KEY`가 `.env`에 설정되어 있어야 한다. RateBudget(38K/day) 내에서 동작.

**Files:**
- Create: `data/universe/equity_smoke.txt` (corp_code 40개)
- Create: `docs/equity-ownership-production-smoke-2026-06-01.md` (결과 기록)

- [ ] **Step 1: universe 확보 (40개사)**

기존 backfill universe + KRX sync로 이미 company 노드가 있는 종목을 사용. 40개 corp_code 목록 작성:
```bash
uv run python -c "
from themek.cli import _session
from themek.ontology.core.models import Node
from sqlalchemy import select
with _session() as s:
    codes=[n.attrs['dart_code'] for n in s.execute(select(Node).where(Node.kind=='company')).scalars().all() if n.attrs.get('dart_code')]
print(len(codes)); print('\n'.join(codes[:40]))
" | tee /tmp/equity_codes.txt
```
company 노드가 40개 미만이면, 먼저 backfill/pipeline structure로 종목을 더 적재하라(기존 `themek pipeline run` 또는 `themek dart backfill`). 40개 확보 후 `data/universe/equity_smoke.txt`에 저장.

Run: `wc -l data/universe/equity_smoke.txt`
Expected: ≥ 40 (corp_code, 주석 허용).

- [ ] **Step 2: 직전 사업연도 지분 적재**

직전 사업연도(예: 2024) 사업보고서 기준으로 40개사 적재. 변동 파생 검증을 위해 2개 연도 적재 권장(2023-2024):
```bash
for code in $(grep -oE '^[0-9]{8}' data/universe/equity_smoke.txt | head -40); do
  uv run themek equity ingest --corp "$code" --years 2023-2024
done
```
Expected: 각 호출 exit 0, 누적 "ingested N ownership edges" 출력. 전부 0이면 fixture 필드명과 실제 API 키 불일치 → Task 3 Step 0로 돌아가 필드명 교정 후 ingest 코드(`trmend_*` 키) 수정·재실행.

- [ ] **Step 3: 엔티티 해소 실행**

```bash
uv run themek ontology resolve
```
Expected: "external companies resolved: N", "owners merged: M" 출력, integrity errors: 0.

- [ ] **Step 4: 검증 게이트 실행**

```bash
uv run themek equity verify
```
Expected (측정 게이트):
- `companies_total` ≈ 40
- `coverage` ≥ 0.85 (최소 34/40 회사가 지분 엣지 보유)
- `owns_edges` ≥ 200
- `person_nodes` ≥ 30
- `overstake_companies` == 0
- `ok: True` → exit code 0

게이트 미달 시 원인 분석:
- coverage 낮음 → 해당 회사가 사업보고서 미제출이거나 API status 비정상. `themek equity ingest --corp <code> --years 2024` 개별 재실행으로 원인 확인.
- overstake > 0 → `is_largest` 판정(`relate` 정규식)이 과포함. Task 5 `_IS_LARGEST` 패턴 좁히고 재적재.

- [ ] **Step 5: 표본 수기 대조 (정확도)**

```bash
uv run python -c "
from themek.cli import _session
from themek.ontology.query.equity import largest_shareholders, owned_companies
from themek.ontology.core.ids import company_id
with _session() as s:
    print('삼성전자 최대주주:', largest_shareholders(s, company_id('00126380'))[:5])
"
```
Expected: 삼성전자(00126380) 주주 목록에 삼성생명/이재용 등 알려진 주주가 등장하고 지분율이 공시값과 근사(±0.5%p). 1개 지주사 표본에 대해 `owned_companies`로 출자 계열사가 합리적으로 나오는지 확인. 대조 결과를 문서에 기록.

- [ ] **Step 6: vault 렌더 확인**

```bash
uv run themek vault build
grep -l "## 지분구조" vault/companies/*.md | wc -l
```
Expected: 지분구조 섹션을 가진 회사 노트 ≥ 34, `vault/people/` 디렉토리에 person 노트 ≥ 30개 생성.

- [ ] **Step 7: 결과 문서화 + 커밋**

`docs/equity-ownership-production-smoke-2026-06-01.md`에 verify 출력 전문, 표본 대조 결과, 게이트 통과 여부, 발견된 이슈를 기록.
```bash
git add data/universe/equity_smoke.txt docs/equity-ownership-production-smoke-2026-06-01.md
git commit -m "data(equity): production smoke — 40 corps ownership ingest + verification"
```
> 적재된 DB/vault 산출물 자체를 커밋할지는 기존 관행(예: `data(vault): regenerate ...` 커밋)을 따른다. vault를 추적 중이면 별도 커밋으로 추가.

**Success gate:** `themek equity verify`가 exit code 0(`ok: True`)을 반환 — coverage ≥ 0.85, owns_edges ≥ 200, person_nodes ≥ 30, overstake_companies == 0. 삼성전자 표본 주주가 공시값과 ±0.5%p 이내 일치. vault 지분구조 섹션 회사 ≥ 34, people 노트 ≥ 30. 결과 문서 커밋됨.

---

## Task 15: 전체 회귀 + 린트 + 최종 커밋

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 전체 테스트 스위트**

Run: `uv run pytest -q`
Expected: 기존 314개 + 신규(약 20개) 전부 PASS, 실패 0.

- [ ] **Step 2: 린트**

Run: `uv run ruff check src/themek tests`
Expected: 0 error (신규 파일 포함).

- [ ] **Step 3: 마이그레이션 round-trip 재확인**

Run: `uv run alembic downgrade base && uv run alembic upgrade head`
Expected: 전 마이그레이션 체인(0001→0008) 무오류 적용.

- [ ] **Step 4: README 상태 갱신 + 커밋**

`README.md`의 진행 history에 한 줄 추가:
```
- Equity Ownership Ontology ✅ 2026-06-01 — OWNS_STAKE_IN(person|company→company) + DART 최대주주/타법인출자 정형 적재 + 외부법인/오너 해소 + 지분구조 vault 투영 + 40개사 프로덕션 검증(`themek equity ingest`/`verify`)
```
```bash
git add README.md
git commit -m "docs: mark equity-ownership ontology complete"
```

**Success gate:** `uv run pytest -q` 전부 PASS(실패 0) · `ruff check` 0 error · alembic base→head round-trip 무오류 · README 갱신 커밋.

---

## Self-Review 체크 결과

- **Spec coverage:** §3 데이터소스→Task 3 · §4 person 노드→Task 1·2·5 · §5 OWNS_STAKE_IN→Task 1·5·6 · §6 ingest/CLI/pipeline→Task 5~9 · §7 해소→Task 10 · §8 vault/CQ→Task 11·12 · §9 프로덕션검증→Task 13·14 · §10 테스트→전 task TDD · §11 마이그레이션→Task 1. 누락 없음.
- **편차(스펙 대비 의도적):** 엣지 `period`를 스펙의 `"2023FY"` 대신 4자리 `"2023"`로 — 기존 structure 엣지·`company_report_years` 정규식과 일치시키기 위함. 최대주주/타법인출자 모두 사업보고서(11011)만 적재 — 분기보고서가 연간 스냅샷을 덮어쓰는 충돌 방지. (스펙 본문에도 이 의도가 반영됨.)
- **Placeholder scan:** 모든 코드 step에 실제 코드 포함. "TBD/TODO" 없음. Task 3 Step 0의 필드명 정찰은 placeholder가 아니라 명시적 검증 단계.
- **Type consistency:** qualifier 키(`stake_pct`/`shares`/`relation`/`is_largest`/`affiliation_type`/`purpose`)가 ingest(Task 5·6)·query(Task 11)·vault(Task 12)·verify(Task 13) 전반에서 일관. 함수 시그니처(`ingest_largest_shareholders`/`ingest_other_corp_investments`/`ingest_equity_for_company`/`ingest_equity_all`/`resolve_external_companies`/`resolve_owners`/`verify_equity`) 호출부와 정의부 일치. ID 헬퍼(`person_id`/`canonical_person_id`/`external_company_id`) 정의(Task 2)와 사용처 일치.
