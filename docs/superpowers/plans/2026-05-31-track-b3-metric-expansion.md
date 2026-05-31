# Track B3 — Financial Metric Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 재무 metric을 `eps`, `cf_operating`/`cf_investing`/`cf_financing`(현금흐름표), `shares_outstanding`(발행주식수)으로 확장한다.

**Architecture:** EPS·현금흐름은 기존 `fnlttSinglAcntAll` 응답(IS/CIS·CF)에 매핑만 추가 — flow 지표로 3개년 전개. 발행주식수는 재무제표 API에 없어 신규 client `fetch_shares`(DART `stockTotqySttus`) + 전용 적재(stock 지표, 당기만). `metric_key` SQLEnum 확장은 실 DB CHECK 재생성 마이그레이션 필요.

**Tech Stack:** Python, SQLAlchemy 2.x SQLEnum, Alembic batch_alter_table, pytest.

**Spec:** `docs/superpowers/specs/2026-05-31-ontology-essence-track-b-design.md` §5

**의존성:** Track A(`_FLOW`/`_STOCK` 분기, `financials.py` 파싱) 완료 위에 얹힌다.

---

## File Structure

- `src/themek/ontology/core/models.py` — **수정**: `METRIC_KEYS`에 5종 추가.
- `src/themek/ontology/ingest/financials.py` — **수정**: 매핑(`_ID_MAP`/`_NM_MAP`/`_METRIC_SJ`/`_FLOW`/`_METRIC_LABEL`) 확장 + `ingest_shares_for_company` + `ingest_financials_all` 배선.
- `src/themek/dart/client.py` — **수정**: `fetch_shares(corp_code, bsns_year, reprt_code)` 추가.
- `migrations/versions/0007_expand_metric_keys.py` — **신규**: metric_key enum CHECK 재생성.
- 테스트: `tests/ontology/test_financials_parse.py`(수정), `tests/ontology/test_financials_shares.py`(신규).

---

## Task 1: metric_key 확장 + EPS/현금흐름 매핑

**Success gate (측정 가능):**
- `.venv/bin/python -m pytest tests/ontology/test_financials_parse.py` 전체 passed(신규 2건 포함).
- eps 3개년 라벨 == {2024,2023,2022}; `cf_operating`은 `sj_div=="CF"` 행에서만 추출(BS 행 999 무시).
- 기존 12-count 테스트(`test_parse_maps_accounts_flow_3yr_stock_1yr`) 불변.

**Files:**
- Modify: `src/themek/ontology/core/models.py:26-29` (`METRIC_KEYS`)
- Modify: `src/themek/ontology/ingest/financials.py` (매핑 + `_METRIC_LABEL`)
- Test: `tests/ontology/test_financials_parse.py` (신규 2건)

- [ ] **Step 1: 실패 테스트 작성**

`tests/ontology/test_financials_parse.py` 끝에 추가:

```python
def test_parse_eps_from_is_flow_expansion():
    rows = [{"account_id": "ifrs-full_BasicEarningsLossPerShare",
             "account_nm": "기본주당이익(손실)", "sj_div": "CIS",
             "thstrm_amount": "8057", "frmtrm_amount": "6461",
             "bfefrmtrm_amount": "5777"}]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY")
    eps = {f["bsns_year"]: f["amount"] for f in facts if f["metric_key"] == "eps"}
    assert eps == {"2024": 8057.0, "2023": 6461.0, "2022": 5777.0}


def test_parse_cashflow_only_from_cf_statement():
    rows = [
        {"account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities",
         "account_nm": "영업활동현금흐름", "sj_div": "CF",
         "thstrm_amount": "100", "frmtrm_amount": "90", "bfefrmtrm_amount": "80"},
        # 같은 account가 다른 표(BS)에 잘못 오면 무시되어야 함
        {"account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities",
         "account_nm": "영업활동현금흐름", "sj_div": "BS",
         "thstrm_amount": "999", "frmtrm_amount": "", "bfefrmtrm_amount": ""},
    ]
    facts = parse_financial_rows(rows, bsns_year="2024", fiscal_period="FY")
    cfo = [f for f in facts if f["metric_key"] == "cf_operating"]
    assert {f["bsns_year"]: f["amount"] for f in cfo} == \
        {"2024": 100.0, "2023": 90.0, "2022": 80.0}
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_financials_parse.py -k "eps or cashflow" -v`
Expected: FAIL — eps/cf_operating가 매핑 안 됨(빈 facts).

- [ ] **Step 3: METRIC_KEYS 확장**

`src/themek/ontology/core/models.py:26-29`를 교체:

```python
METRIC_KEYS = (
    "revenue", "operating_income", "net_income",
    "assets", "liabilities", "equity",
    "eps", "cf_operating", "cf_investing", "cf_financing",
    "shares_outstanding",
)
```

- [ ] **Step 4: financials.py 매핑 확장**

`src/themek/ontology/ingest/financials.py`의 `_ID_MAP`(line 8-18)에 항목 추가:

```python
    "ifrs-full_BasicEarningsLossPerShare": "eps",
    "ifrs-full_CashFlowsFromUsedInOperatingActivities": "cf_operating",
    "ifrs-full_CashFlowsFromUsedInInvestingActivities": "cf_investing",
    "ifrs-full_CashFlowsFromUsedInFinancingActivities": "cf_financing",
```

`_NM_MAP`(line 20-25)에 추가:

```python
    "기본주당이익(손실)": "eps", "기본주당순이익": "eps",
    "영업활동현금흐름": "cf_operating", "영업활동으로인한현금흐름": "cf_operating",
    "투자활동현금흐름": "cf_investing", "투자활동으로인한현금흐름": "cf_investing",
    "재무활동현금흐름": "cf_financing", "재무활동으로인한현금흐름": "cf_financing",
```

`_METRIC_SJ`(line 33-36)에 추가 (eps는 손익, cf는 현금흐름표):

```python
    "eps": _PL,
    "cf_operating": frozenset({"CF"}),
    "cf_investing": frozenset({"CF"}),
    "cf_financing": frozenset({"CF"}),
    "shares_outstanding": frozenset({"BS"}),  # 파싱 경로 미사용(별도 fetch) — 방어값
```

`_FLOW`(Track A에서 추가된 line 37)에 eps/cf 추가:

```python
_FLOW = frozenset({"revenue", "operating_income", "net_income",
                   "eps", "cf_operating", "cf_investing", "cf_financing"})
```

`_METRIC_LABEL`(line 97-100)에 추가:

```python
    "eps": "기본주당순이익", "cf_operating": "영업활동현금흐름",
    "cf_investing": "투자활동현금흐름", "cf_financing": "재무활동현금흐름",
    "shares_outstanding": "발행주식수",
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_financials_parse.py -v`
Expected: PASS (기존 + 신규 2건 모두). 기존 12-count 테스트는 입력 rows에 eps/cf가 없어 영향 없음.

- [ ] **Step 6: 커밋**

```bash
git add src/themek/ontology/core/models.py src/themek/ontology/ingest/financials.py tests/ontology/test_financials_parse.py
git commit -m "feat(financials): add eps + cash-flow metrics (IS/CF mapping, flow expansion)"
```

---

## Task 2: metric_key enum CHECK 재생성 — 마이그레이션 0007

**Success gate (측정 가능):**
- 임시 DB에서 `alembic upgrade head` & `alembic downgrade -1` 모두 종료코드 0.
- upgrade 후 `metric_key="eps"` FinancialFact insert 성공(CHECK 위반 없음).
- 적용 전후 기존 `financial_facts` 행 수 보존(_OLD 값 충돌 0).

**Files:**
- Create: `migrations/versions/0007_expand_metric_keys.py`

- [ ] **Step 1: 마이그레이션 작성**

`migrations/versions/0007_expand_metric_keys.py`:

```python
"""expand financial_facts.metric_key enum (eps, cash flows, shares)

Revision ID: 0007_expand_metrics
Revises: 0006_drop_legacy
Create Date: 2026-05-31 00:00:00.000000

SQLite는 CHECK 제약을 in-place ALTER 못 함 → batch_alter_table로 테이블 재생성.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_expand_metrics"
down_revision: Union[str, Sequence[str], None] = "0006_drop_legacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = ("revenue", "operating_income", "net_income",
        "assets", "liabilities", "equity")
_NEW = _OLD + ("eps", "cf_operating", "cf_investing", "cf_financing",
               "shares_outstanding")


def upgrade() -> None:
    with op.batch_alter_table("financial_facts") as batch:
        batch.alter_column(
            "metric_key",
            existing_type=sa.Enum(*_OLD, name="metric_key"),
            type_=sa.Enum(*_NEW, name="metric_key"),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("financial_facts") as batch:
        batch.alter_column(
            "metric_key",
            existing_type=sa.Enum(*_NEW, name="metric_key"),
            type_=sa.Enum(*_OLD, name="metric_key"),
            existing_nullable=False,
        )
```

- [ ] **Step 2: 마이그레이션 스모크 (임시 DB)**

Run:
```bash
TMPDB=$(mktemp -t b3idx).db; POSTGRES_DSN="sqlite:///$TMPDB" .venv/bin/alembic upgrade head && \
POSTGRES_DSN="sqlite:///$TMPDB" .venv/bin/alembic downgrade -1
```
Expected: upgrade/downgrade 모두 에러 없이 완료.

- [ ] **Step 3: 실 DB 적용**

Run: `.venv/bin/alembic upgrade head`
Expected: `0007_expand_metrics` 적용. 기존 행은 보존(값이 _OLD 범위 내라 충돌 없음).

- [ ] **Step 4: 커밋**

```bash
git add migrations/versions/0007_expand_metric_keys.py
git commit -m "chore(db): migration 0007 — expand metric_key enum for eps/cashflow/shares"
```

---

## Task 3: 발행주식수 — fetch_shares + ingest_shares_for_company

**Success gate (측정 가능):**
- `.venv/bin/python -m pytest tests/ontology/test_financials_shares.py` → 2 passed.
- `shares_outstanding` fact.amount == 보통주 `istc_totqy`(콤마 제거값); `fiscal_period`는 reprt_code 매핑과 일치.
- 재실행 후 shares 행 수 불변(멱등).
- `.venv/bin/python -m pytest tests/ontology/test_pipeline.py` PASS(FakeClient에 `fetch_shares` 추가 후).

**Files:**
- Modify: `src/themek/dart/client.py` (`fetch_shares` 추가)
- Modify: `src/themek/ontology/ingest/financials.py` (`ingest_shares_for_company` + `ingest_financials_all` 배선은 `pipeline.py`)
- Modify: `src/themek/ontology/pipeline.py` (`ingest_financials_all` 루프에 shares 호출)
- Test: `tests/ontology/test_financials_shares.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/ontology/test_financials_shares.py`:

```python
"""발행주식수(stockTotqySttus) → shares_outstanding fact 적재."""
from themek.ontology.core.models import FinancialFact
from themek.ontology.core.resolve import upsert_node
from themek.ontology.ingest.financials import ingest_shares_for_company


class _FakeClient:
    def fetch_shares(self, *, corp_code, bsns_year, reprt_code):
        # 보통주 발행총수 1행 + 우선주 1행
        return [
            {"se": "보통주", "istc_totqy": "5,969,782,550"},
            {"se": "우선주", "istc_totqy": "822,886,700"},
        ]


def test_ingest_shares_picks_common_total(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자",
                {"dart_code": "00126380"}); s.commit()
    n = ingest_shares_for_company(
        s, _FakeClient(), corp_code="00126380", bsns_year="2024",
        reprt_code="11011"); s.commit()
    assert n == 1
    fact = s.query(FinancialFact).filter_by(
        metric_key="shares_outstanding").one()
    assert fact.amount == 5969782550
    assert fact.bsns_year == "2024" and fact.fiscal_period == "FY"


def test_ingest_shares_idempotent(ontology_session):
    s = ontology_session
    upsert_node(s, "company:1", "company", "A", {"dart_code": "1"}); s.commit()
    for _ in range(2):
        ingest_shares_for_company(s, _FakeClient(), corp_code="1",
                                  bsns_year="2024", reprt_code="11011")
    s.commit()
    assert s.query(FinancialFact).filter_by(
        metric_key="shares_outstanding").count() == 1
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_financials_shares.py -v`
Expected: FAIL — `ImportError: cannot import name 'ingest_shares_for_company'`.

- [ ] **Step 3: client fetch_shares 추가**

`src/themek/dart/client.py`의 `fetch_company_profile`(B1 Task2에서 추가) 뒤에 추가:

```python
    def fetch_shares(self, *, corp_code: str, bsns_year: str,
                     reprt_code: str) -> list[dict]:
        """주식총수현황(stockTotqySttus.json). 비정상 status는 빈 리스트."""
        params = {"crtfc_key": self._key, "corp_code": corp_code,
                  "bsns_year": bsns_year, "reprt_code": reprt_code}
        r = self._client.get(f"{self._base}/stockTotqySttus.json", params=params)
        self._raise_on_error(r)
        payload = r.json()
        if payload.get("status") != "000":
            return []
        return payload.get("list", [])
```

- [ ] **Step 4: ingest_shares_for_company 구현**

`src/themek/ontology/ingest/financials.py`의 `ingest_financials_for_company`(line 134 근처) 뒤에 추가:

```python
def ingest_shares_for_company(session: Session, client, *, corp_code: str,
                              bsns_year: str, reprt_code: str) -> int:
    """발행주식수(보통주 총수) → shares_outstanding fact. stock 지표(당기만). 멱등.

    fs_div는 연결/별도 무관 개념이라 관습적으로 'CFS' 고정(unique 키 충족용).
    """
    from themek.ontology.core.ids import company_id as _cid
    fiscal_period = _REPRT_PERIOD[reprt_code]
    rows = client.fetch_shares(corp_code=corp_code, bsns_year=bsns_year,
                               reprt_code=reprt_code)
    common = next((r for r in rows
                   if (r.get("se") or "").strip().startswith("보통")), None)
    if common is None:
        return 0
    amount = _to_amount(common.get("istc_totqy"))
    if amount is None:
        return 0
    _ensure_metric_nodes(session)
    _ensure_period_node(session, bsns_year, fiscal_period)
    _upsert_fact(session, _cid(corp_code), "CFS",
                 {"metric_key": "shares_outstanding", "bsns_year": bsns_year,
                  "fiscal_period": fiscal_period, "amount": amount})
    return 1
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `.venv/bin/python -m pytest tests/ontology/test_financials_shares.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: ingest_financials_all 배선**

`src/themek/ontology/pipeline.py`의 `ingest_financials_all`(line 35-67) 내부 reprt 루프(line 59-66)에서, `ingest_financials_for_company` 호출 뒤에 shares 호출 추가:

```python
        for yr in company_years:
            for rc in _REPRT_CODES:
                try:
                    facts += ingest_financials_for_company(
                        session, client, corp_code=dart_code,
                        bsns_year=yr, reprt_code=rc)
                    facts += ingest_shares_for_company(
                        session, client, corp_code=dart_code,
                        bsns_year=yr, reprt_code=rc)
                except Exception as e:  # 회사별 관용
                    failed.append((dart_code, f"{yr}/{rc}: {e}"))
```

그리고 파일 상단의 financials import(line 44 부근)에 `ingest_shares_for_company` 추가:

```python
    from themek.ontology.ingest.financials import (
        ingest_financials_for_company, ingest_shares_for_company)
```

- [ ] **Step 7: 회귀 테스트 — pipeline rebuild 여전히 동작**

Run: `.venv/bin/python -m pytest tests/ontology/test_pipeline.py -v`
Expected: PASS. (FakeClient에 `fetch_shares`가 없으면 AttributeError → 회사별 except로 흡수되어 facts만 줄어듦. 기존 `test_rebuild_financials_*`의 FakeClient에 `fetch_shares` 빈 메서드를 추가해야 한다.)

> `tests/ontology/test_pipeline.py`의 rebuild 테스트 `_FakeClient`에 추가:
> ```python
>     def fetch_shares(self, *, corp_code, bsns_year, reprt_code):
>         return []
> ```

- [ ] **Step 8: 커밋**

```bash
git add src/themek/dart/client.py src/themek/ontology/ingest/financials.py src/themek/ontology/pipeline.py tests/ontology/test_financials_shares.py tests/ontology/test_pipeline.py
git commit -m "feat(financials): ingest shares_outstanding from stockTotqySttus endpoint"
```

---

## Self-Review

- **Spec coverage:** §5.1 METRIC_KEYS→Task 1 Step3, §5.2 IS/CF 매핑→Task 1 Step4, §5.3 발행주식수→Task 3. enum CHECK 마이그레이션(실 DB 필수)→Task 2.
- **Placeholder scan:** 없음. 모든 스텝에 실제 코드.
- **Type consistency:** `ingest_shares_for_company(session, client, *, corp_code, bsns_year, reprt_code)->int` — Task 3 정의·테스트·pipeline 배선 일관. `_REPRT_PERIOD`/`_to_amount`/`_upsert_fact`/`_ensure_*` 기존 `financials.py` 심볼 재사용. metric_key 문자열은 Task1 METRIC_KEYS와 일치.
- **알려진 관습:** `shares_outstanding`의 `fs_div="CFS"`는 unique 키 충족용 관습값(연결/별도 무의미) — Task 3 docstring 명시. EPS는 stock이 아닌 flow로 처리(3개년 전개) — 주당 *기간* 이익이므로 타당.
- **Track A 상호작용:** `_FLOW` 확장이 Track A의 stock/flow 분기 위에 얹힘 — eps/cf는 비교연도 전개됨(의도).
