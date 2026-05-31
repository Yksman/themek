# Track B1 — Graph Connectivity + Legacy Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 백필된 company 노드에 `ISSUES_STOCK`(기존 관계형 stocks에서 투영)와 `IN_SECTOR`(DART induty_code fetch) 엣지를 채우고, 죽은 관계형 온톨로지 테이블을 제거한다.

**Architecture:** 두 개의 멱등 ingest 함수 — `link_stocks`(관계형 `Stock` → `ISSUES_STOCK` 엣지)와 `link_sectors`(DART `company.json` → sector 노드 + `IN_SECTOR` 엣지). 둘 다 `upsert_node`/`upsert_edge` 기존 패턴 사용. 잔재 테이블은 일방향 cleanup 마이그레이션으로 DROP.

**Tech Stack:** Python, SQLAlchemy 2.x, Alembic, Typer, pytest. 테스트는 `ontology_session` 픽스처(`Base.metadata.create_all`로 corp_models+ontology 테이블 모두 생성).

**Spec:** `docs/superpowers/specs/2026-05-31-ontology-essence-track-b-design.md` §3

---

## File Structure

- `src/themek/ontology/ingest/linkage.py` — **신규**: `link_stocks(session)` (관계형→ISSUES_STOCK).
- `src/themek/dart/client.py` — **수정**: `fetch_company_profile(corp_code)` 추가.
- `src/themek/ontology/ingest/classification.py` — **신규**: `link_sectors(session, client)` (induty→IN_SECTOR).
- `migrations/versions/0006_drop_legacy_ontology_tables.py` — **신규**: 잔재 테이블 DROP.
- `src/themek/cli.py` — **수정**: `ontology link` 커맨드.
- 테스트: `tests/ontology/test_linkage.py`, `tests/ontology/test_classification.py`(신규).

---

## Task 1: link_stocks — 관계형 stocks → ISSUES_STOCK 엣지

**Success gate (측정 가능):**
- `.venv/bin/python -m pytest tests/ontology/test_linkage.py` → 2 passed.
- `link_stocks(session)` 반환값 == 그래프 company의 관계형 `Stock` 행 수(테스트 시나리오: 1).
- 재실행 후 `Edge(predicate="ISSUES_STOCK")` 행 수 불변(멱등 — 증가분 0).
- `dart_code` 없는 company는 0 반환·엣지 생성 0.

**Files:**
- Create: `src/themek/ontology/ingest/linkage.py`
- Test: `tests/ontology/test_linkage.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/ontology/test_linkage.py`:

```python
"""link_stocks — 관계형 stocks를 ISSUES_STOCK 엣지로 투영."""
from sqlalchemy import select

from themek.db.corp_models import Corporation, Stock
from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.linkage import link_stocks


def test_link_stocks_projects_and_is_idempotent(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    s.add(Corporation(dart_code="00126380", name_ko="삼성전자"))
    s.add(Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
                share_class="common", issued_by_id="00126380"))
    s.commit()

    n = link_stocks(s); s.commit()
    assert n == 1
    edge = s.execute(
        select(Edge).where(Edge.predicate == "ISSUES_STOCK")).scalar_one()
    assert edge.object_id == "stock:005930"
    assert edge.source_type == "dart_api"
    node = s.get(Node, "stock:005930")
    assert node.attrs["market"] == "KOSPI"

    link_stocks(s); s.commit()   # 멱등 — 중복 엣지 없음
    assert s.query(Edge).filter_by(predicate="ISSUES_STOCK").count() == 1


def test_link_stocks_skips_company_without_dart_code(ontology_session):
    s = ontology_session
    upsert_node(s, "company:x", "company", "노코드", {})  # dart_code 없음
    s.commit()
    assert link_stocks(s) == 0
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_linkage.py -v`
Expected: FAIL — `ModuleNotFoundError: themek.ontology.ingest.linkage`.

- [ ] **Step 3: 최소 구현**

`src/themek/ontology/ingest/linkage.py`:

```python
"""관계형 운영 테이블 → 코어 그래프 엣지 투영 (provenance method=api)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.db.corp_models import Stock
from themek.ontology.core.ids import stock_id
from themek.ontology.core.models import Node
from themek.ontology.core.resolve import upsert_node, upsert_edge


def link_stocks(session: Session) -> int:
    """company 노드의 dart_code로 관계형 Stock을 찾아 ISSUES_STOCK 엣지 투영. 멱등."""
    companies = session.execute(
        select(Node).where(Node.kind == "company")
    ).scalars().all()
    n = 0
    for c in companies:
        dart_code = c.attrs.get("dart_code")
        if not dart_code:
            continue
        stocks = session.execute(
            select(Stock).where(Stock.issued_by_id == dart_code)
        ).scalars().all()
        for st in stocks:
            sid = stock_id(st.ticker)
            upsert_node(session, sid, "stock", st.name_ko,
                        {"ticker": st.ticker, "market": st.market})
            upsert_edge(session, subject_id=c.id, predicate="ISSUES_STOCK",
                        object_id=sid, period=None, qualifier={},
                        source_type="dart_api", source_ref=None, method="api",
                        confidence=1.0)
            n += 1
    return n
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_linkage.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: 커밋**

```bash
git add src/themek/ontology/ingest/linkage.py tests/ontology/test_linkage.py
git commit -m "feat(ontology): link_stocks — project relational stocks to ISSUES_STOCK edges"
```

---

## Task 2: fetch_company_profile + link_sectors — induty → IN_SECTOR

**Success gate (측정 가능):**
- `.venv/bin/python -m pytest tests/ontology/test_classification.py` → 2 passed.
- 생성된 `IN_SECTOR` 엣지: `source_type=="dart_api"`, `object_id == "sector:{induty_code}"`.
- sector 노드 `label == induty명`(없으면 코드 fallback).
- 재실행 후 `IN_SECTOR` 행 수 불변(멱등). induty_code 없는 응답은 0 반환.

**Files:**
- Modify: `src/themek/dart/client.py` (`fetch_company_profile` 추가, `fetch_financials` 뒤 line 97 이후)
- Create: `src/themek/ontology/ingest/classification.py`
- Test: `tests/ontology/test_classification.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/ontology/test_classification.py`:

```python
"""link_sectors — DART induty_code → IN_SECTOR 엣지 + sector 노드."""
from sqlalchemy import select

from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.classification import link_sectors


class _FakeClient:
    def __init__(self, profiles):
        self.profiles = profiles  # {corp_code: {"induty_code":..,"induty":..}}

    def fetch_company_profile(self, *, corp_code):
        return self.profiles.get(corp_code, {})


def test_link_sectors_creates_sector_and_edge(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    s.commit()
    client = _FakeClient({"00126380": {"induty_code": "264",
                                       "induty": "반도체 제조업"}})
    n = link_sectors(s, client); s.commit()
    assert n == 1
    assert s.get(Node, "sector:264").label == "반도체 제조업"
    edge = s.execute(
        select(Edge).where(Edge.predicate == "IN_SECTOR")).scalar_one()
    assert edge.object_id == "sector:264"
    assert edge.source_type == "dart_api"

    link_sectors(s, client); s.commit()   # 멱등
    assert s.query(Edge).filter_by(predicate="IN_SECTOR").count() == 1


def test_link_sectors_skips_when_no_induty(ontology_session):
    s = ontology_session
    upsert_node(s, "company:1", "company", "A", {"dart_code": "1"})
    s.commit()
    assert link_sectors(s, _FakeClient({"1": {}})) == 0
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_classification.py -v`
Expected: FAIL — `ModuleNotFoundError: themek.ontology.ingest.classification`.

- [ ] **Step 3: client 메서드 추가**

`src/themek/dart/client.py`의 `fetch_financials` 메서드 뒤(line 97 `return payload.get("list", [])` 다음, `_raise_on_error` 앞)에 추가:

```python
    def fetch_company_profile(self, *, corp_code: str) -> dict:
        """기업개황(company.json). induty_code/induty 포함. 비정상 status는 {}."""
        params = {"crtfc_key": self._key, "corp_code": corp_code}
        r = self._client.get(f"{self._base}/company.json", params=params)
        self._raise_on_error(r)
        payload = r.json()
        if payload.get("status") != "000":
            return {}
        return payload
```

- [ ] **Step 4: classification 구현**

`src/themek/ontology/ingest/classification.py`:

```python
"""외부(DART) 분류 데이터 → 코어 섹터 노드/엣지 (provenance method=api)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.ids import sector_id
from themek.ontology.core.models import Node
from themek.ontology.core.resolve import upsert_node, upsert_edge


def link_sectors(session: Session, client) -> int:
    """company 노드별 DART 기업개황 fetch → sector 노드 + IN_SECTOR 엣지. 멱등.

    그래프가 정본이므로 관계형 Corporation.in_sector_id는 동기화하지 않는다
    (induty_code는 sectors.fics_code FK 네임스페이스와 달라 FK 위반 위험).
    """
    companies = session.execute(
        select(Node).where(Node.kind == "company")
    ).scalars().all()
    n = 0
    for c in companies:
        dart_code = c.attrs.get("dart_code")
        if not dart_code:
            continue
        profile = client.fetch_company_profile(corp_code=dart_code)
        code = (profile.get("induty_code") or "").strip()
        if not code:
            continue
        name = (profile.get("induty") or code).strip()
        sid = sector_id(code)
        upsert_node(session, sid, "sector", name)
        upsert_edge(session, subject_id=c.id, predicate="IN_SECTOR",
                    object_id=sid, period=None, qualifier={},
                    source_type="dart_api", source_ref=None, method="api",
                    confidence=1.0)
        n += 1
    return n
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_classification.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: 커밋**

```bash
git add src/themek/dart/client.py src/themek/ontology/ingest/classification.py tests/ontology/test_classification.py
git commit -m "feat(ontology): link_sectors — fetch DART induty_code into IN_SECTOR edges + sector nodes"
```

---

## Task 3: 잔재 테이블 DROP — 마이그레이션 0006

**Success gate (측정 가능):**
- 임시 DB에서 `alembic upgrade head` 종료코드 0.
- upgrade 후 `SELECT name FROM sqlite_master`에 `business_segments`/`customer_relations`/`geographic_exposures`/`revenue_compositions`/`products` **5개 모두 부재**.
- `nodes`/`edges`/`financial_facts` 테이블은 그대로 존재.

**Files:**
- Create: `migrations/versions/0006_drop_legacy_ontology_tables.py`

- [ ] **Step 1: 마이그레이션 작성**

`migrations/versions/0006_drop_legacy_ontology_tables.py`:

```python
"""drop legacy relational ontology tables (replaced by graph-core)

Revision ID: 0006_drop_legacy
Revises: 0005_edge_unique
Create Date: 2026-05-31 00:00:00.000000

구 db/models.py의 온톨로지 테이블(business_segments/customer_relations/
geographic_exposures/revenue_compositions)과 미사용 products는 graph-core(nodes/
edges/financial_facts)로 대체되어 코드 미참조 상태다. 일방향 cleanup —
downgrade는 빈 스텁만 재생성하지 않고 명시적으로 미복원한다(데이터/스키마 모두 폐기).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0006_drop_legacy"
down_revision: Union[str, Sequence[str], None] = "0005_edge_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY = [
    "revenue_compositions",
    "geographic_exposures",
    "customer_relations",
    "business_segments",
    "products",
]


def upgrade() -> None:
    for t in _LEGACY:
        op.execute(f"DROP TABLE IF EXISTS {t}")


def downgrade() -> None:
    # 일방향 cleanup: 폐기된 레거시 테이블은 복원하지 않는다.
    raise NotImplementedError(
        "0006 is a one-way cleanup of dead legacy ontology tables")
```

- [ ] **Step 2: 마이그레이션 스모크 (임시 DB)**

Run:
```bash
TMPDB=$(mktemp -t b1idx).db; POSTGRES_DSN="sqlite:///$TMPDB" .venv/bin/alembic upgrade head
```
Expected: 에러 없이 `0006_drop_legacy`까지 적용 완료. (env 키는 `tests/conftest.py`가 쓰는 `POSTGRES_DSN`과 동일.)

- [ ] **Step 3: 커밋**

```bash
git add migrations/versions/0006_drop_legacy_ontology_tables.py
git commit -m "chore(db): migration 0006 — drop dead legacy relational ontology tables"
```

---

## Task 4: CLI — themek ontology link

**Success gate (측정 가능):**
- `.venv/bin/python -m themek.cli ontology link --help` 출력에 `--skip-sectors` 노출.
- 실 데이터 실행 시 `linked N ISSUES_STOCK, M IN_SECTOR edges` 출력, `N ≥ 1`(백필 39개사 기준 N≈39).
- 명령 종료코드 0.

**Files:**
- Modify: `src/themek/cli.py` (`ontology_app`에 `link` 커맨드 추가)

- [ ] **Step 1: 커맨드 추가**

`src/themek/cli.py`의 `ontology_export_graph_cmd`(line 823 근처) 뒤에 추가:

```python
@ontology_app.command("link")
def ontology_link_cmd(
    skip_sectors: bool = typer.Option(False, "--skip-sectors",
                                      help="섹터 fetch 생략(ISSUES_STOCK만)"),
):
    """ISSUES_STOCK(관계형 투영) + IN_SECTOR(DART induty fetch) 엣지 생성."""
    from themek.ontology.ingest.linkage import link_stocks
    from themek.ontology.ingest.classification import link_sectors
    with _session() as s:
        n_stock = link_stocks(s)
        n_sector = 0
        if not skip_sectors:
            client = DartClient(api_key=get_settings().dart_api_key)
            n_sector = link_sectors(s, client)
        s.commit()
    typer.echo(f"linked {n_stock} ISSUES_STOCK, {n_sector} IN_SECTOR edges")
```

- [ ] **Step 2: CLI 스모크**

Run: `.venv/bin/python -m themek.cli ontology link --help`
Expected: `--skip-sectors` 옵션이 표시.

- [ ] **Step 3: 실 데이터 적용 (선택)**

Run: `.venv/bin/python -m themek.cli ontology link`
Expected: `linked N ISSUES_STOCK, M IN_SECTOR edges` (N≈39, M은 fetch 성공 수).

- [ ] **Step 4: 커밋**

```bash
git add src/themek/cli.py
git commit -m "feat(cli): add 'themek ontology link' (ISSUES_STOCK + IN_SECTOR)"
```

---

## Self-Review

- **Spec coverage:** §3.1 ISSUES_STOCK→Task 1, §3.2 IN_SECTOR fetch→Task 2, §3.3 cleanup→Task 3, §3.4 CLI→Task 4. 그룹은 비목표(미구현) — 스펙과 일치.
- **Placeholder scan:** 없음. downgrade의 NotImplementedError는 placeholder가 아니라 의도된 일방향 마이그레이션(주석 명시).
- **Type consistency:** `link_stocks(session)->int`, `link_sectors(session, client)->int`, `fetch_company_profile(*, corp_code)->dict` — Task 1/2/4 전반 일관. `stock_id`/`sector_id` 기존 `ids.py` 사용.
- **Deviation from spec:** §3.2의 관계형 `in_sector_id` 동기화는 FK 네임스페이스 충돌로 생략(Task 2 docstring 명시) — 그래프 정본 원칙에 부합.
