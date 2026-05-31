"""themek CLI entry point."""
from __future__ import annotations
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import typer
from sqlalchemy.orm import Session
from themek.config import get_settings
from themek.db.engine import make_engine, make_session_factory
from themek.dart.parser import (
    extract_business_sections,
    llm_classify_headers,
)
from themek.dart.client import DartClient, DartAuthError, DartApiError
from themek.dart.cache import DartCache
from themek.dart.corp_lookup import sync_corp_master, lookup_corp_code
from themek.db.corp_models import Corporation
from themek.dart.fetch import (
    fetch_business_report_html, BusinessReportFetchError,
)
from themek.ingest.business_report import ingest_business_report
from themek.llm.schemas import BusinessExtraction
from themek.krx.client import KrxClient
from themek.krx.sync import sync_listed_stocks, fetch_listed_universe
from themek.dart.incremental import run_incremental
from sqlalchemy import select
from themek.ontology.query.screen import screen as _screen
from themek.ontology.ingest.financials import ingest_financials_for_company
from themek.ontology.ingest.seeds import seed_core
from themek.ontology.projection.vault import build_vault
from themek.ontology.projection.graph_export import export_graph
from themek.ontology.core.models import Node
from themek.ontology.pipeline import run_pipeline

app = typer.Typer(help="themek — 한국 테마주 ontology CLI")
query_app = typer.Typer(help="Run competency queries")
app.add_typer(query_app, name="query")
dart_app = typer.Typer(help="DART OpenAPI 명령")
app.add_typer(dart_app, name="dart")
krx_app = typer.Typer(help="KRX 상장사 sync 명령")
app.add_typer(krx_app, name="krx")
vault_app = typer.Typer(help="Obsidian vault 생성 명령")
app.add_typer(vault_app, name="vault")
ingest_app = typer.Typer(help="온톨로지 적재 명령")
app.add_typer(ingest_app, name="ingest")
ontology_app = typer.Typer(help="온톨로지 export 명령")
app.add_typer(ontology_app, name="ontology")
pipeline_app = typer.Typer(help="DART 통합 파이프라인")
app.add_typer(pipeline_app, name="pipeline")
financials_app = typer.Typer(help="재무 정합성 명령")
app.add_typer(financials_app, name="financials")

DEFAULT_LEARNED_PATTERNS_PATH = "data/dart/learned_header_patterns.json"
DEFAULT_PROPOSALS_PATH = "data/dart/pattern_proposals.json"
DEFAULT_FIXTURES_DIR = "tests/fixtures/dart_variants"


def _session() -> Session:
    factory = make_session_factory(make_engine())
    return factory()


@app.command()
def seed():
    """코어 온톨로지 기본 노드 시드."""
    with _session() as s:
        seed_core(s)
        s.commit()
    typer.echo("Seeded core: 3 companies, 3 sectors, 6 regions, stock+sector edges.")


def _stub_extractor_from_env():
    path = os.environ.get("THEMEK_STUB_EXTRACTION_FILE")
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    extraction = BusinessExtraction.model_validate(payload)

    def stub(text: str, period_hint: str) -> BusinessExtraction:
        return extraction

    return stub


def _dart_client_and_cache() -> tuple[DartClient, DartCache]:
    s = get_settings()
    client = DartClient(
        api_key=s.dart_api_key, timeout_sec=s.dart_http_timeout_sec,
    )
    cache = DartCache(base_dir=s.dart_cache_dir)
    return client, cache


@dart_app.command("sync-corp")
def dart_sync_corp_cmd(
    if_stale_days: Optional[int] = typer.Option(
        None, "--if-stale-days",
        help="N일 이내 sync된 corp_master는 skip (cron 안전용)",
    ),
):
    """corp_code 마스터를 DART에서 받아 캐시."""
    import time

    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)

    if if_stale_days is not None and cache.corp_master_path.exists():
        age_days = (
            time.time() - cache.corp_master_path.stat().st_mtime
        ) / 86400
        if age_days < if_stale_days:
            typer.echo(
                f"corp_master {age_days:.1f} days old "
                f"< {if_stale_days} — skipped"
            )
            return

    try:
        n = sync_corp_master(client, cache)
    except DartApiError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=4)
    typer.echo(f"synced {n} corporations to {cache.corp_master_path}")


@dart_app.command("fetch")
def dart_fetch_cmd(
    ticker: str = typer.Option(..., "--ticker"),
    period: str = typer.Option(..., "--period", help="연도 (예: 2023)"),
):
    """ticker+period → 사업보고서 HTML을 캐시에 저장 후 경로 출력."""
    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        corp_code = lookup_corp_code(cache, ticker=ticker)
    except LookupError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        html_path, rcept_no = fetch_business_report_html(
            client, cache,
            ticker=ticker, year=int(period), corp_code=corp_code,
        )
    except BusinessReportFetchError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=5)
    except DartApiError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=4)
    typer.echo(str(html_path))


def _ensure_corporation(session: Session, *, corp_code: str,
                        cache: DartCache) -> None:
    existing = session.get(Corporation, corp_code)
    if existing is not None:
        return
    name_ko = corp_code
    rows = cache.load_corp_master()
    if rows is not None:
        for r in rows:
            if r.get("corp_code") == corp_code:
                name_ko = r.get("corp_name") or corp_code
                break
    session.add(Corporation(dart_code=corp_code, name_ko=name_ko))
    session.flush()


def _learn_from_resolution(
    section_resolution, *, ticker: str, period: str,
) -> None:
    """ingest 후 learned_samples를 proposal에 누적 + N=3 promote 시도."""
    from themek.dart.pattern_learning import (
        propose_keyword_pattern, record_proposal, apply_ready_proposals,
    )
    proposals_path = Path(os.environ.get(
        "THEMEK_PROPOSALS_PATH", DEFAULT_PROPOSALS_PATH,
    ))
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    fixtures_dir = Path(os.environ.get(
        "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
    ))

    for sample in section_resolution.learned_samples:
        regex = propose_keyword_pattern(
            sample["header_text"], target=sample["target"],
        )
        if regex is None:
            continue
        record_proposal(
            proposals_path, target=sample["target"],
            candidate_regex=regex, sample_header=sample["header_text"],
            source_fixture=f"{ticker}_{period}",
        )
    applied = apply_ready_proposals(
        proposals_path=proposals_path, learned_path=learned_path,
        fixtures_dir=fixtures_dir, min_confirmed=3,
    )
    if applied:
        typer.echo(
            f"[parser-learn] applied {len(applied)} new patterns: "
            f"{[(p.target, p.candidate_regex) for p in applied]}"
        )


@dart_app.command("ingest")
def dart_ingest_cmd(
    ticker: str = typer.Option(..., "--ticker"),
    period: str = typer.Option(..., "--period"),
    report_type: str = typer.Option("사업보고서", "--report-type"),
):
    """dart fetch + 기존 ingest_business_report 통합."""
    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        corp_code = lookup_corp_code(cache, ticker=ticker)
    except LookupError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)
    try:
        html_path, rcept_no = fetch_business_report_html(
            client, cache,
            ticker=ticker, year=int(period), corp_code=corp_code,
        )
    except BusinessReportFetchError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=5)
    except DartApiError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=4)

    html = html_path.read_text(encoding="utf-8")
    extractor = _stub_extractor_from_env()
    # Section filter LLM은 extractor stub과 독립. 학습 hook을 위해 항상 활성.
    text, section_resolution = extract_business_sections(
        html, llm_fallback=llm_classify_headers,
    )

    typer.echo(
        f"[section_filter] escalation={section_resolution.escalation_level} "
        f"output_chars={section_resolution.output_chars} "
        f"invalid={section_resolution.invalid_targets}"
    )

    try:
        filing_dt = datetime.strptime(rcept_no[:8], "%Y%m%d").date()
    except ValueError:
        filing_dt = date.today()
    with _session() as s:
        _ensure_corporation(s, corp_code=corp_code, cache=cache)
        kwargs = dict(
            dart_rcept_no=rcept_no,
            corporation_id=corp_code,
            report_type=report_type,
            period=period,
            filing_date=filing_dt,
            raw_text_excerpt=text,
            url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
        )
        if extractor is not None:
            kwargs["extractor"] = extractor
        ingest_business_report(s, **kwargs)
        s.commit()

    # Fixture mirror + learning hook (post-ingest)
    try:
        from themek.dart.fixture_mirror import mirror_fixture
        fixtures_dir = Path(os.environ.get(
            "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
        ))
        mirror_fixture(
            cache_html=html_path, ticker=ticker, period=period,
            fixtures_dir=fixtures_dir,
        )
    except Exception as e:  # noqa: BLE001 — mirror failure non-fatal
        typer.echo(f"[mirror] skipped: {e}")

    try:
        _learn_from_resolution(
            section_resolution, ticker=ticker, period=period,
        )
    except Exception as e:  # noqa: BLE001 — learn failure non-fatal
        typer.echo(f"[parser-learn] skipped: {e}")

    typer.echo(f"Ingested report {rcept_no}")


backfill_app = typer.Typer(help="다종목 backfill 명령")
dart_app.add_typer(backfill_app, name="backfill")

DEFAULT_UNIVERSE_FILE = "data/universe/active.txt"


@backfill_app.command("init")
def backfill_init_cmd(
    universe_file: Optional[Path] = typer.Option(
        None, "--universe-file",
        help="corp_code 1줄당 1개. # 주석 허용. --from-stocks와 배타.",
    ),
    from_stocks: bool = typer.Option(
        False, "--from-stocks",
        help="Stock 테이블의 active 종목을 universe로 사용 (--universe-file 대체).",
    ),
    include_delisted: bool = typer.Option(
        False, "--include-delisted",
        help="--from-stocks 사용 시 delisted_at set된 종목도 포함.",
    ),
    periods: str = typer.Option(
        ..., "--periods",
        help="YYYY 단일 또는 YYYY:YYYY 범위",
    ),
    confirm: bool = typer.Option(
        False, "--confirm",
        help="dry-run 끄고 실제 row 생성",
    ),
):
    """universe × periods → BackfillTarget row 생성 (dry-run 기본)."""
    from sqlalchemy import select

    from themek.dart.backfill import (
        enumerate_targets, enumerate_targets_from_corps,
    )
    from themek.dart.universe import load_universe_from_stocks
    from themek.db.corp_models import BackfillTarget

    if from_stocks and universe_file is not None:
        typer.echo(
            "Error: --from-stocks와 --universe-file 동시 사용 불가",
            err=True,
        )
        raise typer.Exit(code=1)

    if from_stocks:
        with _session() as sess:
            corps = load_universe_from_stocks(
                sess, include_delisted=include_delisted,
            )
        specs = enumerate_targets_from_corps(
            corp_codes=corps, periods=periods,
        )
        universe_label = (
            f"Stock table ({'incl. delisted' if include_delisted else 'active only'})"
        )
    else:
        uf = universe_file or Path(DEFAULT_UNIVERSE_FILE)
        specs = enumerate_targets(universe_file=uf, periods=periods)
        universe_label = str(uf)

    n_targets = len(specs)
    n_calls = n_targets * 2
    est_cost = n_targets * 0.25

    typer.echo("=== Backfill Init Dry-Run ===")
    typer.echo(f"universe: {universe_label}")
    typer.echo(f"periods: {periods}")
    typer.echo(f"예상 처리: {n_targets} target")
    typer.echo(f"예상 DART 호출: ~{n_calls} (limit 38000/day)")
    typer.echo(f"예상 LLM 비용: ~${est_cost:.2f} (평균 단가 기준)")

    if not confirm:
        typer.echo("\n--confirm 추가 시 실제 BackfillTarget row 생성.")
        return

    inserted, skipped = 0, 0
    with _session() as sess:
        for spec in specs:
            existing = sess.scalar(
                select(BackfillTarget)
                .where(BackfillTarget.corp_code == spec.corp_code)
                .where(BackfillTarget.period == spec.period)
            )
            if existing is not None:
                skipped += 1
                continue
            sess.add(BackfillTarget(
                corp_code=spec.corp_code, period=spec.period, status="pending",
            ))
            inserted += 1
        sess.commit()
    typer.echo(f"\ninserted={inserted} skipped (already exists)={skipped}")


@backfill_app.command("run")
def backfill_run_cmd(
    max_targets: int = typer.Option(500, "--max-targets"),
    daily_cap: Optional[int] = typer.Option(None, "--daily-cap"),
    reset_stale_minutes: int = typer.Option(180, "--reset-stale-minutes"),
    purge_zip: bool = typer.Option(
        False, "--purge-zip-after-extract",
        help="business.html 추출 후 document.zip 삭제 (디스크 절약)",
    ),
):
    """pending BackfillTarget을 한도 안에서 처리."""
    from themek.dart.backfill import run_batch
    from themek.dart.rate_budget import RateBudget, RateBudgetExceeded

    s = get_settings()
    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)

    budget = RateBudget(
        daily_cap=daily_cap or 38000,
        state_file=s.dart_cache_dir / "budget_state.json",
    )
    extractor = _stub_extractor_from_env()
    try:
        with _session() as sess:
            summary = run_batch(
                session=sess, client=client, cache=cache,
                rate_budget=budget, extractor=extractor,
                max_targets=max_targets,
                reset_stale_minutes=reset_stale_minutes,
                purge_zip=purge_zip,
            )
    except RateBudgetExceeded as e:
        typer.echo(f"Budget exceeded: {e}", err=True)
        raise typer.Exit(code=6)

    typer.echo(
        f"processed={summary.processed} done={summary.done} "
        f"skipped={summary.skipped} failed={summary.failed} "
        f"pending_remaining={summary.pending_remaining} "
        f"budget_remaining={summary.budget_remaining}"
    )


@backfill_app.command("status")
def backfill_status_cmd(
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="escalation 분포 + 비용 top-10 + 7일 신규/폐지 표시",
    ),
):
    """BackfillTarget status 분포 + 누적 LLM 비용 + lifecycle 요약."""
    from datetime import datetime, timedelta

    from sqlalchemy import select, func, desc

    from themek.db.corp_models import BackfillTarget, Stock

    with _session() as sess:
        rows = sess.execute(
            select(BackfillTarget.status, func.count())
            .group_by(BackfillTarget.status)
        ).all()
        counts = {status: n for status, n in rows}
        total = sum(counts.values())
        total_cost = sess.scalar(
            select(func.sum(BackfillTarget.cost_estimate_usd))
        ) or 0

    typer.echo("=== BackfillTarget summary ===")
    for status in ("pending", "in_progress", "done", "failed", "skipped"):
        typer.echo(f"  {status:12s}: {counts.get(status, 0):6d}")
    typer.echo(f"  {'total':12s}: {total:6d}")
    typer.echo(f"\nTotal LLM cost (done): ${float(total_cost):.2f}")

    if not verbose:
        return

    with _session() as sess:
        esc_rows = sess.execute(
            select(BackfillTarget.escalation_level, func.count())
            .where(BackfillTarget.status == "done")
            .group_by(BackfillTarget.escalation_level)
        ).all()
        typer.echo("\n=== Escalation distribution (done) ===")
        for level, n in esc_rows:
            typer.echo(f"  {str(level):12s}: {n:6d}")

        top = sess.execute(
            select(
                BackfillTarget.corp_code, BackfillTarget.period,
                BackfillTarget.input_chars, BackfillTarget.cost_estimate_usd,
            )
            .where(BackfillTarget.status == "done")
            .order_by(desc(BackfillTarget.cost_estimate_usd))
            .limit(10)
        ).all()
        typer.echo("\n=== Top 10 by cost ===")
        for cc, p, ic, cost in top:
            typer.echo(
                f"  {cc} {p}: input_chars={ic} cost=${float(cost or 0):.4f}"
            )

        # 7일 lifecycle 요약
        cutoff = datetime.utcnow() - timedelta(days=7)
        new_n = sess.scalar(
            select(func.count())
            .select_from(Stock)
            .where(Stock.created_at >= cutoff)
        ) or 0
        delisted_n = sess.scalar(
            select(func.count())
            .select_from(Stock)
            .where(Stock.delisted_at.isnot(None))
            .where(Stock.delisted_at >= cutoff.date())
        ) or 0
        typer.echo("\n=== Lifecycle (7일) ===")
        typer.echo(f"  신규 상장 (7일): {new_n}")
        typer.echo(f"  상장폐지 (7일): {delisted_n}")


@dart_app.command("incremental")
def dart_incremental_cmd(
    since: str = typer.Option("yesterday", "--since"),
    until: str = typer.Option("today", "--until"),
    universe_source: str = typer.Option(
        "stocks", "--universe-source",
        help="stocks (기본, Stock 테이블 전체) | file",
    ),
    universe_file: Optional[Path] = typer.Option(
        None, "--universe-file",
        help="corp_code 파일 경로. 지정 시 source 무관하게 이 파일을 universe로 사용.",
    ),
    include_delisted: bool = typer.Option(
        False, "--include-delisted",
        help="--universe-source=stocks 시 delisted 종목 포함",
    ),
    purge_zip: bool = typer.Option(False, "--purge-zip-after-extract"),
):
    """Layer B: scan → universe filter → 신규만 ingest."""
    from datetime import timedelta

    from themek.dart.universe import load_universe, load_universe_from_stocks
    from themek.dart.rate_budget import RateBudget

    s = get_settings()
    today = date.today()
    since_d = (
        today - timedelta(days=1) if since == "yesterday"
        else date.fromisoformat(since)
    )
    until_d = (
        today if until == "today" else date.fromisoformat(until)
    )

    try:
        client, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)

    if universe_file is not None:
        # 명시적 파일 override (특정 종목군만 처리). source보다 우선.
        universe = set(load_universe(universe_file))
    elif universe_source == "stocks":
        with _session() as sess:
            universe = set(load_universe_from_stocks(
                sess, include_delisted=include_delisted,
            ))
    elif universe_source == "file":
        typer.echo(
            "Error: --universe-source file 사용 시 --universe-file 경로가 필요합니다.",
            err=True,
        )
        raise typer.Exit(code=1)
    else:
        typer.echo(
            f"Error: --universe-source는 'file' 또는 'stocks' (got {universe_source!r})",
            err=True,
        )
        raise typer.Exit(code=1)

    budget = RateBudget(
        daily_cap=38000,
        state_file=s.dart_cache_dir / "budget_state.json",
    )
    extractor = _stub_extractor_from_env()

    with _session() as sess:
        result = run_incremental(
            client=client, cache=cache, session=sess,
            universe=universe, rate_budget=budget, extractor=extractor,
            since=since_d, until=until_d,
            purge_zip=purge_zip,
        )
    typer.echo(
        f"scanned={result.scanned} in_universe={result.in_universe} "
        f"already_ingested={result.already_ingested} "
        f"to_ingest={result.to_ingest} ingested={result.ingested} "
        f"failed={len(result.failed)}"
    )


@dart_app.command("parser-stats")
def dart_parser_stats_cmd():
    """학습 누적 상태 출력."""
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    proposals_path = Path(os.environ.get(
        "THEMEK_PROPOSALS_PATH", DEFAULT_PROPOSALS_PATH,
    ))
    fixtures_dir = Path(os.environ.get(
        "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
    ))
    from themek.dart.learned_patterns import load_learned_patterns
    from themek.dart.pattern_learning import load_proposals
    lp = load_learned_patterns(learned_path)
    proposals = load_proposals(proposals_path)
    fixtures = (
        sorted(fixtures_dir.glob("*.html")) if fixtures_dir.exists() else []
    )
    lines = [
        f"fixtures: {len(fixtures)}",
        "learned patterns:",
    ]
    for t in ("overview", "products", "revenue"):
        learned_count = sum(
            1 for p in lp.target_patterns(t) if p.get("source") == "learned"
        )
        baseline_count = sum(
            1 for p in lp.target_patterns(t) if p.get("source") == "code_baseline"
        )
        lines.append(
            f"  {t}: baseline={baseline_count}, learned={learned_count}"
        )
    lines.append(f"proposals (pending): {len(proposals)}")
    for pr in proposals[:10]:
        lines.append(
            f"  - {pr.target}: {pr.candidate_regex} "
            f"(observed {pr.observed_count}, fixtures={pr.source_fixtures})"
        )
    typer.echo("\n".join(lines))


@dart_app.command("parser-learn")
def dart_parser_learn_cmd():
    """누적 proposal 중 N=3 도달 항목을 learned로 promote."""
    from themek.dart.pattern_learning import apply_ready_proposals
    proposals_path = Path(os.environ.get(
        "THEMEK_PROPOSALS_PATH", DEFAULT_PROPOSALS_PATH,
    ))
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    fixtures_dir = Path(os.environ.get(
        "THEMEK_FIXTURES_DIR", DEFAULT_FIXTURES_DIR,
    ))
    applied = apply_ready_proposals(
        proposals_path=proposals_path, learned_path=learned_path,
        fixtures_dir=fixtures_dir, min_confirmed=3,
    )
    typer.echo(f"applied {len(applied)} new patterns")
    for pr in applied:
        typer.echo(f"  - {pr.target}: {pr.candidate_regex}")


@dart_app.command("parser-consolidate")
def dart_parser_consolidate_cmd():
    """학습 패턴 머지·dedup."""
    learned_path = Path(os.environ.get(
        "THEMEK_LEARNED_PATTERNS_PATH", DEFAULT_LEARNED_PATTERNS_PATH,
    ))
    from themek.dart.learned_patterns import (
        load_learned_patterns, save_learned_patterns, consolidate,
    )
    lp = load_learned_patterns(learned_path)
    before = sum(len(lp.target_patterns(t))
                 for t in ("overview", "products", "revenue"))
    lp = consolidate(lp)
    save_learned_patterns(learned_path, lp)
    after = sum(len(lp.target_patterns(t))
                for t in ("overview", "products", "revenue"))
    typer.echo(f"consolidated: {before} → {after} patterns")


@krx_app.command("sync-listed")
def krx_sync_listed_cmd(
    auto_enroll: bool = typer.Option(
        False, "--auto-enroll",
        help="신규 상장 종목마다 BackfillTarget pending row 자동 생성",
    ),
    periods: Optional[str] = typer.Option(
        None, "--periods",
        help="--auto-enroll 사용 시 BackfillTarget 생성 period 범위 (예: 2023:2024)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="KRX 호출까지만 하고 DB 미변경, ticker 수만 출력",
    ),
):
    """KOSPI/KOSDAQ 상장사를 Stock 테이블에 sync."""
    from sqlalchemy import select

    from themek.db.corp_models import BackfillTarget, Stock
    from themek.dart.backfill import _parse_periods

    try:
        _, cache = _dart_client_and_cache()
    except DartAuthError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2)

    client = KrxClient()

    if dry_run:
        listed = fetch_listed_universe(client)
        typer.echo(
            f"[dry-run] KOSPI/KOSDAQ {len(listed)} listed tickers "
            f"(KOSPI={sum(1 for v in listed.values() if v == 'KOSPI')}, "
            f"KOSDAQ={sum(1 for v in listed.values() if v == 'KOSDAQ')})"
        )
        return

    with _session() as sess:
        r = sync_listed_stocks(
            sess, krx_client=client, cache=cache, today=date.today(),
        )
    typer.echo(
        f"added={len(r.added)} delisted={len(r.delisted)} "
        f"updated={len(r.updated)} unlinked={len(r.unlinked)}"
    )

    if auto_enroll and r.added:
        if not periods:
            typer.echo(
                "Warning: --auto-enroll 사용 시 --periods 필요 — skip",
                err=True,
            )
            return
        period_list = _parse_periods(periods)
        inserted = 0
        with _session() as sess:
            for ticker in r.added:
                stock = sess.get(Stock, ticker)
                if stock is None:
                    continue
                for p in period_list:
                    existing = sess.scalar(
                        select(BackfillTarget)
                        .where(BackfillTarget.corp_code == stock.issued_by_id)
                        .where(BackfillTarget.period == p)
                    )
                    if existing is not None:
                        continue
                    sess.add(BackfillTarget(
                        corp_code=stock.issued_by_id, period=p,
                        status="pending",
                    ))
                    inserted += 1
            sess.commit()
        typer.echo(f"auto-enrolled {inserted} new BackfillTarget rows")


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
    typer.echo(f"vault built: {stats['companies']} companies, "
               f"{stats.get('issues', 0)} integrity issues → {out}/")


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


@ontology_app.command("export-graph")
def ontology_export_graph_cmd(
    out: str = typer.Option("graph", "--out", help="graph export 디렉토리"),
):
    """코어를 nodes.json/edges.json으로 export."""
    with _session() as s:
        stats = export_graph(s, Path(out))
    typer.echo(f"graph exported: {stats['nodes']} nodes, {stats['edges']} edges → {out}/")


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


@pipeline_app.command("run")
def pipeline_run_cmd(
    since: str = typer.Option("yesterday", "--since"),
    until: str = typer.Option("today", "--until"),
    universe_source: str = typer.Option(
        "stocks", "--universe-source",
        help="stocks (기본, Stock 테이블 전체) | file",
    ),
    universe_file: Optional[Path] = typer.Option(
        None, "--universe-file",
        help="corp_code 파일 경로. 지정 시 source 무관하게 이 파일을 universe로 사용.",
    ),
    include_delisted: bool = typer.Option(
        False, "--include-delisted",
        help="--universe-source=stocks 시 delisted 종목 포함",
    ),
    out_vault: str = typer.Option("vault", "--out-vault"),
    out_graph: str = typer.Option("graph", "--out-graph"),
    skip_sync: bool = typer.Option(False, "--skip-sync"),
    skip_structure: bool = typer.Option(False, "--skip-structure"),
    skip_financials: bool = typer.Option(False, "--skip-financials"),
    skip_equity: bool = typer.Option(False, "--skip-equity"),
    skip_export: bool = typer.Option(False, "--skip-export"),
):
    """DART 파이프라인 통합 구동: sync→structure→financials→export (재무 연도 자동)."""
    from datetime import timedelta
    from themek.dart.universe import load_universe, load_universe_from_stocks
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
    if not (skip_sync and skip_structure and skip_financials and skip_equity):
        try:
            client, cache = _dart_client_and_cache()
        except DartAuthError as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(code=2)
    if not skip_structure:
        if universe_file is not None:
            universe = set(load_universe(universe_file))
        elif universe_source == "stocks":
            with _session() as sess:
                universe = set(load_universe_from_stocks(
                    sess, include_delisted=include_delisted))
        elif universe_source == "file":
            typer.echo(
                "Error: --universe-source file 사용 시 --universe-file 경로가 필요합니다.",
                err=True)
            raise typer.Exit(code=1)
        else:
            typer.echo(
                f"Error: --universe-source는 'file' 또는 'stocks' (got {universe_source!r})",
                err=True)
            raise typer.Exit(code=1)
        rate_budget = RateBudget(daily_cap=38000,
                                 state_file=s.dart_cache_dir / "budget_state.json")

    with _session() as sess:
        result = run_pipeline(
            sess, client, cache=cache,
            skip_sync=skip_sync, skip_structure=skip_structure,
            skip_financials=skip_financials, skip_equity=skip_equity,
            skip_export=skip_export,
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
        elif stage == "equity":
            e = result.equity
            typer.echo(f"[equity] companies={e['companies']} edges={e['edges']} "
                       f"failed={len(e['failed'])}")
        elif stage == "export":
            e = result.export
            typer.echo(f"[export] vault {e['companies']} companies → {out_vault}/ ; "
                       f"graph {e['nodes']} nodes/{e['edges']} edges → {out_graph}/")
    typer.echo(f"pipeline done: ran={result.ran} skipped={result.skipped}")


if __name__ == "__main__":
    app()
