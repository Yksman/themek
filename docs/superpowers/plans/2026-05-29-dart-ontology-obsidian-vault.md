# DART 온톨로지 → Obsidian Vault 생성기 Implementation Plan

> **상태: ✅ 구현 완료** — main 반영됨(2026-05-31 기준, 테스트 314개 통과). 아래 체크박스는 실행 추적용 기록이며 갱신되지 않았을 수 있습니다.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `themek vault build` 한 명령으로 현재 `themek.db`의 DART 온톨로지를 Obsidian vault(markdown + `[[wikilink]]`)로 멱등 생성하고, 데이터 품질 이슈를 `_qa-report.md`로 자동 집계한다.

**Architecture:** 신규 `src/themek/vault/` 패키지에 4개 모듈 — `model.py`(DB→그래프 dataclass + dedupe + 고객 분류), `qa.py`(품질 검사, 순수 함수), `render.py`(markdown 렌더 + 파일명 안전화), `builder.py`(멱등 파일 쓰기 오케스트레이션). CLI에 `vault build` 서브앱 추가. 읽기 전용 — vault는 산출물이며 build마다 생성 하위폴더를 비우고 재기록한다.

**Tech Stack:** Python 3.12+, SQLAlchemy 2.0(읽기), typer(CLI), pytest(in-memory SQLite). 신규 의존성 0 (frontmatter는 직접 직렬화).

**Spec:** `docs/superpowers/specs/2026-05-29-dart-ontology-obsidian-vault-design.md`

---

## File Structure (decomposition)

| 파일 | 책임 |
|------|------|
| `src/themek/vault/__init__.py` | 패키지 마커 (빈 파일) |
| `src/themek/vault/model.py` | `VaultGraph` 및 노드 dataclass, `normalize_name`, `classify_customer`, `build_graph(session)` |
| `src/themek/vault/qa.py` | `Issue` dataclass, `detect_issues(graph)` — 순수 함수 |
| `src/themek/vault/render.py` | `safe_filename`, `customer_slug`, `wikilink`, `frontmatter`, `render_company/segment/customer/region/sector/index/qa_report` |
| `src/themek/vault/builder.py` | `build_vault(session, out_dir)` — graph→issues→파일 멱등 기록 |
| `src/themek/cli.py` (수정) | `vault_app` 등록 + `vault build` 명령 |
| `tests/test_vault_model.py` | `normalize_name`, `classify_customer`, `build_graph` |
| `tests/test_vault_qa.py` | `detect_issues` 전 항목 |
| `tests/test_vault_render.py` | 렌더 헬퍼 + 노드 렌더 |
| `tests/test_vault_builder.py` | `build_vault` 통합 + 멱등 |
| `tests/test_cli_vault.py` | CLI `vault build` 통합 |
| `vault/` | 산출물 (build가 생성). git: `.obsidian/` ignore, 생성 md는 tracked |

**의존 방향:** `cli → builder → {model, qa, render}`. `render`는 `model`/`qa`의 dataclass에만 의존. `qa`는 `model`에만 의존. `model`은 DB에만 의존.

---

## Task 0: 스캐폴딩 + gitignore (V8 확정)

**Files:**
- Create: `src/themek/vault/__init__.py`
- Modify: `.gitignore`

- [ ] **Step 1: 패키지 디렉토리/마커 생성**

```bash
mkdir -p src/themek/vault
printf '"""Obsidian vault 생성기 — DART 온톨로지를 markdown vault로 렌더."""\n' > src/themek/vault/__init__.py
```

- [ ] **Step 2: .gitignore에 Obsidian 사용자 설정 제외 추가 (V8 결정: 생성 md는 tracked, .obsidian 작업파일만 ignore)**

`.gitignore` 끝에 다음 블록을 append:

```gitignore

# Obsidian vault (생성 산출물): 노트는 tracked, 사용자 작업 상태/캐시만 ignore
/vault/.obsidian/workspace*
/vault/.obsidian/cache
/vault/.trash/
```

- [ ] **Step 3: import 가능 확인**

Run: `uv run python -c "import themek.vault; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add src/themek/vault/__init__.py .gitignore
git commit -m "chore(vault): scaffold vault package + gitignore obsidian workfiles"
```

✅ **Success Gate:** `uv run python -c "import themek.vault"` 가 exit 0. `git status`에 `src/themek/vault/__init__.py` tracked, `.gitignore`에 `/vault/.obsidian/workspace*` 라인 존재.

---

## Task 1: model.py — dataclass + normalize_name + classify_customer (순수 함수)

**Files:**
- Create: `src/themek/vault/model.py`
- Test: `tests/test_vault_model.py`

- [ ] **Step 1: dataclass + 순수 함수 테스트 작성**

`tests/test_vault_model.py`:

```python
"""vault.model — dataclass·정규화·고객 분류 단위 테스트."""
from themek.vault.model import normalize_name, classify_customer


def test_normalize_name_collapses_whitespace_and_case():
    assert normalize_name("  Apple   Inc. ") == "apple inc."
    assert normalize_name("메모리반도체") == "메모리반도체"
    assert normalize_name("DX 부문") == "dx 부문"


def test_classify_customer_entity_short_propernoun():
    assert classify_customer("Apple Inc.") == "entity"
    assert classify_customer("Qualcomm") == "entity"
    assert classify_customer("Best Buy") == "entity"
    assert classify_customer("Deutsche Telekom") == "entity"


def test_classify_customer_descriptive_by_token():
    assert classify_customer("주요 글로벌 IT 고객사 (비공개)") == "descriptive"
    assert classify_customer("DRAM 수요처") == "descriptive"


def test_classify_customer_descriptive_by_length():
    raw = "세계 유수의 Mobile 및 Computing 관련 전자 업체 (DRAM 수요처)"
    assert classify_customer(raw) == "descriptive"


def test_classify_customer_descriptive_by_list_separators():
    assert classify_customer("합성수지, 플라스틱 가공업체, 가전제품 생산업체") == "descriptive"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_vault_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.vault.model'`

- [ ] **Step 3: model.py 작성 (dataclass + 두 순수 함수)**

`src/themek/vault/model.py`:

```python
"""DB → 내부 그래프 모델. 노드/엣지 dataclass + 정규화/분류 + build_graph."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.db.models import (
    Corporation, Stock, BusinessReport, BusinessSegment,
    RevenueComposition, CustomerRelation, GeographicExposure, Region,
)

_WS = re.compile(r"\s+")
_DESCRIPTIVE_TOKENS = (
    "수요처", "업체", "제조업체", "생산업체", "고객사", "비공개",
    "메이커", "디바이스", "수요", "거래처",
)
_DESCRIPTIVE_LEN = 20


def normalize_name(s: str) -> str:
    """dedupe 키용 정규화: trim + 공백 단일화 + 소문자."""
    return _WS.sub(" ", s.strip()).lower()


def classify_customer(raw: str) -> str:
    """buyer_raw를 'entity'(실회사 후보) | 'descriptive'(설명문)로 분류."""
    t = raw.strip()
    if len(t) > _DESCRIPTIVE_LEN:
        return "descriptive"
    if any(tok in t for tok in _DESCRIPTIVE_TOKENS):
        return "descriptive"
    if "," in t or "/" in t:
        return "descriptive"
    return "entity"


@dataclass
class SegmentLine:
    name_ko: str
    share_pct: float | None


@dataclass
class CustomerLine:
    raw: str
    tier: str
    revenue_share_pct: float | None
    resolved: bool


@dataclass
class RegionLine:
    code: str
    name_ko: str
    share_pct: float


@dataclass
class ReportLine:
    rcept_no: str
    period: str
    report_type: str
    url: str | None


@dataclass
class CompanyNode:
    dart_code: str
    name_ko: str
    name_en: str | None
    ticker: str | None
    market: str | None
    sector_name: str | None
    periods: list[str]
    reports: list[ReportLine] = field(default_factory=list)
    segments: list[SegmentLine] = field(default_factory=list)
    customers: list[CustomerLine] = field(default_factory=list)
    regions: list[RegionLine] = field(default_factory=list)


@dataclass
class SegmentNode:
    name_ko: str
    companies: list[str] = field(default_factory=list)


@dataclass
class CustomerNode:
    raw: str
    kind: str
    resolved: bool
    named_by: list[str] = field(default_factory=list)


@dataclass
class RegionNode:
    code: str
    name_ko: str
    companies: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class SectorNode:
    fics_code: str
    name_ko: str
    parent_name: str | None
    companies: list[str] = field(default_factory=list)


@dataclass
class VaultGraph:
    companies: list[CompanyNode] = field(default_factory=list)
    segments: list[SegmentNode] = field(default_factory=list)
    customers: list[CustomerNode] = field(default_factory=list)
    regions: list[RegionNode] = field(default_factory=list)
    sectors: list[SectorNode] = field(default_factory=list)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_vault_model.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/vault/model.py tests/test_vault_model.py
git commit -m "feat(vault): model dataclasses + normalize_name + classify_customer"
```

✅ **Success Gate:** `uv run pytest tests/test_vault_model.py -v` → 5 passed, 0 failed. `classify_customer`가 4개 분류 케이스(entity / token / length / separator) 모두 정확.

---

## Task 2: model.build_graph — DB → VaultGraph

**Files:**
- Modify: `src/themek/vault/model.py` (build_graph + 헬퍼 추가)
- Test: `tests/test_vault_model.py` (append)

- [ ] **Step 1: build_graph 테스트 작성 (db_session 시드)**

`tests/test_vault_model.py` 상단 import에 추가:

```python
from datetime import date
from themek.db.models import (
    Corporation, Stock, Sector, Region, BusinessReport, BusinessSegment,
    RevenueComposition, CustomerRelation, GeographicExposure,
)
from themek.vault.model import build_graph
```

파일 끝에 시드 헬퍼 + 테스트 추가:

```python
def _seed_two_companies(s):
    """삼성(보고서 有) + 빈회사(보고서 無) 시드. 삼성·현대가 같은 'Apple Inc.' 지목."""
    sec = Sector(fics_code="G2520", name_ko="반도체")
    s.add(sec)
    s.add(Region(code="US", name_ko="미주"))
    s.add(Region(code="CN", name_ko="중국"))
    # 삼성: 보고서 있음
    s.add(Corporation(dart_code="00126380", name_ko="삼성전자",
                      name_en="Samsung", in_sector_id="G2520"))
    s.add(Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
                share_class="common", issued_by_id="00126380"))
    # 현대: 보고서 있음 (Apple 공동 지목 검증용)
    s.add(Corporation(dart_code="00164742", name_ko="현대자동차"))
    s.add(Stock(ticker="005380", name_ko="현대자동차", market="KOSPI",
                share_class="common", issued_by_id="00164742"))
    # 빈 회사: 보고서 없음 → 그래프 제외돼야 함
    s.add(Corporation(dart_code="99999999", name_ko="빈회사"))
    s.flush()

    s.add(BusinessReport(dart_rcept_no="20240314000001", corporation_id="00126380",
                         report_type="사업보고서", period="2023",
                         filing_date=date(2024, 3, 14), url="http://dart/1"))
    s.add(BusinessReport(dart_rcept_no="20240315000002", corporation_id="00164742",
                         report_type="사업보고서", period="2023",
                         filing_date=date(2024, 3, 15)))
    # 삼성 세그먼트 2개 (하나는 매출비중 有, 하나는 無)
    s.add(BusinessSegment(id="seg-mem", corporation_id="00126380", name_ko="메모리반도체"))
    s.add(BusinessSegment(id="seg-dx", corporation_id="00126380", name_ko="DX 부문"))
    s.flush()
    s.add(RevenueComposition(id="rc1", subject_segment_id="seg-mem",
                             period="2023", share_pct=42.5,
                             source_report_id="20240314000001"))
    # 삼성 고객 2건: Apple(entity) + 설명문(descriptive)
    s.add(CustomerRelation(id="cr1", seller_id="00126380", buyer_raw="Apple Inc.",
                           resolved=False, period="2023", tier="1차",
                           revenue_share_pct=18, source_report_id="20240314000001"))
    s.add(CustomerRelation(id="cr2", seller_id="00126380",
                           buyer_raw="주요 글로벌 IT 고객사 (비공개)",
                           resolved=False, period="2023", tier="unknown",
                           source_report_id="20240314000001"))
    # 현대도 Apple 지목 → named_by에 2개사
    s.add(CustomerRelation(id="cr3", seller_id="00164742", buyer_raw="Apple Inc.",
                           resolved=False, period="2023", tier="1차",
                           source_report_id="20240315000002"))
    # 삼성 지역노출 corp-level: 미주 2회(중복) + 중국 1회
    s.add(GeographicExposure(id="ge1", subject_corp_id="00126380", region_id="US",
                             period="2023", share_pct=35,
                             source_report_id="20240314000001"))
    s.add(GeographicExposure(id="ge2", subject_corp_id="00126380", region_id="US",
                             period="2023", share_pct=31.1,
                             source_report_id="20240314000001"))
    s.add(GeographicExposure(id="ge3", subject_corp_id="00126380", region_id="CN",
                             period="2023", share_pct=25.8,
                             source_report_id="20240314000001"))
    s.commit()


def test_build_graph_includes_only_companies_with_reports(db_session):
    _seed_two_companies(db_session)
    graph = build_graph(db_session)
    names = {c.name_ko for c in graph.companies}
    assert names == {"삼성전자", "현대자동차"}  # 빈회사 제외


def test_build_graph_company_fields(db_session):
    _seed_two_companies(db_session)
    graph = build_graph(db_session)
    samsung = next(c for c in graph.companies if c.name_ko == "삼성전자")
    assert samsung.ticker == "005930"
    assert samsung.market == "KOSPI"
    assert samsung.sector_name == "반도체"
    assert samsung.periods == ["2023"]
    assert len(samsung.reports) == 1
    # 세그먼트: 매출비중 有/無 둘 다 존재
    shares = {sl.name_ko: sl.share_pct for sl in samsung.segments}
    assert shares["메모리반도체"] == 42.5
    assert shares["DX 부문"] is None


def test_build_graph_dedupes_customer_node_and_aggregates_named_by(db_session):
    _seed_two_companies(db_session)
    graph = build_graph(db_session)
    apple = next(n for n in graph.customers if n.raw == "Apple Inc.")
    assert apple.kind == "entity"
    assert apple.resolved is False
    assert set(apple.named_by) == {"삼성전자", "현대자동차"}  # 공동 지목 병합


def test_build_graph_region_node_collects_company_shares(db_session):
    _seed_two_companies(db_session)
    graph = build_graph(db_session)
    us = next(n for n in graph.regions if n.code == "US")
    # 미주에 삼성이 2회 노출(중복) → 두 share 모두 수집
    samsung_shares = sorted(sh for name, sh in us.companies if name == "삼성전자")
    assert samsung_shares == [31.1, 35.0]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_vault_model.py -k build_graph -v`
Expected: FAIL — `ImportError: cannot import name 'build_graph'`

- [ ] **Step 3: build_graph + 헬퍼 구현 (model.py 끝에 추가)**

`src/themek/vault/model.py` 끝에 append:

```python
def _collapse_segments(rows) -> list[SegmentLine]:
    """(BusinessSegment, share_pct) 행들을 세그먼트당 1줄로. 같은 세그먼트 다중 share면 max."""
    best: dict[str, tuple[str, float | None]] = {}
    for seg, share in rows:
        share_f = float(share) if share is not None else None
        cur = best.get(seg.id)
        if cur is None:
            best[seg.id] = (seg.name_ko, share_f)
        else:
            name, cur_share = cur
            if share_f is not None and (cur_share is None or share_f > cur_share):
                best[seg.id] = (name, share_f)
    return [SegmentLine(name_ko=n, share_pct=sh) for (n, sh) in best.values()]


def build_graph(session: Session) -> VaultGraph:
    """현재 DB에서 '보고서가 적재된 회사'를 진입점으로 VaultGraph를 구성."""
    corp_ids = sorted(session.execute(
        select(BusinessReport.corporation_id).distinct()
    ).scalars().all())

    companies: list[CompanyNode] = []
    seg_map: dict[str, SegmentNode] = {}
    cust_map: dict[str, CustomerNode] = {}
    region_map: dict[str, RegionNode] = {}
    sector_map: dict[str, SectorNode] = {}

    for corp_id in corp_ids:
        corp = session.get(Corporation, corp_id)
        if corp is None:
            continue

        stock = session.execute(
            select(Stock).where(Stock.issued_by_id == corp_id)
            .order_by(Stock.share_class, Stock.ticker)
        ).scalars().first()

        reports = session.execute(
            select(BusinessReport).where(BusinessReport.corporation_id == corp_id)
            .order_by(BusinessReport.filing_date.desc())
        ).scalars().all()
        report_lines = [
            ReportLine(rcept_no=r.dart_rcept_no, period=r.period,
                       report_type=r.report_type, url=r.url)
            for r in reports
        ]
        periods = sorted({r.period for r in reports})

        seg_rows = session.execute(
            select(BusinessSegment, RevenueComposition.share_pct)
            .join(RevenueComposition,
                  RevenueComposition.subject_segment_id == BusinessSegment.id,
                  isouter=True)
            .where(BusinessSegment.corporation_id == corp_id)
        ).all()
        seg_lines = sorted(
            _collapse_segments(seg_rows),
            key=lambda sl: (sl.share_pct is None, -(sl.share_pct or 0.0), sl.name_ko),
        )

        cust_rows = session.execute(
            select(CustomerRelation).where(CustomerRelation.seller_id == corp_id)
            .order_by(CustomerRelation.id)
        ).scalars().all()
        cust_lines = [
            CustomerLine(
                raw=(c.buyer_raw or (c.buyer_corp.name_ko if c.buyer_corp else "?")),
                tier=c.tier,
                revenue_share_pct=(float(c.revenue_share_pct)
                                   if c.revenue_share_pct is not None else None),
                resolved=c.resolved,
            )
            for c in cust_rows
        ]

        geo_rows = session.execute(
            select(GeographicExposure, Region)
            .join(Region, Region.code == GeographicExposure.region_id)
            .where(GeographicExposure.subject_corp_id == corp_id)
            .order_by(GeographicExposure.share_pct.desc())
        ).all()
        region_lines = [
            RegionLine(code=g.region_id, name_ko=region.name_ko,
                       share_pct=float(g.share_pct))
            for g, region in geo_rows
        ]

        companies.append(CompanyNode(
            dart_code=corp.dart_code, name_ko=corp.name_ko, name_en=corp.name_en,
            ticker=(stock.ticker if stock else None),
            market=(stock.market if stock else None),
            sector_name=(corp.in_sector.name_ko if corp.in_sector else None),
            periods=periods, reports=report_lines,
            segments=seg_lines, customers=cust_lines, regions=region_lines,
        ))

        for sl in seg_lines:
            sn = seg_map.setdefault(normalize_name(sl.name_ko),
                                    SegmentNode(name_ko=sl.name_ko))
            if corp.name_ko not in sn.companies:
                sn.companies.append(corp.name_ko)
        for cl in cust_lines:
            cn = cust_map.setdefault(
                normalize_name(cl.raw),
                CustomerNode(raw=cl.raw, kind=classify_customer(cl.raw),
                             resolved=cl.resolved),
            )
            if corp.name_ko not in cn.named_by:
                cn.named_by.append(corp.name_ko)
        for rl in region_lines:
            rn = region_map.setdefault(rl.code,
                                       RegionNode(code=rl.code, name_ko=rl.name_ko))
            rn.companies.append((corp.name_ko, rl.share_pct))
        if corp.in_sector is not None:
            sec = corp.in_sector
            secn = sector_map.setdefault(
                sec.fics_code,
                SectorNode(fics_code=sec.fics_code, name_ko=sec.name_ko,
                           parent_name=(sec.parent_sector.name_ko
                                        if sec.parent_sector else None)),
            )
            if corp.name_ko not in secn.companies:
                secn.companies.append(corp.name_ko)

    return VaultGraph(
        companies=companies,
        segments=sorted(seg_map.values(), key=lambda n: n.name_ko),
        customers=sorted(cust_map.values(), key=lambda n: n.raw),
        regions=sorted(region_map.values(), key=lambda n: n.code),
        sectors=sorted(sector_map.values(), key=lambda n: n.fics_code),
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_vault_model.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/vault/model.py tests/test_vault_model.py
git commit -m "feat(vault): build_graph — DB to VaultGraph with dedupe + named_by"
```

✅ **Success Gate:** `uv run pytest tests/test_vault_model.py -v` → 9 passed. 검증: (1) 보고서 없는 회사 제외, (2) Apple Inc. 노드의 `named_by`가 삼성·현대 병합, (3) 미주 중복 share 2개 모두 수집, (4) 매출비중 없는 세그먼트 share_pct=None 보존.

---

## Task 3: qa.py — detect_issues

**Files:**
- Create: `src/themek/vault/qa.py`
- Test: `tests/test_vault_qa.py`

- [ ] **Step 1: detect_issues 테스트 작성**

`tests/test_vault_qa.py`:

```python
"""vault.qa — 데이터 품질 검출 단위 테스트. VaultGraph dataclass를 직접 구성."""
from themek.vault.model import (
    VaultGraph, CompanyNode, CustomerNode, RegionLine, SegmentLine,
)
from themek.vault.qa import detect_issues


def _company(**kw):
    base = dict(dart_code="X", name_ko="회사", name_en=None, ticker=None,
                market=None, sector_name=None, periods=["2023"])
    base.update(kw)
    return CompanyNode(**base)


def test_detects_geo_duplicate():
    c = _company(regions=[RegionLine("US", "미주", 35.0),
                          RegionLine("US", "미주", 31.1)],
                 segments=[SegmentLine("a", 50.0), SegmentLine("b", 50.0)],
                 customers=[1])  # customers non-empty to avoid missing flag
    issues = detect_issues(VaultGraph(companies=[c]))
    kinds = [i.kind for i in issues if i.company == "회사"]
    assert "geo_duplicate" in kinds


def test_detects_revenue_sum_anomaly():
    c = _company(segments=[SegmentLine("DX", 60.4), SegmentLine("메모리", 42.5),
                           SegmentLine("DS", 32.6)],
                 regions=[RegionLine("US", "미주", 50.0)], customers=[1])
    issues = detect_issues(VaultGraph(companies=[c]))
    sums = [i for i in issues if i.kind == "revenue_sum_anomaly"]
    assert len(sums) == 1
    assert "135.5" in sums[0].detail


def test_detects_low_segment_count():
    c = _company(segments=[SegmentLine("only", 100.0)],
                 regions=[RegionLine("US", "미주", 100.0)], customers=[1])
    issues = detect_issues(VaultGraph(companies=[c]))
    assert any(i.kind == "low_segment_count" for i in issues)


def test_detects_missing_geo_and_customer():
    c = _company(segments=[SegmentLine("a", 50.0), SegmentLine("b", 50.0)],
                 regions=[], customers=[])
    kinds = {i.kind for i in detect_issues(VaultGraph(companies=[c]))}
    assert "missing_geo" in kinds
    assert "missing_customer" in kinds


def test_detects_segment_no_revenue():
    c = _company(segments=[SegmentLine("a", 50.0), SegmentLine("b", None)],
                 regions=[RegionLine("US", "미주", 50.0)], customers=[1])
    assert any(i.kind == "segment_no_revenue" for i in detect_issues(VaultGraph(companies=[c])))


def test_unresolved_customer_summary_counts_kinds():
    graph = VaultGraph(
        companies=[],
        customers=[
            CustomerNode(raw="Apple Inc.", kind="entity", resolved=False, named_by=["A"]),
            CustomerNode(raw="설명문 고객사", kind="descriptive", resolved=False, named_by=["A"]),
        ],
    )
    issues = detect_issues(graph)
    u = [i for i in issues if i.kind == "unresolved_customer"]
    assert len(u) == 1
    assert "entity 1" in u[0].detail and "descriptive 1" in u[0].detail


def test_clean_company_has_no_warn_issues():
    c = _company(segments=[SegmentLine("a", 50.0), SegmentLine("b", 50.0)],
                 regions=[RegionLine("US", "미주", 60.0), RegionLine("CN", "중국", 40.0)],
                 customers=[1])
    warns = [i for i in detect_issues(VaultGraph(companies=[c])) if i.severity == "warn"]
    assert warns == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_vault_qa.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.vault.qa'`

- [ ] **Step 3: qa.py 구현**

`src/themek/vault/qa.py`:

```python
"""데이터 품질 검사 — VaultGraph를 받아 Issue 리스트를 반환하는 순수 함수."""
from __future__ import annotations

from dataclasses import dataclass

from themek.vault.model import VaultGraph

_SUM_LOW = 90.0
_SUM_HIGH = 110.0


@dataclass
class Issue:
    company: str   # 회사 name_ko, 전역 이슈는 ""
    kind: str
    severity: str  # error | warn | info
    detail: str


def detect_issues(graph: VaultGraph) -> list[Issue]:
    issues: list[Issue] = []

    for c in graph.companies:
        # geo_duplicate: 같은 지역명이 2회+ 노출
        by_region: dict[str, list[float]] = {}
        for r in c.regions:
            by_region.setdefault(r.name_ko, []).append(r.share_pct)
        for name, shares in by_region.items():
            if len(shares) > 1:
                pretty = ", ".join(f"{s:g}%" for s in shares)
                issues.append(Issue(c.name_ko, "geo_duplicate", "warn",
                                    f"지역 '{name}' {len(shares)}회 중복: {pretty}"))

        # revenue_sum_anomaly: 세그먼트 share 합이 100에서 크게 벗어남(중첩 가능)
        present = [s.share_pct for s in c.segments if s.share_pct is not None]
        if present:
            total = sum(present)
            if total > _SUM_HIGH or total < _SUM_LOW:
                issues.append(Issue(c.name_ko, "revenue_sum_anomaly", "warn",
                    f"세그먼트 매출비중 합 {total:.1f}% "
                    f"(세그먼트 {len(c.segments)}개; 중첩 구조 가능)"))

        # low_segment_count
        if len(c.segments) <= 1:
            issues.append(Issue(c.name_ko, "low_segment_count", "warn",
                                f"세그먼트 {len(c.segments)}개 (추출 빈약 가능)"))

        # segment_no_revenue
        for s in c.segments:
            if s.share_pct is None:
                issues.append(Issue(c.name_ko, "segment_no_revenue", "info",
                                    f"세그먼트 '{s.name_ko}' 매출비중 없음"))

        # missing_*
        if not c.regions:
            issues.append(Issue(c.name_ko, "missing_geo", "info", "지역 노출 0건"))
        if not c.customers:
            issues.append(Issue(c.name_ko, "missing_customer", "info", "고객사 0건"))

    # 전역: 미연결 고객 요약
    unresolved = [n for n in graph.customers if not n.resolved]
    if unresolved:
        ent = sum(1 for n in unresolved if n.kind == "entity")
        desc = sum(1 for n in unresolved if n.kind == "descriptive")
        issues.append(Issue("", "unresolved_customer", "info",
            f"미연결 고객사 {len(unresolved)}건 (entity {ent}, descriptive {desc})"))

    return issues
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_vault_qa.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/vault/qa.py tests/test_vault_qa.py
git commit -m "feat(vault): qa.detect_issues — geo dup, revenue sum, missing, unresolved"
```

✅ **Success Gate:** `uv run pytest tests/test_vault_qa.py -v` → 7 passed. 검증: 7개 이슈 종류(geo_duplicate / revenue_sum_anomaly / low_segment_count / missing_geo / missing_customer / segment_no_revenue / unresolved_customer) 모두 정확히 검출되고, 클린 회사는 warn 0건.

---

## Task 4: render.py — 헬퍼 (frontmatter / wikilink / 파일명 안전화)

**Files:**
- Create: `src/themek/vault/render.py`
- Test: `tests/test_vault_render.py`

- [ ] **Step 1: 헬퍼 테스트 작성**

`tests/test_vault_render.py`:

```python
"""vault.render — frontmatter·wikilink·파일명 안전화 단위 테스트."""
from themek.vault.render import (
    safe_filename, customer_slug, wikilink, frontmatter,
)


def test_safe_filename_strips_obsidian_unsafe_chars():
    assert safe_filename("CJ CGV") == "CJ CGV"
    assert safe_filename("스마트폰/네트워크") == "스마트폰 네트워크"
    assert safe_filename('A:B*C?"D<E>F|G') == "A B C D E F G"
    assert safe_filename("HD현대마린솔루션") == "HD현대마린솔루션"


def test_customer_slug_short_name_unchanged():
    assert customer_slug("Apple Inc.") == "Apple Inc."


def test_customer_slug_long_name_truncated_with_hash_suffix():
    raw = "세계 유수의 Mobile 및 Computing 관련 전자 업체 (DRAM 수요처)"
    slug = customer_slug(raw, max_len=20)
    assert len(slug) <= 20 + 1 + 6  # 본문 + 공백 + 6자 해시
    # 같은 원문은 항상 같은 slug (안정적)
    assert slug == customer_slug(raw, max_len=20)
    # 다른 원문은 다른 해시
    assert customer_slug(raw, max_len=20) != customer_slug(raw + "x", max_len=20)


def test_wikilink_plain_and_aliased():
    assert wikilink("삼성전자") == "[[삼성전자]]"
    assert wikilink("slug123", "전체 표시명") == "[[slug123|전체 표시명]]"
    # 동일하면 별칭 생략
    assert wikilink("삼성전자", "삼성전자") == "[[삼성전자]]"
    # display의 파이프/대괄호 제거
    assert wikilink("s", "a|b]c") == "[[s|a b c]]"


def test_frontmatter_serializes_valid_yaml_types():
    fm = frontmatter({
        "type": "company", "dart_code": "00126380", "issue_count": 3,
        "resolved": False, "periods": ["2022", "2023"],
    })
    assert fm.startswith("---\n") and fm.rstrip().endswith("---")
    assert 'type: "company"' in fm
    assert "issue_count: 3" in fm
    assert "resolved: false" in fm
    assert 'periods: ["2022", "2023"]' in fm


def test_frontmatter_escapes_quotes():
    fm = frontmatter({"name": 'A "quoted" name'})
    assert r'name: "A \"quoted\" name"' in fm
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_vault_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.vault.render'`

- [ ] **Step 3: render.py 헬퍼 구현**

`src/themek/vault/render.py`:

```python
"""VaultGraph → markdown 렌더. 파일명 안전화 + frontmatter + wikilink + 노드 렌더."""
from __future__ import annotations

import hashlib
import re

_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')
_WS = re.compile(r"\s+")


def safe_filename(name: str) -> str:
    """Obsidian/파일시스템에서 안전한 basename으로 변환 (확장자 제외)."""
    s = _UNSAFE.sub(" ", name)
    return _WS.sub(" ", s).strip()


def customer_slug(raw: str, max_len: int = 40) -> str:
    """고객사 파일 basename. 길면 잘라내고 원문 해시 6자를 접미 → 충돌 방지·안정적."""
    base = safe_filename(raw)
    if len(base) <= max_len:
        return base
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6]
    return f"{base[:max_len].strip()} {h}"


def _clean_link_text(s: str) -> str:
    return s.replace("[", "").replace("]", "").replace("|", " ")


def wikilink(target: str, display: str | None = None) -> str:
    """[[target]] 또는 [[target|display]]. 대괄호/파이프 제거."""
    t = _clean_link_text(target)
    if display is not None and display != target:
        return f"[[{t}|{_clean_link_text(display)}]]"
    return f"[[{t}]]"


def _yaml_scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def frontmatter(d: dict) -> str:
    """dict → YAML frontmatter 블록 (--- 포함, 끝에 개행)."""
    lines = ["---"]
    for k, v in d.items():
        if isinstance(v, list):
            inner = ", ".join(_yaml_scalar(x) for x in v)
            lines.append(f"{k}: [{inner}]")
        else:
            lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_vault_render.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/vault/render.py tests/test_vault_render.py
git commit -m "feat(vault): render helpers — safe_filename, customer_slug, wikilink, frontmatter"
```

✅ **Success Gate:** `uv run pytest tests/test_vault_render.py -v` → 6 passed. 검증: `스마트폰/네트워크`·`CJ CGV` 등 특수문자 파일명 안전화, 긴 고객명 slug 안정성(동일 입력→동일 출력, 다른 입력→다른 해시), frontmatter가 유효한 YAML 타입 직렬화.

---

## Task 5: render.py — 노드 렌더러 (company/segment/customer/region/sector/index/qa)

**Files:**
- Modify: `src/themek/vault/render.py` (렌더 함수 추가)
- Test: `tests/test_vault_render.py` (append)

- [ ] **Step 1: 노드 렌더 테스트 작성**

`tests/test_vault_render.py` 상단 import에 추가:

```python
from themek.vault.model import (
    CompanyNode, SegmentNode, CustomerNode, RegionNode, SectorNode,
    SegmentLine, CustomerLine, RegionLine, ReportLine, VaultGraph,
)
from themek.vault.render import (
    render_company, render_segment, render_customer, render_region,
    render_sector, render_index, render_qa_report,
)
from themek.vault.qa import Issue, detect_issues
```

파일 끝에 추가:

```python
def _sample_company():
    return CompanyNode(
        dart_code="00126380", name_ko="삼성전자", name_en="Samsung",
        ticker="005930", market="KOSPI", sector_name="반도체", periods=["2023"],
        reports=[ReportLine("20240314000001", "2023", "사업보고서", "http://dart/1")],
        segments=[SegmentLine("메모리반도체", 42.5), SegmentLine("DX 부문", None)],
        customers=[CustomerLine("Apple Inc.", "1차", 18.0, False),
                   CustomerLine("주요 글로벌 IT 고객사 (비공개)", "unknown", None, False)],
        regions=[RegionLine("US", "미주", 35.0)],
    )


def test_render_company_path_and_frontmatter():
    path, text = render_company(_sample_company(), [])
    assert path == "companies/삼성전자.md"
    assert 'type: "company"' in text
    assert 'dart_code: "00126380"' in text
    assert "issue_count: 0" in text
    assert "[[메모리반도체]]" in text
    assert "[[미주]]" in text
    # 매출비중 없는 세그먼트도 렌더
    assert "DX 부문" in text


def test_render_company_links_segments_and_customers():
    path, text = render_company(_sample_company(), [])
    assert "[[Apple Inc.]]" in text
    # 설명문 고객도 링크 (긴 이름은 slug 별칭)
    assert "주요 글로벌 IT 고객사 (비공개)" in text


def test_render_company_embeds_issue_section():
    issues = [Issue("삼성전자", "geo_duplicate", "warn", "지역 '미주' 2회 중복: 35%, 31.1%")]
    path, text = render_company(_sample_company(), issues)
    assert "issue_count: 1" in text
    assert "geo_duplicate" in text
    assert "미주" in text


def test_render_customer_descriptive_tagged_and_named_by():
    node = CustomerNode(raw="주요 글로벌 IT 고객사 (비공개)", kind="descriptive",
                        resolved=False, named_by=["삼성전자", "현대자동차"])
    path, text = render_customer(node)
    assert path.startswith("customers/")
    assert 'kind: "descriptive"' in text
    assert "resolved: false" in text
    assert '"unresolved/descriptive"' in text
    assert "[[삼성전자]]" in text and "[[현대자동차]]" in text


def test_render_segment_lists_companies():
    node = SegmentNode(name_ko="메모리반도체", companies=["삼성전자", "SK하이닉스"])
    path, text = render_segment(node)
    assert path == "segments/메모리반도체.md"
    assert "[[삼성전자]]" in text and "[[SK하이닉스]]" in text


def test_render_region_and_sector():
    rpath, rtext = render_region(RegionNode("US", "미주", [("삼성전자", 35.0)]))
    assert rpath == "regions/미주.md"
    assert "[[삼성전자]]" in rtext and "35" in rtext
    spath, stext = render_sector(SectorNode("G2520", "반도체", None, ["삼성전자"]))
    assert spath == "sectors/반도체.md"
    assert "[[삼성전자]]" in stext


def test_render_index_and_qa_report():
    graph = VaultGraph(companies=[_sample_company()])
    issues = detect_issues(graph)
    ipath, itext = render_index(graph, issues)
    assert ipath == "_index.md"
    assert "[[삼성전자]]" in itext
    qpath, qtext = render_qa_report(graph, issues)
    assert qpath == "_qa-report.md"
    # 미주 단일이라 geo_duplicate 없음; low_segment 아님(2개). 미연결 고객 요약 존재
    assert "unresolved_customer" in qtext or "미연결" in qtext
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_vault_render.py -k "render_company or render_customer or render_segment or render_region or render_index" -v`
Expected: FAIL — `ImportError: cannot import name 'render_company'`

- [ ] **Step 3: 노드 렌더러 구현 (render.py 끝에 추가)**

`src/themek/vault/render.py` 끝에 append:

```python
from themek.vault.model import (  # noqa: E402  (순환 아님 — model은 render 미참조)
    VaultGraph, CompanyNode, SegmentNode, CustomerNode, RegionNode, SectorNode,
)
from themek.vault.qa import Issue  # noqa: E402


def _fmt_pct(v: float | None) -> str:
    return f"{v:g}%" if v is not None else "—"


def render_company(node: CompanyNode, issues: list[Issue]) -> tuple[str, str]:
    fname = safe_filename(node.name_ko)
    fm = frontmatter({
        "type": "company",
        "dart_code": node.dart_code,
        "name_ko": node.name_ko,
        "name_en": node.name_en or "",
        "ticker": node.ticker or "",
        "market": node.market or "",
        "sector": node.sector_name or "",
        "periods": node.periods,
        "report_count": len(node.reports),
        "segment_count": len(node.segments),
        "issue_count": len(issues),
        "tags": ["company"],
    })
    parts = [fm, f"# {node.name_ko}\n"]

    crumb = []
    if node.sector_name:
        crumb.append(wikilink(safe_filename(node.sector_name), node.sector_name))
    if node.market and node.ticker:
        crumb.append(f"{node.market} {node.ticker}")
    crumb.append(f"DART {node.dart_code}")
    parts.append("> " + " · ".join(crumb) + "\n")

    parts.append("\n## 세그먼트\n")
    for s in node.segments:
        link = wikilink(safe_filename(s.name_ko), s.name_ko)
        parts.append(f"- {link} — {_fmt_pct(s.share_pct)}")
    if not node.segments:
        parts.append("- (없음)")

    parts.append("\n## 고객사\n")
    for c in node.customers:
        link = wikilink(customer_slug(c.raw), c.raw)
        meta = []
        if c.tier and c.tier != "unknown":
            meta.append(c.tier)
        if c.revenue_share_pct is not None:
            meta.append(_fmt_pct(c.revenue_share_pct))
        flag = "" if c.resolved else " ⚠️ 미연결"
        suffix = f" ({', '.join(meta)})" if meta else ""
        parts.append(f"- {link}{suffix}{flag}")
    if not node.customers:
        parts.append("- (없음)")

    parts.append("\n## 지역 노출\n")
    for r in node.regions:
        parts.append(f"- {wikilink(safe_filename(r.name_ko), r.name_ko)} — {_fmt_pct(r.share_pct)}")
    if not node.regions:
        parts.append("- (없음)")

    if issues:
        parts.append("\n## ⚠️ 품질 이슈\n")
        for it in issues:
            parts.append(f"- **{it.kind}** ({it.severity}): {it.detail}")

    parts.append("\n## 출처\n")
    for r in node.reports:
        label = f"{r.report_type} {r.period}"
        if r.url:
            parts.append(f"- [{label}]({r.url}) · rcept_no {r.rcept_no}")
        else:
            parts.append(f"- {label} · rcept_no {r.rcept_no}")

    return f"companies/{fname}.md", "\n".join(parts) + "\n"


def render_segment(node: SegmentNode) -> tuple[str, str]:
    fname = safe_filename(node.name_ko)
    fm = frontmatter({"type": "segment", "name_ko": node.name_ko,
                      "company_count": len(node.companies), "tags": ["segment"]})
    parts = [fm, f"# {node.name_ko}\n", "\n## 이 세그먼트를 가진 회사\n"]
    for name in node.companies:
        parts.append(f"- {wikilink(safe_filename(name), name)}")
    return f"segments/{fname}.md", "\n".join(parts) + "\n"


def render_customer(node: CustomerNode) -> tuple[str, str]:
    fname = customer_slug(node.raw)
    fm = frontmatter({
        "type": "customer", "resolved": node.resolved, "kind": node.kind,
        "raw": node.raw, "named_by": node.named_by,
        "tags": ["unresolved", f"unresolved/{node.kind}"] if not node.resolved
                else ["customer"],
    })
    parts = [fm, f"# {node.raw}\n",
             f"\n> 미연결 고객사 ({node.kind})\n" if not node.resolved else "\n",
             "\n## 이 고객사를 지목한 회사\n"]
    for name in node.named_by:
        parts.append(f"- {wikilink(safe_filename(name), name)}")
    return f"customers/{fname}.md", "\n".join(parts) + "\n"


def render_region(node: RegionNode) -> tuple[str, str]:
    fname = safe_filename(node.name_ko)
    fm = frontmatter({"type": "region", "code": node.code, "name_ko": node.name_ko,
                      "tags": ["region"]})
    parts = [fm, f"# {node.name_ko}\n", "\n## 이 지역에 노출된 회사\n"]
    for name, share in node.companies:
        parts.append(f"- {wikilink(safe_filename(name), name)} — {_fmt_pct(share)}")
    return f"regions/{fname}.md", "\n".join(parts) + "\n"


def render_sector(node: SectorNode) -> tuple[str, str]:
    fname = safe_filename(node.name_ko)
    fm = frontmatter({"type": "sector", "fics_code": node.fics_code,
                      "name_ko": node.name_ko, "parent": node.parent_name or "",
                      "tags": ["sector"]})
    parts = [fm, f"# {node.name_ko}\n"]
    if node.parent_name:
        parts.append(f"> 상위: {wikilink(safe_filename(node.parent_name), node.parent_name)}\n")
    parts.append("\n## 소속 회사\n")
    for name in node.companies:
        parts.append(f"- {wikilink(safe_filename(name), name)}")
    return f"sectors/{fname}.md", "\n".join(parts) + "\n"


def render_index(graph: VaultGraph, issues: list[Issue]) -> tuple[str, str]:
    counts: dict[str, int] = {}
    for it in issues:
        if it.company:
            counts[it.company] = counts.get(it.company, 0) + 1
    fm = frontmatter({"type": "index", "tags": ["index"]})
    parts = [fm, "# themek 온톨로지 vault\n",
             f"\n- 회사: {len(graph.companies)}",
             f"- 세그먼트: {len(graph.segments)}",
             f"- 고객사(미연결 포함): {len(graph.customers)}",
             f"- 지역: {len(graph.regions)} · 섹터: {len(graph.sectors)}",
             f"- 검출 이슈: {len(issues)}",
             f"\n관련: [[_qa-report]]\n",
             "\n## 회사 목록\n",
             "| 회사 | 섹터 | 기간 | 세그먼트 | 이슈 |",
             "|------|------|------|----------|------|"]
    for c in sorted(graph.companies, key=lambda x: x.name_ko):
        parts.append(
            f"| {wikilink(safe_filename(c.name_ko), c.name_ko)} "
            f"| {c.sector_name or '—'} | {', '.join(c.periods)} "
            f"| {len(c.segments)} | {counts.get(c.name_ko, 0)} |"
        )
    return "_index.md", "\n".join(parts) + "\n"


def render_qa_report(graph: VaultGraph, issues: list[Issue]) -> tuple[str, str]:
    by_kind: dict[str, list[Issue]] = {}
    for it in issues:
        by_kind.setdefault(it.kind, []).append(it)
    fm = frontmatter({"type": "qa-report", "issue_total": len(issues), "tags": ["qa"]})
    parts = [fm, "# QA 리포트\n", f"\n총 이슈: {len(issues)}\n", "\n## 종류별 집계\n",
             "| 종류 | 건수 |", "|------|------|"]
    for kind in sorted(by_kind):
        parts.append(f"| {kind} | {len(by_kind[kind])} |")
    for kind in sorted(by_kind):
        parts.append(f"\n## {kind}\n")
        for it in by_kind[kind]:
            who = wikilink(safe_filename(it.company), it.company) if it.company else "(전역)"
            parts.append(f"- {who} — {it.detail}")
    return "_qa-report.md", "\n".join(parts) + "\n"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_vault_render.py -v`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/vault/render.py tests/test_vault_render.py
git commit -m "feat(vault): node renderers — company/segment/customer/region/sector/index/qa"
```

✅ **Success Gate:** `uv run pytest tests/test_vault_render.py -v` → 13 passed. 검증: 회사 노트가 frontmatter+세그먼트/고객/지역 wikilink+이슈 섹션 포함, 미연결 descriptive 고객이 `unresolved/descriptive` 태그, index/qa 리포트가 회사 링크 표 생성.

---

## Task 6: builder.py — build_vault 멱등 오케스트레이션

**Files:**
- Create: `src/themek/vault/builder.py`
- Test: `tests/test_vault_builder.py`

- [ ] **Step 1: 통합 + 멱등 테스트 작성**

`tests/test_vault_builder.py`:

```python
"""vault.builder — DB→파일 통합 + 멱등성 테스트."""
from datetime import date

from themek.db.models import (
    Corporation, Stock, Sector, Region, BusinessReport, BusinessSegment,
    RevenueComposition, CustomerRelation, GeographicExposure,
)
from themek.vault.builder import build_vault


def _seed(s):
    s.add(Sector(fics_code="G2520", name_ko="반도체"))
    s.add(Region(code="US", name_ko="미주"))
    s.add(Corporation(dart_code="00126380", name_ko="삼성전자",
                      in_sector_id="G2520"))
    s.add(Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
                share_class="common", issued_by_id="00126380"))
    s.flush()
    s.add(BusinessReport(dart_rcept_no="20240314000001", corporation_id="00126380",
                         report_type="사업보고서", period="2023",
                         filing_date=date(2024, 3, 14)))
    s.add(BusinessSegment(id="seg-mem", corporation_id="00126380", name_ko="메모리반도체"))
    s.flush()
    s.add(RevenueComposition(id="rc1", subject_segment_id="seg-mem", period="2023",
                             share_pct=42.5, source_report_id="20240314000001"))
    s.add(CustomerRelation(id="cr1", seller_id="00126380", buyer_raw="Apple Inc.",
                           resolved=False, period="2023", tier="1차",
                           source_report_id="20240314000001"))
    s.add(GeographicExposure(id="ge1", subject_corp_id="00126380", region_id="US",
                             period="2023", share_pct=35,
                             source_report_id="20240314000001"))
    s.commit()


def test_build_vault_creates_expected_tree(tmp_path, db_session):
    _seed(db_session)
    stats = build_vault(db_session, tmp_path)
    assert stats["companies"] == 1
    assert (tmp_path / "_index.md").exists()
    assert (tmp_path / "_qa-report.md").exists()
    assert (tmp_path / "companies" / "삼성전자.md").exists()
    assert (tmp_path / "segments" / "메모리반도체.md").exists()
    assert (tmp_path / "regions" / "미주.md").exists()
    assert (tmp_path / "sectors" / "반도체.md").exists()
    assert list((tmp_path / "customers").glob("*.md"))


def test_build_vault_idempotent_same_output(tmp_path, db_session):
    _seed(db_session)
    build_vault(db_session, tmp_path)
    first = (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8")
    build_vault(db_session, tmp_path)  # 재실행
    second = (tmp_path / "companies" / "삼성전자.md").read_text(encoding="utf-8")
    assert first == second


def test_build_vault_clears_stale_generated_files(tmp_path, db_session):
    _seed(db_session)
    build_vault(db_session, tmp_path)
    stale = tmp_path / "companies" / "삭제될회사.md"
    stale.write_text("stale", encoding="utf-8")
    build_vault(db_session, tmp_path)  # 재생성
    assert not stale.exists()  # 생성 폴더는 비우고 재기록


def test_build_vault_preserves_obsidian_dir(tmp_path, db_session):
    _seed(db_session)
    obs = tmp_path / ".obsidian"
    obs.mkdir(parents=True)
    (obs / "app.json").write_text("{}", encoding="utf-8")
    build_vault(db_session, tmp_path)
    assert (obs / "app.json").exists()  # 사용자 설정 보존
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_vault_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.vault.builder'`

- [ ] **Step 3: builder.py 구현**

`src/themek/vault/builder.py`:

```python
"""build_vault — VaultGraph + issues를 markdown 파일 트리로 멱등 기록."""
from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from themek.vault.model import build_graph
from themek.vault.qa import detect_issues
from themek.vault import render

_GENERATED_DIRS = ("companies", "segments", "customers", "regions", "sectors")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_vault(session: Session, out_dir: Path) -> dict:
    """현재 DB → out_dir vault. 생성 하위폴더만 비우고 재기록 (멱등, .obsidian 보존)."""
    out_dir = Path(out_dir)
    graph = build_graph(session)
    issues = detect_issues(graph)

    out_dir.mkdir(parents=True, exist_ok=True)
    for d in _GENERATED_DIRS:
        p = out_dir / d
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True)

    by_company: dict[str, list] = {}
    for it in issues:
        if it.company:
            by_company.setdefault(it.company, []).append(it)

    for c in graph.companies:
        rel, text = render.render_company(c, by_company.get(c.name_ko, []))
        _write(out_dir / rel, text)
    for s in graph.segments:
        rel, text = render.render_segment(s)
        _write(out_dir / rel, text)
    for cust in graph.customers:
        rel, text = render.render_customer(cust)
        _write(out_dir / rel, text)
    for r in graph.regions:
        rel, text = render.render_region(r)
        _write(out_dir / rel, text)
    for sec in graph.sectors:
        rel, text = render.render_sector(sec)
        _write(out_dir / rel, text)

    _, idx = render.render_index(graph, issues)
    _write(out_dir / "_index.md", idx)
    _, qa = render.render_qa_report(graph, issues)
    _write(out_dir / "_qa-report.md", qa)

    return {
        "companies": len(graph.companies),
        "segments": len(graph.segments),
        "customers": len(graph.customers),
        "regions": len(graph.regions),
        "sectors": len(graph.sectors),
        "issues": len(issues),
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_vault_builder.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/vault/builder.py tests/test_vault_builder.py
git commit -m "feat(vault): build_vault — idempotent file tree generation"
```

✅ **Success Gate:** `uv run pytest tests/test_vault_builder.py -v` → 4 passed. 검증: (1) 기대 파일 트리 생성, (2) 재실행 시 회사 노트 내용 동일(멱등), (3) 생성 폴더의 stale 파일 제거, (4) `.obsidian/` 사용자 설정 보존.

---

## Task 7: CLI — `themek vault build`

**Files:**
- Modify: `src/themek/cli.py`
- Test: `tests/test_cli_vault.py`

- [ ] **Step 1: CLI 통합 테스트 작성**

`tests/test_cli_vault.py`:

```python
"""CLI `themek vault build` 통합 테스트. 테스트 DB(conftest temp)에 커밋 후 실행."""
from datetime import date

from typer.testing import CliRunner

from themek.cli import app
from themek.db.engine import make_engine, make_session_factory
from themek.db.models import (
    Corporation, Stock, Sector, Region, BusinessReport, BusinessSegment,
    RevenueComposition, CustomerRelation, GeographicExposure,
)

runner = CliRunner()


def _seed_committed():
    s = make_session_factory(make_engine())()
    s.add(Sector(fics_code="G2520", name_ko="반도체"))
    s.add(Region(code="US", name_ko="미주"))
    s.add(Corporation(dart_code="00126380", name_ko="삼성전자", in_sector_id="G2520"))
    s.add(Stock(ticker="005930", name_ko="삼성전자", market="KOSPI",
                share_class="common", issued_by_id="00126380"))
    s.flush()
    s.add(BusinessReport(dart_rcept_no="20240314000001", corporation_id="00126380",
                         report_type="사업보고서", period="2023",
                         filing_date=date(2024, 3, 14)))
    s.add(BusinessSegment(id="seg-mem", corporation_id="00126380", name_ko="메모리반도체"))
    s.flush()
    s.add(RevenueComposition(id="rc1", subject_segment_id="seg-mem", period="2023",
                             share_pct=42.5, source_report_id="20240314000001"))
    s.add(CustomerRelation(id="cr1", seller_id="00126380", buyer_raw="Apple Inc.",
                           resolved=False, period="2023", tier="1차",
                           source_report_id="20240314000001"))
    s.add(GeographicExposure(id="ge1", subject_corp_id="00126380", region_id="US",
                             period="2023", share_pct=35,
                             source_report_id="20240314000001"))
    s.commit()
    s.close()


def test_vault_build_cli(tmp_path, fresh_db):
    _seed_committed()
    out = tmp_path / "vault"
    result = runner.invoke(app, ["vault", "build", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "vault built" in result.output
    assert "1 companies" in result.output
    assert (out / "_index.md").exists()
    assert (out / "_qa-report.md").exists()
    assert (out / "companies" / "삼성전자.md").exists()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/test_cli_vault.py -v`
Expected: FAIL — `vault` 명령 없음 → exit_code != 0 (typer "No such command")

- [ ] **Step 3: cli.py에 vault 서브앱 + build 명령 추가**

`src/themek/cli.py` import 블록(상단)에 추가:

```python
from themek.vault.builder import build_vault
```

`src/themek/cli.py`의 서브앱 등록부(`krx_app = ...` 줄 다음, line ~46)에 추가:

```python
vault_app = typer.Typer(help="Obsidian vault 생성 명령")
app.add_typer(vault_app, name="vault")
```

`src/themek/cli.py` 끝부분(다른 명령들과 같은 모듈 레벨)에 명령 추가:

```python
@vault_app.command("build")
def vault_build_cmd(
    out: str = typer.Option("vault", "--out", help="vault 출력 디렉토리"),
    db: Optional[str] = typer.Option(None, "--db", help="DB DSN override"),
):
    """현재 DB의 DART 온톨로지를 Obsidian vault로 멱등 생성."""
    if db:
        from sqlalchemy import create_engine
        engine = create_engine(db, future=True)
        session = make_session_factory(engine)()
    else:
        session = _session()
    with session as s:
        stats = build_vault(s, Path(out))
    typer.echo(
        f"vault built: {stats['companies']} companies, "
        f"{stats['segments']} segments, {stats['regions']} regions, "
        f"{stats['customers']} customers, {stats['issues']} issues → {out}/"
    )
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/test_cli_vault.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: 전체 스위트 회귀 확인**

Run: `uv run pytest -q`
Expected: 기존 테스트 + 신규 테스트 모두 PASS (실패 0)

- [ ] **Step 6: Commit**

```bash
git add src/themek/cli.py tests/test_cli_vault.py
git commit -m "feat(vault): themek vault build CLI command"
```

✅ **Success Gate:** `uv run pytest tests/test_cli_vault.py -v` → 1 passed. `uv run pytest -q` → 전체 스위트 실패 0건. `themek vault build` 가 exit 0 + "vault built: N companies..." stdout + `_index.md`/`_qa-report.md`/`companies/*.md` 생성.

---

## Task 8: 실 DB smoke build + README + 검증 메모

**Files:**
- Create: `docs/vault-smoke-notes.md`
- Modify: `README.md`

- [ ] **Step 1: 실 themek.db로 vault build 실행**

Run: `uv run themek vault build --out vault`
Expected: exit 0 + `vault built: 44 companies, ... issues → vault/` (회사 수는 현 적재 상태 기준; 44 내외)

- [ ] **Step 2: 산출물 sanity 확인 (자동 점검)**

Run:
```bash
echo "companies: $(ls vault/companies/*.md | wc -l)"
echo "customers: $(ls vault/customers/*.md | wc -l)"
test -f vault/_index.md && test -f vault/_qa-report.md && echo "index+qa OK"
grep -l "미주" vault/companies/삼성전자.md && echo "samsung geo OK"
grep -c "geo_duplicate" vault/_qa-report.md
```
Expected: companies ≥ 40, customers ≥ 1, "index+qa OK", "samsung geo OK", geo_duplicate ≥ 1 (삼성 미주 중복 검출)

- [ ] **Step 3: wikilink 무결성 자동 점검 (깨진 링크가 과도하지 않은지)**

Run:
```bash
uv run python - <<'PY'
import re, pathlib
vault = pathlib.Path("vault")
files = {p.stem for p in vault.rglob("*.md")}
links = set()
for p in vault.rglob("*.md"):
    for m in re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", p.read_text(encoding="utf-8")):
        links.add(m.strip())
missing = sorted(l for l in links if l not in files and not l.startswith("_"))
print(f"total link targets: {len(links)}, missing files: {len(missing)}")
print("sample missing:", missing[:10])
PY
```
Expected: missing files == 0 (모든 wikilink 대상 노트가 실제 존재). 0이 아니면 `safe_filename`/`customer_slug` 불일치 → Task 4/5 회귀.

- [ ] **Step 4: Obsidian 육안 확인 메모 작성**

`docs/vault-smoke-notes.md`:

```markdown
# Vault Smoke Build — 검증 메모 (2026-05-29)

## 명령
`uv run themek vault build --out vault`

## 결과 (실 themek.db)
- companies: <Step1 출력 수>
- customers(미연결 포함): <수>
- segments / regions / sectors: <수>
- 검출 이슈: <수> (geo_duplicate <n>, revenue_sum_anomaly <n>, unresolved_customer 요약 등)

## Obsidian 확인
1. Obsidian → "Open folder as vault" → `themek/vault` 선택
2. Graph View(Ctrl/Cmd+G): 회사–세그먼트–고객–지역 노드 망 렌더 확인
3. `Apple Inc.` 노트: 백링크 패널에 다수 회사(삼성/현대 등) → 공급망 허브 확인
4. `_qa-report.md`: 삼성전자 `미주` 중복 등 이슈 나열 확인
5. (선택) Settings → Appearance/Graph → tag `unresolved/entity` vs `unresolved/descriptive` 색상 그룹 지정 시 실회사 후보/설명문 구분

## 알려진 한계
- 세그먼트 dedupe는 name_ko 정확 일치 기준 ("기타" 등 일반명 과병합 가능 — QA info 아님, 후속 검토)
- 매출비중 합 100 초과는 중첩 세그먼트(DX⊃스마트폰 등) 구조상 정상일 수 있음 — warn은 점검 유도용
```
(실제 수치는 Step 1-3 출력으로 채운다.)

- [ ] **Step 5: README에 사용법 추가**

`README.md`의 명령/도구 섹션에 추가 (적절한 위치 — 기존 `themek query e5` 설명 인근):

```markdown
### Obsidian vault 생성 (온톨로지 점검·탐색)

적재된 DART 온톨로지를 Obsidian vault로 생성해 그래프로 둘러보고 데이터 품질을 점검한다.

```bash
uv run themek vault build            # vault/ 에 생성 (멱등 — 재실행 시 최신 DB 반영)
```

- `vault/companies/` 회사 노트(DB 1:1) · `segments/`·`regions/`·`sectors/` 개념 노드 · `customers/` 미연결 고객(설명문 포함 전부 노드화, `kind` 분류)
- `vault/_qa-report.md` 데이터 품질 이슈 자동 집계(지역 중복·매출합 이상·미연결·누락)
- Obsidian에서 "폴더를 vault로 열기" → Graph View로 노드 망 시각화

백필로 적재가 늘면 `themek vault build`만 재실행하면 새 노드가 자동 반영된다.
```

- [ ] **Step 6: Commit**

```bash
git add docs/vault-smoke-notes.md README.md vault/
git commit -m "docs(vault): smoke build notes + README usage; initial vault snapshot"
```

✅ **Success Gate:** `uv run themek vault build` 실 DB에서 exit 0. Step 3 링크 무결성 스크립트가 `missing files: 0` 출력. `vault/_qa-report.md`에 `geo_duplicate` ≥ 1건(삼성 미주 중복). `docs/vault-smoke-notes.md`에 실제 수치 기록. README에 `themek vault build` 사용법 존재.

---

## Measurable Success Gates 요약

| Task | 측정 명령 | 통과 기준 |
|------|----------|----------|
| 0 | `uv run python -c "import themek.vault"` | exit 0 |
| 1 | `uv run pytest tests/test_vault_model.py` | 5 passed |
| 2 | `uv run pytest tests/test_vault_model.py` | 9 passed (누적) |
| 3 | `uv run pytest tests/test_vault_qa.py` | 7 passed |
| 4 | `uv run pytest tests/test_vault_render.py` | 6 passed |
| 5 | `uv run pytest tests/test_vault_render.py` | 13 passed (누적) |
| 6 | `uv run pytest tests/test_vault_builder.py` | 4 passed |
| 7 | `uv run pytest tests/test_cli_vault.py` + `uv run pytest -q` | 1 passed + 전체 실패 0 |
| 8 | `uv run themek vault build` + 링크 무결성 스크립트 | exit 0, missing files 0, geo_duplicate ≥1 |

전체 신규 테스트: 5+4+7+6+7+4+1 = **34개** (Task1: 5, Task2: +4, Task3: 7, Task4: 6, Task5: +7, Task6: 4, Task7: 1).

---

## Self-Review 결과

- **Spec coverage:** §5 모듈 4개 → Task 1-6. §6 노드 매핑 → Task 5. §7 QA → Task 3. §9 고객 분류 → Task 1. §10 CLI → Task 7. §11 테스트 → 각 Task. Acceptance Criteria 1-7 → Task 6·7·8 gate로 커버. ✅
- **Placeholder scan:** 모든 step에 실제 코드/명령 포함. "TBD" 없음. (smoke 메모의 `<수치>`는 실행 출력으로 채우는 의도된 변수 — step에 채우는 방법 명시.) ✅
- **Type consistency:** `build_graph`→`VaultGraph`(model), `detect_issues(graph)→list[Issue]`(qa), `render_*`→`(path, text)`, `build_vault(session, out_dir)→dict`. CLI는 `build_vault`만 호출. dataclass 필드명(`name_ko`, `share_pct`, `named_by`, `kind`, `resolved`) 전 Task 일관. ✅
- **V8 확정:** Task 0에서 `vault/.obsidian/workspace*` 등만 ignore, 생성 md tracked. ✅
