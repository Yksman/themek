# Financial Integrity (Track A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 분기 재무상태표(BS) 오염 버그를 고치고, 오염 데이터를 purge+재적재로 교정하며, 엣지 중복을 DB 제약으로 막고, 재발 방지용 경량 무결성 가드를 추가한다.

**Architecture:** `parse_financial_rows`를 flow/stock 지표로 분기 처리(stock은 당기만). 순수 함수 `pipeline.rebuild_financials`가 purge→재적재→무결성검사를 오케스트레이션하고 얇은 CLI가 감싼다. 엣지 UNIQUE는 ORM metadata(테스트용 create_all)와 alembic 마이그레이션(실 DB) 양쪽에 정의한다. 무결성 가드는 순수 조회 함수 `ontology/validate.py`.

**Tech Stack:** Python, SQLAlchemy 2.x (DeclarativeBase), Alembic, Typer CLI, pytest. 테스트는 `tests/conftest.py`의 `ontology_session` 픽스처(`Base.metadata.create_all`) 사용.

**Spec:** `docs/superpowers/specs/2026-05-31-financial-integrity-design.md`

---

## File Structure

- `src/themek/ontology/ingest/financials.py` — **수정**: flow/stock 분기 파싱 (Task 1).
- `src/themek/ontology/validate.py` — **신규**: `Issue` dataclass + `check_integrity()` 순수 조회 (Task 2).
- `src/themek/ontology/core/models.py` — **수정**: `Edge.__table_args__`에 함수형 UNIQUE 인덱스 (Task 3).
- `migrations/versions/0005_edge_unique.py` — **신규**: 실 DB용 UNIQUE 인덱스 (Task 3).
- `src/themek/ontology/pipeline.py` — **수정**: `rebuild_financials()` 추가 (Task 4).
- `src/themek/cli.py` — **수정**: `financials_app` + `rebuild` 커맨드 (Task 4).
- 테스트: `tests/ontology/test_financials_parse.py`(수정), `tests/ontology/test_validate.py`(신규), `tests/ontology/test_core_models.py`(수정), `tests/ontology/test_pipeline.py`(수정).
- 운영: 실 DB 교정 실행 (Task 5).

---

## Task 1: parse_financial_rows — flow/stock 분기 처리

**Files:**
- Modify: `src/themek/ontology/ingest/financials.py:63-85` (`parse_financial_rows`)
- Test: `tests/ontology/test_financials_parse.py` (기존 1건 수정 + 신규 1건)

- [ ] **Step 1: 테스트 갱신/추가 (실패하도록)**

`tests/ontology/test_financials_parse.py`의 기존 `test_parse_maps_accounts_and_three_years`를 아래로 교체(18 → 12):

```python
def test_parse_maps_accounts_flow_3yr_stock_1yr():
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY")
    # flow 3종 × 3개년(9) + stock 3종 × 당기만(3) = 12
    assert len(facts) == 12
    rev_2024 = [f for f in facts if f["metric_key"] == "revenue"
                and f["bsns_year"] == "2024"]
    assert len(rev_2024) == 1
    assert rev_2024[0]["amount"] == 3007700000000.0
    # flow(revenue)는 3개년 라벨 유지
    assert {f["bsns_year"] for f in facts if f["metric_key"] == "revenue"} \
        == {"2024", "2023", "2022"}
    # stock(assets)는 당기(2024)만
    assert {f["bsns_year"] for f in facts if f["metric_key"] == "assets"} == {"2024"}
```

그리고 신규 테스트 추가 — interim 보고서에서도 stock은 당기만:

```python
def test_parse_stock_metric_thstrm_only_in_interim():
    """분기보고서의 비교열(frmtrm=직전 연말)은 적재하지 않는다 — stock은 당기만."""
    rows = [
        {"account_id": "ifrs-full_Assets", "account_nm": "자산총계", "sj_div": "BS",
         "thstrm_amount": "100", "frmtrm_amount": "90", "bfefrmtrm_amount": "80"},
        {"account_id": "ifrs-full_Revenue", "account_nm": "매출액", "sj_div": "IS",
         "thstrm_amount": "50", "frmtrm_amount": "40", "bfefrmtrm_amount": "30"},
    ]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="Q1")
    assets = [f for f in facts if f["metric_key"] == "assets"]
    assert len(assets) == 1 and assets[0]["bsns_year"] == "2024" \
        and assets[0]["amount"] == 100.0
    # flow는 3개년 그대로
    rev = {f["bsns_year"]: f["amount"] for f in facts if f["metric_key"] == "revenue"}
    assert rev == {"2024": 50.0, "2023": 40.0, "2022": 30.0}
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/ontology/test_financials_parse.py -v`
Expected: FAIL — 기존 동작은 stock도 3개년(assets 2024/2023/2022) 적재해 len==18, assets years=={2024,2023,2022}.

- [ ] **Step 3: 최소 구현**

`src/themek/ontology/ingest/financials.py` 상단 매핑 근처(line 36 `_METRIC_SJ` 정의 뒤)에 추가:

```python
_FLOW = frozenset({"revenue", "operating_income", "net_income"})
_STOCK = frozenset({"assets", "liabilities", "equity"})
```

`parse_financial_rows`(line 63-85)를 아래로 교체:

```python
def parse_financial_rows(rows: list[dict], *, bsns_year: str,
                         fiscal_period: str) -> list[dict]:
    """행들을 [{company-agnostic fact dict}] 로 평탄화.

    flow 지표(매출/이익)는 당기/전기/전전기 3개년 전개 — 비교열이 '전기 동기'라 의미상 맞다.
    stock 지표(자산/부채/자본)는 당기(thstrm)만 적재 — 분기보고서의 비교열(frmtrm)은
    '직전 사업연도 말' 스냅샷이라 interim period로 라벨링하면 오염된다(연말값으로 덮어씀).
    """
    yr = int(bsns_year)
    flow_years = {
        "thstrm_amount": str(yr),
        "frmtrm_amount": str(yr - 1),
        "bfefrmtrm_amount": str(yr - 2),
    }
    facts: list[dict] = []
    for row in rows:
        metric = _metric_of(row)
        if metric is None:
            continue
        if metric in _STOCK:
            amount = _to_amount(row.get("thstrm_amount"))
            if amount is not None:
                facts.append({"metric_key": metric, "bsns_year": str(yr),
                              "fiscal_period": fiscal_period, "amount": amount})
            continue
        for field, year_label in flow_years.items():
            amount = _to_amount(row.get(field))
            if amount is None:
                continue
            facts.append({"metric_key": metric, "bsns_year": year_label,
                          "fiscal_period": fiscal_period, "amount": amount})
    return facts
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `pytest tests/ontology/test_financials_parse.py -v`
Expected: PASS (5 passed — 기존 3건 + 갱신 1건 + 신규 1건). `test_parse_equity_only_from_bs_not_sce`는 equity(stock)·thstrm만이라 여전히 통과(frmtrm/bfefrmtrm이 빈 값이었음).

- [ ] **Step 5: 커밋**

```bash
git add src/themek/ontology/ingest/financials.py tests/ontology/test_financials_parse.py
git commit -m "fix(financials): stock metrics ingest current period only — interim BS no longer polluted by prior year-end comparative column"
```

---

## Task 2: 무결성 가드 모듈 — ontology/validate.py

**Files:**
- Create: `src/themek/ontology/validate.py`
- Test: `tests/ontology/test_validate.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/ontology/test_validate.py`:

```python
"""check_integrity — 오염 시그니처 탐지 단위 테스트."""
from themek.ontology.core.models import Node, Edge, FinancialFact
from themek.ontology.validate import check_integrity


def _fact(s, *, cid, yr, fp, mk, amt, fsd="CFS"):
    s.add(FinancialFact(company_id=cid, bsns_year=yr, fiscal_period=fp,
                        fs_div=fsd, metric_key=mk, amount=amt, currency="KRW",
                        source_type="dart_api", method="api", confidence=1.0))


def test_clean_data_has_no_errors(ontology_session):
    s = ontology_session
    s.add(Node(id="company:1", kind="company", label="A")); s.commit()
    _fact(s, cid="company:1", yr="2024", fp="FY", mk="assets", amt=100)
    _fact(s, cid="company:1", yr="2024", fp="Q1", mk="assets", amt=95)  # 다름 → OK
    s.commit()
    issues = check_integrity(s)
    assert [i for i in issues if i.severity == "error"] == []


def test_interim_bs_equals_fy_flagged(ontology_session):
    s = ontology_session
    s.add(Node(id="company:1", kind="company", label="A")); s.commit()
    _fact(s, cid="company:1", yr="2024", fp="FY", mk="assets", amt=100)
    _fact(s, cid="company:1", yr="2024", fp="H1", mk="assets", amt=100)  # FY와 동일
    s.commit()
    codes = [i.code for i in check_integrity(s)]
    assert "interim_bs_equals_fy" in codes


def test_duplicate_edge_flagged(ontology_session):
    s = ontology_session
    s.add(Node(id="company:1", kind="company", label="A"))
    s.add(Node(id="segment:x", kind="segment", label="x")); s.commit()
    # ORM UNIQUE 추가 전이므로 직접 2건 insert 가능(Task 3에서 차단됨).
    # 여기선 중복 탐지 로직만 검증하기 위해 동일 키 2건을 강제 구성.
    for _ in range(2):
        s.add(Edge(subject_id="company:1", predicate="HAS_SEGMENT",
                   object_id="segment:x", period="2024", qualifier={},
                   source_type="llm", method="llm", confidence=0.9))
    try:
        s.commit()
    except Exception:
        s.rollback()
        return  # UNIQUE 제약이 이미 있으면(Task 3 이후) 중복 insert 자체가 막힘 — 정상
    codes = [i.code for i in check_integrity(s)]
    assert "duplicate_edge" in codes
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/ontology/test_validate.py -v`
Expected: FAIL — `ModuleNotFoundError: themek.ontology.validate`.

- [ ] **Step 3: 최소 구현**

`src/themek/ontology/validate.py`:

```python
"""온톨로지 경량 무결성 가드 — 순수 조회. 부작용 없음."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from themek.ontology.core.models import Edge, FinancialFact, Node

_STOCK = ("assets", "liabilities", "equity")
_INTERIM = ("Q1", "H1", "Q3")


@dataclass
class Issue:
    code: str
    severity: str  # "error" | "warn" | "info"
    message: str
    subject: str | None = None


def check_integrity(session: Session) -> list[Issue]:
    issues: list[Issue] = []

    # 1. interim_bs_equals_fy (error) — 분기 BS가 FY와 정확히 동일 = 1.1 버그 시그니처
    rows = session.execute(
        select(FinancialFact.company_id, FinancialFact.bsns_year,
               FinancialFact.metric_key, FinancialFact.fiscal_period,
               FinancialFact.fs_div, FinancialFact.amount)
        .where(FinancialFact.metric_key.in_(_STOCK))
    ).all()
    fy = {(c, y, m, d): a for (c, y, m, p, d, a) in rows if p == "FY"}
    for c, y, m, p, d, a in rows:
        if p in _INTERIM and fy.get((c, y, m, d)) == a:
            issues.append(Issue("interim_bs_equals_fy", "error",
                                 f"{c} {y} {m} {p}=={d} matches FY ({a})", c))

    # 2. duplicate_edge (error)
    dups = session.execute(
        select(Edge.subject_id, Edge.predicate, Edge.object_id, Edge.period,
               func.count().label("c"))
        .group_by(Edge.subject_id, Edge.predicate, Edge.object_id, Edge.period)
        .having(func.count() > 1)
    ).all()
    for sid, pred, oid, period, c in dups:
        issues.append(Issue("duplicate_edge", "error",
                             f"{sid} -{pred}-> {oid} @{period} x{c}", sid))

    # 3. orphan_fact (warn)
    orphans = session.execute(
        select(FinancialFact.company_id).distinct()
        .where(FinancialFact.company_id.not_in(select(Node.id)))
    ).scalars().all()
    for cid in orphans:
        issues.append(Issue("orphan_fact", "warn",
                             f"fact company_id {cid} not in nodes", cid))

    # 4. negative_or_zero_equity (info)
    negs = session.execute(
        select(FinancialFact.company_id, FinancialFact.bsns_year,
               FinancialFact.fiscal_period)
        .where(FinancialFact.metric_key == "equity", FinancialFact.amount <= 0)
    ).all()
    for cid, yr, fp in negs:
        issues.append(Issue("negative_or_zero_equity", "info",
                             f"{cid} {yr}{fp} equity<=0", cid))

    return issues
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `pytest tests/ontology/test_validate.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: 커밋**

```bash
git add src/themek/ontology/validate.py tests/ontology/test_validate.py
git commit -m "feat(ontology): add check_integrity guard (interim-BS-equals-FY, duplicate-edge, orphan-fact, neg-equity)"
```

---

## Task 3: 엣지 UNIQUE 제약 — ORM metadata + 마이그레이션 0005

**Files:**
- Modify: `src/themek/ontology/core/models.py` (`Edge` 클래스에 `__table_args__` 추가, import 보강)
- Create: `migrations/versions/0005_edge_unique.py`
- Test: `tests/ontology/test_core_models.py` (신규 1건)

- [ ] **Step 1: 실패 테스트 작성**

`tests/ontology/test_core_models.py` 끝에 추가:

```python
def test_edge_unique_constraint(ontology_session):
    s = ontology_session
    s.add(Node(id="company:1", kind="company", label="A"))
    s.add(Node(id="segment:x", kind="segment", label="x")); s.commit()

    def _edge():
        return Edge(subject_id="company:1", predicate="HAS_SEGMENT",
                    object_id="segment:x", period="2024", qualifier={},
                    source_type="llm", method="llm", confidence=0.9)
    s.add(_edge()); s.commit()
    s.add(_edge())
    with pytest.raises(Exception):   # IntegrityError — 동일 (s,p,o,period)
        s.commit()


def test_edge_unique_constraint_null_period(ontology_session):
    s = ontology_session
    s.rollback()
    s.add(Node(id="company:2", kind="company", label="B"))
    s.add(Node(id="sector:G2520", kind="sector", label="반도체")); s.commit()

    def _edge():
        return Edge(subject_id="company:2", predicate="IN_SECTOR",
                    object_id="sector:G2520", period=None, qualifier={},
                    source_type="manual", method="manual", confidence=1.0)
    s.add(_edge()); s.commit()
    s.add(_edge())
    with pytest.raises(Exception):   # COALESCE(period,'') 덕분에 NULL도 차단
        s.commit()
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/ontology/test_core_models.py -v`
Expected: FAIL — 제약이 없어 중복 insert가 통과(`DID NOT RAISE`).

- [ ] **Step 3: ORM 구현**

`src/themek/ontology/core/models.py` 상단 import에 `Index`, `text` 추가:

```python
from sqlalchemy import (
    String, Float, Numeric, ForeignKey, Enum as SQLEnum, JSON,
    DateTime, UniqueConstraint, Index, func, text,
)
```

`Edge` 클래스 본문 끝(관계 정의 `subject_node`/`object_node` 아래, line 63 뒤)에 추가:

```python
    __table_args__ = (
        Index(
            "ux_edge_spo",
            text("subject_id"), text("predicate"), text("object_id"),
            text("coalesce(period, '')"),
            unique=True,
        ),
    )
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `pytest tests/ontology/test_core_models.py -v`
Expected: PASS (기존 4건 + 신규 2건 = 6 passed).

- [ ] **Step 5: 마이그레이션 0005 작성**

`migrations/versions/0005_edge_unique.py`:

```python
"""add unique index on edges (subject, predicate, object, coalesce(period))

Revision ID: 0005_edge_unique
Revises: 0004_stock_lifecycle
Create Date: 2026-05-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0005_edge_unique"
down_revision: Union[str, Sequence[str], None] = "0004_stock_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ux_edge_spo", "edges",
        ["subject_id", "predicate", "object_id"],
        unique=True,
        sqlite_where=None,
        postgresql_include=None,
    )


def downgrade() -> None:
    op.drop_index("ux_edge_spo", table_name="edges")
```

> 주의: `op.create_index`는 함수형 표현식(`coalesce`)을 인자 리스트로 직접 못 받는다. SQLite/Postgres 양쪽 호환을 위해 raw SQL로 작성한다 — 위 블록을 아래로 교체:

```python
def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX ux_edge_spo ON edges "
        "(subject_id, predicate, object_id, coalesce(period, ''))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ux_edge_spo")
```

(최종 파일에는 raw SQL 버전만 남긴다.)

- [ ] **Step 6: 마이그레이션 스모크 (임시 DB)**

Run:
```bash
THEMEK_DB_URL="sqlite:///$(mktemp -t edgeidx).db" alembic upgrade head && \
THEMEK_DB_URL="sqlite:///$(mktemp -t edgeidx2).db" sh -c 'alembic upgrade head && alembic downgrade -1'
```
Expected: 에러 없이 완료. (환경변수명은 `src/themek/config.py`의 DSN 설정 키에 맞춘다 — `get_settings().postgres_dsn`을 채우는 env. 모르면 `python -c "from themek.config import get_settings; print(get_settings().postgres_dsn)"`로 확인.)

> 스모크가 환경 문제로 어려우면 최소 검증: `python -c "import migrations.versions" `는 불가하므로, `alembic history | grep 0005_edge_unique`로 리비전 등록만 확인하고 실제 적용은 Task 5에서 수행.

- [ ] **Step 7: 커밋**

```bash
git add src/themek/ontology/core/models.py migrations/versions/0005_edge_unique.py tests/ontology/test_core_models.py
git commit -m "feat(ontology): enforce edge uniqueness (subject,predicate,object,coalesce(period)) in ORM + migration 0005"
```

---

## Task 4: rebuild_financials 함수 + CLI 커맨드

**Files:**
- Modify: `src/themek/ontology/pipeline.py` (`rebuild_financials` 추가)
- Modify: `src/themek/cli.py` (`financials_app` + `rebuild` 커맨드)
- Test: `tests/ontology/test_pipeline.py` (신규 1건)

- [ ] **Step 1: 실패 테스트 작성**

`tests/ontology/test_pipeline.py` 끝에 추가:

```python
def test_rebuild_financials_purges_and_reingests(ontology_session):
    from themek.ontology.core.models import Node, Edge, FinancialFact
    from themek.ontology.core.resolve import upsert_node
    from themek.ontology.pipeline import rebuild_financials

    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"})
    # company_report_years가 2024를 반환하도록 엣지 1건(period=2024)
    s.add(Node(id="segment:x", kind="segment", label="x"))
    s.add(Edge(subject_id="company:00126380", predicate="HAS_SEGMENT",
               object_id="segment:x", period="2024", qualifier={},
               source_type="llm", method="llm", confidence=0.9))
    # 오염된(stale) 기존 fact — purge로 사라져야 함
    s.add(FinancialFact(company_id="company:00126380", bsns_year="1999",
                        fiscal_period="FY", fs_div="CFS", metric_key="assets",
                        amount=1, currency="KRW", source_type="dart_api",
                        method="api", confidence=1.0))
    s.commit()

    class _FakeClient:
        def fetch_financials(self, *, corp_code, bsns_year, reprt_code, fs_div):
            if fs_div != "CFS":
                return []
            return [{"account_id": "ifrs-full_Revenue", "account_nm": "매출액",
                     "sj_div": "IS", "thstrm_amount": "500",
                     "frmtrm_amount": "400", "bfefrmtrm_amount": "300"},
                    {"account_id": "ifrs-full_Assets", "account_nm": "자산총계",
                     "sj_div": "BS", "thstrm_amount": "900",
                     "frmtrm_amount": "800", "bfefrmtrm_amount": "700"}]

    res = rebuild_financials(s, _FakeClient())
    s.commit()

    assert res["deleted"] == 1                      # stale fact 제거
    assert res["facts"] > 0                          # 재적재됨
    # stale(1999) fact 사라짐
    assert s.query(FinancialFact).filter_by(bsns_year="1999").count() == 0
    # stock(assets)은 당기만 → 2024만 존재
    assets_years = {f.bsns_year for f in
                    s.query(FinancialFact).filter_by(metric_key="assets").all()}
    assert assets_years == {"2024"}
    assert isinstance(res["issues"], list)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `pytest tests/ontology/test_pipeline.py::test_rebuild_financials_purges_and_reingests -v`
Expected: FAIL — `ImportError: cannot import name 'rebuild_financials'`.

- [ ] **Step 3: pipeline 구현**

`src/themek/ontology/pipeline.py`의 `ingest_financials_all` 함수 정의 뒤(line 67 이후, `@dataclass PipelineResult` 앞)에 추가:

```python
def rebuild_financials(session: Session, client) -> dict:
    """financial_facts 전체 purge 후 회사별 실제 제출 연도로 재적재 + 무결성 검사.

    1.1 BS 오염 교정용. _upsert_fact는 덮어쓰기만 하므로(삭제 안 함) purge가 선행해야
    잘못 라벨된 기존 행이 제거된다. 멱등(재실행 안전).
    """
    from themek.ontology.core.models import FinancialFact
    from themek.ontology.validate import check_integrity

    deleted = session.query(FinancialFact).delete()
    session.flush()
    stats = ingest_financials_all(session, client)
    session.flush()
    issues = check_integrity(session)
    errors = [i for i in issues if i.severity == "error"]
    return {"deleted": deleted, "facts": stats["facts"],
            "failed": stats["failed"], "issues": issues, "errors": errors}
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `pytest tests/ontology/test_pipeline.py::test_rebuild_financials_purges_and_reingests -v`
Expected: PASS.

- [ ] **Step 5: CLI 커맨드 추가**

`src/themek/cli.py`의 typer 앱 등록부(line 50 `pipeline_app` 등록 뒤)에 추가:

```python
financials_app = typer.Typer(help="재무 정합성 명령")
app.add_typer(financials_app, name="financials")
```

그리고 `ingest_financials_cmd`(line 789 근처) 뒤에 커맨드 추가:

```python
@financials_app.command("rebuild")
def financials_rebuild_cmd():
    """financial_facts purge 후 DART 재적재 + 무결성 검사 (BS 오염 교정)."""
    from themek.ontology.pipeline import rebuild_financials
    client = DartClient(api_key=get_settings().dart_api_key)
    with _session() as s:
        res = rebuild_financials(s, client)
        s.commit()
    for i in res["issues"]:
        typer.echo(f"[{i.severity}] {i.code}: {i.message}")
    typer.echo(f"deleted {res['deleted']} facts, ingested {res['facts']}, "
               f"{len(res['errors'])} integrity error(s)")
    if res["errors"]:
        raise typer.Exit(code=1)
```

> `DartClient`, `get_settings`, `_session`, `typer`는 cli.py 상단에 이미 import되어 있다(기존 `ingest_financials_cmd` 참조). 추가 import 불필요.

- [ ] **Step 6: CLI 스모크 (등록 확인)**

Run: `python -m themek.cli financials --help` (또는 프로젝트의 CLI 엔트리포인트)
Expected: `rebuild` 서브커맨드가 목록에 표시.

- [ ] **Step 7: 커밋**

```bash
git add src/themek/ontology/pipeline.py src/themek/cli.py tests/ontology/test_pipeline.py
git commit -m "feat(financials): add rebuild_financials (purge+reingest+integrity) and 'themek financials rebuild' CLI"
```

---

## Task 5: 실 DB 교정 실행 (운영)

**Files:** 코드 변경 없음 — 실 데이터(`themek.db`) 교정.

- [ ] **Step 1: 백업**

```bash
cp themek.db themek.db.pre-integrity.bak
```

- [ ] **Step 2: 마이그레이션 0005 적용 (엣지 UNIQUE)**

Run: `alembic upgrade head`
Expected: `ux_edge_spo` 인덱스 생성 성공(현재 위반 0건이라 충돌 없음). 실패 시 중복 엣지가 새로 생긴 것이므로 `check_integrity`로 조사 후 dedup.

- [ ] **Step 3: 재무 재적재 (purge + DART 재호출)**

Run: `python -m themek.cli financials rebuild`
Expected: `deleted ~1754 facts, ingested N, 0 integrity error(s)`. integrity error가 0이 아니면 출력된 `interim_bs_equals_fy` 항목을 확인 — 실제 동일값(우연)인지 잔여 버그인지 판별.

- [ ] **Step 4: 교정 검증 (CJ 분기 BS가 더 이상 FY와 동일하지 않음)**

Run:
```bash
python3 -c "
import sqlite3; db=sqlite3.connect('themek.db'); cur=db.cursor()
rows=cur.execute(\"SELECT bsns_year,fiscal_period,amount FROM financial_facts WHERE company_id='company:00148540' AND metric_key='assets' AND bsns_year='2024' ORDER BY fiscal_period\").fetchall()
print(rows)
vals={fp:a for _,fp,a in rows}
assert not (vals.get('H1')==vals.get('FY') and vals.get('Q3')==vals.get('FY')), 'STILL POLLUTED'
print('OK: interim BS != FY')
"
```
Expected: `OK: interim BS != FY` (H1/Q3 ≠ FY). 단, 2024 interim 보고서를 CJ가 제출하지 않았다면 해당 분기 행이 아예 없을 수 있음(정상 — 오염 제거).

- [ ] **Step 5: vault 재생성 (교정값 반영) + 전체 테스트**

Run:
```bash
python -m themek.cli vault build && pytest -q
```
Expected: vault 빌드 성공, 전체 테스트 통과.

- [ ] **Step 6: 커밋**

```bash
git add themek.db data vault 2>/dev/null; git status
git commit -m "data: rebuild financials with corrected interim-BS handling + edge unique index (track A remediation)"
```

> `themek.db`/`vault`가 git 추적 대상인지 `git status`로 확인 후 추적되는 것만 커밋한다. 추적 안 되면 데이터 산출물은 스킵하고 코드/마이그레이션만 이미 Task 1-4에서 커밋됨.

---

## Self-Review (작성자 점검 결과)

- **Spec coverage:** §3.1 파싱→Task 1, §3.2 재적재 CLI→Task 4+5, §3.3 엣지 UNIQUE→Task 3, §3.4 무결성 가드→Task 2. §6 테스트 항목 1-5 모두 Task 1-4에 매핑. §7 한계는 코드 변경 없음(문서화만, spec에 기재됨).
- **Placeholder scan:** TBD/TODO 없음. 모든 코드 스텝에 실제 코드 포함. Task 3 Step 5의 마이그레이션은 raw SQL 최종본 명시.
- **Type consistency:** `Issue(code, severity, message, subject)` — Task 2 정의, Task 4에서 `i.severity`/`i.code`/`i.message`로 일관 사용. `rebuild_financials` 반환 `{deleted, facts, failed, issues, errors}` — Task 4 정의·테스트·CLI 일관. `check_integrity(session) -> list[Issue]` 시그니처 Task 2·4 일관. 인덱스명 `ux_edge_spo` — ORM(Task3 Step3)·마이그레이션(Step5) 동일.
- **알려진 주의:** `THEMEK_DB_URL` env 키는 프로젝트 설정에 맞춰 확인 필요(Task 3 Step 6 주석). 실패 시 Task 5에서 실 적용으로 검증.
