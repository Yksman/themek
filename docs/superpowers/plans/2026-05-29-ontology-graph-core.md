# 온톨로지 graph-ready 코어 + 재무 pilot Implementation Plan

> **상태: ✅ 구현 완료** — main 반영됨(2026-05-31 기준, 테스트 314개 통과). 아래 체크박스는 실행 추적용 기록이며 갱신되지 않았을 수 있습니다.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** DART 온톨로지를 graph-ready 관계형 코어(nodes/edges/financial_facts/concept_aliases)로 전면 재설계하고, 재무 KPI 시계열을 정형 API로 적재해 "특정 세그먼트가 주력이면서 특정 기간부터 연속 흑자인 기업" 같은 교차-회사 질의에 답한다.

**Architecture:** 신규 `src/themek/ontology/` 패키지에 코어 ORM(`core/`), 적재(`ingest/`), 투영(`projection/`), 질의(`query/`)를 둔다. 관계형이 system-of-record이고 graph-native 규약(안정 ID·균일 엣지·provenance·개념 정규화)을 지켜 graph export가 가능하다. **coexist-then-remove**: Phase 1–4는 신규 코어를 구축(기존 모델·테스트 유지로 매 커밋 green), Phase 5에서 구 모듈을 일괄 제거·cutover하고 실 DART 재적재로 검증한다.

**Tech Stack:** Python 3.12+, SQLAlchemy 2.0, typer(CLI), httpx(DART API), pytest(in-memory SQLite, vcr 카세트). 신규 의존성 0.

**Spec:** `docs/superpowers/specs/2026-05-29-ontology-graph-core-design.md`

---

## File Structure (decomposition)

| 파일 | 책임 |
|------|------|
| `src/themek/ontology/__init__.py` | 패키지 마커 |
| `src/themek/ontology/core/__init__.py` | 마커 |
| `src/themek/ontology/core/ids.py` | 안정 노드 ID 스킴 + slug |
| `src/themek/ontology/core/models.py` | `Node`·`Edge`·`FinancialFact`·`ConceptAlias` ORM + 열거형 |
| `src/themek/ontology/core/resolve.py` | concept resolver(정확일치+별칭) + upsert 헬퍼 |
| `src/themek/ontology/ingest/__init__.py` | 마커 |
| `src/themek/ontology/ingest/financials.py` | DART 재무 API → financial_facts |
| `src/themek/ontology/ingest/business_structure.py` | LLM 추출 결과 → nodes/edges |
| `src/themek/ontology/projection/__init__.py` | 마커 |
| `src/themek/ontology/projection/vault.py` | 코어 → Obsidian markdown |
| `src/themek/ontology/projection/graph_export.py` | 코어 → nodes.json/edges.json |
| `src/themek/ontology/query/__init__.py` | 마커 |
| `src/themek/ontology/query/screen.py` | competency 스크리닝 함수 |
| `src/themek/dart/client.py` (수정) | `fetch_financials` 추가 |
| `src/themek/cli.py` (수정) | `ingest financials`·`query screen`·`ontology export-graph` + vault build 재배선 |
| `src/themek/seeds.py` (교체) | 코어 노드 시드 |

**의존 방향:** `cli → {ingest, projection, query} → core`. core는 `db.engine.Base`에만 의존.

**제거(Phase 5):** `db/models.py`, `vault/*`, `query/e5.py`, `query/synthesize.py`(e5 의존 시), `ingest/business_report.py`, `eval/e5.py`(또는 코어 적응), 및 대응 테스트(`test_vault_*`, `test_query_e5*`, `test_ingest_business_report*`, `test_cli_vault`, `test_eval_e5*`). 신규 테스트로 대체.

---

## Phase 1 — 코어 기반 (스키마 · ID · resolver)

## Task 1.1: 스캐폴딩 + ids.py

**Files:**
- Create: `src/themek/ontology/__init__.py`, `src/themek/ontology/core/__init__.py`
- Create: `src/themek/ontology/core/ids.py`
- Test: `tests/ontology/test_ids.py`

- [ ] **Step 1: 패키지 마커 생성**

```bash
mkdir -p src/themek/ontology/core tests/ontology
printf '"""graph-ready 온톨로지 코어."""\n' > src/themek/ontology/__init__.py
printf '"""코어 ORM·ID·resolver."""\n' > src/themek/ontology/core/__init__.py
touch tests/ontology/__init__.py
```

- [ ] **Step 2: ids 테스트 작성**

`tests/ontology/test_ids.py`:

```python
"""안정 노드 ID 스킴 단위 테스트."""
from themek.ontology.core.ids import (
    company_id, stock_id, sector_id, region_id, period_id,
    segment_id, customer_id, metric_id, slug,
)


def test_natural_key_ids():
    assert company_id("00126380") == "company:00126380"
    assert stock_id("005930") == "stock:005930"
    assert sector_id("G2520") == "sector:G2520"
    assert region_id("US") == "region:US"
    assert metric_id("operating_income") == "metric:operating_income"


def test_period_id_label():
    assert period_id("2025", "Q1") == "period:2025Q1"
    assert period_id("2025", "H1") == "period:2025H1"
    assert period_id("2023", "FY") == "period:2023FY"


def test_slug_normalizes_korean_and_ascii():
    assert slug("  메모리 반도체 ") == "메모리-반도체"
    assert slug("Apple Inc.") == "apple-inc"
    assert slug("DX 부문") == "dx-부문"


def test_concept_ids_use_slug():
    assert segment_id("메모리반도체") == "segment:메모리반도체"
    assert customer_id("Apple Inc.") == "customer:apple-inc"


def test_long_concept_id_is_stable_and_hashed():
    raw = "세계 유수의 Mobile 및 Computing 관련 전자 업체 (DRAM 수요처)"
    a = customer_id(raw)
    assert a == customer_id(raw)          # 안정적
    assert len(a.split(":", 1)[1]) <= 48  # slug 상한
    assert customer_id(raw) != customer_id(raw + "x")  # 다른 원문 다른 id
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_ids.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.ontology.core.ids'`

- [ ] **Step 4: ids.py 구현**

`src/themek/ontology/core/ids.py`:

```python
"""전역 안정 노드 ID 스킴: `{kind}:{natural_key|slug}`.

자연키가 있는 종류(company/stock/sector/region/metric)는 키 그대로,
개념 종류(segment/customer)는 정규화 slug(+장문 해시)를 쓴다.
"""
from __future__ import annotations

import hashlib
import re

_WS = re.compile(r"\s+")
_UNSAFE = re.compile(r"[^0-9a-z가-힣]+")
_SLUG_MAX = 48


def slug(s: str) -> str:
    """소문자 + 공백/특수문자를 하이픈으로. 한글 보존."""
    base = _WS.sub(" ", s.strip()).lower()
    base = _UNSAFE.sub("-", base).strip("-")
    if len(base) <= _SLUG_MAX:
        return base
    h = hashlib.sha1(s.encode("utf-8")).hexdigest()[:6]
    return f"{base[:_SLUG_MAX - 7].strip('-')}-{h}"


def company_id(dart_code: str) -> str:
    return f"company:{dart_code}"


def stock_id(ticker: str) -> str:
    return f"stock:{ticker}"


def sector_id(fics_code: str) -> str:
    return f"sector:{fics_code}"


def region_id(code: str) -> str:
    return f"region:{code}"


def metric_id(key: str) -> str:
    return f"metric:{key}"


def period_id(bsns_year: str, fiscal_period: str) -> str:
    return f"period:{bsns_year}{fiscal_period}"


def segment_id(name_ko: str) -> str:
    return f"segment:{slug(name_ko)}"


def customer_id(raw: str) -> str:
    return f"customer:{slug(raw)}"
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_ids.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add src/themek/ontology tests/ontology
git commit -m "feat(ontology): scaffold core package + stable node id scheme"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_ids.py -q` → 5 passed. 자연키 ID·period 라벨·concept slug(안정·해시) 정확.

---

## Task 1.2: 코어 ORM 모델 (Node·Edge·FinancialFact·ConceptAlias)

**Files:**
- Create: `src/themek/ontology/core/models.py`
- Test: `tests/ontology/test_core_models.py`

- [ ] **Step 1: 모델 테스트 작성**

`tests/ontology/test_core_models.py`:

```python
"""코어 ORM 생성·제약·조회 단위 테스트."""
import pytest
from sqlalchemy import select
from themek.ontology.core.models import (
    Node, Edge, FinancialFact, ConceptAlias,
)


def test_node_roundtrip(ontology_session):
    s = ontology_session
    s.add(Node(id="company:00126380", kind="company", label="삼성전자",
               attrs={"name_en": "Samsung", "ticker": "005930"}))
    s.commit()
    got = s.get(Node, "company:00126380")
    assert got.kind == "company"
    assert got.attrs["name_en"] == "Samsung"


def test_edge_with_qualifier_and_provenance(ontology_session):
    s = ontology_session
    s.add(Node(id="company:00126380", kind="company", label="삼성전자"))
    s.add(Node(id="segment:메모리반도체", kind="segment", label="메모리반도체"))
    s.commit()
    s.add(Edge(subject_id="company:00126380", predicate="HAS_SEGMENT",
               object_id="segment:메모리반도체", period="2023",
               qualifier={"share_pct": 42.5}, source_type="llm",
               source_ref="20240314000001", method="llm", confidence=0.9))
    s.commit()
    e = s.execute(select(Edge).where(Edge.predicate == "HAS_SEGMENT")).scalar_one()
    assert e.qualifier["share_pct"] == 42.5
    assert e.source_type == "llm"


def test_financial_fact_unique_constraint(ontology_session):
    s = ontology_session
    s.add(Node(id="company:00126380", kind="company", label="삼성전자"))
    s.commit()
    def _fact():
        return FinancialFact(
            company_id="company:00126380", bsns_year="2024", fiscal_period="FY",
            fs_div="CFS", metric_key="operating_income", amount=1000,
            currency="KRW", source_type="dart_api", method="api", confidence=1.0)
    s.add(_fact()); s.commit()
    s.add(_fact())
    with pytest.raises(Exception):
        s.commit()


def test_concept_alias_lookup(ontology_session):
    s = ontology_session
    s.add(Node(id="segment:메모리반도체", kind="segment", label="메모리반도체"))
    s.commit()
    s.add(ConceptAlias(alias_norm="hbm", node_id="segment:메모리반도체",
                       source="manual", confidence=1.0))
    s.commit()
    row = s.get(ConceptAlias, "hbm")
    assert row.node_id == "segment:메모리반도체"
```

- [ ] **Step 2: conftest에 ontology_session fixture 추가**

`tests/conftest.py` 끝에 append:

```python
@pytest.fixture
def ontology_session(engine):
    """코어 온톨로지 테이블만 reset 후 세션 제공."""
    import themek.ontology.core.models  # noqa: F401 — 모델 등록
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    connection = engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    yield session
    session.close()
    try:
        trans.rollback()
    except Exception:
        pass
    connection.close()
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_core_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.ontology.core.models'`

- [ ] **Step 4: models.py 구현**

`src/themek/ontology/core/models.py`:

```python
"""graph-ready 코어 ORM. 프로퍼티그래프(Node/Edge) + 정형 fact(FinancialFact)."""
from __future__ import annotations

from datetime import datetime as _dt

from sqlalchemy import (
    String, Float, Numeric, ForeignKey, Enum as SQLEnum, JSON,
    DateTime, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from themek.db.engine import Base

NODE_KINDS = (
    "company", "stock", "sector", "region", "segment",
    "customer", "period", "metric", "group",
)
PREDICATES = (
    "HAS_SEGMENT", "SELLS_TO", "EXPOSED_TO", "IN_SECTOR",
    "ISSUES_STOCK", "BELONGS_TO_GROUP", "SUB_SECTOR_OF",
)
SOURCE_TYPES = ("dart_api", "dart_report", "social", "llm", "manual")
METHODS = ("api", "llm", "manual")
FISCAL_PERIODS = ("FY", "Q1", "H1", "Q3")
FS_DIVS = ("CFS", "OFS")
METRIC_KEYS = (
    "revenue", "operating_income", "net_income",
    "assets", "liabilities", "equity",
)


class Node(Base):
    __tablename__ = "nodes"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    kind: Mapped[str] = mapped_column(SQLEnum(*NODE_KINDS, name="node_kind"),
                                      nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    attrs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class Edge(Base):
    __tablename__ = "edges"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    subject_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("nodes.id"), nullable=False, index=True)
    predicate: Mapped[str] = mapped_column(
        SQLEnum(*PREDICATES, name="edge_predicate"), nullable=False, index=True)
    object_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("nodes.id"), nullable=False, index=True)
    period: Mapped[str | None] = mapped_column(String(16))
    qualifier: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_type: Mapped[str] = mapped_column(
        SQLEnum(*SOURCE_TYPES, name="source_type"), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512))
    method: Mapped[str] = mapped_column(SQLEnum(*METHODS, name="method"),
                                        nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    extracted_at: Mapped[_dt] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp())


class FinancialFact(Base):
    __tablename__ = "financial_facts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("nodes.id"), nullable=False, index=True)
    bsns_year: Mapped[str] = mapped_column(String(4), nullable=False)
    fiscal_period: Mapped[str] = mapped_column(
        SQLEnum(*FISCAL_PERIODS, name="fiscal_period"), nullable=False)
    fs_div: Mapped[str] = mapped_column(SQLEnum(*FS_DIVS, name="fs_div"),
                                        nullable=False)
    metric_key: Mapped[str] = mapped_column(
        SQLEnum(*METRIC_KEYS, name="metric_key"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(22, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(4), nullable=False, default="KRW")
    source_type: Mapped[str] = mapped_column(
        SQLEnum(*SOURCE_TYPES, name="source_type"), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(512))
    method: Mapped[str] = mapped_column(SQLEnum(*METHODS, name="method"),
                                        nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    __table_args__ = (
        UniqueConstraint("company_id", "bsns_year", "fiscal_period",
                         "fs_div", "metric_key", name="ux_financial_fact"),
    )


class ConceptAlias(Base):
    __tablename__ = "concept_aliases"
    alias_norm: Mapped[str] = mapped_column(String(256), primary_key=True)
    node_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("nodes.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_core_models.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add src/themek/ontology/core/models.py tests/ontology/test_core_models.py tests/conftest.py
git commit -m "feat(ontology): core ORM — Node/Edge/FinancialFact/ConceptAlias"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_core_models.py -q` → 4 passed. Node attrs JSON 라운드트립, Edge qualifier+provenance 저장, FinancialFact 유니크 제약, ConceptAlias 조회 정확.

---

## Task 1.3: concept resolver + 노드/엣지 upsert 헬퍼

**Files:**
- Create: `src/themek/ontology/core/resolve.py`
- Test: `tests/ontology/test_resolve.py`

- [ ] **Step 1: resolver 테스트 작성**

`tests/ontology/test_resolve.py`:

```python
"""concept resolver + upsert 헬퍼 단위 테스트."""
from themek.ontology.core.models import Node, ConceptAlias
from themek.ontology.core.resolve import (
    upsert_node, upsert_edge, resolve_concept, normalize_alias,
)


def test_normalize_alias():
    assert normalize_alias("  HBM 메모리 ") == "hbm 메모리"


def test_upsert_node_is_idempotent(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자", {"ticker": "005930"})
    upsert_node(s, "company:00126380", "company", "삼성전자(갱신)", {"ticker": "005930"})
    s.commit()
    rows = s.query(Node).filter_by(id="company:00126380").all()
    assert len(rows) == 1
    assert rows[0].label == "삼성전자(갱신)"  # 라벨 갱신


def test_upsert_edge_dedupes_same_triple_period(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자")
    upsert_node(s, "segment:메모리반도체", "segment", "메모리반도체")
    s.commit()
    kw = dict(subject_id="company:00126380", predicate="HAS_SEGMENT",
              object_id="segment:메모리반도체", period="2023",
              qualifier={"share_pct": 42.5}, source_type="llm",
              source_ref="r1", method="llm", confidence=0.9)
    upsert_edge(s, **kw)
    upsert_edge(s, **{**kw, "qualifier": {"share_pct": 50.0}})  # 갱신
    s.commit()
    from themek.ontology.core.models import Edge
    edges = s.query(Edge).all()
    assert len(edges) == 1
    assert edges[0].qualifier["share_pct"] == 50.0


def test_resolve_concept_exact_then_alias(ontology_session):
    s = ontology_session
    upsert_node(s, "segment:메모리반도체", "segment", "메모리반도체")
    s.add(ConceptAlias(alias_norm="hbm", node_id="segment:메모리반도체",
                       source="manual", confidence=1.0))
    s.commit()
    # 별칭 매칭
    assert resolve_concept(s, "HBM") == "segment:메모리반도체"
    # 정확 라벨 매칭(별칭 없어도)
    assert resolve_concept(s, "메모리반도체") == "segment:메모리반도체"
    # 미해소
    assert resolve_concept(s, "존재안함") is None
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_resolve.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.ontology.core.resolve'`

- [ ] **Step 3: resolve.py 구현**

`src/themek/ontology/core/resolve.py`:

```python
"""concept resolver + 멱등 upsert 헬퍼."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Node, Edge, ConceptAlias

_WS = re.compile(r"\s+")


def normalize_alias(s: str) -> str:
    """별칭/라벨 비교용 정규화: trim + 공백 단일화 + 소문자."""
    return _WS.sub(" ", s.strip()).lower()


def upsert_node(session: Session, id: str, kind: str, label: str,
                attrs: dict | None = None) -> Node:
    """id 기준 멱등 upsert. 존재하면 label/attrs 갱신."""
    node = session.get(Node, id)
    if node is None:
        node = Node(id=id, kind=kind, label=label, attrs=attrs or {})
        session.add(node)
    else:
        node.label = label
        if attrs is not None:
            node.attrs = attrs
    return node


def upsert_edge(session: Session, *, subject_id: str, predicate: str,
                object_id: str, period: str | None, qualifier: dict,
                source_type: str, source_ref: str | None, method: str,
                confidence: float) -> Edge:
    """(subject, predicate, object, period) 기준 멱등 upsert."""
    existing = session.execute(
        select(Edge).where(
            Edge.subject_id == subject_id, Edge.predicate == predicate,
            Edge.object_id == object_id,
            Edge.period.is_(period) if period is None else Edge.period == period,
        )
    ).scalars().first()
    if existing is None:
        edge = Edge(subject_id=subject_id, predicate=predicate,
                    object_id=object_id, period=period, qualifier=qualifier,
                    source_type=source_type, source_ref=source_ref,
                    method=method, confidence=confidence)
        session.add(edge)
        return edge
    existing.qualifier = qualifier
    existing.source_type = source_type
    existing.source_ref = source_ref
    existing.method = method
    existing.confidence = confidence
    return existing


def resolve_concept(session: Session, text: str) -> str | None:
    """text를 concept 노드 id로 해소: 별칭 → 정확 라벨 순. 미해소 None."""
    norm = normalize_alias(text)
    alias = session.get(ConceptAlias, norm)
    if alias is not None:
        return alias.node_id
    node = session.execute(
        select(Node).where(func_lower_label() == norm)
    ).scalars().first()
    return node.id if node is not None else None


def func_lower_label():
    from sqlalchemy import func
    return func.lower(Node.label)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_resolve.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/ontology/core/resolve.py tests/ontology/test_resolve.py
git commit -m "feat(ontology): concept resolver + idempotent node/edge upsert"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_resolve.py -q` → 4 passed. upsert 멱등(노드 라벨 갱신·엣지 트리플 dedupe), resolve_concept이 별칭→정확라벨 순으로 해소.

---

## Phase 2 — 적재 (재무 API · 사업구조 · 시드)

## Task 2.1: DART client `fetch_financials`

**Files:**
- Modify: `src/themek/dart/client.py`
- Create: `tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json`
- Test: `tests/test_dart_financials.py`

- [ ] **Step 1: 카세트 fixture 작성 (축약된 실제 응답 형태)**

`tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json`:

```json
{
  "status": "000",
  "message": "정상",
  "list": [
    {"rcept_no": "20250311000001", "bsns_year": "2024", "sj_div": "IS",
     "account_id": "ifrs-full_Revenue", "account_nm": "매출액",
     "thstrm_amount": "3007700000000", "frmtrm_amount": "2589400000000",
     "bfefrmtrm_amount": "3022300000000", "fs_div": "CFS"},
    {"rcept_no": "20250311000001", "bsns_year": "2024", "sj_div": "IS",
     "account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익",
     "thstrm_amount": "326700000000", "frmtrm_amount": "65700000000",
     "bfefrmtrm_amount": "433700000000", "fs_div": "CFS"},
    {"rcept_no": "20250311000001", "bsns_year": "2024", "sj_div": "IS",
     "account_id": "ifrs-full_ProfitLoss", "account_nm": "당기순이익",
     "thstrm_amount": "340000000000", "frmtrm_amount": "154000000000",
     "bfefrmtrm_amount": "556500000000", "fs_div": "CFS"},
    {"rcept_no": "20250311000001", "bsns_year": "2024", "sj_div": "BS",
     "account_id": "ifrs-full_Assets", "account_nm": "자산총계",
     "thstrm_amount": "5145000000000", "frmtrm_amount": "4559000000000",
     "bfefrmtrm_amount": "4266000000000", "fs_div": "CFS"},
    {"rcept_no": "20250311000001", "bsns_year": "2024", "sj_div": "BS",
     "account_id": "ifrs-full_Liabilities", "account_nm": "부채총계",
     "thstrm_amount": "1121000000000", "frmtrm_amount": "922000000000",
     "bfefrmtrm_amount": "936000000000", "fs_div": "CFS"},
    {"rcept_no": "20250311000001", "bsns_year": "2024", "sj_div": "BS",
     "account_id": "ifrs-full_Equity", "account_nm": "자본총계",
     "thstrm_amount": "4024000000000", "frmtrm_amount": "3637000000000",
     "bfefrmtrm_amount": "3330000000000", "fs_div": "CFS"}
  ]
}
```

- [ ] **Step 2: 테스트 작성 (httpx mock 주입)**

`tests/test_dart_financials.py`:

```python
"""DART fetch_financials 단위 테스트 (httpx transport mock)."""
import json
from pathlib import Path

import httpx

from themek.dart.client import DartClient, DartApiError

_CASSETTE = Path("tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json")


def _client_with(payload: dict, capture: dict | None = None) -> DartClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture["params"] = dict(request.url.params)
        return httpx.Response(200, json=payload)
    c = DartClient(api_key="dummy")
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_fetch_financials_returns_rows_and_passes_params():
    payload = json.loads(_CASSETTE.read_text(encoding="utf-8"))
    cap = {}
    c = _client_with(payload, cap)
    rows = c.fetch_financials(corp_code="00126380", bsns_year="2024",
                              reprt_code="11011", fs_div="CFS")
    assert len(rows) == 6
    assert cap["params"]["corp_code"] == "00126380"
    assert cap["params"]["reprt_code"] == "11011"
    assert cap["params"]["fs_div"] == "CFS"


def test_fetch_financials_empty_status_returns_empty():
    c = _client_with({"status": "013", "message": "조회된 데이타가 없습니다."})
    rows = c.fetch_financials(corp_code="00000000", bsns_year="2024",
                              reprt_code="11011", fs_div="CFS")
    assert rows == []
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/test_dart_financials.py -q`
Expected: FAIL — `AttributeError: 'DartClient' object has no attribute 'fetch_financials'`

- [ ] **Step 4: client에 fetch_financials 추가**

`src/themek/dart/client.py`의 `fetch_document_zip` 다음(클래스 내부)에 추가:

```python
    def fetch_financials(
        self, *, corp_code: str, bsns_year: str, reprt_code: str, fs_div: str,
    ) -> list[dict]:
        """단일회사 전체 재무제표(fnlttSinglAcntAll.json).

        status '013'(데이터 없음)은 빈 리스트로 정상 처리.
        """
        params = {
            "crtfc_key": self._key, "corp_code": corp_code,
            "bsns_year": bsns_year, "reprt_code": reprt_code, "fs_div": fs_div,
        }
        r = self._client.get(f"{self._base}/fnlttSinglAcntAll.json", params=params)
        self._raise_on_error(r)
        payload = r.json()
        status = payload.get("status")
        if status == "013":
            return []
        if status != "000":
            raise DartApiError(
                f"fnlttSinglAcntAll status={status} msg={payload.get('message')}")
        return payload.get("list", [])
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/test_dart_financials.py -q`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/themek/dart/client.py tests/test_dart_financials.py tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json
git commit -m "feat(dart): fetch_financials — fnlttSinglAcntAll.json endpoint"
```

✅ **Success Gate:** `uv run pytest tests/test_dart_financials.py -q` → 2 passed. 파라미터(corp_code/reprt_code/fs_div) 전달, 6행 파싱, status=013 빈 처리.

---

## Task 2.2: account→metric 매핑 + 행 파서

**Files:**
- Create: `src/themek/ontology/ingest/__init__.py`
- Create: `src/themek/ontology/ingest/financials.py` (파서 부분)
- Test: `tests/ontology/test_financials_parse.py`

- [ ] **Step 1: 파서 테스트 작성**

`tests/ontology/test_financials_parse.py`:

```python
"""재무 API 행 → (metric_key, 연도별 금액) 파싱 단위 테스트."""
import json
from pathlib import Path

from themek.ontology.ingest.financials import parse_financial_rows

_CASSETTE = Path("tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json")


def test_parse_maps_accounts_and_three_years():
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY")
    # 6개 metric × 3개년 = 18 fact
    assert len(facts) == 18
    rev_2024 = [f for f in facts if f["metric_key"] == "revenue"
                and f["bsns_year"] == "2024"]
    assert len(rev_2024) == 1
    assert rev_2024[0]["amount"] == 3007700000000.0
    # 전기/전전기 연도 라벨 = 2023/2022
    years = {f["bsns_year"] for f in facts if f["metric_key"] == "revenue"}
    assert years == {"2024", "2023", "2022"}


def test_parse_skips_unmapped_accounts():
    rows = [{"account_id": "ifrs-full_GrossProfit", "account_nm": "매출총이익",
             "thstrm_amount": "100", "frmtrm_amount": "90",
             "bfefrmtrm_amount": "80", "sj_div": "IS"}]
    assert parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY") == []


def test_parse_handles_blank_and_negative_amounts():
    rows = [{"account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익",
             "thstrm_amount": "-5,000", "frmtrm_amount": "",
             "bfefrmtrm_amount": "1,000", "sj_div": "IS"}]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY")
    by_year = {f["bsns_year"]: f["amount"] for f in facts}
    assert by_year["2024"] == -5000.0   # 음수·콤마 파싱
    assert "2023" not in by_year          # 빈 금액 스킵
    assert by_year["2022"] == 1000.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_financials_parse.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.ontology.ingest.financials'`

- [ ] **Step 3: 파서 구현**

```bash
printf '"""DART 재무 → 코어 적재."""\n' > src/themek/ontology/ingest/__init__.py
```

`src/themek/ontology/ingest/financials.py`:

```python
"""DART fnlttSinglAcntAll 응답 → financial_facts 적재.

응답 1행 = 한 계정의 3개년(당기/전기/전전기) 금액. account_id(IFRS 표준ID)
우선, account_nm fallback으로 KPI metric_key에 매핑한다.
"""
from __future__ import annotations

# account_id → metric_key (우선)
_ID_MAP = {
    "ifrs-full_Revenue": "revenue",
    "ifrs_Revenue": "revenue",
    "dart_OperatingIncomeLoss": "operating_income",
    "ifrs-full_ProfitLossFromOperatingActivities": "operating_income",
    "ifrs-full_ProfitLoss": "net_income",
    "ifrs-full_Assets": "assets",
    "ifrs-full_Liabilities": "liabilities",
    "ifrs-full_Equity": "equity",
}
# account_nm → metric_key (fallback)
_NM_MAP = {
    "매출액": "revenue", "수익(매출액)": "revenue", "영업수익": "revenue",
    "영업이익": "operating_income", "영업이익(손실)": "operating_income",
    "당기순이익": "net_income", "당기순이익(손실)": "net_income",
    "자산총계": "assets", "부채총계": "liabilities", "자본총계": "equity",
}


def _to_amount(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _metric_of(row: dict) -> str | None:
    key = _ID_MAP.get((row.get("account_id") or "").strip())
    if key:
        return key
    return _NM_MAP.get((row.get("account_nm") or "").strip())


def parse_financial_rows(rows: list[dict], *, bsns_year: str,
                         fiscal_period: str) -> list[dict]:
    """행들을 [{company-agnostic fact dict}] 로 평탄화. 3개년 전개."""
    yr = int(bsns_year)
    year_field = {
        "thstrm_amount": str(yr),
        "frmtrm_amount": str(yr - 1),
        "bfefrmtrm_amount": str(yr - 2),
    }
    facts: list[dict] = []
    for row in rows:
        metric = _metric_of(row)
        if metric is None:
            continue
        for field, year_label in year_field.items():
            amount = _to_amount(row.get(field))
            if amount is None:
                continue
            facts.append({
                "metric_key": metric, "bsns_year": year_label,
                "fiscal_period": fiscal_period, "amount": amount,
            })
    return facts
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_financials_parse.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/ontology/ingest/__init__.py src/themek/ontology/ingest/financials.py tests/ontology/test_financials_parse.py
git commit -m "feat(ontology): financial row parser — account→metric, 3-year expand"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_financials_parse.py -q` → 3 passed. account_id/nm 매핑, 3개년 전개, 콤마·음수·빈값 처리, 미매핑 스킵.

---

## Task 2.3: 재무 ingest 오케스트레이션 (facts + period/metric 노드)

**Files:**
- Modify: `src/themek/ontology/ingest/financials.py` (ingest 함수 추가)
- Test: `tests/ontology/test_financials_ingest.py`

- [ ] **Step 1: ingest 테스트 작성**

`tests/ontology/test_financials_ingest.py`:

```python
"""ingest_financials_for_company — facts upsert + 노드 보장 + fallback."""
import json
from pathlib import Path

from themek.ontology.core.models import Node, FinancialFact
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.financials import ingest_financials_for_company

_CASSETTE = Path("tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json")


class _FakeClient:
    """fetch_financials를 카세트로 대체. CFS 있으면 OFS 호출 안 됨을 추적."""
    def __init__(self, cfs_rows, ofs_rows=None):
        self.cfs_rows, self.ofs_rows = cfs_rows, ofs_rows or []
        self.calls = []

    def fetch_financials(self, *, corp_code, bsns_year, reprt_code, fs_div):
        self.calls.append(fs_div)
        return self.cfs_rows if fs_div == "CFS" else self.ofs_rows


def test_ingest_creates_facts_and_period_metric_nodes(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자"); s.commit()
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    client = _FakeClient(cfs_rows=rows)
    n = ingest_financials_for_company(
        s, client, corp_code="00126380", bsns_year="2024", reprt_code="11011")
    s.commit()
    assert n == 18
    facts = s.query(FinancialFact).filter_by(metric_key="operating_income",
                                             bsns_year="2024").all()
    assert len(facts) == 1
    assert facts[0].fs_div == "CFS"
    # period·metric 노드 보장
    assert s.get(Node, "period:2024FY") is not None
    assert s.get(Node, "metric:operating_income") is not None


def test_ingest_falls_back_to_ofs_when_cfs_empty(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00999999", "company", "단일법인"); s.commit()
    ofs = [{"account_id": "ifrs-full_Revenue", "account_nm": "매출액",
            "thstrm_amount": "100", "frmtrm_amount": "90",
            "bfefrmtrm_amount": "80", "sj_div": "IS"}]
    client = _FakeClient(cfs_rows=[], ofs_rows=ofs)
    n = ingest_financials_for_company(
        s, client, corp_code="00999999", bsns_year="2024", reprt_code="11011")
    s.commit()
    assert client.calls == ["CFS", "OFS"]   # CFS 비어서 OFS 시도
    assert n == 3
    assert s.query(FinancialFact).first().fs_div == "OFS"


def test_ingest_idempotent(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자"); s.commit()
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    client = _FakeClient(cfs_rows=rows)
    ingest_financials_for_company(s, client, corp_code="00126380",
                                  bsns_year="2024", reprt_code="11011"); s.commit()
    ingest_financials_for_company(s, client, corp_code="00126380",
                                  bsns_year="2024", reprt_code="11011"); s.commit()
    assert s.query(FinancialFact).count() == 18  # 중복 없음
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_financials_ingest.py -q`
Expected: FAIL — `ImportError: cannot import name 'ingest_financials_for_company'`

- [ ] **Step 3: ingest 함수 구현 (financials.py 끝에 append)**

```python
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from themek.ontology.core.ids import period_id, metric_id  # noqa: E402
from themek.ontology.core.models import FinancialFact, METRIC_KEYS  # noqa: E402
from themek.ontology.core.resolve import upsert_node  # noqa: E402

# reprt_code → fiscal_period 라벨
_REPRT_PERIOD = {"11011": "FY", "11012": "H1", "11013": "Q1", "11014": "Q3"}
_METRIC_LABEL = {
    "revenue": "매출액", "operating_income": "영업이익", "net_income": "당기순이익",
    "assets": "자산총계", "liabilities": "부채총계", "equity": "자본총계",
}


def _ensure_metric_nodes(session: Session) -> None:
    for key in METRIC_KEYS:
        upsert_node(session, metric_id(key), "metric", _METRIC_LABEL[key])


def _ensure_period_node(session: Session, bsns_year: str,
                        fiscal_period: str) -> None:
    upsert_node(session, period_id(bsns_year, fiscal_period), "period",
                f"{bsns_year} {fiscal_period}")


def _upsert_fact(session: Session, company_id: str, fs_div: str, f: dict) -> None:
    existing = session.execute(
        select(FinancialFact).where(
            FinancialFact.company_id == company_id,
            FinancialFact.bsns_year == f["bsns_year"],
            FinancialFact.fiscal_period == f["fiscal_period"],
            FinancialFact.fs_div == fs_div,
            FinancialFact.metric_key == f["metric_key"],
        )
    ).scalars().first()
    if existing is None:
        session.add(FinancialFact(
            company_id=company_id, bsns_year=f["bsns_year"],
            fiscal_period=f["fiscal_period"], fs_div=fs_div,
            metric_key=f["metric_key"], amount=f["amount"], currency="KRW",
            source_type="dart_api", source_ref=None, method="api", confidence=1.0))
    else:
        existing.amount = f["amount"]


def ingest_financials_for_company(session: Session, client, *, corp_code: str,
                                  bsns_year: str, reprt_code: str) -> int:
    """회사 1건 재무 적재. CFS→OFS fallback. 적재한 fact 수 반환."""
    from themek.ontology.core.ids import company_id as _cid
    fiscal_period = _REPRT_PERIOD[reprt_code]
    company_node_id = _cid(corp_code)

    rows = client.fetch_financials(corp_code=corp_code, bsns_year=bsns_year,
                                   reprt_code=reprt_code, fs_div="CFS")
    fs_div = "CFS"
    if not rows:
        rows = client.fetch_financials(corp_code=corp_code, bsns_year=bsns_year,
                                       reprt_code=reprt_code, fs_div="OFS")
        fs_div = "OFS"
    if not rows:
        return 0

    facts = parse_financial_rows(rows, bsns_year=bsns_year,
                                 fiscal_period=fiscal_period)
    if not facts:
        return 0

    _ensure_metric_nodes(session)
    periods_seen = {(f["bsns_year"], f["fiscal_period"]) for f in facts}
    for yr, fp in periods_seen:
        _ensure_period_node(session, yr, fp)
    for f in facts:
        _upsert_fact(session, company_node_id, fs_div, f)
    return len(facts)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_financials_ingest.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/ontology/ingest/financials.py tests/ontology/test_financials_ingest.py
git commit -m "feat(ontology): ingest_financials_for_company — facts + CFS/OFS fallback + nodes"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_financials_ingest.py -q` → 3 passed. facts 18건·period/metric 노드 보장, CFS 빈 시 OFS fallback, 멱등.

---

## Task 2.4: 사업구조 ingest (BusinessExtraction → nodes/edges)

**Files:**
- Create: `src/themek/ontology/ingest/business_structure.py`
- Test: `tests/ontology/test_business_structure_ingest.py`

- [ ] **Step 1: 테스트 작성**

`tests/ontology/test_business_structure_ingest.py`:

```python
"""BusinessExtraction → nodes/edges 적재 단위 테스트."""
from themek.llm.schemas import (
    BusinessExtraction, SegmentItem, CustomerItem, GeographicItem,
)
from themek.ontology.core.models import Node, Edge
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.business_structure import ingest_business_structure


def _extraction():
    return BusinessExtraction(
        period="2023",
        segments=[SegmentItem(name_ko="메모리반도체", share_pct=42.5),
                  SegmentItem(name_ko="DX 부문", share_pct=None)],
        customers=[CustomerItem(name_raw="Apple Inc.", revenue_share_pct=18.0,
                                tier="1차")],
        geographic=[GeographicItem(region_code="US", share_pct=35.0)],
    )


def test_ingest_creates_company_segment_customer_region_edges(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자")
    upsert_node(s, "region:US", "region", "미주")
    s.commit()
    ingest_business_structure(s, corp_code="00126380",
                              extraction=_extraction(), source_ref="r1")
    s.commit()
    # 세그먼트/고객 노드 생성
    assert s.get(Node, "segment:메모리반도체") is not None
    assert s.get(Node, "customer:apple-inc") is not None
    # HAS_SEGMENT 엣지 share_pct qualifier
    seg_edge = s.query(Edge).filter_by(predicate="HAS_SEGMENT",
                                       object_id="segment:메모리반도체").one()
    assert seg_edge.qualifier["share_pct"] == 42.5
    assert seg_edge.period == "2023"
    # SELLS_TO + EXPOSED_TO
    assert s.query(Edge).filter_by(predicate="SELLS_TO",
                                   object_id="customer:apple-inc").count() == 1
    assert s.query(Edge).filter_by(predicate="EXPOSED_TO",
                                   object_id="region:US").one().qualifier["share_pct"] == 35.0


def test_ingest_idempotent(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자")
    upsert_node(s, "region:US", "region", "미주")
    s.commit()
    for _ in range(2):
        ingest_business_structure(s, corp_code="00126380",
                                  extraction=_extraction(), source_ref="r1")
        s.commit()
    assert s.query(Edge).filter_by(predicate="HAS_SEGMENT").count() == 2  # 2 세그먼트
    assert s.query(Edge).filter_by(predicate="SELLS_TO").count() == 1
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_business_structure_ingest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.ontology.ingest.business_structure'`

- [ ] **Step 3: 구현**

`src/themek/ontology/ingest/business_structure.py`:

```python
"""LLM BusinessExtraction → 코어 nodes/edges 적재 (provenance method=llm)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from themek.llm.schemas import BusinessExtraction
from themek.ontology.core.ids import (
    company_id, segment_id, customer_id, region_id,
)
from themek.ontology.core.resolve import upsert_node, upsert_edge


def ingest_business_structure(session: Session, *, corp_code: str,
                              extraction: BusinessExtraction,
                              source_ref: str) -> None:
    """추출 결과를 HAS_SEGMENT/SELLS_TO/EXPOSED_TO 엣지로 적재. 멱등."""
    subj = company_id(corp_code)
    period = extraction.period

    def _edge(predicate, obj, qualifier, confidence=0.9):
        upsert_edge(session, subject_id=subj, predicate=predicate, object_id=obj,
                    period=period, qualifier=qualifier, source_type="llm",
                    source_ref=source_ref, method="llm", confidence=confidence)

    for seg in extraction.segments:
        oid = segment_id(seg.name_ko)
        upsert_node(session, oid, "segment", seg.name_ko)
        q = {} if seg.share_pct is None else {"share_pct": float(seg.share_pct)}
        _edge("HAS_SEGMENT", oid, q)

    for cust in extraction.customers:
        oid = customer_id(cust.name_raw)
        upsert_node(session, oid, "customer", cust.name_raw)
        q = {"tier": cust.tier}
        if cust.revenue_share_pct is not None:
            q["share_pct"] = float(cust.revenue_share_pct)
        _edge("SELLS_TO", oid, q)

    for geo in extraction.geographic:
        oid = region_id(geo.region_code)
        # region 노드는 시드에서 보장되지만, 없으면 코드 라벨로 생성
        if session.get_bind() is not None and session.get(  # type: ignore
                __import__("themek.ontology.core.models", fromlist=["Node"]).Node,
                oid) is None:
            upsert_node(session, oid, "region", geo.region_code)
        _edge("EXPOSED_TO", oid, {"share_pct": float(geo.share_pct)})
```

> 구현 노트: region 노드 보장 분기가 장황하다. 아래 단순화 버전으로 작성할 것:
>
> ```python
> from themek.ontology.core.models import Node
> ...
>     for geo in extraction.geographic:
>         oid = region_id(geo.region_code)
>         if session.get(Node, oid) is None:
>             upsert_node(session, oid, "region", geo.region_code)
>         _edge("EXPOSED_TO", oid, {"share_pct": float(geo.share_pct)})
> ```
> (상단 import에 `from themek.ontology.core.models import Node` 추가.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_business_structure_ingest.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/ontology/ingest/business_structure.py tests/ontology/test_business_structure_ingest.py
git commit -m "feat(ontology): ingest_business_structure — extraction to nodes/edges"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_business_structure_ingest.py -q` → 2 passed. company→segment/customer/region 엣지 생성, share_pct qualifier·period 보존, 멱등.

---

## Task 2.5: seeds 교체 (코어 노드) + IN_SECTOR/ISSUES_STOCK 엣지

**Files:**
- Create: `src/themek/ontology/ingest/seeds.py`
- Test: `tests/ontology/test_seeds.py`

> 기존 `src/themek/seeds.py`는 Phase 5에서 제거. 신규 코어 시드는 별도 파일로 둔다.

- [ ] **Step 1: 테스트 작성**

`tests/ontology/test_seeds.py`:

```python
"""코어 노드/엣지 시드 단위 테스트."""
from themek.ontology.core.models import Node, Edge
from themek.ontology.ingest.seeds import seed_core


def test_seed_core_creates_sector_region_company_stock_nodes(ontology_session):
    s = ontology_session
    seed_core(s)
    s.commit()
    assert s.get(Node, "sector:G2520").label == "반도체"
    assert s.get(Node, "region:US") is not None
    assert s.get(Node, "company:00126380").label == "삼성전자"
    assert s.get(Node, "stock:005930").attrs["market"] == "KOSPI"
    # IN_SECTOR / ISSUES_STOCK 엣지
    assert s.query(Edge).filter_by(predicate="IN_SECTOR",
                                   subject_id="company:00126380",
                                   object_id="sector:G2520").count() == 1
    assert s.query(Edge).filter_by(predicate="ISSUES_STOCK",
                                   subject_id="company:00126380",
                                   object_id="stock:005930").count() == 1


def test_seed_core_idempotent(ontology_session):
    s = ontology_session
    seed_core(s); s.commit()
    seed_core(s); s.commit()
    assert s.query(Node).filter_by(kind="company").count() == 3
    assert s.query(Edge).filter_by(predicate="IN_SECTOR").count() == 3
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_seeds.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.ontology.ingest.seeds'`

- [ ] **Step 3: 구현**

`src/themek/ontology/ingest/seeds.py`:

```python
"""코어 그래프 기본 시드 (sector·region·company·stock 노드 + 구조 엣지)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from themek.ontology.core.ids import company_id, stock_id, sector_id, region_id
from themek.ontology.core.resolve import upsert_node, upsert_edge

_SECTORS = [("G2520", "반도체"), ("G2570", "자동차 및 부품"), ("G2030", "산업기계")]
_REGIONS = [("KR", "국내"), ("US", "미주"), ("EU", "유럽"),
            ("CN", "중국"), ("JP", "일본"), ("ROW", "기타")]
_COMPANIES = [
    ("00126380", "삼성전자", "G2520", "005930", "KOSPI"),
    ("00164742", "현대자동차", "G2570", "005380", "KOSPI"),
    ("01261644", "레인보우로보틱스", "G2030", "277810", "KOSDAQ"),
]


def seed_core(session: Session) -> None:
    for fics, name in _SECTORS:
        upsert_node(session, sector_id(fics), "sector", name)
    for code, name in _REGIONS:
        upsert_node(session, region_id(code), "region", name)
    for dart, name, fics, ticker, market in _COMPANIES:
        cid, sid = company_id(dart), stock_id(ticker)
        upsert_node(session, cid, "company", name, {"dart_code": dart})
        upsert_node(session, sid, "stock", name,
                    {"ticker": ticker, "market": market})
        upsert_edge(session, subject_id=cid, predicate="IN_SECTOR",
                    object_id=sector_id(fics), period=None, qualifier={},
                    source_type="manual", source_ref=None, method="manual",
                    confidence=1.0)
        upsert_edge(session, subject_id=cid, predicate="ISSUES_STOCK",
                    object_id=sid, period=None, qualifier={},
                    source_type="manual", source_ref=None, method="manual",
                    confidence=1.0)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_seeds.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/ontology/ingest/seeds.py tests/ontology/test_seeds.py
git commit -m "feat(ontology): seed_core — sector/region/company/stock nodes + edges"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_seeds.py -q` → 2 passed. 노드 생성·IN_SECTOR/ISSUES_STOCK 엣지·멱등.

---

## Phase 3 — 투영 (vault · graph export)

## Task 3.1: vault projection (코어 → markdown, 재무 시계열 포함)

**Files:**
- Create: `src/themek/ontology/projection/__init__.py`
- Create: `src/themek/ontology/projection/vault.py`
- Test: `tests/ontology/test_projection_vault.py`

- [ ] **Step 1: 테스트 작성**

`tests/ontology/test_projection_vault.py`:

```python
"""코어 → vault markdown 투영 통합 + 멱등 + 재무 시계열 테스트."""
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.core.models import FinancialFact
from themek.ontology.projection.vault import build_vault


def _seed(s):
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380", "ticker": "005930", "market": "KOSPI"})
    upsert_node(s, "sector:G2520", "sector", "반도체")
    upsert_node(s, "segment:메모리반도체", "segment", "메모리반도체")
    upsert_node(s, "region:US", "region", "미주")
    upsert_node(s, "metric:operating_income", "metric", "영업이익")
    upsert_node(s, "period:2024FY", "period", "2024 FY")
    upsert_edge(s, subject_id="company:00126380", predicate="IN_SECTOR",
                object_id="sector:G2520", period=None, qualifier={},
                source_type="manual", source_ref=None, method="manual", confidence=1.0)
    upsert_edge(s, subject_id="company:00126380", predicate="HAS_SEGMENT",
                object_id="segment:메모리반도체", period="2023",
                qualifier={"share_pct": 42.5}, source_type="llm",
                source_ref="r1", method="llm", confidence=0.9)
    for metric, amount in [("revenue", 3007700000000.0),
                           ("operating_income", 326700000000.0),
                           ("equity", 4024000000000.0),
                           ("liabilities", 1121000000000.0)]:
        s.add(FinancialFact(company_id="company:00126380", bsns_year="2024",
                            fiscal_period="FY", fs_div="CFS", metric_key=metric,
                            amount=amount, currency="KRW", source_type="dart_api",
                            method="api", confidence=1.0))
    s.commit()


def test_build_vault_creates_company_note_with_financials(tmp_path, ontology_session):
    s = ontology_session
    _seed(s)
    stats = build_vault(s, tmp_path)
    assert stats["companies"] == 1
    note = (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8")
    assert "## 재무" in note
    assert "영업이익" in note
    # 파생비율: 영업이익률 = 326.7/3007.7 ≈ 10.9%
    assert "영업이익률" in note
    # Dataview 인라인 필드
    assert "operating_income_2024FY::" in note
    # 세그먼트 wikilink
    assert "[[메모리반도체]]" in note


def test_build_vault_idempotent(tmp_path, ontology_session):
    s = ontology_session
    _seed(s)
    build_vault(s, tmp_path)
    first = (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8")
    build_vault(s, tmp_path)
    assert (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8") == first
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_projection_vault.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.ontology.projection.vault'`

- [ ] **Step 3: 구현**

```bash
printf '"""코어 → 산출물 투영."""\n' > src/themek/ontology/projection/__init__.py
```

`src/themek/ontology/projection/vault.py`:

```python
"""코어(nodes/edges/financial_facts) → Obsidian vault markdown 투영.

회사 노트 = frontmatter + 섹터/세그먼트/고객/지역 wikilink + 재무 시계열 표
(+ 파생비율 + Dataview 인라인 필드). 생성 폴더만 비우고 재기록(멱등).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Node, Edge, FinancialFact

_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')
_WS = re.compile(r"\s+")
_FISCAL_ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}
_KPI_ORDER = ["revenue", "operating_income", "net_income",
              "assets", "liabilities", "equity"]
_KPI_LABEL = {"revenue": "매출액", "operating_income": "영업이익",
              "net_income": "당기순이익", "assets": "자산총계",
              "liabilities": "부채총계", "equity": "자본총계"}


def _safe(name: str) -> str:
    return _WS.sub(" ", _UNSAFE.sub(" ", name)).strip()


def _wikilink(label: str) -> str:
    return f"[[{_safe(label)}]]"


def _period_sort_key(year: str, fp: str) -> tuple[int, int]:
    return (int(year), _FISCAL_ORDER.get(fp, 0))


def _eok(amount: float) -> str:
    """원 → 억원 표기."""
    return f"{amount / 1e8:,.0f}억"


def _company_financials(session: Session, company_id: str) -> dict:
    """{(year,fp): {metric: amount}} (CFS 우선)."""
    rows = session.execute(
        select(FinancialFact).where(FinancialFact.company_id == company_id)
    ).scalars().all()
    out: dict[tuple[str, str], dict[str, float]] = {}
    for r in rows:
        # CFS 우선: 같은 (period, metric)에 OFS는 CFS 없을 때만
        key = (r.bsns_year, r.fiscal_period)
        cur = out.setdefault(key, {})
        if r.metric_key not in cur or r.fs_div == "CFS":
            cur[r.metric_key] = float(r.amount)
    return out


def _render_financials(fin: dict) -> list[str]:
    if not fin:
        return []
    periods = sorted(fin.keys(), key=lambda k: _period_sort_key(*k))
    header = "| 지표 | " + " | ".join(f"{y} {fp}" for y, fp in periods) + " |"
    sep = "|------|" + "------|" * len(periods)
    lines = ["\n## 재무 (연결 우선, 단위 억원)\n", header, sep]
    for key in _KPI_ORDER:
        if not any(key in fin[p] for p in periods):
            continue
        cells = [(_eok(fin[p][key]) if key in fin[p] else "—") for p in periods]
        lines.append(f"| {_KPI_LABEL[key]} | " + " | ".join(cells) + " |")
    # 파생비율
    ratio_rows = []
    for p in periods:
        d = fin[p]
        if "operating_income" in d and d.get("revenue"):
            opm = d["operating_income"] / d["revenue"] * 100
        else:
            opm = None
        if "liabilities" in d and d.get("equity"):
            der = d["liabilities"] / d["equity"] * 100
        else:
            der = None
        if "net_income" in d and d.get("equity"):
            roe = d["net_income"] / d["equity"] * 100
        else:
            roe = None
        ratio_rows.append((opm, der, roe))
    def _fmt(v):
        return f"{v:.1f}%" if v is not None else "—"
    lines.append("| 영업이익률 | " + " | ".join(_fmt(r[0]) for r in ratio_rows) + " |")
    lines.append("| 부채비율 | " + " | ".join(_fmt(r[1]) for r in ratio_rows) + " |")
    lines.append("| ROE | " + " | ".join(_fmt(r[2]) for r in ratio_rows) + " |")
    # Dataview 인라인 필드
    lines.append("")
    for (y, fp) in periods:
        for key in _KPI_ORDER:
            if key in fin[(y, fp)]:
                lines.append(f"{key}_{y}{fp}:: {fin[(y, fp)][key]:.0f}")
    return lines


def _company_label(node: Node) -> str:
    return node.label


def build_vault(session: Session, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    companies = session.execute(
        select(Node).where(Node.kind == "company").order_by(Node.label)
    ).scalars().all()

    out_dir.mkdir(parents=True, exist_ok=True)
    cdir = out_dir / "companies"
    if cdir.exists():
        shutil.rmtree(cdir)
    cdir.mkdir(parents=True)

    for c in companies:
        edges = session.execute(
            select(Edge).where(Edge.subject_id == c.id)
        ).scalars().all()
        seg = [e for e in edges if e.predicate == "HAS_SEGMENT"]
        cust = [e for e in edges if e.predicate == "SELLS_TO"]
        reg = [e for e in edges if e.predicate == "EXPOSED_TO"]
        sector = next((e for e in edges if e.predicate == "IN_SECTOR"), None)

        def _label(node_id):
            n = session.get(Node, node_id)
            return n.label if n else node_id

        parts = [
            "---", 'type: "company"',
            f'dart_code: "{c.attrs.get("dart_code", "")}"',
            f'name: "{c.label}"', "tags: [company]", "---",
            f"# {c.label}\n",
        ]
        if sector:
            parts.append(f"> 섹터: {_wikilink(_label(sector.object_id))}\n")
        parts.append("\n## 세그먼트\n")
        for e in seg:
            sp = e.qualifier.get("share_pct")
            suffix = f" — {sp:g}%" if sp is not None else ""
            parts.append(f"- {_wikilink(_label(e.object_id))}{suffix}")
        parts.append("\n## 고객사\n")
        for e in cust:
            parts.append(f"- {_wikilink(_label(e.object_id))}")
        parts.append("\n## 지역 노출\n")
        for e in reg:
            sp = e.qualifier.get("share_pct")
            suffix = f" — {sp:g}%" if sp is not None else ""
            parts.append(f"- {_wikilink(_label(e.object_id))}{suffix}")

        parts += _render_financials(_company_financials(session, c.id))

        text = "\n".join(parts) + "\n"
        (cdir / f"{_safe(c.label)}.md").write_text(text, encoding="utf-8")

    return {"companies": len(companies)}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_projection_vault.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/ontology/projection tests/ontology/test_projection_vault.py
git commit -m "feat(ontology): vault projection from core with financial timeseries"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_projection_vault.py -q` → 2 passed. 회사 노트에 재무 시계열 표 + 파생비율(영업이익률 등) + Dataview 필드 + 세그먼트 wikilink, 멱등.

---

## Task 3.2: graph export (nodes.json / edges.json)

**Files:**
- Create: `src/themek/ontology/projection/graph_export.py`
- Test: `tests/ontology/test_graph_export.py`

- [ ] **Step 1: 테스트 작성**

`tests/ontology/test_graph_export.py`:

```python
"""graph export — nodes.json/edges.json + financial_facts measurement 엣지."""
import json

from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.core.models import FinancialFact
from themek.ontology.projection.graph_export import export_graph


def _seed(s):
    upsert_node(s, "company:00126380", "company", "삼성전자")
    upsert_node(s, "segment:메모리반도체", "segment", "메모리반도체")
    upsert_node(s, "metric:operating_income", "metric", "영업이익")
    upsert_node(s, "period:2024FY", "period", "2024 FY")
    upsert_edge(s, subject_id="company:00126380", predicate="HAS_SEGMENT",
                object_id="segment:메모리반도체", period="2023",
                qualifier={"share_pct": 42.5}, source_type="llm",
                source_ref="r1", method="llm", confidence=0.9)
    s.add(FinancialFact(company_id="company:00126380", bsns_year="2024",
                        fiscal_period="FY", fs_div="CFS",
                        metric_key="operating_income", amount=326700000000.0,
                        currency="KRW", source_type="dart_api", method="api",
                        confidence=1.0))
    s.commit()


def test_export_graph_writes_nodes_and_edges(tmp_path, ontology_session):
    s = ontology_session
    _seed(s)
    export_graph(s, tmp_path)
    nodes = json.loads((tmp_path / "nodes.json").read_text(encoding="utf-8"))
    edges = json.loads((tmp_path / "edges.json").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in nodes}
    assert "company:00126380" in node_ids and "metric:operating_income" in node_ids
    # HAS_SEGMENT 엣지 + financial measurement 엣지(REPORTS)
    preds = {e["predicate"] for e in edges}
    assert "HAS_SEGMENT" in preds and "REPORTS" in preds
    # 깨진 참조 없음: 모든 엣지 endpoint가 노드에 존재
    for e in edges:
        assert e["subject_id"] in node_ids
        assert e["object_id"] in node_ids


def test_financial_measurement_edge_carries_amount(tmp_path, ontology_session):
    s = ontology_session
    _seed(s)
    export_graph(s, tmp_path)
    edges = json.loads((tmp_path / "edges.json").read_text(encoding="utf-8"))
    rep = [e for e in edges if e["predicate"] == "REPORTS"][0]
    assert rep["object_id"] == "metric:operating_income"
    assert rep["qualifier"]["amount"] == 326700000000.0
    assert rep["qualifier"]["fs_div"] == "CFS"
    assert rep["period"] == "2024FY"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_graph_export.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`src/themek/ontology/projection/graph_export.py`:

```python
"""코어 → nodes.json / edges.json. financial_facts는 REPORTS measurement 엣지로 투영.

graph-readiness 증명용 export (Neo4j/RDF import 가능 형태). 멱등.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.ids import metric_id, period_id
from themek.ontology.core.models import Node, Edge, FinancialFact


def export_graph(session: Session, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    nodes = [
        {"id": n.id, "kind": n.kind, "label": n.label, "attrs": n.attrs}
        for n in session.execute(select(Node).order_by(Node.id)).scalars().all()
    ]
    edges = [
        {"subject_id": e.subject_id, "predicate": e.predicate,
         "object_id": e.object_id, "period": e.period, "qualifier": e.qualifier,
         "source_type": e.source_type, "confidence": e.confidence}
        for e in session.execute(select(Edge).order_by(Edge.id)).scalars().all()
    ]
    # financial_facts → REPORTS measurement 엣지 (company → metric)
    for f in session.execute(
        select(FinancialFact).order_by(FinancialFact.id)
    ).scalars().all():
        edges.append({
            "subject_id": f.company_id, "predicate": "REPORTS",
            "object_id": metric_id(f.metric_key),
            "period": f"{f.bsns_year}{f.fiscal_period}",
            "qualifier": {"amount": float(f.amount), "fs_div": f.fs_div,
                          "metric": f.metric_key,
                          "period_node": period_id(f.bsns_year, f.fiscal_period)},
            "source_type": f.source_type, "confidence": f.confidence,
        })

    (out_dir / "nodes.json").write_text(
        json.dumps(nodes, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "edges.json").write_text(
        json.dumps(edges, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"nodes": len(nodes), "edges": len(edges)}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_graph_export.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/ontology/projection/graph_export.py tests/ontology/test_graph_export.py
git commit -m "feat(ontology): graph export — nodes/edges json + REPORTS measurement edges"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_graph_export.py -q` → 2 passed. nodes/edges.json 생성, financial measurement 엣지(REPORTS, amount/fs_div/period), 깨진 참조 0.

---

## Phase 4 — competency-query

## Task 4.1: screen.py — 세그먼트·주력·연속흑자

**Files:**
- Create: `src/themek/ontology/query/__init__.py`
- Create: `src/themek/ontology/query/screen.py`
- Test: `tests/ontology/test_screen.py`

- [ ] **Step 1: 테스트 작성**

`tests/ontology/test_screen.py`:

```python
"""competency 스크리닝 함수 단위 테스트 (예시질의 end-to-end 포함)."""
from themek.ontology.core.models import FinancialFact, ConceptAlias
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.query.screen import (
    companies_with_segment_concept, primary_segment,
    consecutive_positive, screen,
)


def _company(s, dart, name):
    upsert_node(s, f"company:{dart}", "company", name, {"dart_code": dart})


def _seg(s, name):
    upsert_node(s, f"segment:{__import__('themek.ontology.core.ids', fromlist=['slug']).slug(name)}",
                "segment", name)


def _has_seg(s, dart, seg_node, share, period="2024"):
    upsert_edge(s, subject_id=f"company:{dart}", predicate="HAS_SEGMENT",
                object_id=seg_node, period=period, qualifier={"share_pct": share},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)


def _oi(s, dart, year, fp, amount):
    s.add(FinancialFact(company_id=f"company:{dart}", bsns_year=year,
                        fiscal_period=fp, fs_div="CFS",
                        metric_key="operating_income", amount=amount,
                        currency="KRW", source_type="dart_api", method="api",
                        confidence=1.0))


def _seed_hbm(s):
    from themek.ontology.core.ids import segment_id
    mem = segment_id("메모리반도체")
    _seg(s, "메모리반도체")
    s.add(ConceptAlias(alias_norm="hbm", node_id=mem, source="manual", confidence=1.0))
    # A: 메모리 주력(60%) + 2024H1·Q3·FY 흑자 → 통과
    _company(s, "00000001", "흑자메모리")
    _has_seg(s, "00000001", mem, 60.0)
    for fp, amt in [("H1", 10), ("Q3", 20), ("FY", 30)]:
        _oi(s, "00000001", "2024", fp, amt)
    # B: 메모리 주력이지만 2024H1 적자 → 탈락
    _company(s, "00000002", "적자메모리")
    _has_seg(s, "00000002", mem, 70.0)
    for fp, amt in [("H1", -5), ("Q3", 5), ("FY", 10)]:
        _oi(s, "00000002", "2024", fp, amt)
    # C: 메모리 있지만 주력 아님(자동차 80%) → companies_with_segment엔 들지만 primary 아님
    _company(s, "00000003", "비주력메모리")
    auto = segment_id("자동차")
    _seg(s, "자동차")
    _has_seg(s, "00000003", mem, 20.0)
    _has_seg(s, "00000003", auto, 80.0)
    for fp, amt in [("H1", 10), ("Q3", 10), ("FY", 10)]:
        _oi(s, "00000003", "2024", fp, amt)
    s.commit()


def test_companies_with_segment_concept_resolves_alias(ontology_session):
    s = ontology_session
    _seed_hbm(s)
    ids = companies_with_segment_concept(s, "HBM")
    assert ids == {"company:00000001", "company:00000002", "company:00000003"}


def test_primary_segment_is_max_share(ontology_session):
    s = ontology_session
    _seed_hbm(s)
    from themek.ontology.core.ids import segment_id
    assert primary_segment(s, "company:00000001", "2024") == segment_id("메모리반도체")
    assert primary_segment(s, "company:00000003", "2024") == segment_id("자동차")


def test_consecutive_positive_since(ontology_session):
    s = ontology_session
    _seed_hbm(s)
    ids = consecutive_positive(s, "operating_income", "2024H1", "CFS")
    assert "company:00000001" in ids
    assert "company:00000002" not in ids   # 2024H1 적자


def test_screen_example_query_hbm_primary_positive_since_2024H1(ontology_session):
    s = ontology_session
    _seed_hbm(s)
    # 예시질의: HBM 주력 + 영업이익 2024H1부터 연속 흑자
    result = screen(s, segment="HBM", metric="operating_income",
                    positive_since="2024H1", fs_div="CFS")
    # A만 통과 (B 적자, C 메모리 비주력)
    assert result == {"company:00000001"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_screen.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.ontology.query.screen'`

- [ ] **Step 3: 구현**

```bash
printf '"""competency-query 레이어."""\n' > src/themek/ontology/query/__init__.py
```

`src/themek/ontology/query/screen.py`:

```python
"""competency 스크리닝: 세그먼트 개념 · 주력 세그먼트 · 연속 흑자 · 조합.

서비스가 의존하는 안정 계약. period 비교는 (연도, 분기순서) 키로 한다.
"""
from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from themek.ontology.core.models import Edge, FinancialFact
from themek.ontology.core.resolve import resolve_concept

_FISCAL_ORDER = {"Q1": 1, "H1": 2, "Q3": 3, "FY": 4}


def _period_key(year: str, fp: str) -> tuple[int, int]:
    return (int(year), _FISCAL_ORDER.get(fp, 0))


def _parse_period(label: str) -> tuple[str, str]:
    """'2024H1' → ('2024','H1')."""
    return label[:4], label[4:]


def companies_with_segment_concept(session: Session, concept: str) -> set[str]:
    """concept(별칭/라벨)에 해소되는 세그먼트를 가진 회사 id 집합."""
    seg_id = resolve_concept(session, concept)
    if seg_id is None:
        return set()
    rows = session.execute(
        select(Edge.subject_id).where(Edge.predicate == "HAS_SEGMENT",
                                      Edge.object_id == seg_id)
    ).scalars().all()
    return set(rows)


def primary_segment(session: Session, company_id: str,
                    period: str) -> str | None:
    """해당 회사/기간 share_pct 최대 HAS_SEGMENT object_id (주력)."""
    rows = session.execute(
        select(Edge.object_id, Edge.qualifier).where(
            Edge.predicate == "HAS_SEGMENT", Edge.subject_id == company_id,
            Edge.period == period)
    ).all()
    best, best_share = None, float("-inf")
    for obj_id, qual in rows:
        share = (qual or {}).get("share_pct")
        if share is not None and share > best_share:
            best, best_share = obj_id, share
    return best


def consecutive_positive(session: Session, metric_key: str,
                         since_period: str, fs_div: str) -> set[str]:
    """since_period(포함) 이후 기록된 모든 기간이 양수인 회사 id 집합.

    정의: period_key >= since 인 fact가 ≥1개 존재하고, 그 중 최소 amount > 0.
    (기간 연속성/누락은 deferred — 기록된 기간 기준.)
    """
    since = _period_key(*_parse_period(since_period))
    rows = session.execute(
        select(FinancialFact.company_id, FinancialFact.bsns_year,
               FinancialFact.fiscal_period, FinancialFact.amount).where(
            FinancialFact.metric_key == metric_key,
            FinancialFact.fs_div == fs_div)
    ).all()
    agg: dict[str, list[float]] = {}
    for company_id, year, fp, amount in rows:
        if _period_key(year, fp) >= since:
            agg.setdefault(company_id, []).append(float(amount))
    return {cid for cid, amts in agg.items() if amts and min(amts) > 0}


def screen(session: Session, *, segment: str, metric: str,
           positive_since: str, fs_div: str = "CFS") -> set[str]:
    """예시질의: segment가 '주력'이면서 metric이 positive_since부터 연속 양수."""
    seg_id = resolve_concept(session, segment)
    if seg_id is None:
        return set()
    period_year_fp = _parse_period(positive_since)
    # 주력 판정 기간 = positive_since 가 속한 연도의 FY (연 단위 주력)
    primary_period = period_year_fp[0]  # 주력은 연도 기준 HAS_SEGMENT.period
    candidates = companies_with_segment_concept(session, segment)
    primary_ok = {
        cid for cid in candidates
        if primary_segment(session, cid, primary_period) == seg_id
    }
    positive = consecutive_positive(session, metric, positive_since, fs_div)
    return primary_ok & positive
```

> 구현 노트: 테스트 시드는 HAS_SEGMENT.period="2024", positive_since="2024H1" → `primary_period="2024"` 로 일치. 실제 사업구조 엣지 period는 연(예 "2024"), 재무 fiscal_period는 분기/반기를 쓰므로 주력은 연 단위로 본다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_screen.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/ontology/query tests/ontology/test_screen.py
git commit -m "feat(ontology): competency screen — segment/primary/consecutive-positive"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_screen.py -q` → 4 passed. 예시질의("HBM 주력 + 2024H1부터 연속 흑자")가 정답 회사만 반환(B 적자·C 비주력 제외).

---

## Task 4.2: CLI 배선 — `ingest financials` · `query screen` · `ontology export-graph` · vault build 재배선

**Files:**
- Modify: `src/themek/cli.py`
- Test: `tests/ontology/test_cli_ontology.py`

- [ ] **Step 1: CLI 통합 테스트 작성**

`tests/ontology/test_cli_ontology.py`:

```python
"""CLI: query screen 통합 (시드 후 실행)."""
from typer.testing import CliRunner

from themek.cli import app
from themek.db.engine import make_engine, make_session_factory
from themek.ontology.core.models import FinancialFact, ConceptAlias
from themek.ontology.core.ids import segment_id
from themek.ontology.core.resolve import upsert_node, upsert_edge

runner = CliRunner()


def _seed_committed():
    s = make_session_factory(make_engine())()
    mem = segment_id("메모리반도체")
    upsert_node(s, mem, "segment", "메모리반도체")
    s.add(ConceptAlias(alias_norm="hbm", node_id=mem, source="manual", confidence=1.0))
    upsert_node(s, "company:00000001", "company", "흑자메모리", {"dart_code": "00000001"})
    upsert_edge(s, subject_id="company:00000001", predicate="HAS_SEGMENT",
                object_id=mem, period="2024", qualifier={"share_pct": 60.0},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    for fp, amt in [("H1", 10), ("Q3", 20), ("FY", 30)]:
        s.add(FinancialFact(company_id="company:00000001", bsns_year="2024",
                            fiscal_period=fp, fs_div="CFS",
                            metric_key="operating_income", amount=amt,
                            currency="KRW", source_type="dart_api", method="api",
                            confidence=1.0))
    s.commit(); s.close()


def test_query_screen_cli(ontology_fresh_db):
    _seed_committed()
    result = runner.invoke(app, ["query", "screen", "--segment", "HBM",
                                 "--metric", "operating_income",
                                 "--positive-since", "2024H1"])
    assert result.exit_code == 0, result.output
    assert "흑자메모리" in result.output or "company:00000001" in result.output
```

- [ ] **Step 2: conftest에 ontology_fresh_db fixture 추가**

`tests/conftest.py` 끝에 append:

```python
@pytest.fixture
def ontology_fresh_db(engine):
    """CLI 온톨로지 테스트용: 코어 테이블 reset(커밋 가시)."""
    import themek.ontology.core.models  # noqa: F401
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_cli_ontology.py -q`
Expected: FAIL — `query screen` 명령 없음 → exit_code != 0

- [ ] **Step 4: cli.py에 명령 추가**

`src/themek/cli.py` 상단 import 블록에 추가:

```python
from themek.ontology.query.screen import screen as _screen
from themek.ontology.ingest.financials import ingest_financials_for_company
from themek.ontology.projection.graph_export import export_graph
from themek.ontology.core.models import Node
```

서브앱 등록부(기존 `vault_app` 줄 다음)에 추가:

```python
ingest_app = typer.Typer(help="온톨로지 적재 명령")
app.add_typer(ingest_app, name="ingest")
ontology_app = typer.Typer(help="온톨로지 export 명령")
app.add_typer(ontology_app, name="ontology")
```

cli.py 끝부분(모듈 레벨)에 명령 추가:

```python
@query_app.command("screen")
def query_screen_cmd(
    segment: str = typer.Option(..., "--segment", help="세그먼트 개념(별칭/라벨)"),
    metric: str = typer.Option("operating_income", "--metric"),
    positive_since: str = typer.Option(..., "--positive-since",
                                       help="예: 2024H1"),
    fs_div: str = typer.Option("CFS", "--fs-div"),
):
    """'주력 세그먼트 + 특정 기간부터 연속 흑자' 스크리닝."""
    with _session() as s:
        ids = _screen(s, segment=segment, metric=metric,
                      positive_since=positive_since, fs_div=fs_div)
        for cid in sorted(ids):
            node = s.get(Node, cid)
            typer.echo(f"{cid}\t{node.label if node else ''}")
    typer.echo(f"matched: {len(ids)}")


@ingest_app.command("financials")
def ingest_financials_cmd(
    years: str = typer.Option(..., "--years", help="예: 2022-2024 또는 2024"),
    corp: Optional[str] = typer.Option(None, "--corp", help="단일 corp_code"),
):
    """DART 정형 재무를 코어에 적재 (회사별 4 reprt_code)."""
    if "-" in years:
        lo, hi = years.split("-", 1)
        year_list = [str(y) for y in range(int(lo), int(hi) + 1)]
    else:
        year_list = [years]
    client = DartClient(api_key=get_settings().dart_api_key)
    reprt_codes = ["11011", "11012", "11013", "11014"]
    total = 0
    with _session() as s:
        if corp:
            corp_codes = [corp]
        else:
            corp_codes = [
                n.attrs.get("dart_code")
                for n in s.execute(
                    select(Node).where(Node.kind == "company")
                ).scalars().all()
                if n.attrs.get("dart_code")
            ]
        for code in corp_codes:
            for yr in year_list:
                for rc in reprt_codes:
                    total += ingest_financials_for_company(
                        s, client, corp_code=code, bsns_year=yr, reprt_code=rc)
        s.commit()
    typer.echo(f"ingested {total} financial facts")


@ontology_app.command("export-graph")
def ontology_export_graph_cmd(
    out: str = typer.Option("graph", "--out", help="graph export 디렉토리"),
):
    """코어를 nodes.json/edges.json으로 export."""
    with _session() as s:
        stats = export_graph(s, Path(out))
    typer.echo(f"graph exported: {stats['nodes']} nodes, {stats['edges']} edges → {out}/")
```

> 구현 노트: `get_settings().dart_api_key` 속성명은 기존 코드(`themek.config`)와 일치시킬 것. 기존 DartClient 생성부(다른 dart 명령)를 참고해 동일 방식으로 키를 읽는다.

- [ ] **Step 5: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_cli_ontology.py -q`
Expected: PASS (1 passed)

- [ ] **Step 6: Commit**

```bash
git add src/themek/cli.py tests/ontology/test_cli_ontology.py tests/conftest.py
git commit -m "feat(cli): query screen + ingest financials + ontology export-graph"
```

✅ **Success Gate:** `uv run pytest tests/ontology/test_cli_ontology.py -q` → 1 passed. `themek query screen --segment HBM --metric operating_income --positive-since 2024H1` exit 0 + 정답 회사 출력.

---

## Phase 5 — cutover (구 모듈 제거 · vault build 재배선 · 실 재적재)

## Task 5.1: 기존 ingest/vault build 경로를 코어로 재배선 + 구 모듈/테스트 제거

**Files:**
- Modify: `src/themek/cli.py` (vault build → 코어 projection, dart 적재 → business_structure)
- Modify: `src/themek/dart/incremental.py`, `src/themek/ingest/business_report.py` 호출부 (코어 ingest 사용)
- Delete: `src/themek/db/models.py`(구 ORM), `src/themek/vault/`, `src/themek/query/e5.py`, `src/themek/query/synthesize.py`, `src/themek/seeds.py`, `src/themek/eval/e5.py`
- Delete tests: `tests/test_vault_*.py`, `tests/test_cli_vault.py`, `tests/test_query_e5*.py`, `tests/test_synthesize*.py`, `tests/test_ingest_business_report*.py`, `tests/test_eval_e5*.py`, `tests/test_seeds*.py`

> ⚠️ 이 태스크는 광범위 삭제·재배선이다. **discovery 먼저**: 아래 명령으로 구 모델/모듈 참조를 전수 조사한 뒤 순서대로 처리한다.

- [ ] **Step 1: 구 모델/모듈 참조 전수 조사**

```bash
grep -rn "from themek.db.models import\|themek.vault\|query.e5\|query_e5\|ingest.business_report\|ingest_business_report\|themek.seeds\|seed_basic\|eval.e5\|synthesize" src/ tests/ | grep -v "ontology/" > /tmp/old_refs.txt
wc -l /tmp/old_refs.txt && cat /tmp/old_refs.txt
```
Expected: 참조 목록 출력. 각 참조를 코어 대체(아래)로 바꾸거나, 해당 명령/테스트를 제거 대상으로 분류.

- [ ] **Step 2: `themek dart ...` 적재 경로를 business_structure로 재배선**

`src/themek/ingest/business_report.py`의 `ingest_business_report`가 구 모델에 쓰던 부분을, 추출 후 `ingest_business_structure(session, corp_code=..., extraction=..., source_ref=rcept_no)` 호출 + 재무는 별도 명령으로 분리한다. 회사 노드는 `upsert_node(company_id(corp_code), "company", name, {"dart_code": corp_code})`로 보장. BusinessReport 메타(rcept_no/period/filing)는 provenance(`source_ref=rcept_no`)로 엣지에 부착되므로 별도 테이블 불필요.

구체 편집: `ingest_business_report`를 다음 시그니처 유지하되 본문을 코어 적재로 교체:

```python
from themek.ontology.core.ids import company_id
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.business_structure import ingest_business_structure

def ingest_business_report(session, *, dart_rcept_no, corporation_id,
                           report_type, period, filing_date, raw_text_excerpt,
                           url=None, escalation_level=None, extractor=None):
    if extractor is None:
        extractor = _make_default_extractor(escalation_level)
    extraction = extractor(raw_text_excerpt, period)
    upsert_node(session, company_id(corporation_id), "company", corporation_id,
                {"dart_code": corporation_id})
    ingest_business_structure(session, corp_code=corporation_id,
                              extraction=extraction, source_ref=dart_rcept_no)
```

(회사명 라벨은 corp_lookup에서 보강되거나, 후속 재적재 시 seed/lookup이 채운다. 멱등 upsert이므로 라벨은 추후 갱신 가능.)

- [ ] **Step 3: `themek vault build`를 코어 projection으로 재배선**

`src/themek/cli.py`의 `vault_build_cmd`에서 `from themek.vault.builder import build_vault`를 `from themek.ontology.projection.vault import build_vault`로 교체. 출력 문구는 `build_vault`가 반환하는 `{"companies": n}`에 맞춰 단순화:

```python
@vault_app.command("build")
def vault_build_cmd(out: str = typer.Option("vault", "--out"),
                    db: Optional[str] = typer.Option(None, "--db")):
    """코어 온톨로지를 Obsidian vault로 멱등 생성."""
    session = make_session_factory(create_engine_for(db))() if db else _session()
    with session as s:
        stats = build_vault(s, Path(out))
    typer.echo(f"vault built: {stats['companies']} companies → {out}/")
```
(상단 import에서 `from themek.vault.builder import build_vault` 제거, `from themek.ontology.projection.vault import build_vault` 추가. `create_engine_for`는 기존 db override 로직을 인라인 유지해도 됨.)

- [ ] **Step 4: `themek seed`를 seed_core로 재배선**

`src/themek/cli.py`의 `seed` 명령: `from themek.seeds import seed_basic` → `from themek.ontology.ingest.seeds import seed_core`; 본문 `seed_basic(s)` → `seed_core(s)`; echo 문구 수정.

- [ ] **Step 5: 구 모듈 + 구 테스트 삭제**

```bash
git rm src/themek/vault -r src/themek/query/e5.py src/themek/seeds.py
git rm src/themek/db/models.py
# synthesize/eval/e5가 e5에만 의존하면 함께 제거 (Step1 조사 결과에 따름)
git rm tests/test_vault_model.py tests/test_vault_qa.py tests/test_vault_render.py \
       tests/test_vault_builder.py tests/test_cli_vault.py
# Step1에서 발견된 구 모델 의존 테스트 추가 제거 (query_e5/ingest_business_report/seeds/eval 등)
```

> ⚠️ `tests/conftest.py`의 `import themek.db.models` 라인을 `import themek.ontology.core.models`로 교체(구 모델 제거로 import 에러 방지). `db_session`/`fresh_db` fixture는 코어 테이블 기준으로 동작하게 유지.

- [ ] **Step 6: 전체 스위트 회귀 확인 + 잔존 참조 0 확인**

Run:
```bash
grep -rn "themek.db.models\|themek.vault\|query_e5\|seed_basic" src/ tests/ | grep -v "ontology/" | grep -v "core/models"
uv run pytest -q
```
Expected: grep 출력 0줄. pytest 전체 PASS(삭제된 구 테스트 제외, 신규 ontology 테스트 포함), 실패 0.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(ontology): cutover ingest/vault/seed to core; remove legacy models/modules"
```

✅ **Success Gate (측정 가능):**
1. `grep -rn "themek.db.models\|themek.vault\|query_e5\|seed_basic" src/ tests/ | grep -v "ontology/" | grep -v "core/models" | wc -l` → `0`.
2. `uv run pytest -q` → 실패 0 (구 테스트 제거 후 ontology 신규 테스트 포함 전체 PASS).
3. `uv run themek --help` → exit 0 이고 stdout에 `ingest`·`query`·`vault`·`ontology` 서브커맨드 모두 노출.
4. `uv run python -c "import themek.cli"` → exit 0 (구 모델 import 잔존 시 ImportError로 실패).

---

## Task 5.2: 실 DART 재적재 + 예시질의 end-to-end 검증 + 문서

**Files:**
- Create: `docs/ontology-core-smoke-notes.md`
- Modify: `README.md`

- [ ] **Step 1: 코어 초기화 + 시드 + 사업구조 재적재**

기존 themek.db를 백업 후 코어 스키마로 재생성하고, 시드 + (가능 시) 기존 백필 대상 재적재:
```bash
cp themek.db themek.db.pre-core.bak
uv run python -c "from themek.db.engine import Base, make_engine; import themek.ontology.core.models; Base.metadata.create_all(make_engine())"
uv run themek seed
```
(사업구조 재적재는 기존 `themek dart` 백필 명령으로 수행 — 구체 명령은 README의 백필 절차를 따른다.)
Expected: exit 0, 코어 테이블 생성, 시드 3개사 노드.

- [ ] **Step 2: 재무 적재 (DART 키 필요 — best-effort, gating 아님)**

Run: `uv run themek ingest financials --years 2022-2024`
Expected (키/네트워크 가능 시): `ingested N financial facts` (N>0).
**측정 분리:** 실 API는 환경 의존이라 **게이트가 아니다.** 재무 적재의 측정 가능 게이트는 Task 2.1~2.3의 카세트 기반 단위테스트(2+3+3=8 passed)로 이미 충족된다. 실 적재는 가능 환경에서만 수행하고 결과 수치를 Step 5 메모에 기록한다.

- [ ] **Step 3: vault build + graph export + 예시질의**

```bash
uv run themek vault build --out vault
uv run themek ontology export-graph --out graph
uv run themek query screen --segment 반도체 --metric operating_income --positive-since 2023FY
```
Expected: vault built / graph exported(nodes>0, edges>0) / screen이 exit 0로 회사 집합(또는 0건) 반환.

- [ ] **Step 4: graph 무결성 자동 점검**

```bash
uv run python - <<'PY'
import json, pathlib
g = pathlib.Path("graph")
nodes = {n["id"] for n in json.loads((g/"nodes.json").read_text(encoding="utf-8"))}
edges = json.loads((g/"edges.json").read_text(encoding="utf-8"))
broken = [e for e in edges if e["subject_id"] not in nodes or e["object_id"] not in nodes]
print(f"nodes={len(nodes)} edges={len(edges)} broken_refs={len(broken)}")
PY
```
Expected: `broken_refs=0`.

- [ ] **Step 5: smoke 메모 작성**

`docs/ontology-core-smoke-notes.md`에 Step1–4 실제 수치(노드/엣지/fact 수, 예시질의 결과, broken_refs=0) 기록.

- [ ] **Step 6: README 갱신**

`README.md`에 신규 명령 사용법 추가: `themek ingest financials`, `themek query screen`, `themek ontology export-graph`, 그리고 vault가 코어 기반으로 재무 시계열을 포함함을 명시. 구 모델 기반 설명(있다면) 갱신.

- [ ] **Step 7: Commit**

```bash
git add docs/ontology-core-smoke-notes.md README.md vault/ graph/
git commit -m "docs(ontology): core smoke build notes + README; real reingest snapshot"
```

✅ **Success Gate (측정 가능, 결정론적):**
1. `uv run themek seed` → exit 0, 직후 `uv run python -c "from themek.db.engine import make_engine,make_session_factory; from themek.ontology.core.models import Node; s=make_session_factory(make_engine())(); print(s.query(Node).filter_by(kind='company').count())"` → `3` 출력.
2. `uv run themek vault build --out vault` → exit 0 + stdout에 `vault built:` 포함, `vault/companies/*.md` ≥ 3개.
3. `uv run themek ontology export-graph --out graph` → exit 0, `graph/nodes.json`·`graph/edges.json` 존재.
4. Step 4 무결성 스크립트 → `broken_refs=0` 출력.
5. `uv run themek query screen --segment 반도체 --metric operating_income --positive-since 2023FY` → exit 0 (매칭 0건도 통과; exit code만 측정).
6. `docs/ontology-core-smoke-notes.md` 존재 + README에 `themek ingest financials`/`query screen`/`ontology export-graph` 문자열 포함(`grep -q` 통과).

(실 DART 재무 적재량 N은 환경 의존이라 게이트에서 제외 — 메모에 기록만.)

---

## Measurable Success Gates 요약

| Task | 측정 명령 | 통과 기준 |
|------|----------|----------|
| 1.1 | `pytest tests/ontology/test_ids.py` | 5 passed |
| 1.2 | `pytest tests/ontology/test_core_models.py` | 4 passed |
| 1.3 | `pytest tests/ontology/test_resolve.py` | 4 passed |
| 2.1 | `pytest tests/test_dart_financials.py` | 2 passed |
| 2.2 | `pytest tests/ontology/test_financials_parse.py` | 3 passed |
| 2.3 | `pytest tests/ontology/test_financials_ingest.py` | 3 passed |
| 2.4 | `pytest tests/ontology/test_business_structure_ingest.py` | 2 passed |
| 2.5 | `pytest tests/ontology/test_seeds.py` | 2 passed |
| 3.1 | `pytest tests/ontology/test_projection_vault.py` | 2 passed |
| 3.2 | `pytest tests/ontology/test_graph_export.py` | 2 passed |
| 4.1 | `pytest tests/ontology/test_screen.py` | 4 passed |
| 4.2 | `pytest tests/ontology/test_cli_ontology.py` | 1 passed |
| 5.1 | grep 잔존참조 + `pytest -q` | 0줄 + 전체 실패 0 |
| 5.2 | vault build/export-graph/screen + graph 무결성 | exit 0, broken_refs 0 |

신규 테스트: 5+4+4+2+3+3+2+2+2+2+4+1 = **34개**.

---

## Self-Review 결과

- **Spec coverage:** §5 코어 스키마 → Task 1.2. §6 재무 pilot → Task 2.1–2.3. §7 projection → Task 3.1(vault)·3.2(graph). §8 competency-query → Task 4.1·4.2. §9 마이그레이션 → Task 5.1. §10 테스트/§11 acceptance(예시질의 e2e) → Task 4.1·5.2. 개념 정규화(§5.4) → Task 1.3(resolver) + seeds/alias. ✅
- **Placeholder scan:** 모든 step에 실제 코드/명령. Task 5.1은 광범위 삭제라 "discovery 먼저(grep)" + 구체 재배선 코드 제시. ✅
- **Type consistency:** `upsert_node(session,id,kind,label,attrs)`·`upsert_edge(...)`·`resolve_concept`·`ingest_financials_for_company(session,client,*,corp_code,bsns_year,reprt_code)`·`ingest_business_structure(session,*,corp_code,extraction,source_ref)`·`build_vault(session,out)→{"companies"}`·`export_graph(session,out)→{"nodes","edges"}`·`screen(session,*,segment,metric,positive_since,fs_div)→set[str]` 전 Task 일관. ID 헬퍼(`company_id`/`segment_id`/`metric_id`/`period_id`) 일관. ✅
- **알려진 deferred:** 분기 누적 단기환산·제품 1급화·대량 정규화·소셜·지분·Neo4j 실스토어 — spec과 일치, 본 plan 범위 밖. ✅
