# Track B2 — Entity Resolution Implementation Plan

> **상태: ✅ 구현 완료** — main 반영됨(2026-05-31 기준, 테스트 314개 통과). 아래 체크박스는 실행 추적용 기록이며 갱신되지 않았을 수 있습니다.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** customer raw 이름을 정규화 exact 매칭(+ 큐레이션 별칭)으로 상장 corporation에 해소해 `SELLS_TO`를 company 노드로 직결하고, segment 동의어를 canonical 노드로 병합한다.

**Architecture:** 순수 정규화 함수(`normalize_corp_name`) + JSON 별칭 시드(`seed_aliases`) + 재실행 안전 배치 패스(`resolve_customers`, `merge_segments`). 엣지 재지정은 UNIQUE(`ux_edge_spo`) 충돌 시 qualifier 병합 후 source 삭제하는 공통 헬퍼 `_repoint_edges`로 처리. 해소 후 Track A `check_integrity`로 검증.

**Tech Stack:** Python, SQLAlchemy 2.x, stdlib json, pytest.

**Spec:** `docs/superpowers/specs/2026-05-31-ontology-essence-track-b-design.md` §4

**의존성:** Track A(`ux_edge_spo` 엣지 UNIQUE, `check_integrity`) 완료. customer/company 노드는 백필로 이미 존재.

---

## File Structure

- `src/themek/ontology/core/resolve.py` — **수정**: `normalize_corp_name` 추가.
- `data/ontology/aliases.json` — **신규**: 큐레이션 별칭(customer 변형→corp, segment 동의어→canonical).
- `src/themek/ontology/ingest/seeds.py` — **수정**: `seed_aliases(session)` 추가.
- `src/themek/ontology/ingest/resolution.py` — **신규**: `_repoint_edges`, `resolve_customers`, `merge_segments`.
- `src/themek/cli.py` — **수정**: `ontology resolve` 커맨드.
- 테스트: `tests/ontology/test_resolve.py`(수정), `tests/ontology/test_resolution.py`(신규).

---

## Task 1: normalize_corp_name — 법인명 정규화

**Success gate (측정 가능):**
- `.venv/bin/python -m pytest tests/ontology/test_resolve.py` 전체 passed.
- `normalize_corp_name`: `(주)`/`㈜`/`주식회사`/`Inc`/`Co.,Ltd`/`Corp` 제거 + 소문자 + 공백 단일화.
- 수렴 검증: `normalize_corp_name("현대자동차(주)") == normalize_corp_name("현대자동차")`.

**Files:**
- Modify: `src/themek/ontology/core/resolve.py` (`normalize_alias` 뒤 line 17 이후)
- Test: `tests/ontology/test_resolve.py` (신규 1건)

> 주: `normalize_alias`(범용, 세그먼트/쿼리용)는 screen.py 회귀를 피해 그대로 두고, 법인 전용
> `normalize_corp_name`을 신규 추가한다(스펙 §4.1의 "위임" 옵션 대신 분리 — 저위험).

- [ ] **Step 1: 실패 테스트 작성**

`tests/ontology/test_resolve.py` 끝에 추가:

```python
from themek.ontology.core.resolve import normalize_corp_name


def test_normalize_corp_name_strips_legal_forms():
    assert normalize_corp_name("삼성전자(주)") == "삼성전자"
    assert normalize_corp_name("(주)삼성전자") == "삼성전자"
    assert normalize_corp_name("㈜삼성전자") == "삼성전자"
    assert normalize_corp_name("주식회사 삼성전자") == "삼성전자"
    assert normalize_corp_name("  Samsung  Electronics  Co., Ltd. ") \
        == "samsung electronics"
    assert normalize_corp_name("Apple Inc.") == "apple"
    # 동일 정규화로 수렴
    assert normalize_corp_name("현대자동차(주)") == normalize_corp_name("현대자동차")
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_resolve.py -k normalize_corp_name -v`
Expected: FAIL — `ImportError: cannot import name 'normalize_corp_name'`.

- [ ] **Step 3: 구현**

`src/themek/ontology/core/resolve.py`의 `normalize_alias`(line 14-16) 뒤에 추가:

```python
_CORP_AFFIX = re.compile(
    r"\(주\)|㈜|주식회사|\bco\.?,?\s*ltd\.?|\bltd\.?|\binc\.?|\bcorp\.?|"
    r"\bcorporation\b|\bcompany\b",
    re.IGNORECASE,
)


def normalize_corp_name(s: str) -> str:
    """법인명 매칭용 정규화: 법인 형태 접두/접미 제거 + 소문자 + 공백 단일화."""
    out = _CORP_AFFIX.sub(" ", s)
    out = re.sub(r"[,.]", " ", out)
    out = _WS.sub(" ", out).strip().lower()
    return out
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_resolve.py -v`
Expected: PASS (기존 + 신규).

- [ ] **Step 5: 커밋**

```bash
git add src/themek/ontology/core/resolve.py tests/ontology/test_resolve.py
git commit -m "feat(ontology): add normalize_corp_name for legal-form-insensitive corp matching"
```

---

## Task 2: 별칭 시드 — aliases.json + seed_aliases

**Success gate (측정 가능):**
- `.venv/bin/python -m pytest tests/ontology/test_resolution.py::test_seed_aliases_creates_concept_aliases` passed.
- `seed_aliases` 반환 `n == 변형 총수`(테스트: 2).
- customer 변형은 `normalize_corp_name` 키, segment 동의어는 `normalize_alias` 키로 `ConceptAlias` 조회 성공.
- 재실행 시 동일 키 upsert(중복 행 0).

**Files:**
- Create: `data/ontology/aliases.json`
- Modify: `src/themek/ontology/ingest/seeds.py`
- Test: `tests/ontology/test_resolution.py` (신규, seed 파트)

- [ ] **Step 1: 별칭 데이터 작성**

`data/ontology/aliases.json` (초기 큐레이션 — 예시 + 빈 골격):

```json
{
  "customers": [
    {"corp": "00126380", "variants": ["삼성전자", "삼성전자(주)", "Samsung Electronics"]},
    {"corp": "00164742", "variants": ["현대자동차", "현대차", "Hyundai Motor"]}
  ],
  "segments": [
    {"canonical": "메모리반도체", "variants": ["메모리", "메모리 반도체", "메모리 사업"]}
  ]
}
```

- [ ] **Step 2: 실패 테스트 작성**

`tests/ontology/test_resolution.py`:

```python
"""엔티티 해소: 별칭 시드 + customer/segment 배치 패스."""
import json
from pathlib import Path

from sqlalchemy import select

from themek.db.corp_models import Corporation
from themek.ontology.core.ids import company_id, customer_id, segment_id
from themek.ontology.core.models import Node, Edge, ConceptAlias
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.ingest.seeds import seed_aliases


def _aliases(tmp_path, data):
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_seed_aliases_creates_concept_aliases(ontology_session, tmp_path):
    s = ontology_session
    upsert_node(s, company_id("00126380"), "company", "삼성전자",
                {"dart_code": "00126380"})
    upsert_node(s, segment_id("메모리반도체"), "segment", "메모리반도체")
    s.commit()
    path = _aliases(tmp_path, {
        "customers": [{"corp": "00126380", "variants": ["삼성전자(주)"]}],
        "segments": [{"canonical": "메모리반도체", "variants": ["메모리"]}],
    })
    n = seed_aliases(s, path); s.commit()
    assert n == 2
    # customer 변형 → company 노드
    from themek.ontology.core.resolve import normalize_corp_name, normalize_alias
    a1 = s.get(ConceptAlias, normalize_corp_name("삼성전자(주)"))
    assert a1.node_id == company_id("00126380")
    # segment 동의어 → canonical segment 노드
    a2 = s.get(ConceptAlias, normalize_alias("메모리"))
    assert a2.node_id == segment_id("메모리반도체")
```

- [ ] **Step 3: 테스트 실행 → 실패 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_resolution.py::test_seed_aliases_creates_concept_aliases -v`
Expected: FAIL — `ImportError: cannot import name 'seed_aliases'`.

- [ ] **Step 4: seed_aliases 구현**

`src/themek/ontology/ingest/seeds.py` 끝에 추가 (상단 import에 `json`, `Path`, `ConceptAlias`, `customer_id`, `normalize_corp_name`, `normalize_alias` 보강):

```python
import json
from pathlib import Path

from themek.ontology.core.models import ConceptAlias
from themek.ontology.core.ids import customer_id
from themek.ontology.core.resolve import normalize_corp_name, normalize_alias

_DEFAULT_ALIASES = Path("data/ontology/aliases.json")


def _upsert_alias(session: Session, alias_norm: str, node_id: str) -> None:
    row = session.get(ConceptAlias, alias_norm)
    if row is None:
        session.add(ConceptAlias(alias_norm=alias_norm, node_id=node_id,
                                 source="manual", confidence=1.0))
    else:
        row.node_id = node_id


def seed_aliases(session: Session, path: Path = _DEFAULT_ALIASES) -> int:
    """JSON 별칭을 ConceptAlias로 적재. customer 변형은 normalize_corp_name,
    segment 동의어는 normalize_alias 키로 저장. upsert(멱등). 적재 수 반환."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    n = 0
    for entry in data.get("customers", []):
        target = company_id(entry["corp"])
        for variant in entry["variants"]:
            _upsert_alias(session, normalize_corp_name(variant), target)
            n += 1
    for entry in data.get("segments", []):
        target = segment_id(entry["canonical"])
        for variant in entry["variants"]:
            _upsert_alias(session, normalize_alias(variant), target)
            n += 1
    return n
```

> 상단 import에 `segment_id`도 필요 — 기존 `from themek.ontology.core.ids import company_id, stock_id, sector_id, region_id`에 `segment_id, customer_id` 추가.

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_resolution.py::test_seed_aliases_creates_concept_aliases -v`
Expected: PASS.

- [ ] **Step 6: 커밋**

```bash
git add data/ontology/aliases.json src/themek/ontology/ingest/seeds.py tests/ontology/test_resolution.py
git commit -m "feat(ontology): seed_aliases — curated customer/segment aliases into ConceptAlias"
```

---

## Task 3: _repoint_edges + resolve_customers

**Success gate (측정 가능):**
- `.venv/bin/python -m pytest tests/ontology/test_resolution.py -k resolve_customers` → 3 passed.
- 해소: `SELLS_TO.object_id == company_id`, `qualifier["buyer_raw"]` 보존, customer 노드 `None`(삭제).
- 미해소: customer 노드 잔존 + `attrs["resolved"] == False`.
- 충돌: 동일 `(subject, SELLS_TO, company, period)` 엣지 정확히 **1건**(병합 후).

**Files:**
- Create: `src/themek/ontology/ingest/resolution.py`
- Test: `tests/ontology/test_resolution.py` (신규 케이스)

- [ ] **Step 1: 실패 테스트 작성**

`tests/ontology/test_resolution.py`에 추가:

```python
from themek.ontology.ingest.resolution import resolve_customers


def _seller_sells_to(s, *, seller, buyer_node, period="2024"):
    upsert_edge(s, subject_id=seller, predicate="SELLS_TO",
                object_id=buyer_node, period=period, qualifier={},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)


def test_resolve_customers_repoints_and_removes_customer(ontology_session):
    s = ontology_session
    # 그래프 company + 관계형 corp + raw customer 노드
    upsert_node(s, company_id("00164742"), "company", "현대자동차",
                {"dart_code": "00164742"})
    upsert_node(s, company_id("seller1"), "company", "셀러1",
                {"dart_code": "seller1"})
    cust_id = customer_id("현대차(주)")
    upsert_node(s, cust_id, "customer", "현대차(주)")
    s.add(Corporation(dart_code="00164742", name_ko="현대자동차"))
    s.commit()
    _seller_sells_to(s, seller=company_id("seller1"), buyer_node=cust_id)
    s.commit()

    res = resolve_customers(s); s.commit()
    assert res["resolved"] == 1
    # SELLS_TO가 company:현대차로 재지정, buyer_raw 보존
    e = s.execute(select(Edge).where(Edge.predicate == "SELLS_TO")).scalar_one()
    assert e.object_id == company_id("00164742")
    assert e.qualifier["buyer_raw"] == "현대차(주)"
    # customer 노드 제거
    assert s.get(Node, cust_id) is None


def test_resolve_customers_marks_unresolved(ontology_session):
    s = ontology_session
    upsert_node(s, company_id("s"), "company", "셀러", {"dart_code": "s"})
    cid = customer_id("이름없는해외바이어")
    upsert_node(s, cid, "customer", "이름없는해외바이어"); s.commit()
    _seller_sells_to(s, seller=company_id("s"), buyer_node=cid); s.commit()
    res = resolve_customers(s); s.commit()
    assert res["unresolved"] == 1
    assert s.get(Node, cid).attrs.get("resolved") is False


def test_resolve_customers_merges_on_conflict(ontology_session):
    """셀러가 raw customer와 (해소대상)company 둘 다 같은 period로 SELLS_TO하면 병합."""
    s = ontology_session
    upsert_node(s, company_id("00164742"), "company", "현대자동차",
                {"dart_code": "00164742"})
    upsert_node(s, company_id("seller1"), "company", "셀러1",
                {"dart_code": "seller1"})
    cust_id = customer_id("현대차")
    upsert_node(s, cust_id, "customer", "현대차")
    s.add(Corporation(dart_code="00164742", name_ko="현대자동차")); s.commit()
    # 이미 company로 직접 + raw로도 SELLS_TO (동일 period)
    _seller_sells_to(s, seller=company_id("seller1"),
                     buyer_node=company_id("00164742"))
    _seller_sells_to(s, seller=company_id("seller1"), buyer_node=cust_id)
    s.commit()
    res = resolve_customers(s); s.commit()
    # 충돌 병합 → SELLS_TO(seller1→현대차) 1건만
    edges = s.execute(select(Edge).where(
        Edge.subject_id == company_id("seller1"),
        Edge.predicate == "SELLS_TO",
        Edge.object_id == company_id("00164742"))).scalars().all()
    assert len(edges) == 1
    assert s.get(Node, cust_id) is None
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_resolution.py -k resolve_customers -v`
Expected: FAIL — `ModuleNotFoundError: themek.ontology.ingest.resolution`.

- [ ] **Step 3: 구현**

`src/themek/ontology/ingest/resolution.py`:

```python
"""엔티티 해소 배치 패스 — customer→company, segment 병합. 재실행 안전."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.db.corp_models import Corporation
from themek.ontology.core.ids import company_id
from themek.ontology.core.models import Node, Edge, ConceptAlias
from themek.ontology.core.resolve import normalize_corp_name


def _repoint_edges(session: Session, *, old_object_id: str,
                   new_object_id: str, raw_label: str | None = None) -> int:
    """old_object_id를 object로 하는 엣지를 new_object_id로 재지정.
    동일 (subject,predicate,object,period) 기존 엣지와 충돌 시 병합 후 source 삭제."""
    edges = session.execute(
        select(Edge).where(Edge.object_id == old_object_id)
    ).scalars().all()
    moved = 0
    for e in edges:
        if raw_label is not None and "buyer_raw" not in e.qualifier:
            q = dict(e.qualifier); q["buyer_raw"] = raw_label; e.qualifier = q
        existing = session.execute(
            select(Edge).where(
                Edge.subject_id == e.subject_id,
                Edge.predicate == e.predicate,
                Edge.object_id == new_object_id,
                Edge.period.is_(None) if e.period is None
                else Edge.period == e.period,
            )
        ).scalars().first()
        if existing is not None and existing.id != e.id:
            if raw_label is not None and "buyer_raw" not in existing.qualifier:
                q = dict(existing.qualifier); q["buyer_raw"] = raw_label
                existing.qualifier = q
            session.delete(e)
        else:
            e.object_id = new_object_id
        moved += 1
    session.flush()
    return moved


def resolve_customers(session: Session) -> dict:
    """customer 노드를 정규화 exact(별칭 우선)로 company에 해소.
    매칭 시 SELLS_TO를 company로 재지정 + customer 제거, 미매칭은 resolved=false 표식."""
    corp_index = {
        normalize_corp_name(c.name_ko): company_id(c.dart_code)
        for c in session.execute(select(Corporation)).scalars().all()
    }
    customers = session.execute(
        select(Node).where(Node.kind == "customer")
    ).scalars().all()
    resolved = unresolved = repointed = 0
    for cust in customers:
        norm = normalize_corp_name(cust.label)
        target = None
        alias = session.get(ConceptAlias, norm)
        if alias is not None and alias.node_id.startswith("company:"):
            target = alias.node_id
        elif norm in corp_index:
            target = corp_index[norm]
        # 그래프에 존재하는 company로만 해소
        if target is None or session.get(Node, target) is None:
            attrs = dict(cust.attrs); attrs["resolved"] = False
            cust.attrs = attrs
            unresolved += 1
            continue
        repointed += _repoint_edges(session, old_object_id=cust.id,
                                    new_object_id=target, raw_label=cust.label)
        session.delete(cust)
        resolved += 1
    session.flush()
    return {"resolved": resolved, "unresolved": unresolved,
            "edges_repointed": repointed}
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_resolution.py -k resolve_customers -v`
Expected: PASS (3 passed).

- [ ] **Step 5: 커밋**

```bash
git add src/themek/ontology/ingest/resolution.py tests/ontology/test_resolution.py
git commit -m "feat(ontology): resolve_customers — repoint SELLS_TO to matched company, merge on conflict"
```

---

## Task 4: merge_segments

**Success gate (측정 가능):**
- `.venv/bin/python -m pytest tests/ontology/test_resolution.py -k merge_segments` passed.
- 반환 `merged == 1`; 변형 segment의 `HAS_SEGMENT`가 canonical 노드로 재지정.
- 변형 segment 노드 삭제(`None`); canonical 노드 유지.

**Files:**
- Modify: `src/themek/ontology/ingest/resolution.py` (`merge_segments` 추가)
- Test: `tests/ontology/test_resolution.py` (신규 케이스)

- [ ] **Step 1: 실패 테스트 작성**

`tests/ontology/test_resolution.py`에 추가:

```python
from themek.ontology.ingest.resolution import merge_segments
from themek.ontology.core.resolve import normalize_alias


def test_merge_segments_repoints_to_canonical(ontology_session):
    s = ontology_session
    canon = segment_id("메모리반도체")
    variant = segment_id("메모리")
    upsert_node(s, company_id("c"), "company", "회사", {"dart_code": "c"})
    upsert_node(s, canon, "segment", "메모리반도체")
    upsert_node(s, variant, "segment", "메모리")
    # 별칭: normalize_alias("메모리") → canonical
    s.add(ConceptAlias(alias_norm=normalize_alias("메모리"), node_id=canon,
                       source="manual", confidence=1.0))
    s.commit()
    upsert_edge(s, subject_id=company_id("c"), predicate="HAS_SEGMENT",
                object_id=variant, period="2024", qualifier={"share_pct": 30.0},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    s.commit()

    res = merge_segments(s); s.commit()
    assert res["merged"] == 1
    e = s.execute(select(Edge).where(Edge.predicate == "HAS_SEGMENT")).scalar_one()
    assert e.object_id == canon
    assert s.get(Node, variant) is None
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_resolution.py -k merge_segments -v`
Expected: FAIL — `ImportError: cannot import name 'merge_segments'`.

- [ ] **Step 3: 구현**

`src/themek/ontology/ingest/resolution.py` 상단 import에 `normalize_alias` 추가하고 끝에 추가:

```python
def merge_segments(session: Session) -> dict:
    """별칭 시드에 따라 비-canonical segment 노드의 HAS_SEGMENT 엣지를 canonical로
    재지정 + 고아 노드 제거. ConceptAlias(segment)는 normalize_alias 키 사용."""
    from themek.ontology.core.resolve import normalize_alias
    segments = session.execute(
        select(Node).where(Node.kind == "segment")
    ).scalars().all()
    merged = 0
    for seg in segments:
        alias = session.get(ConceptAlias, normalize_alias(seg.label))
        if alias is None or alias.node_id == seg.id:
            continue
        if not alias.node_id.startswith("segment:") \
                or session.get(Node, alias.node_id) is None:
            continue
        _repoint_edges(session, old_object_id=seg.id,
                       new_object_id=alias.node_id)
        session.delete(seg)
        merged += 1
    session.flush()
    return {"merged": merged}
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_resolution.py -v`
Expected: PASS (전체).

- [ ] **Step 5: 커밋**

```bash
git add src/themek/ontology/ingest/resolution.py tests/ontology/test_resolution.py
git commit -m "feat(ontology): merge_segments — fold synonym segments into canonical via aliases"
```

---

## Task 5: CLI — themek ontology resolve

**Success gate (측정 가능):**
- `.venv/bin/python -m themek.cli ontology resolve --help` 커맨드 표시.
- `.venv/bin/python -m pytest tests/ontology -q` 전체 PASS.
- 실 실행 시 `integrity errors: 0` 출력 + 종료코드 0(해소 후 중복 엣지/고아 없음).

**Files:**
- Modify: `src/themek/cli.py` (`ontology_app`에 `resolve` 커맨드)

- [ ] **Step 1: 커맨드 추가**

`src/themek/cli.py`의 `ontology_link_cmd`(B1 Task4) 뒤에 추가:

```python
@ontology_app.command("resolve")
def ontology_resolve_cmd():
    """별칭 시드 → customer→company 해소 → segment 병합 → 무결성 검사."""
    from themek.ontology.ingest.seeds import seed_aliases
    from themek.ontology.ingest.resolution import resolve_customers, merge_segments
    from themek.ontology.validate import check_integrity
    with _session() as s:
        seeded = seed_aliases(s)
        cust = resolve_customers(s)
        seg = merge_segments(s)
        errors = [i for i in check_integrity(s) if i.severity == "error"]
        s.commit()
    typer.echo(f"aliases seeded: {seeded}")
    typer.echo(f"customers resolved: {cust['resolved']}, "
               f"unresolved: {cust['unresolved']}, "
               f"edges repointed: {cust['edges_repointed']}")
    typer.echo(f"segments merged: {seg['merged']}")
    typer.echo(f"integrity errors: {len(errors)}")
    if errors:
        raise typer.Exit(code=1)
```

- [ ] **Step 2: CLI 스모크**

Run: `.venv/bin/python -m themek.cli ontology resolve --help`
Expected: 커맨드 표시.

- [ ] **Step 3: 실 데이터 적용 (선택)**

Run: `.venv/bin/python -m themek.cli ontology resolve`
Expected: 해소/미해소/병합 카운트 + `integrity errors: 0`.

- [ ] **Step 4: 전체 테스트**

Run: `.venv/bin/python -m pytest tests/ontology -q`
Expected: 전체 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/themek/cli.py
git commit -m "feat(cli): add 'themek ontology resolve' (seed aliases + resolve + merge + verify)"
```

---

## Self-Review

- **Spec coverage:** §4.1 정규화→Task 1, §4.2 별칭 시드→Task 2, §4.3 해소 배치(resolve_customers/merge_segments/_repoint)→Task 3·4, §4.4 CLI→Task 5. 해소 후 `check_integrity` 재사용→Task 5.
- **Placeholder scan:** 없음. 모든 스텝 실제 코드.
- **Type consistency:** `normalize_corp_name(s)->str`, `seed_aliases(session, path=...)->int`, `_repoint_edges(session,*,old_object_id,new_object_id,raw_label=None)->int`, `resolve_customers(session)->{resolved,unresolved,edges_repointed}`, `merge_segments(session)->{merged}` — 정의·테스트·CLI 전반 일관. customer 별칭은 `normalize_corp_name` 키, segment 별칭은 `normalize_alias` 키로 일관(seed_aliases·resolve_customers·merge_segments 동일 규약).
- **Deviation from spec:** §4.1 "normalize_alias 통합" 대신 분리 신설(screen.py 회귀 회피). 해소 대상은 **그래프에 존재하는 company 노드로 한정**(매칭됐으나 미적재 corp는 unresolved 유지) — 회사 간 네트워크 형성이라는 목표에 부합하는 MVP 선택.
- **UNIQUE 상호작용:** `_repoint_edges`가 `ux_edge_spo`(Track A) 충돌을 사전 검사·병합으로 처리해 IntegrityError 회피 — 멱등.
