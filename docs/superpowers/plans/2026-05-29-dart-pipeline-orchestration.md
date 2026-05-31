# DART 통합 파이프라인 오케스트레이션 Implementation Plan

> **상태: ✅ 구현 완료** — main 반영됨(2026-05-31 기준, 테스트 314개 통과). 아래 체크박스는 실행 추적용 기록이며 갱신되지 않았을 수 있습니다.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `themek pipeline run` 한 명령으로 DART 파이프라인(sync → 사업구조 → 재무 → 산출물)을 통합 구동하고, 재무 적재 연도를 적재된 코어 데이터에서 자동 도출한다.

**Architecture:** 신규 `src/themek/ontology/pipeline.py`에 순수 오케스트레이션(`derive_financial_years`·`ingest_financials_all`·`run_pipeline`·`PipelineResult`)을 두고 기존 조각(`sync_corp_master`·`run_incremental`·`ingest_financials_for_company`·`build_vault`·`export_graph`)을 호출만 한다. CLI `themek pipeline run`은 옵션 파싱 후 `run_pipeline`을 호출하는 얇은 래퍼.

**Tech Stack:** Python 3.12+, SQLAlchemy 2.0, typer(CLI), pytest(in-memory SQLite). 신규 의존성 0.

**Spec:** `docs/superpowers/specs/2026-05-29-dart-pipeline-orchestration-design.md`

---

## File Structure (decomposition)

| 파일 | 책임 |
|------|------|
| `src/themek/ontology/pipeline.py` | `derive_financial_years`·`ingest_financials_all`·`run_pipeline`·`PipelineResult` |
| `src/themek/cli.py` (수정) | `pipeline_app` 등록 + `pipeline run` 명령 |
| `tests/ontology/test_pipeline.py` | 단위(연도도출·financials_all·skip) + 통합(run_pipeline) |
| `tests/ontology/test_cli_pipeline.py` | CLI `pipeline run` 통합 |

**의존 방향:** `cli → pipeline → {dart.corp_lookup, dart.incremental, ontology.ingest.financials, ontology.projection.vault, ontology.projection.graph_export, ontology.core.models}`.

**참조 시그니처 (기존, 확인됨):**
- `sync_corp_master(client, cache) -> int`
- `run_incremental(*, client, cache, session, universe, rate_budget, extractor, since, until, fetcher=None, purge_zip=False) -> IncrementalRunResult`
- `ingest_financials_for_company(session, client, *, corp_code, bsns_year, reprt_code) -> int`
- `build_vault(session, out_dir) -> dict`  (`{"companies": n}`)
- `export_graph(session, out_dir) -> dict`  (`{"nodes": n, "edges": m}`)

---

## Task 1: pipeline 헬퍼 — derive_financial_years + ingest_financials_all

**Files:**
- Create: `src/themek/ontology/pipeline.py`
- Test: `tests/ontology/test_pipeline.py`

- [ ] **Step 1: 헬퍼 테스트 작성**

`tests/ontology/test_pipeline.py`:

```python
"""pipeline 헬퍼 단위 테스트."""
import json
from pathlib import Path

from themek.ontology.core.models import Node, FinancialFact
from themek.ontology.core.resolve import upsert_node, upsert_edge
from themek.ontology.pipeline import (
    derive_financial_years, ingest_financials_all,
)

_CASSETTE = Path("tests/fixtures/dart_cassettes/fnlttSinglAcntAll_samsung_2024.json")


def _edge(s, subj, obj, period):
    upsert_node(s, subj, "company", subj)
    upsert_node(s, obj, "segment", obj)
    upsert_edge(s, subject_id=subj, predicate="HAS_SEGMENT", object_id=obj,
                period=period, qualifier={}, source_type="llm",
                source_ref="r", method="llm", confidence=0.9)


def test_derive_financial_years_distinct_4digit_sorted(ontology_session):
    s = ontology_session
    _edge(s, "company:1", "segment:a", "2023")
    _edge(s, "company:1", "segment:b", "2024")
    _edge(s, "company:2", "segment:c", "2023")     # 중복 연도
    _edge(s, "company:2", "segment:d", None)        # null 제외
    _edge(s, "company:2", "segment:e", "2024Q1")    # 비-4자리 제외
    s.commit()
    assert derive_financial_years(s) == ["2023", "2024"]


def test_derive_financial_years_empty(ontology_session):
    assert derive_financial_years(ontology_session) == []


class _FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def fetch_financials(self, *, corp_code, bsns_year, reprt_code, fs_div):
        self.calls.append((corp_code, bsns_year, reprt_code, fs_div))
        return self.rows if fs_div == "CFS" else []


def test_ingest_financials_all_iterates_companies_years_reprtcodes(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자", {"dart_code": "00126380"})
    upsert_node(s, "company:00164742", "company", "현대차", {"dart_code": "00164742"})
    upsert_node(s, "segment:x", "segment", "x")  # company 아닌 노드는 무시
    s.commit()
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    client = _FakeClient(rows)
    stats = ingest_financials_all(s, client, years=["2024"])
    s.commit()
    assert stats["companies"] == 2
    # 회사2 × reprt4 = 8 CFS 호출 (+OFS는 CFS 있으면 안 함)
    assert len([c for c in client.calls if c[3] == "CFS"]) == 8
    # 각 호출 18 fact(6 metric×3년) → 단, 같은 (company,year,fp,fs,metric) UNIQUE라
    # 4개 reprt_code가 fiscal_period(FY/H1/Q1/Q3)로 구분되어 중복 안 됨.
    assert s.query(FinancialFact).count() > 0
    assert stats["facts"] > 0
    assert stats["failed"] == []


def test_ingest_financials_all_collects_failures(ontology_session):
    s = ontology_session
    upsert_node(s, "company:00126380", "company", "삼성전자", {"dart_code": "00126380"})
    s.commit()

    class _BoomClient:
        def fetch_financials(self, **kw):
            raise RuntimeError("boom")

    stats = ingest_financials_all(s, _BoomClient(), years=["2024"])
    assert stats["companies"] == 1
    assert len(stats["failed"]) >= 1
    assert stats["facts"] == 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_pipeline.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'themek.ontology.pipeline'`

- [ ] **Step 3: pipeline.py 헬퍼 구현**

`src/themek/ontology/pipeline.py`:

```python
"""DART 통합 파이프라인 오케스트레이션 (순수 함수 + 얇은 단계 조합)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from themek.ontology.core.models import Node, Edge

_YEAR = re.compile(r"^\d{4}$")
_REPRT_CODES = ("11011", "11012", "11013", "11014")


def derive_financial_years(session: Session) -> list[str]:
    """코어 엣지 period 중 4자리 연도만 distinct·정렬 반환."""
    rows = session.execute(
        select(Edge.period).where(Edge.period.is_not(None)).distinct()
    ).scalars().all()
    years = {p for p in rows if p and _YEAR.match(p)}
    return sorted(years)


def ingest_financials_all(session: Session, client, *, years: list[str]) -> dict:
    """DB 내 모든 company 노드 × years × 4 reprt_code 재무 적재. 회사별 실패 관용."""
    from themek.ontology.ingest.financials import ingest_financials_for_company

    companies = session.execute(
        select(Node).where(Node.kind == "company")
    ).scalars().all()
    facts = 0
    failed: list[tuple[str, str]] = []
    processed = 0
    for node in companies:
        dart_code = node.attrs.get("dart_code")
        if not dart_code:
            continue
        processed += 1
        for yr in years:
            for rc in _REPRT_CODES:
                try:
                    facts += ingest_financials_for_company(
                        session, client, corp_code=dart_code,
                        bsns_year=yr, reprt_code=rc)
                except Exception as e:  # 회사별 관용
                    failed.append((dart_code, f"{yr}/{rc}: {e}"))
    return {"companies": processed, "facts": facts, "failed": failed}


@dataclass
class PipelineResult:
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    sync: int | None = None
    structure: object | None = None
    financials: dict | None = None
    export: dict | None = None
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_pipeline.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/ontology/pipeline.py tests/ontology/test_pipeline.py
git commit -m "feat(pipeline): derive_financial_years + ingest_financials_all + PipelineResult"
```

✅ **Success Gate (측정 가능):**
1. `uv run pytest tests/ontology/test_pipeline.py -q` → `4 passed`, 0 failed.
2. `test_derive_financial_years_distinct_4digit_sorted` 통과 = null·"2024Q1" 제외하고 정확히 `["2023","2024"]` 반환.
3. `test_ingest_financials_all_iterates_companies_years_reprtcodes` 통과 = CFS 호출 `8`회(회사2×코드4), `stats["companies"]==2`, `stats["facts"]>0`, `stats["failed"]==[]`.
4. `test_ingest_financials_all_collects_failures` 통과 = `len(stats["failed"])>=1` 이고 `facts==0`.

---

## Task 2: run_pipeline 오케스트레이션 (단계 + skip)

**Files:**
- Modify: `src/themek/ontology/pipeline.py` (run_pipeline 추가)
- Test: `tests/ontology/test_pipeline.py` (append)

- [ ] **Step 1: run_pipeline 테스트 작성 (append)**

`tests/ontology/test_pipeline.py` 상단 import에 추가:

```python
from themek.ontology.pipeline import run_pipeline
```

파일 끝에 추가:

```python
def _seed_company_with_edges(s):
    upsert_node(s, "company:00126380", "company", "삼성전자", {"dart_code": "00126380"})
    upsert_node(s, "segment:메모리", "segment", "메모리")
    upsert_edge(s, subject_id="company:00126380", predicate="HAS_SEGMENT",
                object_id="segment:메모리", period="2024", qualifier={"share_pct": 50.0},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    s.commit()


def test_run_pipeline_skips_sync_and_structure(tmp_path, ontology_session):
    s = ontology_session
    _seed_company_with_edges(s)
    rows = json.loads(_CASSETTE.read_text(encoding="utf-8"))["list"]
    client = _FakeClient(rows)
    result = run_pipeline(
        s, client, cache=None,
        skip_sync=True, skip_structure=True,
        skip_financials=False, skip_export=False,
        since=None, until=None, universe=set(), rate_budget=None, extractor=None,
        out_vault=tmp_path / "vault", out_graph=tmp_path / "graph",
    )
    assert "sync" in result.skipped and "structure" in result.skipped
    assert "financials" in result.ran and "export" in result.ran
    # 재무: 도출 연도 2024 사용
    assert result.financials["facts"] > 0
    # export 산출물
    assert (tmp_path / "vault" / "companies" / "삼성전자.md").exists()
    assert (tmp_path / "graph" / "nodes.json").exists()
    assert result.export["nodes"] > 0


def test_run_pipeline_financials_skipped_when_no_years(tmp_path, ontology_session):
    s = ontology_session
    # 엣지 없음 → 도출 연도 0 → financials는 ran이지만 facts 0
    upsert_node(s, "company:00126380", "company", "삼성전자", {"dart_code": "00126380"})
    s.commit()
    client = _FakeClient([])
    result = run_pipeline(
        s, client, cache=None, skip_sync=True, skip_structure=True,
        skip_financials=False, skip_export=True,
        since=None, until=None, universe=set(), rate_budget=None, extractor=None,
        out_vault=tmp_path / "v", out_graph=tmp_path / "g",
    )
    assert result.financials["facts"] == 0
    assert result.financials.get("years") == []


def test_run_pipeline_all_skipped(tmp_path, ontology_session):
    s = ontology_session
    result = run_pipeline(
        s, client=None, cache=None,
        skip_sync=True, skip_structure=True, skip_financials=True, skip_export=True,
        since=None, until=None, universe=set(), rate_budget=None, extractor=None,
        out_vault=tmp_path / "v", out_graph=tmp_path / "g",
    )
    assert result.ran == []
    assert set(result.skipped) == {"sync", "structure", "financials", "export"}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_pipeline.py -k run_pipeline -q`
Expected: FAIL — `ImportError: cannot import name 'run_pipeline'`

- [ ] **Step 3: run_pipeline 구현 (pipeline.py 끝에 append)**

```python
from pathlib import Path  # noqa: E402


def run_pipeline(
    session: Session, client, *, cache,
    skip_sync: bool, skip_structure: bool, skip_financials: bool, skip_export: bool,
    since, until, universe, rate_budget, extractor,
    out_vault, out_graph,
) -> PipelineResult:
    """4단계(sync→structure→financials→export) 오케스트레이션. skip 플래그 존중."""
    from themek.dart.corp_lookup import sync_corp_master
    from themek.dart.incremental import run_incremental
    from themek.ontology.projection.vault import build_vault
    from themek.ontology.projection.graph_export import export_graph

    result = PipelineResult()

    # 1. sync
    if skip_sync:
        result.skipped.append("sync")
    else:
        result.sync = sync_corp_master(client, cache)
        result.ran.append("sync")

    # 2. structure (incremental, 자동 기간)
    if skip_structure:
        result.skipped.append("structure")
    else:
        result.structure = run_incremental(
            client=client, cache=cache, session=session, universe=universe,
            rate_budget=rate_budget, extractor=extractor, since=since, until=until)
        result.ran.append("structure")

    # 3. financials (연도 자동 도출)
    if skip_financials:
        result.skipped.append("financials")
    else:
        years = derive_financial_years(session)
        stats = ingest_financials_all(session, client, years=years)
        stats["years"] = years
        result.financials = stats
        result.ran.append("financials")

    # 4. export (vault + graph)
    if skip_export:
        result.skipped.append("export")
    else:
        v = build_vault(session, Path(out_vault))
        g = export_graph(session, Path(out_graph))
        result.export = {"companies": v["companies"], "nodes": g["nodes"],
                         "edges": g["edges"]}
        result.ran.append("export")

    return result
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_pipeline.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/themek/ontology/pipeline.py tests/ontology/test_pipeline.py
git commit -m "feat(pipeline): run_pipeline — 4-stage orchestration with skip flags"
```

✅ **Success Gate (측정 가능):**
1. `uv run pytest tests/ontology/test_pipeline.py -q` → `7 passed`, 0 failed.
2. `test_run_pipeline_skips_sync_and_structure` 통과 = `result.skipped ⊇ {sync,structure}`, `result.ran ⊇ {financials,export}`, `result.financials["facts"]>0`, `vault/companies/삼성전자.md` 및 `graph/nodes.json` 존재, `result.export["nodes"]>0`.
3. `test_run_pipeline_financials_skipped_when_no_years` 통과 = 엣지 0건일 때 `financials["facts"]==0` 이고 `financials["years"]==[]`.
4. `test_run_pipeline_all_skipped` 통과 = `result.ran==[]` 이고 `set(result.skipped)=={sync,structure,financials,export}`.

---

## Task 3: CLI `themek pipeline run`

**Files:**
- Modify: `src/themek/cli.py`
- Test: `tests/ontology/test_cli_pipeline.py`

- [ ] **Step 1: CLI 통합 테스트 작성**

`tests/ontology/test_cli_pipeline.py`:

```python
"""CLI `themek pipeline run` 통합 테스트 (export만 — 네트워크 불필요)."""
from typer.testing import CliRunner

from themek.cli import app
from themek.db.engine import make_engine, make_session_factory
from themek.ontology.core.resolve import upsert_node, upsert_edge

runner = CliRunner()


def _seed_committed():
    s = make_session_factory(make_engine())()
    upsert_node(s, "company:00126380", "company", "삼성전자", {"dart_code": "00126380"})
    upsert_node(s, "segment:메모리", "segment", "메모리")
    upsert_edge(s, subject_id="company:00126380", predicate="HAS_SEGMENT",
                object_id="segment:메모리", period="2024", qualifier={"share_pct": 50.0},
                source_type="llm", source_ref="r", method="llm", confidence=0.9)
    s.commit(); s.close()


def test_pipeline_run_export_only(tmp_path, ontology_fresh_db):
    _seed_committed()
    result = runner.invoke(app, [
        "pipeline", "run", "--skip-sync", "--skip-structure", "--skip-financials",
        "--out-vault", str(tmp_path / "vault"), "--out-graph", str(tmp_path / "graph"),
    ])
    assert result.exit_code == 0, result.output
    assert "export" in result.output
    assert (tmp_path / "vault" / "companies" / "삼성전자.md").exists()
    assert (tmp_path / "graph" / "nodes.json").exists()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `uv run pytest tests/ontology/test_cli_pipeline.py -q`
Expected: FAIL — `pipeline` 명령 없음 → exit_code != 0

- [ ] **Step 3: cli.py에 pipeline 서브앱 + run 명령 추가**

`src/themek/cli.py` 상단 import 블록에 추가:

```python
from themek.ontology.pipeline import run_pipeline
```

서브앱 등록부(`ontology_app` 줄 다음, line ~48)에 추가:

```python
pipeline_app = typer.Typer(help="DART 통합 파이프라인")
app.add_typer(pipeline_app, name="pipeline")
```

cli.py 끝부분(모듈 레벨)에 명령 추가:

```python
@pipeline_app.command("run")
def pipeline_run_cmd(
    since: str = typer.Option("yesterday", "--since"),
    until: str = typer.Option("today", "--until"),
    universe_file: Path = typer.Option(DEFAULT_UNIVERSE_FILE, "--universe-file"),
    out_vault: str = typer.Option("vault", "--out-vault"),
    out_graph: str = typer.Option("graph", "--out-graph"),
    skip_sync: bool = typer.Option(False, "--skip-sync"),
    skip_structure: bool = typer.Option(False, "--skip-structure"),
    skip_financials: bool = typer.Option(False, "--skip-financials"),
    skip_export: bool = typer.Option(False, "--skip-export"),
):
    """DART 파이프라인 통합 구동: sync→structure→financials→export (재무 연도 자동)."""
    from datetime import timedelta
    from themek.dart.universe import load_universe
    from themek.dart.rate_budget import RateBudget

    s = get_settings()
    today = date.today()
    since_d = (today - timedelta(days=1) if since == "yesterday"
               else date.fromisoformat(since))
    until_d = today if until == "today" else date.fromisoformat(until)

    # structure/sync 단계에서만 client/cache 필요
    client = cache = None
    universe: set[str] = set()
    rate_budget = None
    extractor = _stub_extractor_from_env()
    if not (skip_sync and skip_structure and skip_financials):
        try:
            client, cache = _dart_client_and_cache()
        except DartAuthError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=2)
    if not skip_structure:
        universe = set(load_universe(universe_file))
        rate_budget = RateBudget(daily_cap=38000,
                                 state_file=s.dart_cache_dir / "budget_state.json")

    with _session() as sess:
        result = run_pipeline(
            sess, client, cache=cache,
            skip_sync=skip_sync, skip_structure=skip_structure,
            skip_financials=skip_financials, skip_export=skip_export,
            since=since_d, until=until_d, universe=universe,
            rate_budget=rate_budget, extractor=extractor,
            out_vault=out_vault, out_graph=out_graph,
        )
        sess.commit()

    for stage in result.ran:
        if stage == "sync":
            typer.echo(f"[sync] corp master rows: {result.sync}")
        elif stage == "structure":
            r = result.structure
            typer.echo(f"[structure] scanned={r.scanned} ingested={r.ingested} "
                       f"failed={len(r.failed)}")
        elif stage == "financials":
            f = result.financials
            typer.echo(f"[financials] years={f['years']} companies={f['companies']} "
                       f"facts={f['facts']} failed={len(f['failed'])}")
        elif stage == "export":
            e = result.export
            typer.echo(f"[export] vault {e['companies']} companies → {out_vault}/ ; "
                       f"graph {e['nodes']} nodes/{e['edges']} edges → {out_graph}/")
    typer.echo(f"pipeline done: ran={result.ran} skipped={result.skipped}")
```

> 구현 노트: `_session`·`_dart_client_and_cache`·`_stub_extractor_from_env`·`DEFAULT_UNIVERSE_FILE`·`get_settings`·`DartAuthError`·`date`·`Path`는 cli.py에 이미 존재(import 추가 불필요). financials만 실행할 때도 client는 필요(`fetch_financials`)하므로 위 조건은 `skip_financials`도 포함해 client 준비.

- [ ] **Step 4: 테스트 통과 확인**

Run: `uv run pytest tests/ontology/test_cli_pipeline.py -q`
Expected: PASS (1 passed)

- [ ] **Step 5: 전체 스위트 회귀 확인**

Run: `uv run pytest -q`
Expected: 전체 PASS, 실패 0.

- [ ] **Step 6: Commit**

```bash
git add src/themek/cli.py tests/ontology/test_cli_pipeline.py
git commit -m "feat(cli): themek pipeline run — integrated DART pipeline"
```

✅ **Success Gate (측정 가능):**
1. `uv run pytest tests/ontology/test_cli_pipeline.py -q` → `1 passed`, 0 failed.
2. `uv run pytest -q` → 전체 실패 `0`.
3. `uv run themek pipeline run --skip-sync --skip-structure --skip-financials --out-vault /tmp/pv --out-graph /tmp/pg` → exit `0`, stdout에 `[export]` 와 `pipeline done: ran=['export']` 포함, `/tmp/pv/companies/*.md`≥1·`/tmp/pg/nodes.json` 존재.
4. `uv run themek pipeline run --help` → exit 0, `--skip-sync`·`--skip-structure`·`--skip-financials`·`--skip-export` 4개 플래그 모두 노출.

---

## Task 4: README + 실 스모크(가능 환경)

**Files:**
- Modify: `README.md`

- [ ] **Step 1: README에 통합 명령 사용법 추가**

`README.md`의 DART/온톨로지 명령 섹션에 추가:

```markdown
### 통합 파이프라인 (한 번에 구동)

```bash
# 전체: corp sync → 신규 사업보고서 적재 → 재무 자동적재 → vault+graph 산출
uv run themek pipeline run

# 초기 대량 적재(스캔 창 확대)
uv run themek pipeline run --since 2023-01-01

# 부분 실행 (예: 산출물만 재생성)
uv run themek pipeline run --skip-sync --skip-structure --skip-financials
```

- 재무 적재 연도는 **적재된 사업보고서에서 자동 도출**(`--years` 불필요).
- 단계별 `--skip-sync` / `--skip-structure` / `--skip-financials` / `--skip-export`.
```

- [ ] **Step 2: 실 스모크 (DART 키/네트워크 가능 시 — gating 아님)**

Run: `uv run themek pipeline run --skip-structure --out-vault vault --out-graph graph`
Expected: `[financials] years=[...]` + `[export] ...` + `pipeline done: ran=[...]`. 키 미설정/네트워크 불가 시 Task 3 통합테스트로 게이트 충족(실 스모크는 환경 가능 시만).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(pipeline): README usage for themek pipeline run"
```

✅ **Success Gate (측정 가능):** `grep -q "themek pipeline run" README.md` 통과. (실 스모크는 환경 의존 — gating 아님. 결정론적 게이트는 Task 3 통합테스트 + 전체 스위트.)

---

## Measurable Success Gates 요약

| Task | 측정 명령 | 통과 기준 |
|------|----------|----------|
| 1 | `pytest tests/ontology/test_pipeline.py` | 4 passed |
| 2 | `pytest tests/ontology/test_pipeline.py` | 7 passed (누적) |
| 3 | `pytest tests/ontology/test_cli_pipeline.py` + `pytest -q` | 1 passed + 전체 실패 0 |
| 4 | `grep -q "themek pipeline run" README.md` | 통과 |

신규 테스트: 4(Task1) + 3(Task2) + 1(Task3) = **8개**.

---

## Self-Review 결과

- **Spec coverage:** §3 아키텍처(pipeline.py 순수함수) → Task 1·2. §4 단계·기간자동화(derive_financial_years, ingest_financials_all, run_incremental 호출) → Task 1·2. §4 skip 플래그 → Task 2·3. §5 에러처리(fail-fast 인증, 항목 관용) → Task 3(DartAuthError exit 2)·1(financials try/except). §5 출력(단계별+요약) → Task 3. §6 테스트 → 각 Task. §7 Acceptance 1-6 → Task1(AC1,2)·Task2(AC3)·Task3(AC4,5,6). ✅
- **Placeholder scan:** 모든 step에 실제 코드/명령. TBD 없음. ✅
- **Type consistency:** `derive_financial_years(session)->list[str]`·`ingest_financials_all(session,client,*,years)->dict{companies,facts,failed(+years in run_pipeline)}`·`run_pipeline(session,client,*,cache,skip_*,since,until,universe,rate_budget,extractor,out_vault,out_graph)->PipelineResult`·`PipelineResult{ran,skipped,sync,structure,financials,export}` 전 Task 일관. 기존 `build_vault(session,out)->{"companies"}`·`export_graph(session,out)->{"nodes","edges"}`·`run_incremental(*, ...)`·`sync_corp_master(client,cache)->int` 시그니처 일치. ✅
- **YAGNI:** 병렬·재시도 미추가, 기존 RateBudget/incremental 위임. ✅
